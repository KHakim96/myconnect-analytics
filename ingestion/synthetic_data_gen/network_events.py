"""
MYConnect synthetic network events generator.

SOURCE CONTRACT: src_network_events
Expected rows: 2,000,000
Columns: 11 (exact order)
1. event_id             VARCHAR(20), PK
2. node_id              VARCHAR(20)
3. event_type           VARCHAR(30)
4. severity             VARCHAR(10)
5. start_time           TIMESTAMP
6. end_time             TIMESTAMP (nullable)
7. affected_subscribers INT
8. region               VARCHAR(50)
9. state                VARCHAR(50)
10. root_cause          VARCHAR(100) (nullable)
11. created_at          TIMESTAMP

Strict Enum Restrictions:
- event_type: ONLY 'outage', 'degradation', 'maintenance', 'restoration'
  (FORBIDDEN: 'hardware_failure', 'congestion', 'warning', etc.)
- severity: ONLY 'minor', 'major', 'critical'
  (FORBIDDEN: 'warning', 'info', 'moderate', etc.)

Strict Date Range:
- 2024-01-01 through 2025-06-30

Contractual Data Quality Targets:
- Exactly 500 events with end_time < start_time
- Some events with affected_subscribers = 0 AND severity = 'critical'
- Inconsistent region names

Synthetic Assumptions for Unspecified "some":
- 2,000 records with severity = 'critical' and affected_subscribers = 0
- 10,000 records with inconsistent region names
- 50,000 ongoing events with end_time = NULL
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# PATHS & CONFIGURATION
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DATA_DIR = PROJECT_ROOT / "generated"

OUTPUT_DIR = GENERATED_DATA_DIR / "network_events"
OUTPUT_PATH = OUTPUT_DIR / "part-00000.parquet"

RANDOM_SEED = 42

EVENT_COUNT = 2_000_000

# Contractual DQ target
INVALID_END_TIME_COUNT = 500

# Explicit synthetic assumptions for unspecified contractual quantities
CRITICAL_ZERO_SUBSCRIBERS_COUNT = 2_000  # synthetic assumption
INCONSISTENT_REGION_COUNT = 10_000        # synthetic assumption
ONGOING_EVENT_COUNT = 50_000              # synthetic assumption

BATCH_SIZE = 250_000

ALLOWED_EVENT_TYPES = ("outage", "degradation", "maintenance", "restoration")
ALLOWED_SEVERITIES = ("minor", "major", "critical")
ALLOWED_ROOT_CAUSES = ("fibre_cut", "equipment_failure", "power_outage")
CANONICAL_REGIONS = ("Klang Valley", "Northern", "Southern", "East Coast", "Sabah", "Sarawak")

OUTPUT_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("node_id", pa.string()),
        ("event_type", pa.string()),
        ("severity", pa.string()),
        ("start_time", pa.timestamp("ns")),
        ("end_time", pa.timestamp("ns")),
        ("affected_subscribers", pa.int64()),
        ("region", pa.string()),
        ("state", pa.string()),
        ("root_cause", pa.string()),
        ("created_at", pa.timestamp("ns")),
    ]
)


# ---------------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------------


def generate_network_events() -> None:
    """Generate src_network_events dataset adhering strictly to contract specifications."""
    rng = np.random.default_rng(RANDOM_SEED)

    # 1. Geographic & Node Configuration
    print("[load] Setting up nodes, regions, and states catalog...")
    region_state_defs = [
        # Klang Valley (40% weight)
        ("Klang Valley", "Selangor", "KV", 0.40 * 0.65),
        ("Klang Valley", "Kuala Lumpur", "KV", 0.40 * 0.32),
        ("Klang Valley", "Putrajaya", "KV", 0.40 * 0.03),
        # Northern (20% weight)
        ("Northern", "Penang", "NR", 0.20 * 0.45),
        ("Northern", "Perak", "NR", 0.20 * 0.35),
        ("Northern", "Kedah", "NR", 0.20 * 0.15),
        ("Northern", "Perlis", "NR", 0.20 * 0.05),
        # Southern (18% weight)
        ("Southern", "Johor", "SR", 0.18 * 0.60),
        ("Southern", "Melaka", "SR", 0.18 * 0.22),
        ("Southern", "Negeri Sembilan", "SR", 0.18 * 0.18),
        # East Coast (10% weight)
        ("East Coast", "Pahang", "EC", 0.10 * 0.45),
        ("East Coast", "Terengganu", "EC", 0.10 * 0.30),
        ("East Coast", "Kelantan", "EC", 0.10 * 0.25),
        # Sabah (6% weight)
        ("Sabah", "Sabah", "SB", 0.06 * 0.90),
        ("Sabah", "Labuan", "SB", 0.06 * 0.10),
        # Sarawak (6% weight)
        ("Sarawak", "Sarawak", "SW", 0.06 * 1.00),
    ]

    region_weights = np.array([item[3] for item in region_state_defs])
    region_weights = region_weights / np.sum(region_weights)

    # 50 nodes per region code matching format NODE-KV-001
    nodes_by_code: dict[str, list[str]] = {}
    for code in ("KV", "NR", "SR", "EC", "SB", "SW"):
        nodes_by_code[code] = [f"NODE-{code}-{n:03d}" for n in range(1, 51)]

    # 2. Sample Geographic and Node Assignments
    print("[sample] Sampling region, state, and node assignments across 2,000,000 events...")
    geo_indices = rng.choice(len(region_state_defs), size=EVENT_COUNT, p=region_weights)

    all_regions = np.array([region_state_defs[i][0] for i in geo_indices], dtype=object)
    all_states = np.array([region_state_defs[i][1] for i in geo_indices], dtype=object)
    geo_codes = [region_state_defs[i][2] for i in geo_indices]

    node_num_indices = rng.integers(0, 50, size=EVENT_COUNT)
    all_nodes = np.array(
        [nodes_by_code[code][n] for code, n in zip(geo_codes, node_num_indices)],
        dtype=object,
    )

    # 3. Partition Disjoint DQ Populations
    print("[partition] Allocating mutually disjoint DQ populations...")
    # Population A: 500 invalid end_time records (indices 0..499)
    invalid_idx = np.arange(0, INVALID_END_TIME_COUNT)

    # Population B: 2,000 critical + zero affected_subscribers records (indices 500..2,499)
    critical_zero_idx = np.arange(
        INVALID_END_TIME_COUNT,
        INVALID_END_TIME_COUNT + CRITICAL_ZERO_SUBSCRIBERS_COUNT,
    )

    # Population C: 10,000 inconsistent region records (indices 2,500..12,499)
    inconsistent_region_idx = np.arange(
        INVALID_END_TIME_COUNT + CRITICAL_ZERO_SUBSCRIBERS_COUNT,
        INVALID_END_TIME_COUNT + CRITICAL_ZERO_SUBSCRIBERS_COUNT + INCONSISTENT_REGION_COUNT,
    )

    # Population D: 50,000 ongoing events with end_time = NULL (indices 12,500..62,499)
    ongoing_idx = np.arange(
        INVALID_END_TIME_COUNT + CRITICAL_ZERO_SUBSCRIBERS_COUNT + INCONSISTENT_REGION_COUNT,
        INVALID_END_TIME_COUNT + CRITICAL_ZERO_SUBSCRIBERS_COUNT + INCONSISTENT_REGION_COUNT + ONGOING_EVENT_COUNT,
    )

    # 4. Inject Inconsistent Region DQ (Population C)
    print(f"[dq] Injecting {INCONSISTENT_REGION_COUNT:,} inconsistent region records (synthetic assumption)...")
    variant_map = {
        "Klang Valley": ["KlangValley", "Klang valley"],
        "Northern": ["North"],
        "Southern": ["South"],
        "East Coast": ["EAST COAST"],
        "Sabah": ["SABAH"],
        "Sarawak": ["SARAWAK"],
    }
    for i in inconsistent_region_idx:
        curr_reg = all_regions[i]
        variants = variant_map[curr_reg]
        all_regions[i] = rng.choice(variants)

    # 5. Event Types and Severities
    print("[generate] Generating strictly compliant event types and severities...")
    # Strict event_type domain: outage, degradation, maintenance, restoration
    event_types = rng.choice(
        list(ALLOWED_EVENT_TYPES),
        size=EVENT_COUNT,
        p=[0.25, 0.45, 0.20, 0.10],
    )

    # Strict severity domain: minor, major, critical
    # Distribution: many minor (85%), major (13%), critical (2%)
    severities = rng.choice(
        list(ALLOWED_SEVERITIES),
        size=EVENT_COUNT,
        p=[0.85, 0.13, 0.02],
    )

    # Explicitly assign critical severity to critical_zero_idx (Population B)
    severities[critical_zero_idx] = "critical"

    # Ensure invalid_idx (Population A) is strictly non-critical to prevent accidental cross-contamination
    severities[invalid_idx] = rng.choice(["minor", "major"], size=INVALID_END_TIME_COUNT, p=[0.85, 0.15])

    # 6. Affected Subscribers
    print("[generate] Generating affected subscriber counts...")
    affected_subscribers = np.empty(EVENT_COUNT, dtype=np.int64)

    minor_mask = severities == "minor"
    major_mask = severities == "major"
    critical_mask = severities == "critical"

    affected_subscribers[minor_mask] = rng.integers(1, 500, size=int(minor_mask.sum()))
    affected_subscribers[major_mask] = rng.integers(500, 5000, size=int(major_mask.sum()))
    # Normal critical events have positive affected_subscribers >= 1000
    affected_subscribers[critical_mask] = rng.integers(1000, 50000, size=int(critical_mask.sum()))

    # DQ: Explicitly set the 2,000 critical-zero rows to 0 (Population B)
    print(f"[dq] Injecting {CRITICAL_ZERO_SUBSCRIBERS_COUNT:,} critical-zero-subscriber records (synthetic assumption)...")
    affected_subscribers[critical_zero_idx] = 0

    # 7. Root Causes
    # STRICT CONTRACT: fibre_cut / equipment_failure / power_outage, Often NULL
    print("[generate] Generating root causes (often NULL)...")
    root_causes = np.full(EVENT_COUNT, None, dtype=object)

    # ~40% NULL, ~60% populated with allowed examples
    has_rc = rng.uniform(0.0, 1.0, size=EVENT_COUNT) < 0.60
    root_causes[has_rc] = rng.choice(list(ALLOWED_ROOT_CAUSES), size=int(has_rc.sum()))

    # 8. Timestamps (start_time, end_time, created_at)
    # STRICT PROJECT RANGE: 2024-01-01 through 2025-06-30
    print("[generate] Generating timestamps strictly within 2024-01-01 to 2025-06-30...")
    start_dt = pd.Timestamp("2024-01-01 00:00:00")
    end_dt = pd.Timestamp("2025-06-30 23:59:59")
    total_seconds = int((end_dt - start_dt).total_seconds())

    # Ensure Population A start times are at least 1 day after 2024-01-01 so invalid end_times remain in 2024
    sec_offsets = rng.integers(86400, total_seconds - 3600, size=EVENT_COUNT).astype("timedelta64[s]")
    base_start = np.datetime64("2024-01-01T00:00:00", "s")

    start_times = (base_start + sec_offsets).astype("datetime64[ns]")

    # created_at: on or shortly after start_time (0 to 60 seconds)
    created_at = (
        base_start + sec_offsets + rng.integers(0, 60, size=EVENT_COUNT).astype("timedelta64[s]")
    ).astype("datetime64[ns]")

    # Event durations: minor shorter, major/critical/maintenance longer
    durations = np.empty(EVENT_COUNT, dtype="timedelta64[s]")
    durations[minor_mask] = rng.integers(300, 7200, size=int(minor_mask.sum())).astype("timedelta64[s]")
    durations[major_mask] = rng.integers(3600, 28800, size=int(major_mask.sum())).astype("timedelta64[s]")
    durations[critical_mask] = rng.integers(7200, 86400, size=int(critical_mask.sum())).astype("timedelta64[s]")

    end_times = np.full(EVENT_COUNT, None, dtype=object)

    # Completed events: everything except ongoing_idx and invalid_idx
    completed_mask = np.ones(EVENT_COUNT, dtype=bool)
    completed_mask[ongoing_idx] = False
    completed_mask[invalid_idx] = False

    raw_end = start_times[completed_mask].astype("datetime64[s]") + durations[completed_mask]
    # Cap normal end_time at 2025-06-30 23:59:59 so no timestamp extends past project end
    max_end = np.datetime64("2025-06-30T23:59:59", "s")
    raw_end = np.minimum(raw_end, max_end)
    end_times[completed_mask] = raw_end.astype("datetime64[ns]")

    # Population A DQ: exactly 500 invalid end_time records (end_time < start_time by 15 mins to 4 hours)
    print(f"[dq] Injecting {INVALID_END_TIME_COUNT:,} invalid end_time records...")
    invalid_back_offsets = rng.integers(900, 14400, size=INVALID_END_TIME_COUNT).astype("timedelta64[s]")
    end_times[invalid_idx] = (
        start_times[invalid_idx].astype("datetime64[s]") - invalid_back_offsets
    ).astype("datetime64[ns]")

    # 9. Globally Unique event_id: NET-00000001 through NET-02000000
    print("[assemble] Generating globally unique event IDs...")
    event_numbers = np.arange(1, EVENT_COUNT + 1, dtype=np.int64)
    event_ids = [f"NET-{n:08d}" for n in event_numbers]

    # 10. Write Output in Batches
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temp_output_path = OUTPUT_DIR / f"{OUTPUT_PATH.name}.tmp"

    if temp_output_path.exists():
        temp_output_path.unlink()

    print(f"[write] Streaming Parquet to {OUTPUT_PATH} in batches of {BATCH_SIZE:,}...")
    writer = pq.ParquetWriter(temp_output_path, schema=OUTPUT_SCHEMA, compression="snappy")

    try:
        for start_idx in range(0, EVENT_COUNT, BATCH_SIZE):
            end_idx = min(start_idx + BATCH_SIZE, EVENT_COUNT)
            batch = pa.RecordBatch.from_arrays(
                [
                    pa.array(event_ids[start_idx:end_idx], type=pa.string()),
                    pa.array(all_nodes[start_idx:end_idx], type=pa.string()),
                    pa.array(event_types[start_idx:end_idx], type=pa.string()),
                    pa.array(severities[start_idx:end_idx], type=pa.string()),
                    pa.array(start_times[start_idx:end_idx], type=pa.timestamp("ns")),
                    pa.array(end_times[start_idx:end_idx], type=pa.timestamp("ns")),
                    pa.array(affected_subscribers[start_idx:end_idx], type=pa.int64()),
                    pa.array(all_regions[start_idx:end_idx], type=pa.string()),
                    pa.array(all_states[start_idx:end_idx], type=pa.string()),
                    pa.array(root_causes[start_idx:end_idx], type=pa.string()),
                    pa.array(created_at[start_idx:end_idx], type=pa.timestamp("ns")),
                ],
                schema=OUTPUT_SCHEMA,
            )
            writer.write_batch(batch)
            pct = (end_idx / EVENT_COUNT) * 100.0
            print(f"[progress] written {end_idx:,} / {EVENT_COUNT:,} rows ({pct:.1f}%)")
    finally:
        writer.close()

    # Atomically replace target Parquet file
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()
    temp_output_path.replace(OUTPUT_PATH)
    print(f"[write] Successfully saved {OUTPUT_PATH}")

    # 11. Final Validation of Written Parquet
    print("\n[validate] Reading back and strictly validating final Parquet dataset...")
    output_reader = pq.ParquetFile(OUTPUT_PATH)
    output_rows = output_reader.metadata.num_rows

    if output_rows != EVENT_COUNT:
        raise AssertionError(f"Expected {EVENT_COUNT:,} rows, found {output_rows:,}.")

    schema_arrow = output_reader.schema_arrow
    expected_col_names = [f.name for f in OUTPUT_SCHEMA]
    actual_col_names = list(schema_arrow.names)
    if actual_col_names != expected_col_names:
        raise AssertionError(
            f"Columns mismatch: expected {expected_col_names}, got {actual_col_names}"
        )

    # Check physical Arrow types
    if schema_arrow.field("event_id").type != pa.string():
        raise AssertionError("event_id physical type must be string.")
    if schema_arrow.field("node_id").type != pa.string():
        raise AssertionError("node_id physical type must be string.")
    if schema_arrow.field("event_type").type != pa.string():
        raise AssertionError("event_type physical type must be string.")
    if schema_arrow.field("severity").type != pa.string():
        raise AssertionError("severity physical type must be string.")
    if schema_arrow.field("start_time").type != pa.timestamp("ns"):
        raise AssertionError("start_time physical type must be timestamp[ns].")
    if schema_arrow.field("end_time").type != pa.timestamp("ns"):
        raise AssertionError("end_time physical type must be timestamp[ns].")
    if schema_arrow.field("affected_subscribers").type != pa.int64():
        raise AssertionError("affected_subscribers physical type must be int64.")
    if schema_arrow.field("region").type != pa.string():
        raise AssertionError("region physical type must be string.")
    if schema_arrow.field("state").type != pa.string():
        raise AssertionError("state physical type must be string.")
    if schema_arrow.field("root_cause").type != pa.string():
        raise AssertionError("root_cause physical type must be string.")
    if schema_arrow.field("created_at").type != pa.timestamp("ns"):
        raise AssertionError("created_at physical type must be timestamp[ns].")

    # Read output table with pandas for content validation
    output = pd.read_parquet(OUTPUT_PATH)

    # 1. Uniqueness of event_id
    null_event_id_count = int(output["event_id"].isna().sum())
    if null_event_id_count != 0:
        raise AssertionError(f"Found {null_event_id_count:,} NULL event IDs.")

    duplicate_event_id_count = int(output["event_id"].duplicated().sum())
    if duplicate_event_id_count != 0:
        raise AssertionError(f"Found {duplicate_event_id_count:,} duplicate event IDs.")

    # 2. Allowed event types and FORBIDDEN assertions
    actual_types = set(output["event_type"].unique())
    invalid_event_types = actual_types - set(ALLOWED_EVENT_TYPES)
    if len(invalid_event_types) != 0:
        raise AssertionError(f"Invalid event types found: {invalid_event_types}")

    if "hardware_failure" in actual_types:
        raise AssertionError("FORBIDDEN: 'hardware_failure' found in event_type!")
    if "congestion" in actual_types:
        raise AssertionError("FORBIDDEN: 'congestion' found in event_type!")

    # 3. Allowed severities and FORBIDDEN assertions
    actual_severities = set(output["severity"].unique())
    invalid_severities = actual_severities - set(ALLOWED_SEVERITIES)
    if len(invalid_severities) != 0:
        raise AssertionError(f"Invalid severities found: {invalid_severities}")

    if "warning" in actual_severities:
        raise AssertionError("FORBIDDEN: 'warning' found in severity!")

    # 4. Strict project date range validation: 2024-01-01 to 2025-06-30
    min_start = output["start_time"].min()
    max_start = output["start_time"].max()
    normal_date_range_violations = int(
        ((output["start_time"] < "2024-01-01 00:00:00") | (output["start_time"] > "2025-06-30 23:59:59")).sum()
    )
    if normal_date_range_violations != 0:
        raise AssertionError(
            f"Found {normal_date_range_violations:,} normal date-range violations. Min: {min_start}, Max: {max_start}"
        )

    # 5. Invalid end_time records (end_time < start_time)
    invalid_end_count = int(
        (output["end_time"].notna() & (output["end_time"] < output["start_time"])).sum()
    )
    if invalid_end_count != INVALID_END_TIME_COUNT:
        raise AssertionError(
            f"Expected {INVALID_END_TIME_COUNT:,} invalid end_time records, found {invalid_end_count:,}."
        )

    # 6. Critical + zero subscribers count
    critical_zero_count = int(
        ((output["severity"] == "critical") & (output["affected_subscribers"] == 0)).sum()
    )
    if critical_zero_count != CRITICAL_ZERO_SUBSCRIBERS_COUNT:
        raise AssertionError(
            f"Expected {CRITICAL_ZERO_SUBSCRIBERS_COUNT:,} critical-zero records, found {critical_zero_count:,}."
        )

    # 7. Inconsistent region count
    inconsistent_region_count = int((~output["region"].isin(CANONICAL_REGIONS)).sum())
    if inconsistent_region_count != INCONSISTENT_REGION_COUNT:
        raise AssertionError(
            f"Expected {INCONSISTENT_REGION_COUNT:,} inconsistent region records, found {inconsistent_region_count:,}."
        )

    # 8. Non-negative affected_subscribers
    negative_subscribers_count = int((output["affected_subscribers"] < 0).sum())
    if negative_subscribers_count != 0:
        raise AssertionError(f"Found {negative_subscribers_count:,} negative affected_subscribers.")

    # 9. Ongoing events count
    ongoing_count = int(output["end_time"].isna().sum())

    # 10. Root causes validation (strictly allowed or NULL)
    actual_rcs = set(output["root_cause"].dropna().unique())
    invalid_rcs = actual_rcs - set(ALLOWED_ROOT_CAUSES)
    if len(invalid_rcs) != 0:
        raise AssertionError(f"Invalid root causes found: {invalid_rcs}")
    null_rc_count = int(output["root_cause"].isna().sum())
    if null_rc_count == 0:
        raise AssertionError("root_cause must have NULL values ('Often NULL').")

    # 12. Print formatted report exactly matching prompt specification
    print(f"\n[generated] src_network_events {output_rows:,} rows \u2192 {OUTPUT_PATH}")

    print("\nSchema:")
    for field in schema_arrow:
        print(f"  {field.name}: {field.type}")

    print("\nDQ expectations:")
    print(f"  invalid end_time rows       : ~{INVALID_END_TIME_COUNT}")
    print(
        f"  critical + zero subscribers: synthetic assumption = {CRITICAL_ZERO_SUBSCRIBERS_COUNT:,}"
    )
    print(
        f"  inconsistent region names   : synthetic assumption = {INCONSISTENT_REGION_COUNT:,}"
    )

    print("\nDQ validation:")
    print(f"  row count                   : {output_rows:,}")
    print(f"  duplicate event_id          : {duplicate_event_id_count:,}")
    print(f"  invalid end_time count      : {invalid_end_count:,}")
    print(f"  critical-zero count         : {critical_zero_count:,}")
    print(f"  inconsistent-region count   : {inconsistent_region_count:,}")
    print(f"  negative affected_subscribers: {negative_subscribers_count:,}")
    print(f"  invalid event_type count    : {len(invalid_event_types):,}")
    print(f"  invalid severity count      : {len(invalid_severities):,}")
    print(f"  normal date-range violations: {normal_date_range_violations:,}")
    print(f"  ongoing event count         : {ongoing_count:,}")

    print("\nOutput:")
    print(f"  {OUTPUT_PATH}")


def main() -> None:
    generate_network_events()


if __name__ == "__main__":
    main()
