"""
MYConnect synthetic payment generator.

SOURCE CONTRACT: src_payments
Expected rows: 2,800,000
Columns: 9 (exact order)
1. payment_id        VARCHAR(20), PK
2. invoice_id        VARCHAR(20), FK -> src_billing
3. customer_id       VARCHAR(20), FK -> src_customers
4. payment_date      DATE
5. payment_amount    DECIMAL(10,2)
6. payment_method    VARCHAR(30)
7. payment_status    VARCHAR(20)
8. reference_number  VARCHAR(50)
9. created_at        TIMESTAMP

Allowed payment_method values:
- credit_card
- fpx
- auto_debit
- cash

Allowed payment_status values:
- success
- failed
- reversed
- pending

Contractual Data Quality Targets:
- ~3,000 duplicate payments (same invoice_id + payment_date + payment_amount, different payment_id)
- ~5,000 orphan invoice_id values (not in src_billing)
- ~2,000 reversed payments
- Some payments exceed invoice amount (overpayments)
- Partial payments where payment_amount < invoice total

Synthetic Assumptions for Unspecified "some":
- 20,000 overpayments
- 1,200,000 partial payments

Architecture & Performance:
- Disjoint index populations guarantee exact DQ targets without cross-contamination.
- Vectorized NumPy / PyArrow operations; zero row-by-row Python loops.
- Batched Parquet streaming with snappy compression.
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

BILLING_PATH = GENERATED_DATA_DIR / "billing" / "part-00000.parquet"
CUSTOMERS_PATH = GENERATED_DATA_DIR / "customers" / "part-00000.parquet"

OUTPUT_DIR = GENERATED_DATA_DIR / "payments"
OUTPUT_PATH = OUTPUT_DIR / "part-00000.parquet"

RANDOM_SEED = 42

PAYMENT_COUNT = 2_800_000

# Contractual DQ targets
DUPLICATE_PAYMENT_COUNT = 3_000
ORPHAN_PAYMENT_COUNT = 5_000
REVERSED_PAYMENT_COUNT = 2_000

# Explicit synthetic assumptions for unspecified quantities
OVERPAYMENT_COUNT = 20_000
PARTIAL_PAYMENT_COUNT = 1_200_000

BATCH_SIZE = 100_000

ALLOWED_METHODS = ("credit_card", "fpx", "auto_debit", "cash")
ALLOWED_STATUSES = ("success", "failed", "reversed", "pending")

OUTPUT_SCHEMA = pa.schema(
    [
        ("payment_id", pa.string()),
        ("invoice_id", pa.string()),
        ("customer_id", pa.string()),
        ("payment_date", pa.date32()),
        ("payment_amount", pa.decimal128(10, 2)),
        ("payment_method", pa.string()),
        ("payment_status", pa.string()),
        ("reference_number", pa.string()),
        ("created_at", pa.timestamp("ns")),
    ]
)


# ---------------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------------


def generate_payments() -> None:
    """Generate the synthetic src_payments dataset with exact contractual DQ requirements."""
    rng = np.random.default_rng(RANDOM_SEED)

    if not BILLING_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {BILLING_PATH}")

    if not CUSTOMERS_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {CUSTOMERS_PATH}")

    print("[load] Reading billing table...")
    billing_tbl = pq.read_table(
        BILLING_PATH,
        columns=["invoice_id", "customer_id", "invoice_date", "total_amount"],
    )
    b_invoice_ids = billing_tbl["invoice_id"].to_numpy(zero_copy_only=False)
    b_customer_ids = billing_tbl["customer_id"].to_numpy(zero_copy_only=False)
    b_invoice_dates = billing_tbl["invoice_date"].to_numpy(zero_copy_only=False)
    b_totals = billing_tbl["total_amount"].to_numpy(zero_copy_only=False)

    if len(b_invoice_ids) != 3_000_000:
        raise ValueError(f"Expected 3,000,000 billing rows, found {len(b_invoice_ids):,}.")

    print("[load] Reading customers table...")
    cust_tbl = pq.read_table(CUSTOMERS_PATH, columns=["customer_id"])
    valid_customer_ids = cust_tbl["customer_id"].to_numpy(zero_copy_only=False)

    # -----------------------------------------------------------------------
    # POPULATION PARTITIONING (DISJOINT DESIGN)
    # -----------------------------------------------------------------------
    # Total rows = 2,800,000
    # Base valid payments: 2,792,000
    # Duplicate payments:      3,000 (cloned from duplicate_source_pos in base)
    # Orphan payments:         5,000 (synthetic invoice IDs not in billing)
    base_valid_count = PAYMENT_COUNT - DUPLICATE_PAYMENT_COUNT - ORPHAN_PAYMENT_COUNT

    # Payments are made against positive invoices (total_amount > 0).
    positive_indices = np.flatnonzero(b_totals > 0)
    if len(positive_indices) < base_valid_count:
        raise ValueError(
            f"Not enough positive invoices ({len(positive_indices):,}) for base payments ({base_valid_count:,})."
        )

    print(
        f"[sample] Selecting {base_valid_count:,} unique invoices from "
        f"{len(positive_indices):,} positive billing rows..."
    )
    base_selected = rng.choice(positive_indices, size=base_valid_count, replace=False)

    base_inv_ids = b_invoice_ids[base_selected]
    base_cust_ids = b_customer_ids[base_selected]
    base_inv_dates = b_invoice_dates[base_selected]
    base_totals = b_totals[base_selected]

    # Partition base into mutually disjoint populations:
    # 1. partial_pos (1,200,000)
    # 2. over_pos (20,000)
    # 3. rev_pos (2,000)
    # 4. dup_source_pos (3,000)
    # 5. remaining are standard full payments
    print("[partition] Allocating mutually disjoint DQ populations...")
    partial_pos = rng.choice(
        base_valid_count,
        size=PARTIAL_PAYMENT_COUNT,
        replace=False,
    )

    rem_1 = np.setdiff1d(
        np.arange(base_valid_count),
        partial_pos,
        assume_unique=True,
    )
    over_pos = rng.choice(
        rem_1,
        size=OVERPAYMENT_COUNT,
        replace=False,
    )

    rem_2 = np.setdiff1d(
        rem_1,
        over_pos,
        assume_unique=True,
    )
    rev_pos = rng.choice(
        rem_2,
        size=REVERSED_PAYMENT_COUNT,
        replace=False,
    )

    rem_3 = np.setdiff1d(
        rem_2,
        rev_pos,
        assume_unique=True,
    )
    dup_source_pos = rng.choice(
        rem_3,
        size=DUPLICATE_PAYMENT_COUNT,
        replace=False,
    )

    # -----------------------------------------------------------------------
    # AMOUNTS
    # -----------------------------------------------------------------------
    base_amounts = base_totals.copy()

    # Partials: strictly < invoice total_amount and >= 0.01
    partial_factors = rng.uniform(0.20, 0.90, size=PARTIAL_PAYMENT_COUNT)
    p_amounts = np.round(base_totals[partial_pos] * partial_factors, 2)
    p_amounts = np.minimum(p_amounts, base_totals[partial_pos] - 0.01)
    p_amounts = np.maximum(p_amounts, 0.01)
    base_amounts[partial_pos] = p_amounts

    # Overpayments: strictly > invoice total_amount
    over_factors = rng.uniform(1.05, 1.35, size=OVERPAYMENT_COUNT)
    o_amounts = np.round(base_totals[over_pos] * over_factors, 2)
    o_amounts = np.maximum(o_amounts, base_totals[over_pos] + 0.01)
    base_amounts[over_pos] = o_amounts

    # -----------------------------------------------------------------------
    # METHODS, STATUSES, DATES
    # -----------------------------------------------------------------------
    method_choices = np.array(list(ALLOWED_METHODS), dtype=object)
    base_methods = rng.choice(
        method_choices,
        size=base_valid_count,
        p=[0.30, 0.30, 0.35, 0.05],
    )

    # Base statuses: generated from success/failed/pending ONLY
    base_statuses = rng.choice(
        np.array(["success", "failed", "pending"], dtype=object),
        size=base_valid_count,
        p=[0.90, 0.06, 0.04],
    )
    # Explicitly assign exactly 2,000 reversed payments to rev_pos
    base_statuses[rev_pos] = "reversed"

    # payment_date: 0-30 days after invoice_date
    day_offsets = rng.integers(0, 31, size=base_valid_count).astype("timedelta64[D]")
    base_payment_dates = base_inv_dates + day_offsets

    # created_at: on payment_date + random seconds
    sec_offsets = rng.integers(0, 86400, size=base_valid_count).astype("timedelta64[s]")
    base_created_at = (
        base_payment_dates.astype("datetime64[s]") + sec_offsets
    ).astype("datetime64[ns]")

    # -----------------------------------------------------------------------
    # DELIBERATE DUPLICATE PAYMENTS (3,000 ROWS)
    # -----------------------------------------------------------------------
    # Business key (invoice_id, payment_date, payment_amount) cloned from dup_source_pos.
    # Statuses NEVER reversed; customer_id consistent with invoice.
    print("[dq] Constructing 3,000 duplicate business-key payments...")
    dup_inv_ids = base_inv_ids[dup_source_pos]
    dup_cust_ids = base_cust_ids[dup_source_pos]
    dup_payment_dates = base_payment_dates[dup_source_pos]
    dup_amounts = base_amounts[dup_source_pos]
    dup_methods = base_methods[dup_source_pos]

    dup_statuses = rng.choice(
        np.array(["failed", "success", "pending"], dtype=object),
        size=DUPLICATE_PAYMENT_COUNT,
        p=[0.70, 0.20, 0.10],
    )
    dup_delay = rng.integers(30, 1800, size=DUPLICATE_PAYMENT_COUNT).astype("timedelta64[s]")
    dup_created_at = (
        base_created_at[dup_source_pos].astype("datetime64[s]") + dup_delay
    ).astype("datetime64[ns]")

    # -----------------------------------------------------------------------
    # DELIBERATE ORPHAN PAYMENTS (5,000 ROWS)
    # -----------------------------------------------------------------------
    # Synthetic invoice IDs not in billing; valid customer IDs; statuses NEVER reversed.
    print("[dq] Constructing 5,000 deliberate orphan invoice payments...")
    orphan_inv_ids = np.array(
        [f"INV-ORPH-{n:06d}" for n in range(1, ORPHAN_PAYMENT_COUNT + 1)],
        dtype=object,
    )
    orphan_cust_ids = rng.choice(valid_customer_ids, size=ORPHAN_PAYMENT_COUNT, replace=True)
    orphan_payment_dates = rng.choice(base_payment_dates, size=ORPHAN_PAYMENT_COUNT)
    orphan_amounts = np.round(rng.uniform(20.00, 350.00, size=ORPHAN_PAYMENT_COUNT), 2)
    orphan_methods = rng.choice(
        method_choices,
        size=ORPHAN_PAYMENT_COUNT,
        p=[0.30, 0.30, 0.35, 0.05],
    )
    orphan_statuses = rng.choice(
        np.array(["success", "failed", "pending"], dtype=object),
        size=ORPHAN_PAYMENT_COUNT,
        p=[0.85, 0.10, 0.05],
    )
    orphan_sec = rng.integers(0, 86400, size=ORPHAN_PAYMENT_COUNT).astype("timedelta64[s]")
    orphan_created_at = (
        orphan_payment_dates.astype("datetime64[s]") + orphan_sec
    ).astype("datetime64[ns]")

    # -----------------------------------------------------------------------
    # CONCATENATE EXACTLY TO 2,800,000 ROWS
    # -----------------------------------------------------------------------
    print("[assemble] Concatenating disjoint populations to 2,800,000 rows...")
    all_invoice_ids = np.concatenate([base_inv_ids, dup_inv_ids, orphan_inv_ids])
    all_customer_ids = np.concatenate([base_cust_ids, dup_cust_ids, orphan_cust_ids])
    all_payment_dates = np.concatenate([base_payment_dates, dup_payment_dates, orphan_payment_dates])
    all_amounts = np.concatenate([base_amounts, dup_amounts, orphan_amounts])
    all_methods = np.concatenate([base_methods, dup_methods, orphan_methods])
    all_statuses = np.concatenate([base_statuses, dup_statuses, orphan_statuses])
    all_created_at = np.concatenate([base_created_at, dup_created_at, orphan_created_at])

    if len(all_invoice_ids) != PAYMENT_COUNT:
        raise ValueError(
            f"Expected {PAYMENT_COUNT:,} assembled rows, got {len(all_invoice_ids):,}."
        )

    # -----------------------------------------------------------------------
    # GLOBAL UNIQUE PAYMENT IDs & REFERENCE NUMBERS
    # -----------------------------------------------------------------------
    print("[assemble] Generating global payment IDs and reference numbers...")
    numbers = np.arange(1, PAYMENT_COUNT + 1, dtype=np.int64)
    all_payment_ids = [f"PAY-{n:08d}" for n in numbers]

    prefix_map = np.select(
        [
            all_methods == "credit_card",
            all_methods == "fpx",
            all_methods == "auto_debit",
            all_methods == "cash",
        ],
        ["CC", "FPX", "AD", "CASH"],
        default="PAY",
    )

    date_compact = np.char.replace(
        np.datetime_as_string(all_payment_dates, unit="D"),
        "-",
        "",
    )
    all_ref_numbers = [
        f"{p}-{d}-{n:08d}"
        for p, d, n in zip(prefix_map, date_compact, numbers)
    ]

    # -----------------------------------------------------------------------
    # SAFELY WRITE BATCHED PARQUET OUTPUT
    # -----------------------------------------------------------------------
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
        for start_idx in range(0, PAYMENT_COUNT, BATCH_SIZE):
            end_idx = min(start_idx + BATCH_SIZE, PAYMENT_COUNT)
            batch_record = pa.RecordBatch.from_arrays(
                [
                    pa.array(all_payment_ids[start_idx:end_idx], type=pa.string()),
                    pa.array(all_invoice_ids[start_idx:end_idx], type=pa.string()),
                    pa.array(all_customer_ids[start_idx:end_idx], type=pa.string()),
                    pa.array(all_payment_dates[start_idx:end_idx], type=pa.date32()),
                    pc.cast(
                        pa.array(all_amounts[start_idx:end_idx], type=pa.float64()),
                        pa.decimal128(10, 2),
                    ),
                    pa.array(all_methods[start_idx:end_idx], type=pa.string()),
                    pa.array(all_statuses[start_idx:end_idx], type=pa.string()),
                    pa.array(all_ref_numbers[start_idx:end_idx], type=pa.string()),
                    pa.array(all_created_at[start_idx:end_idx], type=pa.timestamp("ns")),
                ],
                schema=OUTPUT_SCHEMA,
            )
            writer.write_batch(batch_record)
            pct = (end_idx / PAYMENT_COUNT) * 100.0
            print(f"[progress] written {end_idx:,} / {PAYMENT_COUNT:,} rows ({pct:.1f}%)")
    finally:
        writer.close()

    # Atomically replace target Parquet file
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()
    temp_output_path.replace(OUTPUT_PATH)
    print(f"[write] Successfully saved {OUTPUT_PATH}")

    # -----------------------------------------------------------------------
    # FINAL VALIDATION OF SAVED PARQUET DATASET
    # -----------------------------------------------------------------------
    print("\n[validate] Validating final Parquet dataset...")
    output_reader = pq.ParquetFile(OUTPUT_PATH)
    output_rows = output_reader.metadata.num_rows

    if output_rows != PAYMENT_COUNT:
        raise AssertionError(f"Expected {PAYMENT_COUNT:,} rows, found {output_rows:,}.")

    schema_arrow = output_reader.schema_arrow
    expected_col_names = [f.name for f in OUTPUT_SCHEMA]
    actual_col_names = list(schema_arrow.names)
    if actual_col_names != expected_col_names:
        raise AssertionError(
            f"Columns mismatch: expected {expected_col_names}, got {actual_col_names}"
        )

    if schema_arrow.field("payment_amount").type != pa.decimal128(10, 2):
        raise AssertionError(
            f"payment_amount type mismatch: expected decimal128(10, 2), got {schema_arrow.field('payment_amount').type}"
        )

    if schema_arrow.field("payment_date").type != pa.date32():
        raise AssertionError(
            f"payment_date type mismatch: expected date32, got {schema_arrow.field('payment_date').type}"
        )

    # Read output table with pandas for data content validations
    output = pd.read_parquet(
        OUTPUT_PATH,
        columns=[
            "payment_id",
            "invoice_id",
            "customer_id",
            "payment_date",
            "payment_amount",
            "payment_method",
            "payment_status",
            "reference_number",
        ],
    )

    if not output["payment_id"].is_unique:
        raise AssertionError("payment_id is not globally unique.")

    actual_methods = set(output["payment_method"].unique())
    if not actual_methods.issubset(set(ALLOWED_METHODS)):
        raise AssertionError(f"Invalid payment methods found: {actual_methods - set(ALLOWED_METHODS)}")

    actual_statuses = set(output["payment_status"].unique())
    if not actual_statuses.issubset(set(ALLOWED_STATUSES)):
        raise AssertionError(f"Invalid payment statuses found: {actual_statuses - set(ALLOWED_STATUSES)}")

    max_ref_len = output["reference_number"].astype(str).str.len().max()
    if max_ref_len > 50:
        raise AssertionError(f"reference_number exceeds max length 50: {max_ref_len}")

    billing_ids = set(b_invoice_ids)
    orphan_count = int((~output["invoice_id"].astype(str).isin(billing_ids)).sum())
    if orphan_count != ORPHAN_PAYMENT_COUNT:
        raise AssertionError(
            f"Expected {ORPHAN_PAYMENT_COUNT:,} orphan payments, found {orphan_count:,}."
        )

    duplicate_business_keys = output.groupby(
        [
            "invoice_id",
            "payment_date",
            "payment_amount",
        ],
        dropna=False,
    ).size()
    duplicate_extra_rows = int((duplicate_business_keys - 1).clip(lower=0).sum())
    if duplicate_extra_rows != DUPLICATE_PAYMENT_COUNT:
        raise AssertionError(
            f"Expected {DUPLICATE_PAYMENT_COUNT:,} duplicate payment extra rows, found {duplicate_extra_rows:,}."
        )

    reversed_count = int((output["payment_status"] == "reversed").sum())
    if reversed_count != REVERSED_PAYMENT_COUNT:
        raise AssertionError(
            f"Expected {REVERSED_PAYMENT_COUNT:,} reversed payments, found {reversed_count:,}."
        )

    billing_totals_map = dict(zip(b_invoice_ids, b_totals))
    matched_invoice_totals = output["invoice_id"].astype(str).map(billing_totals_map)

    overpayment_count = int(
        (
            matched_invoice_totals.notna()
            & (output["payment_amount"].astype(float) > matched_invoice_totals)
        ).sum()
    )
    if overpayment_count != OVERPAYMENT_COUNT:
        raise AssertionError(
            f"Expected {OVERPAYMENT_COUNT:,} overpayments, found {overpayment_count:,}."
        )

    partial_count = int(
        (
            matched_invoice_totals.notna()
            & (output["payment_amount"].astype(float) < matched_invoice_totals)
        ).sum()
    )
    if partial_count != PARTIAL_PAYMENT_COUNT:
        raise AssertionError(
            f"Expected {PARTIAL_PAYMENT_COUNT:,} partial payments, found {partial_count:,}."
        )

    # -----------------------------------------------------------------------
    # PRINT RESULTS
    # -----------------------------------------------------------------------
    print(f"\n[generated] src_payments {output_rows:,} rows  →  {OUTPUT_PATH}")
    print("\nPayment generation complete.")

    print("\nSchema:")
    print(output_reader.schema_arrow)

    print("\nDQ expectations:")
    print(f"  duplicate payments       : ~{DUPLICATE_PAYMENT_COUNT:,}")
    print(f"  orphan invoice payments  : ~{ORPHAN_PAYMENT_COUNT:,}")
    print(f"  reversed payments        : ~{REVERSED_PAYMENT_COUNT:,}")
    print(f"  overpayments             : positive/plausible ({OVERPAYMENT_COUNT:,})")
    print(f"  partial payments         : positive/plausible ({PARTIAL_PAYMENT_COUNT:,})")

    print("\nDQ validation:")
    print(f"  row count                : {output_rows:,}")
    print(f"  duplicate payment rows   : {duplicate_extra_rows:,}")
    print(f"  orphan invoice_id        : {orphan_count:,}")
    print(f"  reversed payments        : {reversed_count:,}")
    print(f"  overpayments             : {overpayment_count:,}")
    print(f"  partial payments         : {partial_count:,}")

    print("\nOutput:")
    print(f"  {OUTPUT_PATH}")


def main() -> None:
    generate_payments()


if __name__ == "__main__":
    main()
