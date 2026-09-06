"""
MYConnect synthetic daily usage generator.

SOURCE CONTRACT: src_usage_daily
Expected rows: 4,500,000
Columns: 9 (exact order)
1. usage_id             VARCHAR(30), PK
2. subscription_id      VARCHAR(20), FK -> src_subscriptions
3. usage_date           DATE
4. download_gb          DECIMAL(10,3)
5. upload_gb            DECIMAL(10,3)
6. peak_download_mbps   DECIMAL(8,2)
7. avg_download_mbps    DECIMAL(8,2)
8. session_count        INT
9. created_at           TIMESTAMP

Contractual Data Quality Targets:
- ~10,000 records arriving 1-3 days late (created_at occurs 1-3 days after usage_date)
- ~500 records with negative download_gb / upload_gb (sensor errors)
- ~2,000 records with peak speed exceeding plan_speed * 1.5 (outliers)
- ~1,000 duplicate (subscription_id + usage_date) pairs
- Some usage records for terminated subscriptions

Explicit Synthetic Assumption for Unspecified "some":
- 5,000 usage records for terminated subscriptions (status == 'terminated' and usage_date > subscription_end_date)

Architecture & Performance:
- Fully vectorized NumPy array operations and cumulative searchsorted mapping.
- Mutually disjoint DQ populations preventing cross-contamination.
- Zero row-by-row Python loops over 4.5M records.
- Batched streaming into Snappy-compressed Parquet.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# PATHS & CONFIGURATION
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DATA_DIR = PROJECT_ROOT / "generated"

SUBSCRIPTIONS_PATH = GENERATED_DATA_DIR / "subscriptions" / "part-00000.parquet"
PLANS_PATH = GENERATED_DATA_DIR / "plans" / "part-00000.parquet"

OUTPUT_DIR = GENERATED_DATA_DIR / "usage_daily"
OUTPUT_PATH = OUTPUT_DIR / "part-00000.parquet"

RANDOM_SEED = 42

USAGE_COUNT = 4_500_000

# Contractual DQ targets
LATE_ARRIVING_COUNT = 10_000
NEGATIVE_SENSOR_COUNT = 500
PEAK_SPEED_OUTLIER_COUNT = 2_000
DUPLICATE_KEY_COUNT = 1_000

# Synthetic assumption for "some"
TERMINATED_USAGE_COUNT = 5_000

BATCH_SIZE = 250_000

DATA_START = np.datetime64("2024-01-01", "D")
DATA_END = np.datetime64("2025-06-30", "D")

OUTPUT_SCHEMA = pa.schema(
    [
        ("usage_id", pa.string()),
        ("subscription_id", pa.string()),
        ("usage_date", pa.date32()),
        ("download_gb", pa.decimal128(10, 3)),
        ("upload_gb", pa.decimal128(10, 3)),
        ("peak_download_mbps", pa.decimal128(8, 2)),
        ("avg_download_mbps", pa.decimal128(8, 2)),
        ("session_count", pa.int64()),
        ("created_at", pa.timestamp("ns")),
    ]
)


# ---------------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------------


def generate_usage_daily() -> None:
    """Generate the synthetic src_usage_daily dataset with exact contractual DQ requirements."""
    rng = np.random.default_rng(RANDOM_SEED)

    if not SUBSCRIPTIONS_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {SUBSCRIPTIONS_PATH}")

    if not PLANS_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {PLANS_PATH}")

    # 1. Load plans and subscriptions
    print("[load] Reading plans table...")
    plans_tbl = pq.read_table(PLANS_PATH, columns=["plan_id", "speed_mbps", "upload_speed_mbps"])
    plan_speeds_dict = dict(
        zip(
            plans_tbl["plan_id"].to_numpy(zero_copy_only=False),
            plans_tbl["speed_mbps"].to_numpy(zero_copy_only=False),
        )
    )

    print("[load] Reading subscriptions table...")
    subs_tbl = pq.read_table(
        SUBSCRIPTIONS_PATH,
        columns=[
            "subscription_id",
            "plan_id",
            "subscription_start_date",
            "subscription_end_date",
            "status",
        ],
    )
    sub_ids = subs_tbl["subscription_id"].to_numpy(zero_copy_only=False)
    sub_plan_ids = subs_tbl["plan_id"].to_numpy(zero_copy_only=False)
    sub_starts = subs_tbl["subscription_start_date"].to_numpy(zero_copy_only=False)
    sub_ends = subs_tbl["subscription_end_date"].to_numpy(zero_copy_only=False)
    sub_statuses = subs_tbl["status"].to_numpy(zero_copy_only=False)

    sub_speeds = np.array([plan_speeds_dict[pid] for pid in sub_plan_ids], dtype=np.int64)

    # 2. Filter active subscriptions for base population
    print("[filter] Filtering active subscriptions during project data period...")
    has_end = ~np.isnat(sub_ends)
    active_mask = (
        (sub_statuses == "active")
        & (sub_starts <= DATA_END)
        & (~has_end | (sub_ends >= DATA_START))
    )

    active_sub_ids = sub_ids[active_mask]
    active_sub_starts = sub_starts[active_mask]
    active_sub_ends = sub_ends[active_mask]
    active_has_end = has_end[active_mask]
    active_speeds = sub_speeds[active_mask]

    effective_starts = np.maximum(active_sub_starts, DATA_START)
    effective_ends = np.where(active_has_end, np.minimum(active_sub_ends, DATA_END), DATA_END)

    valid_days = (effective_ends - effective_starts).astype(np.int64) + 1
    total_active_pairs = int(np.sum(valid_days))
    cumsum_starts = np.cumsum(valid_days) - valid_days

    print(
        f"[sample] Active subscriptions: {len(active_sub_ids):,}, "
        f"total available active days: {total_active_pairs:,}"
    )

    # Base count needed from active subscriptions:
    # 4,500,000 - 1,000 (duplicate clones) - 5,000 (terminated DQ) = 4,494,000
    base_active_count = USAGE_COUNT - DUPLICATE_KEY_COUNT - TERMINATED_USAGE_COUNT

    print(f"[sample] Sampling {base_active_count:,} unique active (subscription, date) pairs...")
    flat_indices = rng.choice(total_active_pairs, size=base_active_count, replace=False)

    sub_local_idx = np.searchsorted(cumsum_starts, flat_indices, side="right") - 1
    day_offsets = (flat_indices - cumsum_starts[sub_local_idx]).astype("timedelta64[D]")

    base_sub_ids = active_sub_ids[sub_local_idx]
    base_usage_dates = effective_starts[sub_local_idx] + day_offsets
    base_speeds = active_speeds[sub_local_idx]

    # 3. Partition disjoint DQ populations across active records
    # By partitioning inside base_active_count, we guarantee that no duplicate clone,
    # negative volume, peak outlier, late record, or terminated record accidentally overlaps.
    print("[partition] Allocating mutually disjoint DQ populations on active records...")
    late_pos = rng.choice(base_active_count, size=LATE_ARRIVING_COUNT, replace=False)

    rem_1 = np.setdiff1d(np.arange(base_active_count), late_pos, assume_unique=True)
    neg_pos = rng.choice(rem_1, size=NEGATIVE_SENSOR_COUNT, replace=False)

    rem_2 = np.setdiff1d(rem_1, neg_pos, assume_unique=True)
    peak_outlier_pos = rng.choice(rem_2, size=PEAK_SPEED_OUTLIER_COUNT, replace=False)

    rem_3 = np.setdiff1d(rem_2, peak_outlier_pos, assume_unique=True)
    dup_source_pos = rng.choice(rem_3, size=DUPLICATE_KEY_COUNT, replace=False)

    # 4. Generate metrics for active records
    print("[generate] Generating broadband usage volumes and throughput metrics...")
    speed_factor = 0.5 + (base_speeds / 1000.0) * 0.5
    raw_download = rng.lognormal(mean=2.4, sigma=0.6, size=base_active_count) * speed_factor
    base_download_gb = np.round(np.clip(raw_download, 0.100, 300.000), 3)

    base_upload_gb = np.round(base_download_gb * rng.uniform(0.12, 0.35, size=base_active_count), 3)
    base_upload_gb = np.maximum(base_upload_gb, 0.050)

    # Peak download speed: normally 0.60x - 1.05x plan speed (strictly <= 1.5x for normal)
    peak_factor = rng.uniform(0.60, 1.05, size=base_active_count)
    base_peak_mbps = np.round(base_speeds * peak_factor, 2)

    # Average download speed: <= peak download speed
    avg_factor = rng.uniform(0.45, 0.85, size=base_active_count)
    base_avg_mbps = np.round(base_peak_mbps * avg_factor, 2)

    base_sessions = rng.integers(15, 300, size=base_active_count, dtype=np.int64)

    # 5. Apply Injected DQ on active records
    # A. Negative sensor errors (500 rows)
    # 250 negative download, 200 negative upload, 50 negative both
    neg_dl_only = neg_pos[:250]
    neg_ul_only = neg_pos[250:450]
    neg_both = neg_pos[450:]

    base_download_gb[neg_dl_only] = -np.round(rng.uniform(0.500, 25.000, size=250), 3)
    base_upload_gb[neg_ul_only] = -np.round(rng.uniform(0.200, 10.000, size=200), 3)
    base_download_gb[neg_both] = -np.round(rng.uniform(0.500, 25.000, size=50), 3)
    base_upload_gb[neg_both] = -np.round(rng.uniform(0.200, 10.000, size=50), 3)

    # B. Peak speed outliers (2,000 rows): peak_download_mbps > plan_speed * 1.5
    outlier_factors = rng.uniform(1.55, 2.50, size=PEAK_SPEED_OUTLIER_COUNT)
    base_peak_mbps[peak_outlier_pos] = np.round(base_speeds[peak_outlier_pos] * outlier_factors, 2)
    base_avg_mbps[peak_outlier_pos] = np.round(
        base_peak_mbps[peak_outlier_pos] * rng.uniform(0.50, 0.80, size=PEAK_SPEED_OUTLIER_COUNT),
        2,
    )

    # C. Created at: normally on usage_date (0 to 86,000 seconds, strictly on same calendar day)
    base_sec_offsets = rng.integers(0, 86000, size=base_active_count).astype("timedelta64[s]")
    base_created_at = (base_usage_dates.astype("datetime64[s]") + base_sec_offsets).astype("datetime64[ns]")

    # Late arriving (10,000 rows): created_at occurs 1 to 3 days after usage_date
    late_delay_days = rng.integers(1, 4, size=LATE_ARRIVING_COUNT).astype("timedelta64[D]")
    late_dates = base_usage_dates[late_pos] + late_delay_days
    late_secs = rng.integers(0, 86400, size=LATE_ARRIVING_COUNT).astype("timedelta64[s]")
    base_created_at[late_pos] = (late_dates.astype("datetime64[s]") + late_secs).astype("datetime64[ns]")

    # 6. Generate Duplicate Extra Rows (1,000 rows)
    # Cloned from dup_source_pos (which is strictly normal active records)
    print(f"[dq] Generating {DUPLICATE_KEY_COUNT:,} duplicate business key rows...")
    dup_sub_ids = base_sub_ids[dup_source_pos]
    dup_usage_dates = base_usage_dates[dup_source_pos]
    dup_download_gb = base_download_gb[dup_source_pos]
    dup_upload_gb = base_upload_gb[dup_source_pos]
    dup_peak_mbps = base_peak_mbps[dup_source_pos]
    dup_avg_mbps = base_avg_mbps[dup_source_pos]
    dup_sessions = base_sessions[dup_source_pos]
    # Ingestion retry within same day (+1 to 300 seconds; never crosses midnight because base was <= 86,000s)
    dup_created_at = (
        base_created_at[dup_source_pos].astype("datetime64[s]")
        + rng.integers(1, 300, size=DUPLICATE_KEY_COUNT).astype("timedelta64[s]")
    ).astype("datetime64[ns]")

    # 7. Terminated Subscription Usage Records (5,000 rows)
    # Status = terminated, usage_date > subscription_end_date
    print(f"[dq] Generating {TERMINATED_USAGE_COUNT:,} post-termination usage records...")
    term_mask = (
        (sub_statuses == "terminated")
        & has_end
        & (sub_ends >= DATA_START)
        & (sub_ends < DATA_END)
    )
    term_candidate_indices = np.flatnonzero(term_mask)

    term_selected = rng.choice(term_candidate_indices, size=TERMINATED_USAGE_COUNT, replace=False)
    term_sub_ids = sub_ids[term_selected]
    term_end_dates = sub_ends[term_selected]
    term_speeds = sub_speeds[term_selected]

    post_term_days = rng.integers(1, 15, size=TERMINATED_USAGE_COUNT).astype("timedelta64[D]")
    term_usage_dates = np.minimum(term_end_dates + post_term_days, DATA_END)
    term_usage_dates = np.maximum(term_usage_dates, term_end_dates + np.timedelta64(1, "D"))

    term_raw_dl = rng.lognormal(mean=2.2, sigma=0.6, size=TERMINATED_USAGE_COUNT)
    term_download_gb = np.round(np.clip(term_raw_dl, 0.100, 150.000), 3)
    term_upload_gb = np.round(term_download_gb * rng.uniform(0.12, 0.35, size=TERMINATED_USAGE_COUNT), 3)
    term_upload_gb = np.maximum(term_upload_gb, 0.050)

    term_peak_mbps = np.round(term_speeds * rng.uniform(0.60, 0.95, size=TERMINATED_USAGE_COUNT), 2)
    term_avg_mbps = np.round(term_peak_mbps * rng.uniform(0.45, 0.80, size=TERMINATED_USAGE_COUNT), 2)
    term_sessions = rng.integers(10, 200, size=TERMINATED_USAGE_COUNT, dtype=np.int64)

    term_sec_offsets = rng.integers(0, 86000, size=TERMINATED_USAGE_COUNT).astype("timedelta64[s]")
    term_created_at = (term_usage_dates.astype("datetime64[s]") + term_sec_offsets).astype("datetime64[ns]")

    # 8. Concatenate full dataset exactly to 4,500,000 rows
    print("[assemble] Concatenating full dataset to 4,500,000 rows...")
    all_sub_ids = np.concatenate([base_sub_ids, dup_sub_ids, term_sub_ids])
    all_usage_dates = np.concatenate([base_usage_dates, dup_usage_dates, term_usage_dates])
    all_download_gb = np.concatenate([base_download_gb, dup_download_gb, term_download_gb])
    all_upload_gb = np.concatenate([base_upload_gb, dup_upload_gb, term_upload_gb])
    all_peak_mbps = np.concatenate([base_peak_mbps, dup_peak_mbps, term_peak_mbps])
    all_avg_mbps = np.concatenate([base_avg_mbps, dup_avg_mbps, term_avg_mbps])
    all_sessions = np.concatenate([base_sessions, dup_sessions, term_sessions])
    all_created_at = np.concatenate([base_created_at, dup_created_at, term_created_at])

    if len(all_sub_ids) != USAGE_COUNT:
        raise ValueError(f"Expected {USAGE_COUNT:,} rows, got {len(all_sub_ids):,}.")

    # 9. Generate globally unique usage_id
    print("[assemble] Generating globally unique usage IDs...")
    usage_numbers = np.arange(1, USAGE_COUNT + 1, dtype=np.int64)
    all_usage_ids = [f"USG-{n:09d}" for n in usage_numbers]

    # 10. Stream batched Parquet output safely
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temp_output_path = OUTPUT_DIR / f"{OUTPUT_PATH.name}.tmp"

    if temp_output_path.exists():
        temp_output_path.unlink()

    print(f"[write] Streaming Parquet to {OUTPUT_PATH} in batches of {BATCH_SIZE:,}...")
    writer = pq.ParquetWriter(
        temp_output_path,
        schema=OUTPUT_SCHEMA,
        compression="snappy",
    )

    try:
        for start_idx in range(0, USAGE_COUNT, BATCH_SIZE):
            end_idx = min(start_idx + BATCH_SIZE, USAGE_COUNT)
            batch = pa.RecordBatch.from_arrays(
                [
                    pa.array(all_usage_ids[start_idx:end_idx], type=pa.string()),
                    pa.array(all_sub_ids[start_idx:end_idx], type=pa.string()),
                    pa.array(all_usage_dates[start_idx:end_idx], type=pa.date32()),
                    pc.cast(
                        pa.array(all_download_gb[start_idx:end_idx], type=pa.float64()),
                        pa.decimal128(10, 3),
                    ),
                    pc.cast(
                        pa.array(all_upload_gb[start_idx:end_idx], type=pa.float64()),
                        pa.decimal128(10, 3),
                    ),
                    pc.cast(
                        pa.array(all_peak_mbps[start_idx:end_idx], type=pa.float64()),
                        pa.decimal128(8, 2),
                    ),
                    pc.cast(
                        pa.array(all_avg_mbps[start_idx:end_idx], type=pa.float64()),
                        pa.decimal128(8, 2),
                    ),
                    pa.array(all_sessions[start_idx:end_idx], type=pa.int64()),
                    pa.array(all_created_at[start_idx:end_idx], type=pa.timestamp("ns")),
                ],
                schema=OUTPUT_SCHEMA,
            )
            writer.write_batch(batch)
            pct = (end_idx / USAGE_COUNT) * 100.0
            print(f"[progress] written {end_idx:,} / {USAGE_COUNT:,} rows ({pct:.1f}%)")
    finally:
        writer.close()

    # Atomically replace final output
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()
    temp_output_path.replace(OUTPUT_PATH)
    print(f"[write] Successfully saved {OUTPUT_PATH}")

    # 11. Final validation on written Parquet dataset
    print("\n[validate] Validating final Parquet dataset...")
    output_reader = pq.ParquetFile(OUTPUT_PATH)
    output_rows = output_reader.metadata.num_rows

    if output_rows != USAGE_COUNT:
        raise AssertionError(f"Expected {USAGE_COUNT:,} rows, found {output_rows:,}.")

    schema_arrow = output_reader.schema_arrow
    expected_col_names = [f.name for f in OUTPUT_SCHEMA]
    actual_col_names = list(schema_arrow.names)
    if actual_col_names != expected_col_names:
        raise AssertionError(
            f"Columns mismatch: expected {expected_col_names}, got {actual_col_names}"
        )

    if schema_arrow.field("usage_date").type != pa.date32():
        raise AssertionError(f"usage_date type mismatch: expected date32, got {schema_arrow.field('usage_date').type}")
    if schema_arrow.field("download_gb").type != pa.decimal128(10, 3):
        raise AssertionError(f"download_gb type mismatch: expected decimal128(10, 3), got {schema_arrow.field('download_gb').type}")
    if schema_arrow.field("upload_gb").type != pa.decimal128(10, 3):
        raise AssertionError(f"upload_gb type mismatch: expected decimal128(10, 3), got {schema_arrow.field('upload_gb').type}")
    if schema_arrow.field("peak_download_mbps").type != pa.decimal128(8, 2):
        raise AssertionError(f"peak_download_mbps type mismatch: expected decimal128(8, 2), got {schema_arrow.field('peak_download_mbps').type}")
    if schema_arrow.field("avg_download_mbps").type != pa.decimal128(8, 2):
        raise AssertionError(f"avg_download_mbps type mismatch: expected decimal128(8, 2), got {schema_arrow.field('avg_download_mbps').type}")
    if schema_arrow.field("session_count").type != pa.int64():
        raise AssertionError(f"session_count type mismatch: expected int64, got {schema_arrow.field('session_count').type}")

    # Read output table with pandas for content validation
    output = pd.read_parquet(
        OUTPUT_PATH,
        columns=[
            "usage_id",
            "subscription_id",
            "usage_date",
            "download_gb",
            "upload_gb",
            "peak_download_mbps",
            "avg_download_mbps",
            "created_at",
        ],
    )

    # 1. Unique usage_id
    duplicate_usage_id_count = int(output["usage_id"].duplicated().sum())
    if duplicate_usage_id_count != 0:
        raise AssertionError(f"Found {duplicate_usage_id_count:,} duplicate usage_id values.")

    # 2. Orphan subscription IDs (must be 0)
    valid_sub_ids = set(sub_ids)
    orphan_subs = int((~output["subscription_id"].isin(valid_sub_ids)).sum())
    if orphan_subs != 0:
        raise AssertionError(f"Found {orphan_subs:,} orphan subscription IDs.")

    # 3. Duplicate subscription_id + usage_date extra rows
    dup_keys = output.groupby(["subscription_id", "usage_date"], dropna=False).size()
    duplicate_extra_rows = int((dup_keys - 1).clip(lower=0).sum())
    if duplicate_extra_rows != DUPLICATE_KEY_COUNT:
        raise AssertionError(
            f"Expected {DUPLICATE_KEY_COUNT:,} duplicate extra rows, found {duplicate_extra_rows:,}."
        )

    # 4. Late arriving records (created_at 1-3 days after usage_date)
    created_days = output["created_at"].dt.floor("D")
    usage_days = pd.to_datetime(output["usage_date"])
    day_diff = (created_days - usage_days).dt.days
    late_count = int(day_diff.between(1, 3).sum())
    if late_count != LATE_ARRIVING_COUNT:
        raise AssertionError(
            f"Expected {LATE_ARRIVING_COUNT:,} late-arriving records, found {late_count:,}."
        )

    # 5. Negative volume records
    neg_count = int(((output["download_gb"].astype(float) < 0) | (output["upload_gb"].astype(float) < 0)).sum())
    if neg_count != NEGATIVE_SENSOR_COUNT:
        raise AssertionError(
            f"Expected {NEGATIVE_SENSOR_COUNT:,} negative volume records, found {neg_count:,}."
        )

    # 6. Peak speed outliers (peak_download_mbps > plan_speed * 1.5)
    sub_speed_map = dict(zip(sub_ids, sub_speeds))
    matched_speeds = output["subscription_id"].map(sub_speed_map)
    outlier_count = int((output["peak_download_mbps"].astype(float) > matched_speeds * 1.5).sum())
    if outlier_count != PEAK_SPEED_OUTLIER_COUNT:
        raise AssertionError(
            f"Expected {PEAK_SPEED_OUTLIER_COUNT:,} peak speed outliers, found {outlier_count:,}."
        )

    # 7. Terminated subscription usage records
    sub_status_map = dict(zip(sub_ids, sub_statuses))
    matched_status = output["subscription_id"].map(sub_status_map)
    term_count = int((matched_status == "terminated").sum())
    if term_count != TERMINATED_USAGE_COUNT:
        raise AssertionError(
            f"Expected {TERMINATED_USAGE_COUNT:,} terminated subscription usage records, found {term_count:,}."
        )

    # Verify usage_date > subscription_end_date for terminated records
    sub_end_map = dict(zip(sub_ids, sub_ends))
    term_rows = output[matched_status == "terminated"]
    matched_ends = term_rows["subscription_id"].map(sub_end_map)
    post_term_count = int((pd.to_datetime(term_rows["usage_date"]) > pd.to_datetime(matched_ends)).sum())
    if post_term_count != TERMINATED_USAGE_COUNT:
        raise AssertionError(
            f"Expected {TERMINATED_USAGE_COUNT:,} post-termination date records, found {post_term_count:,}."
        )

    # 8. Avg <= peak for normal rows
    normal_mask = (output["peak_download_mbps"].astype(float) <= matched_speeds * 1.5)
    violating_avg = int(
        (
            output.loc[normal_mask, "avg_download_mbps"].astype(float)
            > output.loc[normal_mask, "peak_download_mbps"].astype(float)
        ).sum()
    )
    if violating_avg != 0:
        raise AssertionError(f"Found {violating_avg:,} normal records with avg > peak download speed.")

    # 12. Print formatted summary
    print(f"\n[generated] src_usage_daily {output_rows:,} rows  →  {OUTPUT_PATH}")
    print("\nDaily usage generation complete.")

    print("\nSchema:")
    print(output_reader.schema_arrow)

    print("\nDQ expectations:")
    print(f"  late-arriving records        : ~{LATE_ARRIVING_COUNT:,}")
    print(f"  negative sensor records      : ~{NEGATIVE_SENSOR_COUNT:,}")
    print(f"  peak-speed outliers          : ~{PEAK_SPEED_OUTLIER_COUNT:,}")
    print(f"  duplicate subscription/date  : ~{DUPLICATE_KEY_COUNT:,}")
    print(f"  terminated-subscription use  : {TERMINATED_USAGE_COUNT:,} (explicit synthetic assumption)")

    print("\nDQ validation:")
    print(f"  row count                    : {output_rows:,}")
    print(f"  duplicate extra rows         : {duplicate_extra_rows:,}")
    print(f"  late-arriving count          : {late_count:,}")
    print(f"  negative-volume count        : {neg_count:,}")
    print(f"  peak-speed outlier count     : {outlier_count:,}")
    print(f"  terminated-subscription count: {term_count:,}")
    print(f"  orphan subscription IDs      : {orphan_subs:,}")
    print(f"  duplicate usage_id count     : {duplicate_usage_id_count:,}")

    print("\nOutput:")
    print(f"  {OUTPUT_PATH}")


def main() -> None:
    generate_usage_daily()


if __name__ == "__main__":
    main()
