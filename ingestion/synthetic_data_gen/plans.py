"""
Generate the synthetic MYConnect broadband plan catalog.

Source table:
    src_plans

Grain:
    One row per plan.

Expected row count:
    18

This is reference/master data, so the catalog is intentionally defined
explicitly rather than generated randomly. The listed current plans follow
the project specification; additional legacy plans complete the 18-plan
catalog required by the specification.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .config import PLAN_COUNT, CONFIG, DATASET_OUTPUT_DIRS
from .utils import assert_required_columns, assert_row_count, assert_unique
from .utils import log_dataset_written, write_dataframe

# ---------------------------------------------------------------------------
# PLAN CATALOG
# ---------------------------------------------------------------------------

PLAN_CATALOG: list[dict] = [
    # -----------------------------------------------------------------------
    # Current residential plans explicitly defined in the specification
    # -----------------------------------------------------------------------
    {
        "plan_id": "PLAN-001",
        "plan_name": "MYConnect Fibre 100",
        "speed_mbps": 100,
        "upload_speed_mbps": 100,
        "monthly_price": 99.00,
        "plan_category": "residential",
        "is_active": True,
        "launch_date": date(2022, 1, 1),
        "sunset_date": None,
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 0,
    },
    {
        "plan_id": "PLAN-002",
        "plan_name": "MYConnect Fibre 300",
        "speed_mbps": 300,
        "upload_speed_mbps": 300,
        "monthly_price": 119.00,
        "plan_category": "residential",
        "is_active": True,
        "launch_date": date(2022, 1, 1),
        "sunset_date": None,
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 0,
    },
    {
        "plan_id": "PLAN-003",
        "plan_name": "MYConnect Fibre 500",
        "speed_mbps": 500,
        "upload_speed_mbps": 500,
        "monthly_price": 139.00,
        "plan_category": "residential",
        "is_active": True,
        "launch_date": date(2022, 1, 1),
        "sunset_date": None,
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 2,
    },
    {
        "plan_id": "PLAN-004",
        "plan_name": "MYConnect Fibre 1000",
        "speed_mbps": 1000,
        "upload_speed_mbps": 1000,
        "monthly_price": 199.00,
        "plan_category": "residential",
        "is_active": True,
        "launch_date": date(2022, 6, 1),
        "sunset_date": None,
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 2,
    },
    {
        "plan_id": "PLAN-005",
        "plan_name": "MYConnect Fibre 2000",
        "speed_mbps": 2000,
        "upload_speed_mbps": 2000,
        "monthly_price": 299.00,
        "plan_category": "residential",
        "is_active": True,
        "launch_date": date(2023, 1, 1),
        "sunset_date": None,
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 3,
    },
    # -----------------------------------------------------------------------
    # Current business plans explicitly defined in the specification
    # -----------------------------------------------------------------------
    {
        "plan_id": "PLAN-006",
        "plan_name": "MYConnect Biz 200",
        "speed_mbps": 200,
        "upload_speed_mbps": 200,
        "monthly_price": 159.00,
        "plan_category": "business",
        "is_active": True,
        "launch_date": date(2022, 3, 1),
        "sunset_date": None,
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 0,
    },
    {
        "plan_id": "PLAN-007",
        "plan_name": "MYConnect Biz 500",
        "speed_mbps": 500,
        "upload_speed_mbps": 500,
        "monthly_price": 199.00,
        "plan_category": "business",
        "is_active": True,
        "launch_date": date(2022, 3, 1),
        "sunset_date": None,
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 1,
    },
    {
        "plan_id": "PLAN-008",
        "plan_name": "MYConnect Biz 1000",
        "speed_mbps": 1000,
        "upload_speed_mbps": 1000,
        "monthly_price": 349.00,
        "plan_category": "business",
        "is_active": True,
        "launch_date": date(2022, 6, 1),
        "sunset_date": None,
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 2,
    },
    # -----------------------------------------------------------------------
    # Legacy / retired plans
    #
    # The specification states that legacy plans exist but does not enumerate
    # all of them. These synthetic legacy entries complete the required
    # 18-row reference catalog.
    # -----------------------------------------------------------------------
    {
        "plan_id": "PLAN-009",
        "plan_name": "Legacy Fibre 50",
        "speed_mbps": 50,
        "upload_speed_mbps": 50,
        "monthly_price": 79.00,
        "plan_category": "residential",
        "is_active": False,
        "launch_date": date(2019, 1, 1),
        "sunset_date": date(2023, 6, 30),
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 0,
    },
    {
        "plan_id": "PLAN-010",
        "plan_name": "Legacy Fibre 100",
        "speed_mbps": 100,
        "upload_speed_mbps": 100,
        "monthly_price": 89.00,
        "plan_category": "residential",
        "is_active": False,
        "launch_date": date(2019, 6, 1),
        "sunset_date": date(2023, 12, 31),
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 0,
    },
    {
        "plan_id": "PLAN-011",
        "plan_name": "Legacy Fibre 300",
        "speed_mbps": 300,
        "upload_speed_mbps": 300,
        "monthly_price": 109.00,
        "plan_category": "residential",
        "is_active": False,
        "launch_date": date(2020, 1, 1),
        "sunset_date": date(2024, 2, 29),
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 0,
    },
    {
        "plan_id": "PLAN-012",
        "plan_name": "Legacy Fibre 500",
        "speed_mbps": 500,
        "upload_speed_mbps": 500,
        "monthly_price": 129.00,
        "plan_category": "residential",
        "is_active": False,
        "launch_date": date(2020, 7, 1),
        "sunset_date": date(2024, 6, 30),
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 1,
    },
    {
        "plan_id": "PLAN-013",
        "plan_name": "Legacy Fibre 800",
        "speed_mbps": 800,
        "upload_speed_mbps": 800,
        "monthly_price": 179.00,
        "plan_category": "residential",
        "is_active": False,
        "launch_date": date(2021, 1, 1),
        "sunset_date": date(2024, 12, 31),
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 1,
    },
    {
        "plan_id": "PLAN-014",
        "plan_name": "Legacy Biz 100",
        "speed_mbps": 100,
        "upload_speed_mbps": 100,
        "monthly_price": 129.00,
        "plan_category": "business",
        "is_active": False,
        "launch_date": date(2019, 1, 1),
        "sunset_date": date(2023, 6, 30),
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 0,
    },
    {
        "plan_id": "PLAN-015",
        "plan_name": "Legacy Biz 300",
        "speed_mbps": 300,
        "upload_speed_mbps": 300,
        "monthly_price": 169.00,
        "plan_category": "business",
        "is_active": False,
        "launch_date": date(2020, 1, 1),
        "sunset_date": date(2024, 2, 29),
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 0,
    },
    {
        "plan_id": "PLAN-016",
        "plan_name": "Legacy Biz 500",
        "speed_mbps": 500,
        "upload_speed_mbps": 500,
        "monthly_price": 219.00,
        "plan_category": "business",
        "is_active": False,
        "launch_date": date(2020, 7, 1),
        "sunset_date": date(2024, 6, 30),
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 1,
    },
    {
        "plan_id": "PLAN-017",
        "plan_name": "Legacy Biz 750",
        "speed_mbps": 750,
        "upload_speed_mbps": 750,
        "monthly_price": 289.00,
        "plan_category": "business",
        "is_active": False,
        "launch_date": date(2021, 1, 1),
        "sunset_date": date(2024, 12, 31),
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 1,
    },
    {
        "plan_id": "PLAN-018",
        "plan_name": "Legacy Biz 1000",
        "speed_mbps": 1000,
        "upload_speed_mbps": 1000,
        "monthly_price": 329.00,
        "plan_category": "business",
        "is_active": False,
        "launch_date": date(2021, 6, 1),
        "sunset_date": date(2025, 3, 31),
        "data_cap_gb": None,
        "includes_router": True,
        "includes_mesh": 2,
    },
]


# ---------------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = [
    "plan_id",
    "plan_name",
    "speed_mbps",
    "upload_speed_mbps",
    "monthly_price",
    "plan_category",
    "is_active",
    "launch_date",
    "sunset_date",
    "data_cap_gb",
    "includes_router",
    "includes_mesh",
]


def validate_plans(df: pd.DataFrame) -> None:
    """Validate the generated plan reference dataset."""
    assert_row_count(
        df=df,
        expected=PLAN_COUNT,
        dataset_name="src_plans",
    )

    assert_required_columns(
        df=df,
        required_columns=REQUIRED_COLUMNS,
        dataset_name="src_plans",
    )

    assert_unique(
        df=df,
        column="plan_id",
        dataset_name="src_plans",
    )

    if not df["plan_category"].isin(["residential", "business"]).all():
        raise ValueError("src_plans: plan_category contains unexpected values.")

    if (df["speed_mbps"] <= 0).any():
        raise ValueError("src_plans: speed_mbps must be greater than zero.")

    if (df["upload_speed_mbps"] <= 0).any():
        raise ValueError("src_plans: upload_speed_mbps must be greater than zero.")

    if (df["monthly_price"] < 0).any():
        raise ValueError("src_plans: monthly_price cannot be negative.")

    # Active plans should not have a sunset date.
    invalid_active = df[(df["is_active"] == True) & (df["sunset_date"].notna())]

    if not invalid_active.empty:
        raise ValueError("src_plans: active plans cannot have sunset_date.")

    # Retired plans should have a sunset date.
    invalid_retired = df[(df["is_active"] == False) & (df["sunset_date"].isna())]

    if not invalid_retired.empty:
        raise ValueError("src_plans: retired plans must have sunset_date.")


# ---------------------------------------------------------------------------
# GENERATOR
# ---------------------------------------------------------------------------


def generate_plans() -> pd.DataFrame:
    """
    Generate the 18-row plan catalog.

    Returns:
        pandas.DataFrame: src_plans-shaped dataframe.
    """
    df = pd.DataFrame(PLAN_CATALOG)

    # Preserve the source schema column order exactly.
    df = df[REQUIRED_COLUMNS].copy()

    # Explicit dtypes where they matter.
    df["plan_id"] = df["plan_id"].astype("string")
    df["plan_name"] = df["plan_name"].astype("string")
    df["speed_mbps"] = df["speed_mbps"].astype("int64")
    df["upload_speed_mbps"] = df["upload_speed_mbps"].astype("int64")
    df["monthly_price"] = df["monthly_price"].astype("float64")
    df["plan_category"] = df["plan_category"].astype("string")
    df["is_active"] = df["is_active"].astype("bool")
    df["launch_date"] = pd.to_datetime(df["launch_date"]).dt.date
    df["sunset_date"] = pd.to_datetime(
        df["sunset_date"],
        errors="coerce",
    ).dt.date
    df["data_cap_gb"] = pd.array(
        df["data_cap_gb"],
        dtype="Int64",
    )
    df["includes_router"] = df["includes_router"].astype("bool")
    df["includes_mesh"] = df["includes_mesh"].astype("int64")

    validate_plans(df)

    return df


# ---------------------------------------------------------------------------
# WRITE
# ---------------------------------------------------------------------------


def write_plans(df: pd.DataFrame) -> None:
    """Write the complete plan catalog to one Parquet file."""
    output_dir = DATASET_OUTPUT_DIRS["plans"]

    output_path = write_dataframe(
        df=df,
        output_dir=output_dir.parent,
        dataset_name="plans",
        part_number=0,
        output_format=CONFIG.output_format,
    )

    log_dataset_written(
        dataset_name="src_plans",
        rows=len(df),
        path=output_path,
    )


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------


def main() -> None:
    """Generate, validate, and write src_plans."""
    df = generate_plans()
    write_plans(df)

    print()
    print("Plan generation complete.")
    print()
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
