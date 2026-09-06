"""
MYConnect synthetic bill-line-item generator.

SOURCE CONTRACT: src_bill_line_items
Expected rows: 5,000,000
Columns: 7

DQ represented:
- ~2% of invoices have line-item sums that do not match invoice total_amount.
- Some line items have NULL charge_type.
- Negative amounts for adjustments/credits (legitimate).

Synthetic assumptions for unspecified "some":
- 50,000 NULL charge_type rows (1% of line items)
- 25,000 negative adjustment/credit rows

The generator is batch/vectorized and intentionally avoids a Python loop over
3,000,000 invoices.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# PATHS / CONFIG
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DATA_DIR = PROJECT_ROOT / "generated"

BILLING_PATH = GENERATED_DATA_DIR / "billing" / "part-00000.parquet"
SUBSCRIPTIONS_PATH = GENERATED_DATA_DIR / "subscriptions" / "part-00000.parquet"
PLANS_PATH = GENERATED_DATA_DIR / "plans" / "part-00000.parquet"

OUTPUT_DIR = GENERATED_DATA_DIR / "bill_line_items"
OUTPUT_PATH = OUTPUT_DIR / "part-00000.parquet"

RANDOM_SEED = 42

BILLING_COUNT = 3_000_000
LINE_ITEM_COUNT = 5_000_000

MISMATCH_INVOICE_COUNT = 60_000  # 2% of 3M
NULL_CHARGE_TYPE_COUNT = 50_000  # "some" -> explicit synthetic assumption
NEGATIVE_LINE_COUNT = 25_000  # "some" -> explicit synthetic assumption

BILLING_BATCH_SIZE = 100_000

TWO_LINE_INVOICE_COUNT = LINE_ITEM_COUNT - BILLING_COUNT  # 2,000,000


# ---------------------------------------------------------------------------
# LOOKUPS
# ---------------------------------------------------------------------------


def load_plan_names() -> dict[str, str]:
    if not PLANS_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {PLANS_PATH}")

    plans = pd.read_parquet(
        PLANS_PATH,
        columns=["plan_id", "plan_name"],
    )

    return dict(
        zip(
            plans["plan_id"].astype(str),
            plans["plan_name"].astype(str),
        )
    )


def load_subscription_plans() -> dict[str, str]:
    if not SUBSCRIPTIONS_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {SUBSCRIPTIONS_PATH}")

    subscriptions = pd.read_parquet(
        SUBSCRIPTIONS_PATH,
        columns=["subscription_id", "plan_id"],
    )

    return dict(
        zip(
            subscriptions["subscription_id"].astype(str),
            subscriptions["plan_id"].astype(str),
        )
    )


# ---------------------------------------------------------------------------
# BATCH GENERATOR
# ---------------------------------------------------------------------------


def build_batch(
    billing: pd.DataFrame,
    rng: np.random.Generator,
    plan_by_subscription: dict[str, str],
    plan_names: dict[str, str],
    global_invoice_offset: int,
    global_line_offset: int,
) -> pd.DataFrame:
    """
    Vectorized batch generator.

    Exactly 2 lines are generated for the first 2,000,000 invoices.
    The remaining 1,000,000 invoices receive exactly 1 line.

    Total = 2,000,000 * 2 + 1,000,000 * 1 = 5,000,000.
    """

    n = len(billing)

    local_invoice_pos = np.arange(
        n,
        dtype=np.int64,
    )

    global_invoice_pos = global_invoice_offset + local_invoice_pos

    # First 2M invoices have 2 lines; final 1M have 1 line.
    line_counts = np.where(
        global_invoice_pos < TWO_LINE_INVOICE_COUNT,
        2,
        1,
    ).astype(np.int8)

    # Flatten invoices into line rows.
    repeated_local = np.repeat(
        local_invoice_pos,
        line_counts,
    )

    repeated_global_invoice = np.repeat(
        global_invoice_pos,
        line_counts,
    )

    # 0 for first line, 1 for second line.
    starts = np.cumsum(line_counts) - line_counts
    line_position = (
        np.arange(
            len(repeated_local),
            dtype=np.int64,
        )
        - np.repeat(
            starts,
            line_counts,
        )
    ).astype(np.int8)

    # Global line positions are contiguous across batches.
    global_line_pos = global_line_offset + np.arange(
        len(repeated_local),
        dtype=np.int64,
    )

    invoice_ids = billing["invoice_id"].astype(str).to_numpy()

    subscription_ids = billing["subscription_id"].astype(str).to_numpy()

    total_amounts = (
        pd.to_numeric(
            billing["total_amount"],
            errors="coerce",
        )
        .fillna(0.0)
        .to_numpy(dtype=float)
    )

    created_values = pd.to_datetime(
        billing["created_at"],
        errors="coerce",
    ).to_numpy(dtype="datetime64[ns]")

    repeated_invoice_ids = invoice_ids[repeated_local]
    repeated_subscription_ids = subscription_ids[repeated_local]
    repeated_totals = total_amounts[repeated_local]
    repeated_created = created_values[repeated_local]

    # -----------------------------------------------------------------------
    # AMOUNTS
    # -----------------------------------------------------------------------

    amounts = np.empty(
        len(repeated_local),
        dtype=float,
    )

    flat_starts = np.cumsum(line_counts) - line_counts

    two_invoice_local = np.flatnonzero(line_counts == 2)

    if len(two_invoice_local):
        two_totals = total_amounts[two_invoice_local]

        first_amount = np.round(
            two_totals
            * rng.uniform(
                0.80,
                0.95,
                size=len(two_invoice_local),
            ),
            2,
        )

        second_amount = np.round(
            two_totals - first_amount,
            2,
        )

        first_flat = flat_starts[two_invoice_local]
        second_flat = first_flat + 1

        amounts[first_flat] = first_amount
        amounts[second_flat] = second_amount

    one_invoice_local = np.flatnonzero(line_counts == 1)

    if len(one_invoice_local):
        one_flat = flat_starts[one_invoice_local]

        amounts[one_flat] = total_amounts[one_invoice_local]

    # -----------------------------------------------------------------------
    # CHARGE TYPES
    # -----------------------------------------------------------------------

    charge_types = np.empty(
        len(repeated_local),
        dtype=object,
    )

    first_line_mask = line_position == 0

    charge_types[first_line_mask] = "monthly_recurring"

    second_line_mask = line_position == 1

    second_count = int(second_line_mask.sum())

    if second_count:
        charge_types[second_line_mask] = rng.choice(
            np.array(
                [
                    "installation",
                    "proration",
                    "adjustment",
                    "penalty",
                ],
                dtype=object,
            ),
            size=second_count,
            p=[
                0.20,
                0.35,
                0.35,
                0.10,
            ],
        )

    # -----------------------------------------------------------------------
    # NEGATIVE ADJUSTMENT / CREDIT LINES
    # -----------------------------------------------------------------------

    # Exactly 25,000 negative rows globally.
    negative_mask = second_line_mask & (global_line_pos < NEGATIVE_LINE_COUNT * 2)

    negative_indices = np.flatnonzero(negative_mask)[:NEGATIVE_LINE_COUNT]

    if len(negative_indices):
        negative_values = np.round(
            np.maximum(
                1.00,
                np.abs(amounts[negative_indices])
                * rng.uniform(
                    0.02,
                    0.12,
                    size=len(negative_indices),
                ),
            ),
            2,
        )

        amounts[negative_indices] = -negative_values

        charge_types[negative_indices] = "adjustment"

        # Make the first line absorb the negative
        # adjustment so the invoice remains reconciled.
        negative_invoice_local = repeated_local[negative_indices]

        negative_first_flat = flat_starts[negative_invoice_local]

        amounts[negative_first_flat] = np.round(
            total_amounts[negative_invoice_local] - amounts[negative_indices],
            2,
        )

    # -----------------------------------------------------------------------
    # 2% RECONCILIATION MISMATCH
    # -----------------------------------------------------------------------

    mismatch_invoice_mask = global_invoice_pos < MISMATCH_INVOICE_COUNT

    mismatch_first_lines = mismatch_invoice_mask[repeated_local] & first_line_mask

    mismatch_indices = np.flatnonzero(mismatch_first_lines)

    if len(mismatch_indices):
        mismatch_adjustment = np.round(
            np.maximum(
                0.50,
                np.abs(amounts[mismatch_indices])
                * rng.uniform(
                    0.01,
                    0.08,
                    size=len(mismatch_indices),
                ),
            ),
            2,
        )

        amounts[mismatch_indices] = np.round(
            amounts[mismatch_indices] + mismatch_adjustment,
            2,
        )

    # -----------------------------------------------------------------------
    # NULL CHARGE TYPE
    # -----------------------------------------------------------------------

    # Global line positions 0,100,200,...,4,999,900
    # give exactly 50,000 NULL rows across 5M rows.
    null_mask = global_line_pos % 100 == 0

    charge_types[null_mask] = None

    # -----------------------------------------------------------------------
    # DESCRIPTION
    # -----------------------------------------------------------------------

    # pandas.Series.map is substantially cheaper than a Python loop over
    # every generated line and keeps the implementation readable.
    subscription_plan_series = (
        pd.Series(
            repeated_subscription_ids,
        )
        .map(plan_by_subscription)
        .fillna("UNKNOWN")
    )

    plan_name_array = (
        subscription_plan_series.map(plan_names)
        .fillna("MYConnect Service")
        .to_numpy(dtype=object)
    )

    descriptions = np.empty(
        len(plan_name_array),
        dtype=object,
    )

    descriptions[:] = plan_name_array + " - Monthly"

    mask = charge_types == "installation"
    descriptions[mask] = plan_name_array[mask] + " - Installation"

    mask = charge_types == "proration"
    descriptions[mask] = plan_name_array[mask] + " - Proration"

    mask = charge_types == "adjustment"
    descriptions[mask] = plan_name_array[mask] + " - Adjustment"

    mask = charge_types == "penalty"
    descriptions[mask] = plan_name_array[mask] + " - Penalty"

    mask = pd.isna(charge_types)
    descriptions[mask] = plan_name_array[mask] + " - Charge Type Unclassified"

    # -----------------------------------------------------------------------
    # TIMESTAMPS
    # -----------------------------------------------------------------------

    created_at = pd.to_datetime(repeated_created) + pd.to_timedelta(
        rng.integers(
            0,
            3600,
            size=len(repeated_local),
        ),
        unit="s",
    )

    # -----------------------------------------------------------------------
    # IDs
    # -----------------------------------------------------------------------

    line_numbers = global_line_pos + 1

    line_item_ids = np.array(
        [f"BLI-{number:08d}" for number in line_numbers],
        dtype=object,
    )

    return pd.DataFrame(
        {
            "line_item_id": pd.Series(
                line_item_ids,
                dtype="string",
            ),
            "invoice_id": pd.Series(
                repeated_invoice_ids,
                dtype="string",
            ),
            "charge_type": pd.Series(
                charge_types,
                dtype="string",
            ),
            "description": pd.Series(
                descriptions,
                dtype="string",
            ),
            "amount": pd.Series(
                amounts,
                dtype="float64",
            ),
            "quantity": pd.Series(
                np.ones(
                    len(repeated_local),
                    dtype=np.int64,
                ),
                dtype="Int64",
            ),
            "created_at": created_at,
        }
    )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main() -> None:
    rng = np.random.default_rng(RANDOM_SEED)

    if not BILLING_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {BILLING_PATH}")

    if not SUBSCRIPTIONS_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {SUBSCRIPTIONS_PATH}")

    if not PLANS_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {PLANS_PATH}")

    billing_metadata = pq.ParquetFile(BILLING_PATH).metadata

    if billing_metadata.num_rows != BILLING_COUNT:
        raise ValueError(
            f"Expected {BILLING_COUNT:,} billing rows, found "
            f"{billing_metadata.num_rows:,}."
        )

    plan_names = load_plan_names()
    plan_by_subscription = load_subscription_plans()

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    output_schema = pa.schema(
        [
            ("line_item_id", pa.string()),
            ("invoice_id", pa.string()),
            ("charge_type", pa.string()),
            ("description", pa.string()),
            ("amount", pa.decimal128(10, 2)),
            ("quantity", pa.int64()),
            ("created_at", pa.timestamp("ns")),
        ]
    )

    writer = pq.ParquetWriter(
        OUTPUT_PATH,
        schema=output_schema,
        compression="snappy",
    )

    total_written = 0
    invoice_offset = 0
    line_offset = 0

    try:
        billing_reader = pq.ParquetFile(BILLING_PATH)

        for batch in billing_reader.iter_batches(
            batch_size=BILLING_BATCH_SIZE,
            columns=[
                "invoice_id",
                "subscription_id",
                "total_amount",
                "created_at",
            ],
        ):
            billing = batch.to_pandas()

            lines = build_batch(
                billing=billing,
                rng=rng,
                plan_by_subscription=plan_by_subscription,
                plan_names=plan_names,
                global_invoice_offset=invoice_offset,
                global_line_offset=line_offset,
            )

            lines["amount"] = [
                Decimal(f"{float(value):.2f}") for value in lines["amount"].to_numpy()
            ]

            table = pa.Table.from_pandas(
                lines,
                schema=output_schema,
                preserve_index=False,
            )

            writer.write_table(table)

            rows_written = len(lines)

            total_written += rows_written
            invoice_offset += len(billing)
            line_offset += rows_written

            print(
                f"[progress] invoices={invoice_offset:,}/{BILLING_COUNT:,} "
                f"lines={total_written:,}/{LINE_ITEM_COUNT:,}"
            )

    finally:
        writer.close()

    # -----------------------------------------------------------------------
    # FINAL VALIDATION
    # -----------------------------------------------------------------------

    output_reader = pq.ParquetFile(OUTPUT_PATH)

    output_rows = output_reader.metadata.num_rows

    if output_rows != LINE_ITEM_COUNT:
        raise AssertionError(
            f"Expected {LINE_ITEM_COUNT:,} line items, found " f"{output_rows:,}."
        )

    null_count = 0
    negative_count = 0
    id_breaks = 0

    previous_line_number = 0

    for batch in output_reader.iter_batches(
        batch_size=BILLING_BATCH_SIZE,
        columns=[
            "line_item_id",
            "charge_type",
            "amount",
        ],
    ):
        chunk = batch.to_pandas()

        null_count += int(chunk["charge_type"].isna().sum())

        negative_count += int((chunk["amount"] < 0).sum())

        numbers = (
            chunk["line_item_id"]
            .astype(str)
            .str.split("-")
            .str[-1]
            .astype(int)
            .to_numpy()
        )

        if numbers[0] != previous_line_number + 1:
            id_breaks += 1

        if len(numbers) > 1 and np.any(np.diff(numbers) != 1):
            id_breaks += 1

        previous_line_number = int(numbers[-1])

    if null_count != NULL_CHARGE_TYPE_COUNT:
        raise AssertionError(
            f"Expected {NULL_CHARGE_TYPE_COUNT:,} NULL charge_type rows, "
            f"found {null_count:,}."
        )

    if negative_count < NEGATIVE_LINE_COUNT:
        raise AssertionError(
            f"Expected at least {NEGATIVE_LINE_COUNT:,} negative rows, "
            f"found {negative_count:,}."
        )

    if id_breaks != 0:
        raise AssertionError(
            f"Line-item ID sequence validation failed: " f"{id_breaks:,} break(s)."
        )

    print(
        f"\n[generated] src_bill_line_items " f"{output_rows:,} rows  →  {OUTPUT_PATH}"
    )

    print("\nBill line-item generation complete.")

    print("\nSchema:")
    print(
        pd.read_parquet(
            OUTPUT_PATH,
            engine="pyarrow",
        ).dtypes
    )

    print("\nDQ expectations:")
    print(
        f"  invoice reconciliation mismatch : "
        f"~{MISMATCH_INVOICE_COUNT:,} invoices (2%)"
    )
    print(
        f"  NULL charge_type                : "
        f"{NULL_CHARGE_TYPE_COUNT:,} "
        f"(synthetic assumption for 'some')"
    )
    print(
        f"  injected negative adjustment rows : "
        f"{NEGATIVE_LINE_COUNT:,} "
        f"(synthetic assumption for 'some')"
    )

    print("\nDQ validation:")
    print(f"  row count                       : " f"{output_rows:,}")
    print(f"  NULL charge_type                : " f"{null_count:,}")
    print(f"  negative amount rows            : " f"{negative_count:,}")
    print(f"  line-item ID sequence breaks    : " f"{id_breaks:,}")
    print(
        f"  mismatch invoices              : "
        f"{MISMATCH_INVOICE_COUNT:,} (constructed)"
    )

    print("\nOutput:")
    print(f"  {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
