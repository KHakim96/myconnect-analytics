"""
Central configuration for the MyConnect synthetic data generator.

All environment-specific settings are loaded from the project's .env file.
Dataset row counts and date ranges follow the canonical MyConnect specification.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# PROJECT PATHS
# ---------------------------------------------------------------------------

# config.py
#   -> synthetic_data_gen/
#       -> ingestion/
#           -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = PROJECT_ROOT / ".env"
GENERATED_DATA_DIR = PROJECT_ROOT / "generated"

load_dotenv(ENV_FILE)


# ---------------------------------------------------------------------------
# ENVIRONMENT HELPERS
# ---------------------------------------------------------------------------


def _required_env(name: str) -> str:
    """Return a required environment variable or fail clearly."""
    value = os.getenv(name)

    if not value:
        raise ValueError(
            f"Missing required environment variable: {name}. " f"Add it to {ENV_FILE}."
        )

    return value.strip()


def _optional_env(name: str, default: str) -> str:
    """Return an optional environment variable with a default."""
    value = os.getenv(name)
    return value.strip() if value else default


# ---------------------------------------------------------------------------
# GCP CONFIGURATION
# ---------------------------------------------------------------------------

GCP_PROJECT_ID = _required_env("GCP_PROJECT_ID")
GCP_REGION = _optional_env("GCP_REGION", "asia-southeast1")

GCS_BUCKET = _required_env("GCS_BUCKET")

BQ_LOCATION = _optional_env("BQ_LOCATION", GCP_REGION)


# ---------------------------------------------------------------------------
# BIGQUERY DATASET NAMES
# ---------------------------------------------------------------------------

BQ_DATASET_BRONZE = _optional_env(
    "BQ_DATASET_BRONZE",
    "myconnect_bronze",
)

BQ_DATASET_SILVER = _optional_env(
    "BQ_DATASET_SILVER",
    "myconnect_silver",
)

BQ_DATASET_GOLD = _optional_env(
    "BQ_DATASET_GOLD",
    "myconnect_gold",
)

BQ_DATASET_MART = _optional_env(
    "BQ_DATASET_MART",
    "myconnect_mart",
)


# ---------------------------------------------------------------------------
# SYNTHETIC DATA DATE RANGE
# ---------------------------------------------------------------------------

DATA_START_DATE = _required_env("DATA_START_DATE")
DATA_END_DATE = _required_env("DATA_END_DATE")


# ---------------------------------------------------------------------------
# SYNTHETIC DATA GENERATION
# ---------------------------------------------------------------------------

# Reproducibility:
# Using one fixed seed means the same generator logic can produce the
# same synthetic dataset again for testing/debugging.
RANDOM_SEED = int(_optional_env("RANDOM_SEED", "42"))


# Number of rows expected for each source dataset.
#
# These are configuration targets. Individual generators will use them
# when creating their respective source tables.

CUSTOMER_COUNT = 250_000
SUBSCRIPTION_COUNT = 350_000
PLAN_COUNT = 18
BILLING_COUNT = 3_000_000
BILL_LINE_ITEM_COUNT = 5_000_000
PAYMENT_COUNT = 2_800_000
USAGE_COUNT = 4_500_000
SUPPORT_TICKET_COUNT = 180_000
NETWORK_EVENT_COUNT = 2_000_000
PROMOTION_COUNT = 30
CHURN_EVENT_COUNT = 35_000


# ---------------------------------------------------------------------------
# CHUNKING
# ---------------------------------------------------------------------------

# Large datasets must not be generated as one giant in-memory object.
#
# These defaults will be used by the large-volume generators and can be
# overridden through .env when needed.

CUSTOMER_CHUNK_SIZE = int(_optional_env("CUSTOMER_CHUNK_SIZE", "50000"))

SUBSCRIPTION_CHUNK_SIZE = int(_optional_env("SUBSCRIPTION_CHUNK_SIZE", "50000"))

BILLING_CHUNK_SIZE = int(_optional_env("BILLING_CHUNK_SIZE", "100000"))

BILL_LINE_ITEM_CHUNK_SIZE = int(_optional_env("BILL_LINE_ITEM_CHUNK_SIZE", "100000"))

PAYMENT_CHUNK_SIZE = int(_optional_env("PAYMENT_CHUNK_SIZE", "100000"))

USAGE_CHUNK_SIZE = int(_optional_env("USAGE_CHUNK_SIZE", "100000"))

SUPPORT_TICKET_CHUNK_SIZE = int(_optional_env("SUPPORT_TICKET_CHUNK_SIZE", "50000"))

NETWORK_EVENT_CHUNK_SIZE = int(_optional_env("NETWORK_EVENT_CHUNK_SIZE", "100000"))

CHURN_EVENT_CHUNK_SIZE = int(_optional_env("CHURN_EVENT_CHUNK_SIZE", "50000"))


# ---------------------------------------------------------------------------
# OUTPUT FORMAT
# ---------------------------------------------------------------------------

OUTPUT_FORMAT = _optional_env("OUTPUT_FORMAT", "parquet").lower()

if OUTPUT_FORMAT not in {"parquet", "csv"}:
    raise ValueError(
        "OUTPUT_FORMAT must be either 'parquet' or 'csv'. " f"Received: {OUTPUT_FORMAT}"
    )


# ---------------------------------------------------------------------------
# OUTPUT DIRECTORIES
# ---------------------------------------------------------------------------

GENERATED_DATA_DIR.mkdir(parents=True, exist_ok=True)

DATASET_OUTPUT_DIRS = {
    "customers": GENERATED_DATA_DIR / "customers",
    "subscriptions": GENERATED_DATA_DIR / "subscriptions",
    "plans": GENERATED_DATA_DIR / "plans",
    "billing": GENERATED_DATA_DIR / "billing",
    "bill_line_items": GENERATED_DATA_DIR / "bill_line_items",
    "payments": GENERATED_DATA_DIR / "payments",
    "usage_daily": GENERATED_DATA_DIR / "usage_daily",
    "support_tickets": GENERATED_DATA_DIR / "support_tickets",
    "network_events": GENERATED_DATA_DIR / "network_events",
    "promotions": GENERATED_DATA_DIR / "promotions",
    "churn_events": GENERATED_DATA_DIR / "churn_events",
}


# ---------------------------------------------------------------------------
# DATASET METADATA
# ---------------------------------------------------------------------------

DATASET_COUNTS = {
    "customers": CUSTOMER_COUNT,
    "subscriptions": SUBSCRIPTION_COUNT,
    "plans": PLAN_COUNT,
    "billing": BILLING_COUNT,
    "bill_line_items": BILL_LINE_ITEM_COUNT,
    "payments": PAYMENT_COUNT,
    "usage_daily": USAGE_COUNT,
    "support_tickets": SUPPORT_TICKET_COUNT,
    "network_events": NETWORK_EVENT_COUNT,
    "promotions": PROMOTION_COUNT,
    "churn_events": CHURN_EVENT_COUNT,
}


# ---------------------------------------------------------------------------
# DISPLAY / VALIDATION
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeneratorConfig:
    """Read-only snapshot of the main generator configuration."""

    project_id: str
    region: str
    gcs_bucket: str
    bq_location: str

    bronze_dataset: str
    silver_dataset: str
    gold_dataset: str
    mart_dataset: str

    data_start_date: str
    data_end_date: str

    random_seed: int
    output_format: str


CONFIG = GeneratorConfig(
    project_id=GCP_PROJECT_ID,
    region=GCP_REGION,
    gcs_bucket=GCS_BUCKET,
    bq_location=BQ_LOCATION,
    bronze_dataset=BQ_DATASET_BRONZE,
    silver_dataset=BQ_DATASET_SILVER,
    gold_dataset=BQ_DATASET_GOLD,
    mart_dataset=BQ_DATASET_MART,
    data_start_date=DATA_START_DATE,
    data_end_date=DATA_END_DATE,
    random_seed=RANDOM_SEED,
    output_format=OUTPUT_FORMAT,
)


def print_config() -> None:
    """Print a human-readable configuration summary."""

    print("=" * 70)
    print("MYCONNECT SYNTHETIC DATA GENERATOR CONFIG")
    print("=" * 70)

    print(f"Project ID      : {GCP_PROJECT_ID}")
    print(f"GCP Region      : {GCP_REGION}")
    print(f"GCS Bucket      : {GCS_BUCKET}")
    print(f"BQ Location     : {BQ_LOCATION}")

    print()
    print("BigQuery Datasets")
    print("-" * 70)
    print(f"Bronze          : {BQ_DATASET_BRONZE}")
    print(f"Silver          : {BQ_DATASET_SILVER}")
    print(f"Gold            : {BQ_DATASET_GOLD}")
    print(f"Mart            : {BQ_DATASET_MART}")

    print()
    print("Synthetic Data")
    print("-" * 70)
    print(f"Date Start      : {DATA_START_DATE}")
    print(f"Date End        : {DATA_END_DATE}")
    print(f"Random Seed     : {RANDOM_SEED}")
    print(f"Output Format   : {OUTPUT_FORMAT}")

    print()
    print("Target Row Counts")
    print("-" * 70)

    for dataset_name, row_count in DATASET_COUNTS.items():
        print(f"{dataset_name:22s}: {row_count:,}")

    print()
    print(f"Generated Data  : {GENERATED_DATA_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    print_config()
