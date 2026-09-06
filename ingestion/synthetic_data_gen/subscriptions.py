"""
MYConnect synthetic subscription generator.

Generates:
    src_subscriptions

Grain:
    One row per subscription

Target:
    350,000 rows

Canonical columns:
    subscription_id
    customer_id
    plan_id
    subscription_start_date
    subscription_end_date
    contract_months
    status
    monthly_recurring_charge
    installation_date
    installation_fee
    termination_reason
    promo_id
    created_at
    updated_at

Intentional DQ issues from the project specification:
    - ~800 orphan customer_id values
    - ~400 subscriptions where start_date > end_date
    - ~1,200 overlapping active subscriptions for the same customer
    - Some MRC values do not match plan price
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    DATASET_COUNTS,
    DATA_END_DATE,
    GENERATED_DATA_DIR,
    OUTPUT_FORMAT,
    RANDOM_SEED,
)
from .utils import (
    assert_required_columns,
    assert_row_count,
    assert_unique,
    get_rng,
    log_dataset_written,
    make_id_series,
    sample_indices,
    write_dataframe,
)

# ============================================================
# CONFIG
# ============================================================

DATASET_NAME = "subscriptions"

SUBSCRIPTION_COUNT = int(DATASET_COUNTS.get(DATASET_NAME, 350_000))

# Exact DQ targets from the pasted specification.
ORPHAN_CUSTOMER_COUNT = 800
INVALID_DATE_COUNT = 400
OVERLAPPING_ACTIVE_COUNT = 1_200

# The specification says "some" MRC values mismatch plan price.
# No exact count is specified, so this is an intentionally controlled
# portfolio assumption rather than a claimed source requirement.
MRC_MISMATCH_COUNT = 18_000


EXPECTED_COLUMNS = [
    "subscription_id",
    "customer_id",
    "plan_id",
    "subscription_start_date",
    "subscription_end_date",
    "contract_months",
    "status",
    "monthly_recurring_charge",
    "installation_date",
    "installation_fee",
    "termination_reason",
    "promo_id",
    "created_at",
    "updated_at",
]


STATUSES = [
    "active",
    "terminated",
    "suspended",
    "pending",
]

STATUS_PROBABILITIES = [
    0.72,
    0.18,
    0.07,
    0.03,
]

CONTRACT_MONTHS = [
    12,
    24,
]

CONTRACT_PROBABILITIES = [
    0.35,
    0.65,
]

TERMINATION_REASONS = [
    "competitor_switch",
    "relocation",
    "non_payment",
    "service_issue",
    "price",
]

PROMO_IDS = [f"PROMO-{i:03d}" for i in range(1, 31)]


# ============================================================
# SOURCE REFERENCES
# ============================================================


def load_source_customers() -> pd.DataFrame:
    """
    Load the already-generated customer dataset.

    This is used only to generate valid customer foreign keys for the
    normal subscription records. The 800 orphan IDs are injected later.
    """
    path = Path(GENERATED_DATA_DIR) / "customers" / "part-00000.parquet"

    if not path.exists():
        raise FileNotFoundError(
            "Customer source file not found:\n"
            f"  {path}\n\n"
            "Generate src_customers before src_subscriptions."
        )

    customers = pd.read_parquet(path)

    required = ["customer_id"]

    missing = [column for column in required if column not in customers.columns]

    if missing:
        raise ValueError(
            "Generated customers dataset is missing columns: " f"{missing}"
        )

    return customers[["customer_id"]].copy()


def load_source_plans() -> pd.DataFrame:
    """
    Load the already-generated 18-row plan catalogue.
    """
    path = Path(GENERATED_DATA_DIR) / "plans" / "part-00000.parquet"

    if not path.exists():
        raise FileNotFoundError(
            "Plan source file not found:\n"
            f"  {path}\n\n"
            "Generate src_plans before src_subscriptions."
        )

    plans = pd.read_parquet(path)

    required = [
        "plan_id",
        "monthly_price",
    ]

    missing = [column for column in required if column not in plans.columns]

    if missing:
        raise ValueError("Generated plans dataset is missing columns: " f"{missing}")

    return plans[
        [
            "plan_id",
            "monthly_price",
        ]
    ].copy()


# ============================================================
# DATE HELPERS
# ============================================================


def random_datetime_series(
    rng: np.random.Generator,
    start_date: date,
    end_date: date,
    size: int,
) -> pd.Series:
    """Generate random timestamps between two dates."""
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    total_seconds = int((end_ts - start_ts).total_seconds())

    if total_seconds < 0:
        raise ValueError("end_date must be >= start_date")

    offsets = rng.integers(
        0,
        total_seconds + 1,
        size=size,
    )

    return pd.Series(
        start_ts
        + pd.to_timedelta(
            offsets,
            unit="s",
        )
    )


def add_months_approx(
    values: pd.Series,
    rng: np.random.Generator,
    min_months: int,
    max_months: int,
) -> pd.Series:
    """
    Add an approximate number of contract months using 30-day months.

    The source schema cares about realistic contract durations rather than
    calendar-perfect contract arithmetic at ingestion time.
    """
    months = rng.integers(
        min_months,
        max_months + 1,
        size=len(values),
    )

    offsets = pd.to_timedelta(
        months * 30,
        unit="D",
    )

    return values + offsets


# ============================================================
# GENERATOR
# ============================================================


def generate_subscriptions() -> pd.DataFrame:
    """Generate the complete src_subscriptions dataframe."""
    rng = get_rng(RANDOM_SEED + 1)

    customers = load_source_customers()
    plans = load_source_plans()

    customer_ids = customers["customer_id"].astype("string")
    plan_ids = plans["plan_id"].astype("string")

    plan_price_map = dict(
        zip(
            plans["plan_id"].astype(str),
            plans["monthly_price"].astype(float),
        )
    )

    # --------------------------------------------------------
    # IDs
    # --------------------------------------------------------

    subscription_ids = make_id_series(
        prefix="SUB",
        start=1,
        count=SUBSCRIPTION_COUNT,
        width=6,
    )

    # --------------------------------------------------------
    # Customer assignment
    # --------------------------------------------------------

    """
    Construct the customer assignment deliberately:

    248,800 customers get one normal subscription.
    1,200 customers get a second overlapping ACTIVE subscription.
    The remaining 100,000 rows become historical/re-subscription records
    attached to existing customers and are generated mostly as
    terminated/suspended/pending.

    This creates the required 1,200 overlapping-active cases without relying
    on random assignment accidentally producing an unpredictable number.
    """

    unique_customer_count = len(customer_ids)

    if unique_customer_count < 2_500:
        raise ValueError("Not enough customers to construct subscription population.")

    # First 248,800 unique customers receive their primary subscription.
    primary_customer_ids = customer_ids.iloc[:248_800].to_numpy()

    # First 1,200 of those customers receive a second active subscription.
    overlap_customer_ids = customer_ids.iloc[:OVERLAPPING_ACTIVE_COUNT].to_numpy()

    remaining_count = (
        SUBSCRIPTION_COUNT - len(primary_customer_ids) - OVERLAPPING_ACTIVE_COUNT
    )

    historical_customer_ids = rng.choice(
        customer_ids.to_numpy(),
        size=remaining_count,
        replace=True,
    )

    assigned_customer_ids = np.concatenate(
        [
            primary_customer_ids,
            overlap_customer_ids,
            historical_customer_ids,
        ]
    )

    if len(assigned_customer_ids) != SUBSCRIPTION_COUNT:
        raise ValueError(
            "Subscription customer assignment produced " "an unexpected row count."
        )

    # --------------------------------------------------------
    # Plan assignment
    # --------------------------------------------------------

    assigned_plan_ids = rng.choice(
        plan_ids.to_numpy(),
        size=SUBSCRIPTION_COUNT,
        replace=True,
    )

    # --------------------------------------------------------
    # Contract length
    # --------------------------------------------------------

    contract_months = rng.choice(
        CONTRACT_MONTHS,
        size=SUBSCRIPTION_COUNT,
        p=CONTRACT_PROBABILITIES,
    )

    # --------------------------------------------------------
    # Status
    # --------------------------------------------------------

    status = rng.choice(
        STATUSES,
        size=SUBSCRIPTION_COUNT,
        p=STATUS_PROBABILITIES,
    )

    # --------------------------------------------------------
    # Control the subscription population
    # --------------------------------------------------------
    #
    # Rows 0:248,800
    #     Primary subscription per customer.
    #
    # Rows 248,800:250,000
    #     The exact 1,200 intentional overlapping active
    #     subscriptions.
    #
    # Rows 250,000:350,000
    #     Historical / re-subscription records.
    #     These MUST NOT be active, otherwise random reuse of
    #     customers would create unintended active overlaps.

    PRIMARY_SUBSCRIPTION_COUNT = 248_800

    overlap_start = PRIMARY_SUBSCRIPTION_COUNT
    overlap_end = PRIMARY_SUBSCRIPTION_COUNT + OVERLAPPING_ACTIVE_COUNT

    # Force the intended overlap records to ACTIVE.
    status[overlap_start:overlap_end] = "active"

    # Historical records cannot be active.
    historical_start = overlap_end

    historical_status_choices = rng.choice(
        [
            "terminated",
            "suspended",
            "pending",
        ],
        size=SUBSCRIPTION_COUNT - historical_start,
        p=[
            0.70,
            0.20,
            0.10,
        ],
    )

    status[historical_start:] = historical_status_choices

    # --------------------------------------------------------
    # Start dates
    # --------------------------------------------------------

    subscription_start_date = random_datetime_series(
        rng=rng,
        start_date=date(2022, 1, 1),
        end_date=DATA_END_DATE,
        size=SUBSCRIPTION_COUNT,
    ).dt.normalize()

    # --------------------------------------------------------
    # End dates
    # --------------------------------------------------------

    subscription_end_date = subscription_start_date.copy()

    # Generate normal end dates from contract duration.
    contract_days = contract_months * 30

    normal_end_dates = subscription_start_date + pd.to_timedelta(
        contract_days,
        unit="D",
    )

    subscription_end_date = normal_end_dates

    # Active subscriptions normally have NULL end dates.
    active_mask = status == "active"

    subscription_end_date.loc[active_mask] = pd.NaT

    # Pending subscriptions can also be open-ended.
    pending_mask = status == "pending"

    subscription_end_date.loc[pending_mask] = pd.NaT

    # --------------------------------------------------------
    # Force intentional active overlaps
    # --------------------------------------------------------

    """
    For each intended overlap customer:

        row A = active subscription
        row B = active subscription

    Both share customer_id and their date intervals overlap.

    Since active subscriptions have NULL end dates, the overlap is genuine
    from a temporal perspective.
    """

    primary_rows = np.arange(
        0,
        OVERLAPPING_ACTIVE_COUNT,
        dtype=np.int64,
    )

    overlap_rows = np.arange(
        248_800,
        248_800 + OVERLAPPING_ACTIVE_COUNT,
        dtype=np.int64,
    )

    overlap_start = subscription_start_date.iloc[primary_rows].reset_index(drop=True)

    # Put the second active subscription 30–120 days after the first.
    overlap_offsets = rng.integers(
        30,
        121,
        size=OVERLAPPING_ACTIVE_COUNT,
    )

    overlap_second_start = overlap_start + pd.to_timedelta(
        overlap_offsets,
        unit="D",
    )

    # subscription_start_date.iloc[overlap_rows] = overlap_second_start.to_numpy()

    subscription_start_date = subscription_start_date.copy()

    subscription_start_date.loc[subscription_start_date.index[overlap_rows]] = (
        overlap_second_start.to_numpy()
    )

    # subscription_end_date.iloc[primary_rows] = pd.NaT

    # subscription_end_date.iloc[overlap_rows] = pd.NaT

    subscription_end_date = subscription_end_date.copy()

    subscription_end_date.loc[subscription_end_date.index[primary_rows]] = pd.NaT

    subscription_end_date.loc[subscription_end_date.index[overlap_rows]] = pd.NaT

    # --------------------------------------------------------
    # Invalid start/end dates
    # --------------------------------------------------------

    invalid_indices = sample_indices(
        rng=rng,
        row_count=SUBSCRIPTION_COUNT,
        issue_count=INVALID_DATE_COUNT,
    )

    for index in invalid_indices:
        row_start = pd.Timestamp(subscription_start_date.iloc[index])

        # End intentionally before start.
        invalid_days_before = int(rng.integers(1, 365))

        subscription_end_date.iloc[index] = row_start - pd.Timedelta(
            days=invalid_days_before
        )

    # --------------------------------------------------------
    # MRC from plan price
    # --------------------------------------------------------

    base_mrc = np.array(
        [plan_price_map[str(plan_id)] for plan_id in assigned_plan_ids],
        dtype=float,
    )

    monthly_recurring_charge = np.round(
        base_mrc,
        2,
    )

    # --------------------------------------------------------
    # Promotion / legitimate discount pattern
    # --------------------------------------------------------

    promo_probability = 0.18

    promo_mask = rng.random(SUBSCRIPTION_COUNT) < promo_probability

    promo_id = np.full(
        SUBSCRIPTION_COUNT,
        pd.NA,
        dtype=object,
    )

    promo_indices = np.flatnonzero(promo_mask)

    if len(promo_indices) > 0:
        promo_id[promo_indices] = rng.choice(
            PROMO_IDS,
            size=len(promo_indices),
            replace=True,
        )

        promo_discounts = rng.choice(
            [0.05, 0.10, 0.15, 0.20],
            size=len(promo_indices),
            p=[0.35, 0.35, 0.20, 0.10],
        )

        monthly_recurring_charge[promo_indices] = np.round(
            monthly_recurring_charge[promo_indices] * (1 - promo_discounts),
            2,
        )

    # --------------------------------------------------------
    # Intentional MRC mismatches
    # --------------------------------------------------------

    """
    The source says that some MRC values don't match plan price and that
    legitimate promotional discounts exist alongside data errors.

    Therefore the injected mismatch group is created separately from the
    normal promo group.
    """

    mismatch_candidate_indices = np.flatnonzero(~promo_mask)

    if len(mismatch_candidate_indices) < MRC_MISMATCH_COUNT:
        raise ValueError(
            "Not enough non-promo subscriptions to inject " "MRC mismatches."
        )

    mismatch_indices = rng.choice(
        mismatch_candidate_indices,
        size=MRC_MISMATCH_COUNT,
        replace=False,
    )

    mismatch_factors = rng.choice(
        [0.80, 0.85, 0.90, 1.05, 1.10, 1.15],
        size=MRC_MISMATCH_COUNT,
        p=[
            0.20,
            0.20,
            0.20,
            0.15,
            0.15,
            0.10,
        ],
    )

    monthly_recurring_charge[mismatch_indices] = np.round(
        monthly_recurring_charge[mismatch_indices] * mismatch_factors,
        2,
    )

    # --------------------------------------------------------
    # Installation dates
    # --------------------------------------------------------

    installation_offsets = rng.integers(
        0,
        31,
        size=SUBSCRIPTION_COUNT,
    )

    installation_date = subscription_start_date + pd.to_timedelta(
        installation_offsets,
        unit="D",
    )

    # Occasionally installation occurs after start date,
    # matching the source note.
    installation_date = installation_date.dt.date

    # --------------------------------------------------------
    # Installation fees
    # --------------------------------------------------------

    installation_fee = rng.choice(
        [0.00, 99.00, 199.00],
        size=SUBSCRIPTION_COUNT,
        p=[0.65, 0.15, 0.20],
    )

    # Promo subscriptions are more likely to have waived fees.
    installation_fee[promo_mask] = np.where(
        rng.random(promo_mask.sum()) < 0.75,
        0.00,
        installation_fee[promo_mask],
    )

    installation_fee = np.round(
        installation_fee,
        2,
    )

    # --------------------------------------------------------
    # Termination reason
    # --------------------------------------------------------

    termination_reason = np.full(
        SUBSCRIPTION_COUNT,
        pd.NA,
        dtype=object,
    )

    terminated_indices = np.flatnonzero(status == "terminated")

    if len(terminated_indices) > 0:
        termination_reason[terminated_indices] = rng.choice(
            TERMINATION_REASONS,
            size=len(terminated_indices),
            replace=True,
        )

    # Suspended subscriptions can have non-payment reasons.
    suspended_indices = np.flatnonzero(status == "suspended")

    if len(suspended_indices) > 0:
        suspended_reason_mask = rng.random(len(suspended_indices)) < 0.35

        selected_suspended = suspended_indices[suspended_reason_mask]

        termination_reason[selected_suspended] = "non_payment"

    # --------------------------------------------------------
    # Orphan customer IDs
    # --------------------------------------------------------

    """
    Generate 800 customer IDs that do not exist in src_customers.
    They still look structurally valid but fail referential integrity.
    """

    orphan_row_indices = sample_indices(
        rng=rng,
        row_count=SUBSCRIPTION_COUNT,
        issue_count=ORPHAN_CUSTOMER_COUNT,
    )

    orphan_customer_ids = np.array(
        [f"CUST-ORPHAN-{i:04d}" for i in range(1, ORPHAN_CUSTOMER_COUNT + 1)],
        dtype=object,
    )

    # Avoid putting orphan IDs onto the intended overlap rows.
    overlap_set = set(overlap_rows.tolist())

    available_orphan_rows = [
        int(index) for index in orphan_row_indices if int(index) not in overlap_set
    ]

    # In the unlikely event that random sampling selected overlap rows,
    # replace those choices with safe rows.
    if len(available_orphan_rows) < ORPHAN_CUSTOMER_COUNT:
        safe_candidates = np.array(
            [
                i
                for i in range(SUBSCRIPTION_COUNT)
                if i not in overlap_set and i not in set(orphan_row_indices.tolist())
            ],
            dtype=np.int64,
        )

        replacement_count = ORPHAN_CUSTOMER_COUNT - len(available_orphan_rows)

        replacements = rng.choice(
            safe_candidates,
            size=replacement_count,
            replace=False,
        )

        available_orphan_rows.extend(replacements.tolist())

    available_orphan_rows = np.array(
        available_orphan_rows[:ORPHAN_CUSTOMER_COUNT],
        dtype=np.int64,
    )

    assigned_customer_ids[available_orphan_rows] = orphan_customer_ids

    # --------------------------------------------------------
    # Timestamps
    # --------------------------------------------------------

    created_at = random_datetime_series(
        rng=rng,
        start_date=date(2022, 1, 1),
        end_date=DATA_END_DATE,
        size=SUBSCRIPTION_COUNT,
    )

    updated_offsets = rng.integers(
        0,
        181,
        size=SUBSCRIPTION_COUNT,
    )

    updated_at = created_at + pd.to_timedelta(
        updated_offsets,
        unit="D",
    )

    # --------------------------------------------------------
    # Ensure temporal relationship between creation and start
    # --------------------------------------------------------

    start_timestamp = pd.to_datetime(subscription_start_date)

    # The record can be created slightly before or after the service start.
    created_at = start_timestamp - pd.to_timedelta(
        rng.integers(
            0,
            15,
            size=SUBSCRIPTION_COUNT,
        ),
        unit="D",
    )

    updated_at = created_at + pd.to_timedelta(
        rng.integers(
            0,
            181,
            size=SUBSCRIPTION_COUNT,
        ),
        unit="D",
    )

    # --------------------------------------------------------
    # Build dataframe
    # --------------------------------------------------------

    df = pd.DataFrame(
        {
            "subscription_id": subscription_ids,
            "customer_id": pd.Series(
                assigned_customer_ids,
                dtype="string",
            ),
            "plan_id": pd.Series(
                assigned_plan_ids,
                dtype="string",
            ),
            "subscription_start_date": pd.to_datetime(subscription_start_date).dt.date,
            "subscription_end_date": pd.to_datetime(subscription_end_date).dt.date,
            "contract_months": pd.Series(
                contract_months,
                dtype="Int64",
            ),
            "status": pd.Series(
                status,
                dtype="string",
            ),
            "monthly_recurring_charge": pd.Series(
                monthly_recurring_charge,
                dtype="float64",
            ),
            "installation_date": pd.Series(
                installation_date,
            ),
            "installation_fee": pd.Series(
                installation_fee,
                dtype="float64",
            ),
            "termination_reason": pd.Series(
                termination_reason,
                dtype="string",
            ),
            "promo_id": pd.Series(
                promo_id,
                dtype="string",
            ),
            "created_at": pd.to_datetime(created_at),
            "updated_at": pd.to_datetime(updated_at),
        }
    )

    # --------------------------------------------------------
    # Final validation
    # --------------------------------------------------------

    assert_row_count(
        df=df,
        expected=SUBSCRIPTION_COUNT,
        dataset_name="src_subscriptions",
    )

    assert_required_columns(
        df=df,
        required_columns=EXPECTED_COLUMNS,
        dataset_name="src_subscriptions",
    )

    assert_unique(
        df=df,
        column="subscription_id",
        dataset_name="src_subscriptions",
    )

    # Exact source schema order.
    df = df[EXPECTED_COLUMNS]

    return df


# ============================================================
# OUTPUT
# ============================================================


def main() -> None:
    """Generate src_subscriptions and write it to disk."""
    df = generate_subscriptions()

    output_path = write_dataframe(
        df=df,
        output_dir=GENERATED_DATA_DIR,
        dataset_name=DATASET_NAME,
        part_number=0,
        output_format=OUTPUT_FORMAT,
    )

    log_dataset_written(
        dataset_name="src_subscriptions",
        rows=len(df),
        path=output_path,
    )

    print()
    print("Subscription generation complete.")
    print()

    print(df.head(10).to_string(index=False))

    print()
    print("Schema:")
    print(df.dtypes)

    print()
    print("DQ injection targets:")
    print(f"  orphan customer IDs       : " f"{ORPHAN_CUSTOMER_COUNT:,}")
    print(f"  invalid start/end dates   : " f"{INVALID_DATE_COUNT:,}")
    print(f"  overlapping active subs   : " f"{OVERLAPPING_ACTIVE_COUNT:,}")
    print(f"  MRC mismatch records      : " f"{MRC_MISMATCH_COUNT:,}")

    print()
    print("Relationship checks:")

    # --------------------------------------------------------
    # Orphan customer check
    # --------------------------------------------------------

    valid_customer_set = set(load_source_customers()["customer_id"].astype(str))

    # orphan_count = int(~df["customer_id"].astype(str).isin(valid_customer_set)).sum()

    orphan_count = int((~df["customer_id"].astype(str).isin(valid_customer_set)).sum())

    print(f"  orphan customer IDs       : " f"{orphan_count:,}")

    # --------------------------------------------------------
    # Invalid date check
    # --------------------------------------------------------

    start_dates = pd.to_datetime(df["subscription_start_date"])

    end_dates = pd.to_datetime(df["subscription_end_date"])

    invalid_date_count = int(
        (df["subscription_end_date"].notna() & (start_dates > end_dates)).sum()
    )

    print(f"  start > end records       : " f"{invalid_date_count:,}")

    # --------------------------------------------------------
    # Overlapping active subscriptions
    # --------------------------------------------------------

    active_df = df[df["status"] == "active"].copy()

    active_df["subscription_start_date"] = pd.to_datetime(
        active_df["subscription_start_date"]
    )

    # Every active subscription is open-ended in this source,
    # so multiple active subscriptions for one customer are
    # overlapping by definition.
    active_counts = active_df.groupby("customer_id").size()

    affected_customers = active_counts[active_counts > 1]

    overlapping_active_rows = int((affected_customers - 1).sum())

    affected_customer_count = int(len(affected_customers))

    print(f"  overlapping active rows : " f"{overlapping_active_rows:,}")

    print(f"  affected customers      : " f"{affected_customer_count:,}")

    print()
    print("Output:")
    print(f"  {output_path}")


if __name__ == "__main__":
    main()
