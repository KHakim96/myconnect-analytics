"""
MYConnect synthetic billing generator.

Contract: src_billing
Expected rows: 3,000,000
Columns: 13

Raw DQ intentionally injected:
- ~5,000 duplicate invoices (same subscription + billing period, new invoice_id)
- ~3,000 zero-amount invoices with status != void
- ~1,000 invoices with billing_period_start > billing_period_end
- ~2,000 invoices for terminated subscriptions (late billing)
- some negative amounts (credit notes)

The source contract specifies approximate DQ volumes. The generator uses exact
counts for the four quantified issues and 1,000 negative-credit-note rows as a
small deterministic synthetic assumption for "some negative amounts".
"""

from __future__ import annotations

import calendar
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# PROJECT / CONFIG
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DATA_DIR = PROJECT_ROOT / "generated"

SUBSCRIPTIONS_PATH = GENERATED_DATA_DIR / "subscriptions" / "part-00000.parquet"
OUTPUT_DIR = GENERATED_DATA_DIR / "billing"
OUTPUT_PATH = OUTPUT_DIR / "part-00000.parquet"

DATA_START = pd.Timestamp("2024-01-01")
DATA_END = pd.Timestamp("2025-06-30")
RANDOM_SEED = 42

INVOICE_COUNT = 3_000_000

DUPLICATE_COUNT = 5_000
ZERO_AMOUNT_COUNT = 3_000
INVALID_PERIOD_COUNT = 1_000
TERMINATED_BILLING_COUNT = 2_000
NEGATIVE_AMOUNT_COUNT = 1_000  # "some" = deterministic synthetic assumption


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def month_starts() -> list[pd.Timestamp]:
    """Return the 18 calendar months from 2024-01 through 2025-06."""
    return list(pd.date_range(DATA_START, DATA_END, freq="MS"))


def month_end(month_start: pd.Timestamp) -> pd.Timestamp:
    """Return the calendar month-end for a month-start timestamp."""
    return month_start + pd.offsets.MonthEnd(0)


def allocate_counts(total: int, buckets: int) -> list[int]:
    """Split total deterministically across buckets with max 1-row imbalance."""
    base, remainder = divmod(total, buckets)
    return [base + (1 if i < remainder else 0) for i in range(buckets)]


def money(value: float) -> float:
    return round(float(value), 2)


def invoice_status(
    rng: np.random.Generator,
    size: int,
) -> np.ndarray:
    return rng.choice(
        np.array(["paid", "unpaid", "overdue", "void"], dtype=object),
        size=size,
        p=[0.72, 0.14, 0.11, 0.03],
    )


def build_invoice_rows(
    subscriptions: pd.DataFrame,
    selected_idx: np.ndarray,
    month_start: pd.Timestamp,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Build one monthly invoice batch from subscription rows selected for that month.
    One row represents one subscription billing period.
    """
    month_finish = month_end(month_start)
    sub = subscriptions.iloc[selected_idx].copy()

    mrc = pd.to_numeric(
        sub["monthly_recurring_charge"],
        errors="coerce",
    ).fillna(0.0)

    # Discounts are synthetic billing-level discounts; subscription MRC already
    # contains promo pricing when applicable.
    discount = np.round(
        np.where(
            rng.random(len(sub)) < 0.12,
            mrc.to_numpy(dtype=float) * rng.uniform(0.05, 0.20, len(sub)),
            0.0,
        ),
        2,
    )

    # SST is applied to a subset of invoice service amounts.
    taxable = rng.random(len(sub)) < 0.55

    subtotal = np.maximum(
        mrc.to_numpy(dtype=float) - discount,
        0.0,
    )

    tax = np.round(
        np.where(taxable, subtotal * 0.06, 0.0),
        2,
    )

    total = np.round(
        subtotal + tax,
        2,
    )

    statuses = invoice_status(rng, len(sub))
    invoice_dates = month_finish + pd.Timedelta(days=1)
    due_dates = invoice_dates + pd.Timedelta(days=14)

    payment_offsets = rng.integers(
        0,
        31,
        size=len(sub),
    )

    payment_status_dates = invoice_dates + pd.to_timedelta(
        payment_offsets,
        unit="D",
    )

    created_offsets = rng.integers(
        0,
        4,
        size=len(sub),
    )

    created_at = (
        invoice_dates
        - pd.to_timedelta(
            created_offsets,
            unit="D",
        )
        + pd.to_timedelta(
            rng.integers(0, 86400, size=len(sub)),
            unit="s",
        )
    )

    invoice_date_values = invoice_dates.normalize()
    due_date_values = due_dates.normalize()

    return pd.DataFrame(
        {
            "invoice_id": pd.Series(dtype="string"),
            "subscription_id": sub["subscription_id"].astype("string").to_numpy(),
            "customer_id": sub["customer_id"].astype("string").to_numpy(),
            "billing_period_start": [d.date() for d in [month_start] * len(sub)],
            "billing_period_end": [d.date() for d in [month_finish] * len(sub)],
            "invoice_date": [invoice_date_values.date()] * len(sub),
            "due_date": [due_date_values.date()] * len(sub),
            "total_amount": total.astype(float),
            "tax_amount": tax.astype(float),
            "discount_amount": discount.astype(float),
            "status": pd.Series(statuses, dtype="string"),
            "payment_status_date": [d.date() for d in payment_status_dates.normalize()],
            "created_at": created_at,
        }
    )


def assign_invoice_ids(
    df: pd.DataFrame,
    start_number: int,
) -> None:
    """Assign deterministic unique invoice IDs in-place."""
    numbers = np.arange(
        start_number,
        start_number + len(df),
        dtype=np.int64,
    )

    df["invoice_id"] = pd.Series(
        [f"INV-{n:08d}" for n in numbers],
        dtype="string",
    )


def make_late_terminated_rows(
    subscriptions: pd.DataFrame,
    terminated_idx: np.ndarray,
    month_start: pd.Timestamp,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Create invoices whose billing period starts after the subscription ended.
    These are deliberate 'late billing' DQ rows.
    """
    month_finish = month_end(month_start)
    sub = subscriptions.iloc[terminated_idx].copy()

    mrc = (
        pd.to_numeric(
            sub["monthly_recurring_charge"],
            errors="coerce",
        )
        .fillna(0.0)
        .to_numpy(dtype=float)
    )

    discount = np.round(
        np.where(
            rng.random(len(sub)) < 0.10,
            mrc * rng.uniform(0.05, 0.15, len(sub)),
            0.0,
        ),
        2,
    )

    taxable = rng.random(len(sub)) < 0.50
    subtotal = np.maximum(mrc - discount, 0.0)
    tax = np.round(np.where(taxable, subtotal * 0.06, 0.0), 2)
    total = np.round(subtotal + tax, 2)

    invoice_date = month_finish + pd.Timedelta(days=1)
    due_date = invoice_date + pd.Timedelta(days=14)

    return pd.DataFrame(
        {
            "invoice_id": pd.Series(dtype="string"),
            "subscription_id": sub["subscription_id"].astype("string").to_numpy(),
            "customer_id": sub["customer_id"].astype("string").to_numpy(),
            "billing_period_start": [month_start.date()] * len(sub),
            "billing_period_end": [month_finish.date()] * len(sub),
            "invoice_date": [invoice_date.date()] * len(sub),
            "due_date": [due_date.date()] * len(sub),
            "total_amount": total.astype(float),
            "tax_amount": tax.astype(float),
            "discount_amount": discount.astype(float),
            "status": pd.Series(
                rng.choice(
                    ["unpaid", "overdue", "paid"],
                    size=len(sub),
                    p=[0.50, 0.35, 0.15],
                ),
                dtype="string",
            ),
            "payment_status_date": [due_date.date()] * len(sub),
            "created_at": (
                invoice_date
                - pd.to_timedelta(
                    rng.integers(0, 4, size=len(sub)),
                    unit="D",
                )
                + pd.to_timedelta(
                    rng.integers(0, 86400, size=len(sub)),
                    unit="s",
                )
            ),
        }
    )


def validate_contract(df: pd.DataFrame) -> None:
    expected_columns = [
        "invoice_id",
        "subscription_id",
        "customer_id",
        "billing_period_start",
        "billing_period_end",
        "invoice_date",
        "due_date",
        "total_amount",
        "tax_amount",
        "discount_amount",
        "status",
        "payment_status_date",
        "created_at",
    ]

    assert list(df.columns) == expected_columns
    assert len(df) == INVOICE_COUNT
    assert df["invoice_id"].is_unique

    allowed_statuses = {"paid", "unpaid", "overdue", "void"}
    assert set(df["status"].dropna().unique()).issubset(allowed_statuses)

    print("\nSchema:")
    print(df.dtypes)


def main() -> None:
    rng = np.random.default_rng(RANDOM_SEED)

    if not SUBSCRIPTIONS_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {SUBSCRIPTIONS_PATH}")

    subscriptions = pd.read_parquet(
        SUBSCRIPTIONS_PATH,
        columns=[
            "subscription_id",
            "customer_id",
            "subscription_start_date",
            "subscription_end_date",
            "monthly_recurring_charge",
            "status",
        ],
    )

    subscriptions["subscription_start_date"] = pd.to_datetime(
        subscriptions["subscription_start_date"],
        errors="coerce",
    )

    subscriptions["subscription_end_date"] = pd.to_datetime(
        subscriptions["subscription_end_date"],
        errors="coerce",
    )

    subscriptions["monthly_recurring_charge"] = pd.to_numeric(
        subscriptions["monthly_recurring_charge"],
        errors="coerce",
    ).fillna(0.0)

    # We first create exactly 2,995,000 base invoices. The remaining 5,000
    # rows are deliberate duplicate invoices with different invoice IDs.
    base_count = INVOICE_COUNT - DUPLICATE_COUNT

    months = month_starts()
    month_targets = allocate_counts(
        base_count,
        len(months),
    )

    terminated_mask = subscriptions["status"].eq("terminated")

    # For the deliberate "late billing" DQ, require the subscription to have
    # ended before the 2025-06 billing period starts. This makes the injected
    # records unambiguously late rather than merely occurring in the same
    # calendar month as termination.
    terminated_late_candidates = (
        terminated_mask
        & subscriptions["subscription_end_date"].notna()
        & (subscriptions["subscription_end_date"] < pd.Timestamp("2025-06-01"))
    )

    terminated_idx_all = np.flatnonzero(terminated_late_candidates.to_numpy())

    if len(terminated_idx_all) < TERMINATED_BILLING_COUNT:
        raise RuntimeError(
            "Not enough terminated subscriptions with an end date before "
            "2025-06-01 to create the requested "
            f"{TERMINATED_BILLING_COUNT:,} late-billing rows."
        )

    # Use a fixed terminated-subscription sample for the late-billing DQ.
    late_terminated_idx = rng.choice(
        terminated_idx_all,
        size=TERMINATED_BILLING_COUNT,
        replace=False,
    )

    # Select normal monthly eligible subscriptions.
    monthly_batches: list[pd.DataFrame] = []

    global_position = 0
    invoice_number = 1

    # Keep 5,000 valid source rows for the duplicate-invoice injection.
    duplicate_sources: list[pd.DataFrame] = []

    for month_index, (month_start, target) in enumerate(zip(months, month_targets)):
        month_finish = month_end(month_start)

        eligible_mask = (
            (subscriptions["subscription_start_date"] <= month_finish)
            & (
                subscriptions["subscription_end_date"].isna()
                | (subscriptions["subscription_end_date"] >= month_start)
            )
            & (
                ~terminated_mask
                | (subscriptions["subscription_end_date"] >= month_start)
            )
        )

        eligible_idx = np.flatnonzero(eligible_mask.to_numpy())

        if len(eligible_idx) < target:
            raise RuntimeError(
                f"Month {month_start:%Y-%m} has only "
                f"{len(eligible_idx):,} eligible subscriptions but "
                f"{target:,} invoices are required."
            )

        selected_idx = rng.choice(
            eligible_idx,
            size=target,
            replace=False,
        )

        batch = build_invoice_rows(
            subscriptions=subscriptions,
            selected_idx=selected_idx,
            month_start=month_start,
            rng=rng,
        )

        assign_invoice_ids(
            batch,
            invoice_number,
        )

        # Reserve 5,000 ordinary source rows for duplicate invoices.
        if sum(len(x) for x in duplicate_sources) < DUPLICATE_COUNT:
            need = DUPLICATE_COUNT - sum(len(x) for x in duplicate_sources)
            take = min(need, len(batch))
            if take:
                duplicate_sources.append(batch.iloc[:take].copy())

        monthly_batches.append(batch)

        invoice_number += len(batch)
        global_position += len(batch)

    base_df = pd.concat(
        monthly_batches,
        ignore_index=True,
    )

    # -----------------------------------------------------------------------
    # DQ INJECTION ON BASE DATA
    # -----------------------------------------------------------------------

    # 1) Zero total, non-void status: exact 3,000 rows.
    zero_idx = np.arange(
        0,
        ZERO_AMOUNT_COUNT,
        dtype=np.int64,
    )

    base_df.loc[zero_idx, "total_amount"] = 0.0
    base_df.loc[zero_idx, "tax_amount"] = 0.0
    base_df.loc[zero_idx, "discount_amount"] = 0.0
    base_df.loc[zero_idx, "status"] = "unpaid"

    # 2) Invalid period: exact 1,000 rows.
    invalid_start = ZERO_AMOUNT_COUNT
    invalid_end = invalid_start + INVALID_PERIOD_COUNT
    invalid_idx = np.arange(
        invalid_start,
        invalid_end,
        dtype=np.int64,
    )

    original_starts = pd.to_datetime(base_df.loc[invalid_idx, "billing_period_start"])
    original_ends = pd.to_datetime(base_df.loc[invalid_idx, "billing_period_end"])

    base_df.loc[invalid_idx, "billing_period_start"] = [d.date() for d in original_ends]
    base_df.loc[invalid_idx, "billing_period_end"] = [d.date() for d in original_starts]

    # 3) Negative credit-note amount: deterministic "some" = 1,000 rows.
    negative_start = invalid_end
    negative_end = negative_start + NEGATIVE_AMOUNT_COUNT
    negative_idx = np.arange(
        negative_start,
        negative_end,
        dtype=np.int64,
    )

    positive_amounts = pd.to_numeric(
        base_df.loc[negative_idx, "total_amount"],
        errors="coerce",
    ).fillna(0.0)

    credit_values = -np.maximum(
        np.round(
            positive_amounts.to_numpy(dtype=float)
            * rng.uniform(0.10, 1.00, len(negative_idx)),
            2,
        ),
        1.00,
    )

    base_df.loc[negative_idx, "total_amount"] = credit_values

    # 4) Replace exactly 2,000 base rows with invoices for terminated
    # subscriptions whose billing period is after termination.
    late_start = negative_end
    late_end = late_start + TERMINATED_BILLING_COUNT
    late_rows_idx = np.arange(
        late_start,
        late_end,
        dtype=np.int64,
    )

    late_month = months[-1]
    late_df = make_late_terminated_rows(
        subscriptions=subscriptions,
        terminated_idx=late_terminated_idx,
        month_start=late_month,
        rng=rng,
    )

    # Use new invoice IDs for the replaced rows.
    assign_invoice_ids(
        late_df,
        start_number=1,
    )

    # Retain the original invoice IDs for row identity stability.
    late_df["invoice_id"] = base_df.loc[
        late_rows_idx,
        "invoice_id",
    ].to_numpy()

    base_df.loc[
        late_rows_idx,
        [
            "subscription_id",
            "customer_id",
            "billing_period_start",
            "billing_period_end",
            "invoice_date",
            "due_date",
            "total_amount",
            "tax_amount",
            "discount_amount",
            "status",
            "payment_status_date",
            "created_at",
        ],
    ] = late_df[
        [
            "subscription_id",
            "customer_id",
            "billing_period_start",
            "billing_period_end",
            "invoice_date",
            "due_date",
            "total_amount",
            "tax_amount",
            "discount_amount",
            "status",
            "payment_status_date",
            "created_at",
        ]
    ].to_numpy()

    # -----------------------------------------------------------------------
    # DUPLICATE INVOICES
    # -----------------------------------------------------------------------

    duplicate_df = (
        pd.concat(
            duplicate_sources,
            ignore_index=True,
        )
        .iloc[:DUPLICATE_COUNT]
        .copy()
    )

    # New invoice IDs, same subscription + billing period.
    duplicate_start_number = INVOICE_COUNT - DUPLICATE_COUNT + 1

    assign_invoice_ids(
        duplicate_df,
        duplicate_start_number,
    )

    # Small created_at variation keeps the duplicate invoices realistic while
    # preserving the duplicate business key.
    duplicate_df["created_at"] = pd.to_datetime(
        duplicate_df["created_at"]
    ) + pd.to_timedelta(
        rng.integers(1, 86400, size=len(duplicate_df)),
        unit="s",
    )

    final_df = pd.concat(
        [base_df, duplicate_df],
        ignore_index=True,
    )

    # Re-assert contiguous unique invoice IDs.
    final_df["invoice_id"] = pd.Series(
        [f"INV-{n:08d}" for n in range(1, INVOICE_COUNT + 1)],
        dtype="string",
    )

    validate_contract(final_df)

    # -----------------------------------------------------------------------
    # DQ VALIDATION
    # -----------------------------------------------------------------------

    duplicate_business_keys = final_df.groupby(
        ["subscription_id", "billing_period_start", "billing_period_end"],
        dropna=False,
    ).size()

    duplicate_invoice_rows = int((duplicate_business_keys - 1).clip(lower=0).sum())

    zero_suspicious = int(
        ((final_df["total_amount"] == 0) & (final_df["status"] != "void")).sum()
    )

    invalid_periods = int(
        (
            pd.to_datetime(final_df["billing_period_start"])
            > pd.to_datetime(final_df["billing_period_end"])
        ).sum()
    )

    terminated_lookup = (
        subscriptions[
            [
                "subscription_id",
                "subscription_end_date",
            ]
        ]
        .dropna(subset=["subscription_end_date"])
        .assign(subscription_id=lambda x: x["subscription_id"].astype(str))
        .drop_duplicates("subscription_id")
        .set_index("subscription_id")["subscription_end_date"]
    )

    final_end_dates = final_df["subscription_id"].astype(str).map(terminated_lookup)

    terminated_billing_rows = int(
        (
            final_end_dates.notna()
            & (
                pd.to_datetime(final_df["billing_period_start"])
                > pd.to_datetime(final_end_dates)
            )
        ).sum()
    )

    negative_rows = int((final_df["total_amount"] < 0).sum())

    # -----------------------------------------------------------------------
    # OUTPUT
    # -----------------------------------------------------------------------

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    table = pa.Table.from_pandas(
        final_df,
        preserve_index=False,
    )

    pq.write_table(
        table,
        OUTPUT_PATH,
        compression="snappy",
    )

    print(f"\n[generated] src_billing " f"{len(final_df):,} rows  →  {OUTPUT_PATH}")

    print("\nBilling generation complete.")
    print("\nSchema:")
    print(final_df.dtypes)

    print("\nDQ injection targets:")
    print(f"  duplicate invoices       : {DUPLICATE_COUNT:,}")
    print(f"  zero total, non-void     : {ZERO_AMOUNT_COUNT:,}")
    print(f"  invalid start/end dates  : {INVALID_PERIOD_COUNT:,}")
    print(f"  terminated late billing  : {TERMINATED_BILLING_COUNT:,}")
    print(
        f"  negative credit notes    : "
        f"{NEGATIVE_AMOUNT_COUNT:,} "
        f"(synthetic assumption for 'some')"
    )

    print("\nDQ validation:")
    print(f"  duplicate business keys  : " f"{duplicate_invoice_rows:,}")
    print(f"  zero total, non-void     : " f"{zero_suspicious:,}")
    print(f"  start > end records      : " f"{invalid_periods:,}")
    print(f"  late billing after end   : " f"{terminated_billing_rows:,}")
    print(f"  negative amount rows     : " f"{negative_rows:,}")

    print(f"\nOutput:\n  {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
