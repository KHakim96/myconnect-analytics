"""
MYConnect synthetic churn events generator.

SOURCE CONTRACT: src_churn_events
Expected rows: 35,000
Columns: 12 (exact order)
1. churn_event_id            VARCHAR(20), PK
2. customer_id               VARCHAR(20), FK -> src_customers
3. subscription_id           VARCHAR(20), FK -> src_subscriptions
4. churn_date                DATE
5. churn_type                VARCHAR(20)
6. churn_reason              VARCHAR(100) (nullable)
7. contract_remaining_months INT
8. early_termination_fee     DECIMAL(10,2)
9. retention_attempted       BOOLEAN
10. retention_offer          VARCHAR(100) (nullable)
11. retention_accepted       BOOLEAN
12. created_at               TIMESTAMP

Strict Enum Restrictions:
- churn_type: ONLY 'voluntary', 'involuntary'
- churn_reason: ONLY 'competitor_switch', 'relocation', 'price', 'service_quality', 'non_payment' (or NULL for DQ)

Contractual Data Quality Targets:
- Some churn events for customers whose subscription status is still 'active' (synthetic assumption: 1,000 rows)
- Churn reasons sometimes NULL for involuntary churns (synthetic assumption: 500 rows)

Date Range:
- 2024-01-01 through 2025-06-30
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
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

CUSTOMERS_PATH = GENERATED_DATA_DIR / "customers" / "part-00000.parquet"
SUBSCRIPTIONS_PATH = GENERATED_DATA_DIR / "subscriptions" / "part-00000.parquet"

OUTPUT_DIR = GENERATED_DATA_DIR / "churn_events"
OUTPUT_PATH = OUTPUT_DIR / "part-00000.parquet"

RANDOM_SEED = 42

CHURN_EVENT_COUNT = 35_000

# Controlled contractual DQ targets (explicit synthetic assumptions)
ACTIVE_STATUS_CHURN_COUNT = 1_000       # synthetic assumption
NULL_INVOLUNTARY_REASON_COUNT = 500     # synthetic assumption

ALLOWED_CHURN_TYPES = ("voluntary", "involuntary")
ALLOWED_CHURN_REASONS = (
    "competitor_switch",
    "relocation",
    "price",
    "service_quality",
    "non_payment",
)
VOLUNTARY_REASONS = (
    "competitor_switch",
    "relocation",
    "price",
    "service_quality",
)

RETENTION_OFFERS = (
    "20% discount for 6 months",
    "10% discount for 12 months",
    "Free speed upgrade for 6 months",
    "RM30 monthly rebate for 6 months",
    "Free WiFi 6 router upgrade",
    "1 month bill waiver",
)

OUTPUT_SCHEMA = pa.schema(
    [
        ("churn_event_id", pa.string()),
        ("customer_id", pa.string()),
        ("subscription_id", pa.string()),
        ("churn_date", pa.date32()),
        ("churn_type", pa.string()),
        ("churn_reason", pa.string()),
        ("contract_remaining_months", pa.int64()),
        ("early_termination_fee", pa.decimal128(10, 2)),
        ("retention_attempted", pa.bool_()),
        ("retention_offer", pa.string()),
        ("retention_accepted", pa.bool_()),
        ("created_at", pa.timestamp("ns")),
    ]
)


# ---------------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------------


def generate_churn_events() -> None:
    """Generate src_churn_events dataset adhering strictly to contract specifications."""
    print("[start] Generating src_churn_events dataset...")
    rng = np.random.default_rng(RANDOM_SEED)

    # 1. Load source customers and subscriptions
    if not CUSTOMERS_PATH.exists():
        raise FileNotFoundError(f"Required dataset not found: {CUSTOMERS_PATH}")
    if not SUBSCRIPTIONS_PATH.exists():
        raise FileNotFoundError(f"Required dataset not found: {SUBSCRIPTIONS_PATH}")

    print(f"[load] Reading customers table from {CUSTOMERS_PATH}...")
    cust_df = pd.read_parquet(CUSTOMERS_PATH, columns=["customer_id"])
    valid_customer_ids = set(cust_df["customer_id"].unique())

    print(f"[load] Reading subscriptions table from {SUBSCRIPTIONS_PATH}...")
    sub_df = pd.read_parquet(
        SUBSCRIPTIONS_PATH,
        columns=[
            "subscription_id",
            "customer_id",
            "status",
            "subscription_start_date",
            "subscription_end_date",
            "contract_months",
            "monthly_recurring_charge",
            "termination_reason",
        ],
    )

    # Filter subscriptions with valid customer relationships (preventing orphan keys)
    valid_subs = sub_df[sub_df["customer_id"].isin(valid_customer_ids)].copy()
    valid_subs["start_dt"] = pd.to_datetime(valid_subs["subscription_start_date"])
    valid_subs["end_dt"] = pd.to_datetime(valid_subs["subscription_end_date"])

    # 2. Filter eligible pools for sampling
    print("[filter] Filtering eligible subscription pools...")
    # Terminated pool: terminated subscriptions ending within project window 2024-01-01 to 2025-06-30
    eligible_term = valid_subs[
        (valid_subs["status"] == "terminated")
        & (valid_subs["end_dt"] >= "2024-01-01")
        & (valid_subs["end_dt"] <= "2025-06-30")
        & (valid_subs["end_dt"] >= valid_subs["start_dt"])
    ].copy().reset_index(drop=True)

    # Active pool: active subscriptions started before/during project window
    eligible_act = valid_subs[
        (valid_subs["status"] == "active")
        & (valid_subs["start_dt"] <= "2025-06-30")
    ].copy().reset_index(drop=True)

    term_needed = CHURN_EVENT_COUNT - ACTIVE_STATUS_CHURN_COUNT
    if len(eligible_term) < term_needed:
        raise ValueError(
            f"Not enough clean terminated subscriptions: needed {term_needed}, found {len(eligible_term)}"
        )
    if len(eligible_act) < ACTIVE_STATUS_CHURN_COUNT:
        raise ValueError(
            f"Not enough clean active subscriptions: needed {ACTIVE_STATUS_CHURN_COUNT}, found {len(eligible_act)}"
        )

    # 3. Deterministic sampling of subscriptions
    print("[sample] Selecting source subscriptions...")
    act_indices = rng.choice(len(eligible_act), size=ACTIVE_STATUS_CHURN_COUNT, replace=False)
    sample_act = eligible_act.iloc[act_indices].copy().reset_index(drop=True)

    term_indices = rng.choice(len(eligible_term), size=term_needed, replace=False)
    sample_term = eligible_term.iloc[term_indices].copy().reset_index(drop=True)

    # 4. Partition and allocate records across populations
    print("[partition] Allocating DQ populations...")
    # Arrays for column values
    churn_event_ids = [f"CHN-{i:06d}" for i in range(1, CHURN_EVENT_COUNT + 1)]
    customer_ids: list[str] = []
    subscription_ids: list[str] = []
    churn_dates: list[date] = []
    churn_types: list[str] = []
    churn_reasons: list[str | None] = []
    contract_remaining_months_list: list[int] = []
    early_termination_fees: list[Decimal] = []
    retention_attempteds: list[bool] = []
    retention_offers: list[str | None] = []
    retention_accepteds: list[bool] = []
    created_ats: list[pd.Timestamp] = []

    # -----------------------------------------------------------------------
    # Population A: 1,000 Active-status subscriptions DQ
    # -----------------------------------------------------------------------
    print(f"[dq] Injecting {ACTIVE_STATUS_CHURN_COUNT:,} active-subscription churn records (synthetic assumption)...")
    for i in range(ACTIVE_STATUS_CHURN_COUNT):
        row = sample_act.iloc[i]
        c_id = str(row["customer_id"])
        s_id = str(row["subscription_id"])
        s_start = row["subscription_start_date"]
        c_months = int(row["contract_months"])

        # Sample churn_date between max(start, 2024-01-01) and 2025-06-30
        min_d = max(s_start, date(2024, 1, 1))
        max_d = date(2025, 6, 30)
        days_range = (max_d - min_d).days
        offset = rng.integers(0, days_range + 1) if days_range > 0 else 0
        c_date = min_d + timedelta(days=int(offset))

        # 80% voluntary, 20% involuntary non_payment (strictly non-null reason)
        is_vol = bool(rng.random() < 0.80)
        c_type = "voluntary" if is_vol else "involuntary"
        c_reason = str(rng.choice(list(VOLUNTARY_REASONS))) if is_vol else "non_payment"

        # Calculate contract remaining months
        elapsed_days = (c_date - s_start).days
        elapsed_m = max(0, int(elapsed_days / 30.4375))
        rem_m = max(0, c_months - elapsed_m)

        # Early termination fee
        if rem_m > 0:
            fee = Decimal("0.00") if (is_vol and rng.random() < 0.20) else Decimal(f"{min(1000, rem_m * 100):.2f}")
        else:
            fee = Decimal("0.00")

        # Retention fields
        if is_vol and rng.random() < 0.60:
            ret_att = True
            ret_off = str(rng.choice(list(RETENTION_OFFERS)))
            ret_acc = bool(rng.random() < 0.05)
        else:
            ret_att = False
            ret_off = None
            ret_acc = False

        sec_offset = int(rng.integers(0, 86400))
        c_created = pd.Timestamp(c_date) + pd.Timedelta(seconds=sec_offset)

        customer_ids.append(c_id)
        subscription_ids.append(s_id)
        churn_dates.append(c_date)
        churn_types.append(c_type)
        churn_reasons.append(c_reason)
        contract_remaining_months_list.append(rem_m)
        early_termination_fees.append(fee)
        retention_attempteds.append(ret_att)
        retention_offers.append(ret_off)
        retention_accepteds.append(ret_acc)
        created_ats.append(c_created)

    # -----------------------------------------------------------------------
    # Population B: 500 Involuntary NULL-reason DQ (from terminated subscriptions)
    # -----------------------------------------------------------------------
    print(f"[dq] Injecting {NULL_INVOLUNTARY_REASON_COUNT:,} involuntary NULL-reason churn records (synthetic assumption)...")
    for i in range(NULL_INVOLUNTARY_REASON_COUNT):
        row = sample_term.iloc[i]
        c_id = str(row["customer_id"])
        s_id = str(row["subscription_id"])
        s_start = row["subscription_start_date"]
        c_date = row["subscription_end_date"]
        c_months = int(row["contract_months"])

        c_type = "involuntary"
        c_reason = None  # Deliberate DQ: involuntary churn with NULL reason

        elapsed_days = (c_date - s_start).days
        elapsed_m = max(0, int(elapsed_days / 30.4375))
        rem_m = max(0, c_months - elapsed_m)
        fee = Decimal(f"{min(1000, rem_m * 100):.2f}") if rem_m > 0 else Decimal("0.00")

        ret_att = False
        ret_off = None
        ret_acc = False

        sec_offset = int(rng.integers(0, 86400))
        c_created = pd.Timestamp(c_date) + pd.Timedelta(seconds=sec_offset)

        customer_ids.append(c_id)
        subscription_ids.append(s_id)
        churn_dates.append(c_date)
        churn_types.append(c_type)
        churn_reasons.append(c_reason)
        contract_remaining_months_list.append(rem_m)
        early_termination_fees.append(fee)
        retention_attempteds.append(ret_att)
        retention_offers.append(ret_off)
        retention_accepteds.append(ret_acc)
        created_ats.append(c_created)

    # -----------------------------------------------------------------------
    # Remaining 33,500 normal terminated subscriptions
    # -----------------------------------------------------------------------
    print(f"[generate] Generating remaining {term_needed - NULL_INVOLUNTARY_REASON_COUNT:,} normal churn events...")
    for i in range(NULL_INVOLUNTARY_REASON_COUNT, len(sample_term)):
        row = sample_term.iloc[i]
        c_id = str(row["customer_id"])
        s_id = str(row["subscription_id"])
        s_start = row["subscription_start_date"]
        c_date = row["subscription_end_date"]
        c_months = int(row["contract_months"])
        term_reason = row["termination_reason"]

        if term_reason == "non_payment":
            c_type = "involuntary"
            c_reason = "non_payment"
            is_vol = False
        elif term_reason == "service_issue":
            c_type = "voluntary"
            c_reason = "service_quality"
            is_vol = True
        elif term_reason in VOLUNTARY_REASONS:
            c_type = "voluntary"
            c_reason = str(term_reason)
            is_vol = True
        else:
            c_type = "voluntary"
            c_reason = str(rng.choice(list(VOLUNTARY_REASONS)))
            is_vol = True

        elapsed_days = (c_date - s_start).days
        elapsed_m = max(0, int(elapsed_days / 30.4375))
        rem_m = max(0, c_months - elapsed_m)

        if rem_m > 0:
            fee = Decimal("0.00") if (is_vol and rng.random() < 0.20) else Decimal(f"{min(1000, rem_m * 100):.2f}")
        else:
            fee = Decimal("0.00")

        if is_vol and rng.random() < 0.60:
            ret_att = True
            ret_off = str(rng.choice(list(RETENTION_OFFERS)))
            ret_acc = bool(rng.random() < 0.05)
        else:
            ret_att = False
            ret_off = None
            ret_acc = False

        sec_offset = int(rng.integers(0, 86400))
        c_created = pd.Timestamp(c_date) + pd.Timedelta(seconds=sec_offset)

        customer_ids.append(c_id)
        subscription_ids.append(s_id)
        churn_dates.append(c_date)
        churn_types.append(c_type)
        churn_reasons.append(c_reason)
        contract_remaining_months_list.append(rem_m)
        early_termination_fees.append(fee)
        retention_attempteds.append(ret_att)
        retention_offers.append(ret_off)
        retention_accepteds.append(ret_acc)
        created_ats.append(c_created)

    # 5. Assemble PyArrow RecordBatch
    print("[assemble] Constructing RecordBatch with exact Arrow schema...")
    batch = pa.RecordBatch.from_arrays(
        [
            pa.array(churn_event_ids, type=pa.string()),
            pa.array(customer_ids, type=pa.string()),
            pa.array(subscription_ids, type=pa.string()),
            pa.array(churn_dates, type=pa.date32()),
            pa.array(churn_types, type=pa.string()),
            pa.array(churn_reasons, type=pa.string()),
            pa.array(contract_remaining_months_list, type=pa.int64()),
            pa.array(early_termination_fees, type=pa.decimal128(10, 2)),
            pa.array(retention_attempteds, type=pa.bool_()),
            pa.array(retention_offers, type=pa.string()),
            pa.array(retention_accepteds, type=pa.bool_()),
            pa.array(created_ats, type=pa.timestamp("ns")),
        ],
        schema=OUTPUT_SCHEMA,
    )

    # 6. Write output to Snappy-compressed Parquet atomically
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temp_output_path = OUTPUT_DIR / f"{OUTPUT_PATH.name}.tmp"

    if temp_output_path.exists():
        temp_output_path.unlink()

    print(f"[write] Writing Parquet to {OUTPUT_PATH}...")
    table = pa.Table.from_batches([batch])
    pq.write_table(table, temp_output_path, compression="snappy")

    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()
    temp_output_path.replace(OUTPUT_PATH)
    print(f"[write] Successfully saved {OUTPUT_PATH}")

    # ---------------------------------------------------------------------------
    # 7. FINAL PHYSICAL VALIDATION OF WRITTEN PARQUET
    # ---------------------------------------------------------------------------
    print("\n[validate] Reading back and strictly validating final Parquet dataset...")
    output_reader = pq.ParquetFile(OUTPUT_PATH)
    output_rows = output_reader.metadata.num_rows

    if output_rows != CHURN_EVENT_COUNT:
        raise AssertionError(f"Expected {CHURN_EVENT_COUNT} rows, found {output_rows}.")

    schema_arrow = output_reader.schema_arrow
    expected_col_names = [f.name for f in OUTPUT_SCHEMA]
    actual_col_names = list(schema_arrow.names)
    if actual_col_names != expected_col_names:
        raise AssertionError(
            f"Columns mismatch: expected {expected_col_names}, got {actual_col_names}"
        )

    # Validate physical types
    if schema_arrow.field("churn_event_id").type != pa.string():
        raise AssertionError("churn_event_id physical type must be string.")
    if schema_arrow.field("customer_id").type != pa.string():
        raise AssertionError("customer_id physical type must be string.")
    if schema_arrow.field("subscription_id").type != pa.string():
        raise AssertionError("subscription_id physical type must be string.")
    if schema_arrow.field("churn_date").type != pa.date32():
        raise AssertionError("churn_date physical type must be date32.")
    if schema_arrow.field("churn_type").type != pa.string():
        raise AssertionError("churn_type physical type must be string.")
    if schema_arrow.field("churn_reason").type != pa.string():
        raise AssertionError("churn_reason physical type must be string.")
    if schema_arrow.field("contract_remaining_months").type != pa.int64():
        raise AssertionError("contract_remaining_months physical type must be int64.")
    if schema_arrow.field("early_termination_fee").type != pa.decimal128(10, 2):
        raise AssertionError("early_termination_fee physical type must be decimal128(10, 2).")
    if schema_arrow.field("retention_attempted").type != pa.bool_():
        raise AssertionError("retention_attempted physical type must be bool.")
    if schema_arrow.field("retention_offer").type != pa.string():
        raise AssertionError("retention_offer physical type must be string.")
    if schema_arrow.field("retention_accepted").type != pa.bool_():
        raise AssertionError("retention_accepted physical type must be bool.")
    if schema_arrow.field("created_at").type != pa.timestamp("ns"):
        raise AssertionError("created_at physical type must be timestamp[ns].")

    # Read back with pandas for content validation
    output = pd.read_parquet(OUTPUT_PATH)

    # 1. churn_event_id uniqueness and non-null
    null_churn_id = int(output["churn_event_id"].isna().sum())
    if null_churn_id != 0:
        raise AssertionError(f"Found {null_churn_id} NULL churn_event_id.")
    duplicate_churn_id = int(output["churn_event_id"].duplicated().sum())
    if duplicate_churn_id != 0:
        raise AssertionError(f"Found {duplicate_churn_id} duplicate churn_event_id.")

    # 2. Relationship integrity: orphan FKs & customer/subscription match
    orphan_cust_count = int((~output["customer_id"].isin(valid_customer_ids)).sum())
    if orphan_cust_count != 0:
        raise AssertionError(f"Found {orphan_cust_count} orphan customer IDs.")

    sub_lookup = sub_df.set_index("subscription_id")
    orphan_sub_count = int((~output["subscription_id"].isin(sub_lookup.index)).sum())
    if orphan_sub_count != 0:
        raise AssertionError(f"Found {orphan_sub_count} orphan subscription IDs.")

    # Check customer/subscription match
    expected_customers = sub_lookup.loc[output["subscription_id"], "customer_id"].to_numpy()
    actual_customers = output["customer_id"].to_numpy()
    mismatch_count = int((expected_customers != actual_customers).sum())
    if mismatch_count != 0:
        raise AssertionError(f"Found {mismatch_count} customer/subscription mismatches.")

    # 3. Active-subscription churn DQ count
    sub_statuses = sub_lookup.loc[output["subscription_id"], "status"].to_numpy()
    active_churn_count = int((sub_statuses == "active").sum())
    if active_churn_count != ACTIVE_STATUS_CHURN_COUNT:
        raise AssertionError(
            f"Expected {ACTIVE_STATUS_CHURN_COUNT} active-subscription churn records, found {active_churn_count}."
        )

    # 4. Churn types domain
    actual_types = set(output["churn_type"].unique())
    invalid_types = actual_types - set(ALLOWED_CHURN_TYPES)
    if len(invalid_types) != 0:
        raise AssertionError(f"Invalid churn types found: {invalid_types}")

    # 5. Involuntary NULL-reason DQ count
    null_reason_mask = output["churn_reason"].isna()
    involuntary_mask = output["churn_type"] == "involuntary"
    invol_null_reason_count = int((involuntary_mask & null_reason_mask).sum())
    if invol_null_reason_count != NULL_INVOLUNTARY_REASON_COUNT:
        raise AssertionError(
            f"Expected {NULL_INVOLUNTARY_REASON_COUNT} involuntary NULL-reason records, found {invol_null_reason_count}."
        )

    # Ensure NO other rows have NULL churn_reason
    total_null_reason_count = int(null_reason_mask.sum())
    if total_null_reason_count != NULL_INVOLUNTARY_REASON_COUNT:
        raise AssertionError(
            f"Unexpected NULL churn reasons found: total {total_null_reason_count}, expected {NULL_INVOLUNTARY_REASON_COUNT}"
        )

    # 6. Churn reasons domain (for non-null records)
    actual_reasons = set(output["churn_reason"].dropna().unique())
    invalid_reasons = actual_reasons - set(ALLOWED_CHURN_REASONS)
    if len(invalid_reasons) != 0:
        raise AssertionError(f"Invalid churn reasons found: {invalid_reasons}")

    # 7. Non-negative contract_remaining_months
    negative_months = int((output["contract_remaining_months"] < 0).sum())
    if negative_months != 0:
        raise AssertionError(f"Found {negative_months} negative contract_remaining_months.")

    # 8. Non-negative early_termination_fee
    negative_fee = int((output["early_termination_fee"] < 0).sum())
    if negative_fee != 0:
        raise AssertionError(f"Found {negative_fee} negative early_termination_fee.")

    # 9. Boolean fields validation
    invalid_ret_att = int((~output["retention_attempted"].isin([True, False])).sum())
    invalid_ret_acc = int((~output["retention_accepted"].isin([True, False])).sum())
    invalid_boolean_fields = invalid_ret_att + invalid_ret_acc
    if invalid_boolean_fields != 0:
        raise AssertionError("Invalid boolean values found in retention fields.")

    # 10. Date range validation: 2024-01-01 through 2025-06-30
    date_range_violations = int(
        ((output["churn_date"] < date(2024, 1, 1)) | (output["churn_date"] > date(2025, 6, 30))).sum()
    )
    if date_range_violations != 0:
        raise AssertionError(f"Found {date_range_violations} churn_date range violations.")

    # ---------------------------------------------------------------------------
    # 8. FORMATTED REPORT
    # ---------------------------------------------------------------------------
    print(f"\n[generated] src_churn_events {output_rows:,} rows \u2192 {OUTPUT_PATH}")
    print("\nChurn event generation complete.")

    print("\nSchema:")
    for field in schema_arrow:
        print(f"  {field.name}: {field.type}")

    print("\nDQ expectations:")
    print(f"  active-subscription churn        : synthetic assumption = {ACTIVE_STATUS_CHURN_COUNT:,}")
    print(f"  involuntary NULL-reason churn   : synthetic assumption = {NULL_INVOLUNTARY_REASON_COUNT:,}")

    print("\nDQ validation:")
    print(f"  row count                   : {output_rows:,}")
    print(f"  duplicate churn_event_id    : {duplicate_churn_id:,}")
    print(f"  orphan customer IDs         : {orphan_cust_count:,}")
    print(f"  orphan subscription IDs     : {orphan_sub_count:,}")
    print(f"  customer/subscription mismatches: {mismatch_count:,}")
    print(f"  active-subscription churn count: {active_churn_count:,}")
    print(f"  involuntary NULL-reason count: {invol_null_reason_count:,}")
    print(f"  invalid churn_type count    : {len(invalid_types):,}")
    print(f"  invalid churn_reason count  : {len(invalid_reasons):,}")
    print(f"  negative contract_remaining_months: {negative_months:,}")
    print(f"  negative early_termination_fee: {negative_fee:,}")
    print(f"  invalid boolean fields      : {invalid_boolean_fields:,}")
    print(f"  date-range violations       : {date_range_violations:,}")

    print("\nOutput:")
    print(f"  {OUTPUT_PATH}")


def main() -> None:
    generate_churn_events()


if __name__ == "__main__":
    main()
