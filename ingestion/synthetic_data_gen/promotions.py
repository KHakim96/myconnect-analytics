"""
MYConnect synthetic promotions generator.

SOURCE CONTRACT: src_promotions
Expected rows: 30
Columns: 10 (exact order)
1. promo_id              VARCHAR(20), PK
2. promo_name            VARCHAR(100)
3. promo_type            VARCHAR(30)
4. discount_amount       DECIMAL(10,2)
5. discount_percentage   DECIMAL(5,2) (nullable)
6. promo_duration_months INT
7. start_date            DATE
8. end_date              DATE
9. eligible_plans        VARCHAR(255)
10. is_active            BOOLEAN

Contractual Data Quality Targets:
- Some promos have end_date before start_date (synthetic assumption: 2 rows)
- eligible_plans is a comma-separated string (needs parsing downstream)

Deterministic Reference Date for is_active:
- SYNTHETIC_REFERENCE_DATE = date(2025, 1, 1)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# PATHS & CONFIGURATION
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DATA_DIR = PROJECT_ROOT / "generated"

PLANS_PATH = GENERATED_DATA_DIR / "plans" / "part-00000.parquet"
OUTPUT_DIR = GENERATED_DATA_DIR / "promotions"
OUTPUT_PATH = OUTPUT_DIR / "part-00000.parquet"

RANDOM_SEED = 42

PROMOTION_COUNT = 30
INVALID_DATE_COUNT = 2  # synthetic assumption

# Fixed deterministic synthetic reference date for determining campaign is_active state
SYNTHETIC_REFERENCE_DATE = date(2025, 1, 1)

ALLOWED_PROMO_TYPES = ("discount", "waived_installation", "free_upgrade", "cashback")

OUTPUT_SCHEMA = pa.schema(
    [
        ("promo_id", pa.string()),
        ("promo_name", pa.string()),
        ("promo_type", pa.string()),
        ("discount_amount", pa.decimal128(10, 2)),
        ("discount_percentage", pa.decimal128(5, 2)),
        ("promo_duration_months", pa.int64()),
        ("start_date", pa.date32()),
        ("end_date", pa.date32()),
        ("eligible_plans", pa.string()),
        ("is_active", pa.bool_()),
    ]
)

# ---------------------------------------------------------------------------
# PROMOTION CATALOG DEFINITIONS (30 promotions)
# ---------------------------------------------------------------------------

PROMOTIONS_DEFINITIONS: list[dict] = [
    {
        "promo_id": "PROMO-001",
        "promo_name": "New Year Fibre Fiesta 2024",
        "promo_type": "discount",
        "discount_amount": Decimal("20.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 2, 28),
        "eligible_plans": "PLAN-001,PLAN-002,PLAN-003",
    },
    {
        "promo_id": "PROMO-002",
        "promo_name": "CNY Huat Broadband Rebate",
        "promo_type": "cashback",
        "discount_amount": Decimal("88.00"),
        "discount_percentage": None,
        "promo_duration_months": 3,
        "start_date": date(2024, 1, 15),
        "end_date": date(2024, 2, 29),
        "eligible_plans": "PLAN-002,PLAN-003,PLAN-004",
    },
    {
        "promo_id": "PROMO-003",
        "promo_name": "Raya Special 2024",
        "promo_type": "discount",
        "discount_amount": Decimal("30.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2024, 3, 15),
        "end_date": date(2024, 4, 30),
        "eligible_plans": "PLAN-003,PLAN-004,PLAN-005",
    },
    {
        "promo_id": "PROMO-004",
        "promo_name": "Zero Installation Ramadan Promo",
        "promo_type": "waived_installation",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": None,
        "promo_duration_months": 12,
        "start_date": date(2024, 3, 1),
        "end_date": date(2024, 4, 15),
        "eligible_plans": "PLAN-001,PLAN-002",
    },
    {
        # Contractual DQ record 1: end_date < start_date (synthetic assumption)
        "promo_id": "PROMO-005",
        "promo_name": "Hari Raya Aidiladha Flash Deal",
        "promo_type": "discount",
        "discount_amount": Decimal("25.00"),
        "discount_percentage": None,
        "promo_duration_months": 3,
        "start_date": date(2024, 6, 15),
        "end_date": date(2024, 6, 1),
        "eligible_plans": "PLAN-002,PLAN-003",
    },
    {
        "promo_id": "PROMO-006",
        "promo_name": "Mid-Year Speed Doubler",
        "promo_type": "free_upgrade",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2024, 5, 1),
        "end_date": date(2024, 6, 30),
        "eligible_plans": "PLAN-001,PLAN-002",
    },
    {
        "promo_id": "PROMO-007",
        "promo_name": "Merdeka 67 Fibre Celebration",
        "promo_type": "discount",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": Decimal("15.00"),
        "promo_duration_months": 12,
        "start_date": date(2024, 8, 1),
        "end_date": date(2024, 9, 16),
        "eligible_plans": "PLAN-001,PLAN-002,PLAN-003,PLAN-004",
    },
    {
        "promo_id": "PROMO-008",
        "promo_name": "Malaysia Day Connectivity Rebate",
        "promo_type": "cashback",
        "discount_amount": Decimal("67.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2024, 9, 1),
        "end_date": date(2024, 9, 30),
        "eligible_plans": "PLAN-003,PLAN-004,PLAN-005",
    },
    {
        "promo_id": "PROMO-009",
        "promo_name": "Deepavali Lights Fibre Special",
        "promo_type": "discount",
        "discount_amount": Decimal("15.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2024, 10, 15),
        "end_date": date(2024, 11, 15),
        "eligible_plans": "PLAN-001,PLAN-002",
    },
    {
        "promo_id": "PROMO-010",
        "promo_name": "SME Digitalization Grant Partner",
        "promo_type": "discount",
        "discount_amount": Decimal("50.00"),
        "discount_percentage": None,
        "promo_duration_months": 24,
        "start_date": date(2024, 6, 1),
        "end_date": date(2024, 12, 31),
        "eligible_plans": "PLAN-006,PLAN-007,PLAN-008",
    },
    {
        "promo_id": "PROMO-011",
        "promo_name": "Gigabit Gamer Speed Boost",
        "promo_type": "free_upgrade",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": None,
        "promo_duration_months": 12,
        "start_date": date(2024, 7, 1),
        "end_date": date(2024, 12, 31),
        "eligible_plans": "PLAN-003,PLAN-004",
    },
    {
        "promo_id": "PROMO-012",
        "promo_name": "11.11 Mega Online Shopping Rebate",
        "promo_type": "cashback",
        "discount_amount": Decimal("50.00"),
        "discount_percentage": None,
        "promo_duration_months": 3,
        "start_date": date(2024, 11, 1),
        "end_date": date(2024, 11, 15),
        "eligible_plans": "PLAN-002,PLAN-003",
    },
    {
        "promo_id": "PROMO-013",
        "promo_name": "12.12 Year-End Countdown Saver",
        "promo_type": "discount",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": Decimal("20.00"),
        "promo_duration_months": 6,
        "start_date": date(2024, 12, 1),
        "end_date": date(2024, 12, 31),
        "eligible_plans": "PLAN-001,PLAN-002,PLAN-003",
    },
    {
        "promo_id": "PROMO-014",
        "promo_name": "Year-End Free Installation Gala",
        "promo_type": "waived_installation",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": None,
        "promo_duration_months": 12,
        "start_date": date(2024, 11, 15),
        "end_date": date(2024, 12, 31),
        "eligible_plans": "PLAN-001,PLAN-002,PLAN-003,PLAN-004,PLAN-005",
    },
    {
        # Contractual DQ record 2: end_date < start_date (synthetic assumption)
        "promo_id": "PROMO-015",
        "promo_name": "Christmas Home Fibre Special",
        "promo_type": "discount",
        "discount_amount": Decimal("20.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2024, 12, 15),
        "end_date": date(2024, 12, 1),
        "eligible_plans": "PLAN-001,PLAN-002",
    },
    {
        "promo_id": "PROMO-016",
        "promo_name": "New Year 2025 Resolution Fibre",
        "promo_type": "discount",
        "discount_amount": Decimal("20.00"),
        "discount_percentage": None,
        "promo_duration_months": 12,
        "start_date": date(2024, 12, 15),
        "end_date": date(2025, 1, 31),
        "eligible_plans": "PLAN-001,PLAN-002,PLAN-003",
    },
    {
        "promo_id": "PROMO-017",
        "promo_name": "CNY 2025 Prosperity Cashback",
        "promo_type": "cashback",
        "discount_amount": Decimal("100.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2024, 12, 20),
        "end_date": date(2025, 2, 15),
        "eligible_plans": "PLAN-003,PLAN-004,PLAN-005",
    },
    {
        "promo_id": "PROMO-018",
        "promo_name": "Biz Pro Fibre Upgrade Campaign",
        "promo_type": "free_upgrade",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": None,
        "promo_duration_months": 12,
        "start_date": date(2024, 10, 1),
        "end_date": date(2025, 3, 31),
        "eligible_plans": "PLAN-006,PLAN-007,PLAN-008",
    },
    {
        "promo_id": "PROMO-019",
        "promo_name": "Home Fibre Welcome Rebate 2025",
        "promo_type": "discount",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": Decimal("10.00"),
        "promo_duration_months": 12,
        "start_date": date(2024, 11, 1),
        "end_date": date(2025, 4, 30),
        "eligible_plans": "PLAN-001,PLAN-002",
    },
    {
        "promo_id": "PROMO-020",
        "promo_name": "Ultra Gigabit Zero Install Waiver",
        "promo_type": "waived_installation",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": None,
        "promo_duration_months": 24,
        "start_date": date(2024, 10, 15),
        "end_date": date(2025, 4, 15),
        "eligible_plans": "PLAN-004,PLAN-005",
    },
    {
        "promo_id": "PROMO-021",
        "promo_name": "Family Mesh WiFi Bundle Discount",
        "promo_type": "discount",
        "discount_amount": Decimal("30.00"),
        "discount_percentage": None,
        "promo_duration_months": 12,
        "start_date": date(2024, 12, 1),
        "end_date": date(2025, 5, 31),
        "eligible_plans": "PLAN-003,PLAN-004",
    },
    {
        "promo_id": "PROMO-022",
        "promo_name": "Borneo High-Speed Expansion Deal",
        "promo_type": "discount",
        "discount_amount": Decimal("15.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2024, 11, 15),
        "end_date": date(2025, 5, 15),
        "eligible_plans": "PLAN-001,PLAN-002,PLAN-003",
    },
    {
        "promo_id": "PROMO-023",
        "promo_name": "Enterprise Cloud Partner Discount",
        "promo_type": "discount",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": Decimal("25.00"),
        "promo_duration_months": 24,
        "start_date": date(2024, 7, 1),
        "end_date": date(2025, 6, 30),
        "eligible_plans": "PLAN-007,PLAN-008",
    },
    {
        "promo_id": "PROMO-024",
        "promo_name": "Senior Citizen & OKU Rebate",
        "promo_type": "discount",
        "discount_amount": Decimal("10.00"),
        "discount_percentage": None,
        "promo_duration_months": 24,
        "start_date": date(2024, 1, 1),
        "end_date": date(2025, 6, 30),
        "eligible_plans": "PLAN-001,PLAN-002",
    },
    {
        "promo_id": "PROMO-025",
        "promo_name": "Student Connectivity Pass",
        "promo_type": "discount",
        "discount_amount": Decimal("15.00"),
        "discount_percentage": None,
        "promo_duration_months": 12,
        "start_date": date(2024, 3, 1),
        "end_date": date(2025, 6, 30),
        "eligible_plans": "PLAN-001,PLAN-002",
    },
    {
        "promo_id": "PROMO-026",
        "promo_name": "Nationwide Zero Setup Promo",
        "promo_type": "waived_installation",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": None,
        "promo_duration_months": 12,
        "start_date": date(2024, 6, 1),
        "end_date": date(2025, 6, 30),
        "eligible_plans": "PLAN-001,PLAN-002,PLAN-003,PLAN-004,PLAN-005",
    },
    {
        "promo_id": "PROMO-027",
        "promo_name": "Raya Aidilfitri 2025 Early Bird",
        "promo_type": "cashback",
        "discount_amount": Decimal("50.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2025, 2, 15),
        "end_date": date(2025, 4, 15),
        "eligible_plans": "PLAN-002,PLAN-003,PLAN-004",
    },
    {
        "promo_id": "PROMO-028",
        "promo_name": "Fibre Speed Upgrade Spring 2025",
        "promo_type": "free_upgrade",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2025, 3, 1),
        "end_date": date(2025, 5, 31),
        "eligible_plans": "PLAN-001,PLAN-002",
    },
    {
        "promo_id": "PROMO-029",
        "promo_name": "East Coast Fibre Drive 2025",
        "promo_type": "waived_installation",
        "discount_amount": Decimal("0.00"),
        "discount_percentage": None,
        "promo_duration_months": 12,
        "start_date": date(2025, 3, 15),
        "end_date": date(2025, 6, 15),
        "eligible_plans": "PLAN-001,PLAN-002,PLAN-003",
    },
    {
        "promo_id": "PROMO-030",
        "promo_name": "Mid-Year 2025 Gigabit Bonanza",
        "promo_type": "discount",
        "discount_amount": Decimal("40.00"),
        "discount_percentage": None,
        "promo_duration_months": 6,
        "start_date": date(2025, 5, 1),
        "end_date": date(2025, 6, 30),
        "eligible_plans": "PLAN-003,PLAN-004,PLAN-005",
    },
]


# ---------------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------------


def generate_promotions() -> None:
    """Generate src_promotions dataset adhering strictly to contract specifications."""
    print("[start] Generating src_promotions dataset...")

    # 1. Verify and read existing plans dataset to ensure valid foreign plan references
    if not PLANS_PATH.exists():
        raise FileNotFoundError(
            f"Required source dataset not found: {PLANS_PATH}. "
            "Please generate src_plans first."
        )

    print(f"[load] Reading valid plan IDs from {PLANS_PATH}...")
    plans_table = pq.read_table(PLANS_PATH)
    valid_plan_ids = set(plans_table.column("plan_id").to_pylist())

    if len(PROMOTIONS_DEFINITIONS) != PROMOTION_COUNT:
        raise ValueError(
            f"Expected {PROMOTION_COUNT} promotions in catalog, got {len(PROMOTIONS_DEFINITIONS)}"
        )

    # 2. Build rows and compute is_active deterministically
    promo_ids = []
    promo_names = []
    promo_types = []
    discount_amounts = []
    discount_percentages = []
    durations = []
    start_dates = []
    end_dates = []
    eligible_plans_list = []
    is_actives = []

    for item in PROMOTIONS_DEFINITIONS:
        p_id = item["promo_id"]
        p_name = item["promo_name"]
        p_type = item["promo_type"]
        p_amt = item["discount_amount"]
        p_pct = item["discount_percentage"]
        p_dur = item["promo_duration_months"]
        p_start = item["start_date"]
        p_end = item["end_date"]
        p_plans = item["eligible_plans"]

        # Validate eligible plans references
        referenced_plans = [p.strip() for p in p_plans.split(",")]
        for rp in referenced_plans:
            if rp not in valid_plan_ids:
                raise ValueError(
                    f"Promo {p_id} references nonexistent plan ID '{rp}'"
                )

        # Deterministic activity status relative to SYNTHETIC_REFERENCE_DATE:
        # A campaign is active if reference date falls within its campaign window and dates are not inverted
        active = (p_start <= SYNTHETIC_REFERENCE_DATE <= p_end) and (p_end >= p_start)

        promo_ids.append(p_id)
        promo_names.append(p_name)
        promo_types.append(p_type)
        discount_amounts.append(p_amt)
        discount_percentages.append(p_pct)
        durations.append(p_dur)
        start_dates.append(p_start)
        end_dates.append(p_end)
        eligible_plans_list.append(p_plans)
        is_actives.append(active)

    # 3. Build PyArrow RecordBatch with exact physical types
    print("[assemble] Constructing RecordBatch with exact Arrow schema...")
    batch = pa.RecordBatch.from_arrays(
        [
            pa.array(promo_ids, type=pa.string()),
            pa.array(promo_names, type=pa.string()),
            pa.array(promo_types, type=pa.string()),
            pa.array(discount_amounts, type=pa.decimal128(10, 2)),
            pa.array(discount_percentages, type=pa.decimal128(5, 2)),
            pa.array(durations, type=pa.int64()),
            pa.array(start_dates, type=pa.date32()),
            pa.array(end_dates, type=pa.date32()),
            pa.array(eligible_plans_list, type=pa.string()),
            pa.array(is_actives, type=pa.bool_()),
        ],
        schema=OUTPUT_SCHEMA,
    )

    # 4. Write output to Snappy-compressed Parquet atomically
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
    # 5. FINAL PHYSICAL VALIDATION OF WRITTEN PARQUET
    # ---------------------------------------------------------------------------
    print("\n[validate] Reading back and strictly validating final Parquet dataset...")
    output_reader = pq.ParquetFile(OUTPUT_PATH)
    output_rows = output_reader.metadata.num_rows

    if output_rows != PROMOTION_COUNT:
        raise AssertionError(
            f"Expected {PROMOTION_COUNT} rows, found {output_rows}."
        )

    schema_arrow = output_reader.schema_arrow
    expected_col_names = [f.name for f in OUTPUT_SCHEMA]
    actual_col_names = list(schema_arrow.names)
    if actual_col_names != expected_col_names:
        raise AssertionError(
            f"Columns mismatch: expected {expected_col_names}, got {actual_col_names}"
        )

    # Validate physical types
    if schema_arrow.field("promo_id").type != pa.string():
        raise AssertionError("promo_id physical type must be string.")
    if schema_arrow.field("promo_name").type != pa.string():
        raise AssertionError("promo_name physical type must be string.")
    if schema_arrow.field("promo_type").type != pa.string():
        raise AssertionError("promo_type physical type must be string.")
    if schema_arrow.field("discount_amount").type != pa.decimal128(10, 2):
        raise AssertionError("discount_amount physical type must be decimal128(10, 2).")
    if schema_arrow.field("discount_percentage").type != pa.decimal128(5, 2):
        raise AssertionError("discount_percentage physical type must be decimal128(5, 2).")
    if schema_arrow.field("promo_duration_months").type != pa.int64():
        raise AssertionError("promo_duration_months physical type must be int64.")
    if schema_arrow.field("start_date").type != pa.date32():
        raise AssertionError("start_date physical type must be date32.")
    if schema_arrow.field("end_date").type != pa.date32():
        raise AssertionError("end_date physical type must be date32.")
    if schema_arrow.field("eligible_plans").type != pa.string():
        raise AssertionError("eligible_plans physical type must be string.")
    if schema_arrow.field("is_active").type != pa.bool_():
        raise AssertionError("is_active physical type must be bool.")

    # Read back with pandas / Arrow for data content assertions
    output = pd.read_parquet(OUTPUT_PATH)

    # 1. promo_id uniqueness & non-null
    null_promo_id = int(output["promo_id"].isna().sum())
    if null_promo_id != 0:
        raise AssertionError(f"Found {null_promo_id} NULL promo IDs.")

    duplicate_promo_id = int(output["promo_id"].duplicated().sum())
    if duplicate_promo_id != 0:
        raise AssertionError(f"Found {duplicate_promo_id} duplicate promo IDs.")

    # 2. Allowed promo types
    actual_types = set(output["promo_type"].unique())
    invalid_types = actual_types - set(ALLOWED_PROMO_TYPES)
    if len(invalid_types) != 0:
        raise AssertionError(f"Invalid promo types found: {invalid_types}")

    # 3. Non-negative discount_amount
    negative_discount_count = int((output["discount_amount"] < 0).sum())
    if negative_discount_count != 0:
        raise AssertionError(f"Found {negative_discount_count} negative discount amounts.")

    # 4. Valid discount_percentage (between 0 and 100)
    non_null_pcts = output["discount_percentage"].dropna()
    invalid_pct_count = int(((non_null_pcts < 0) | (non_null_pcts > 100)).sum())
    if invalid_pct_count != 0:
        raise AssertionError(f"Found {invalid_pct_count} invalid discount percentages.")

    # 5. Positive promo_duration_months
    invalid_duration_count = int((output["promo_duration_months"] <= 0).sum())
    if invalid_duration_count != 0:
        raise AssertionError(f"Found {invalid_duration_count} invalid promo durations.")

    # 6. Dates: invalid-date DQ vs normal dates
    invalid_date_count = int((output["end_date"] < output["start_date"]).sum())
    if invalid_date_count != INVALID_DATE_COUNT:
        raise AssertionError(
            f"Expected {INVALID_DATE_COUNT} invalid date records (end_date < start_date), found {invalid_date_count}."
        )

    # 7. Normal records date range: 2024-01-01 to 2025-06-30
    normal_dates = output[output["end_date"] >= output["start_date"]]
    min_start = normal_dates["start_date"].min()
    max_end = normal_dates["end_date"].max()
    if min_start < date(2024, 1, 1) or max_end > date(2025, 6, 30):
        raise AssertionError(
            f"Normal date range outside project period: min start={min_start}, max end={max_end}"
        )

    # 8. Eligible plans validation
    invalid_plan_refs = 0
    for p_plans in output["eligible_plans"]:
        if len(p_plans) > 255:
            raise AssertionError(f"eligible_plans string exceeds 255 characters: {len(p_plans)}")
        for ref_plan in p_plans.split(","):
            if ref_plan.strip() not in valid_plan_ids:
                invalid_plan_refs += 1
    if invalid_plan_refs != 0:
        raise AssertionError(f"Found {invalid_plan_refs} invalid eligible plan references.")

    # 9. is_active type check
    invalid_is_active_type = int((~output["is_active"].isin([True, False])).sum())
    if invalid_is_active_type != 0:
        raise AssertionError("is_active contains non-boolean values.")

    # ---------------------------------------------------------------------------
    # 6. FORMATTED REPORT
    # ---------------------------------------------------------------------------
    print(f"\n[generated] src_promotions {output_rows} rows \u2192 {OUTPUT_PATH}")

    print("\nSchema:")
    for field in schema_arrow:
        print(f"  {field.name}: {field.type}")

    print("\nDQ expectations:")
    print(f"  invalid end_date < start_date : synthetic assumption = {INVALID_DATE_COUNT}")

    print("\nDQ validation:")
    print(f"  row count                   : {output_rows}")
    print(f"  duplicate promo_id          : {duplicate_promo_id}")
    print(f"  invalid promo_type count    : {len(invalid_types)}")
    print(f"  negative discount count     : {negative_discount_count}")
    print(f"  invalid discount percentage count : {invalid_pct_count}")
    print(f"  invalid date count          : {invalid_date_count}")
    print(f"  invalid eligible plan references  : {invalid_plan_refs}")
    print(f"  invalid promo duration count: {invalid_duration_count}")
    print(f"  invalid is_active type count: {invalid_is_active_type}")

    print("\nOutput:")
    print(f"  {OUTPUT_PATH}")


def main() -> None:
    generate_promotions()


if __name__ == "__main__":
    main()
