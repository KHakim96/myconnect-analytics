"""
MYConnect synthetic customer generator.

Generates:
    src_customers

Grain:
    One row per customer

Target:
    250,000 rows

Intentional DQ issues from the project specification:
    - ~500 duplicate IC numbers
    - ~2,000 invalid emails
    - ~1,000 mixed-case status values
    - ~500 invalid postcodes
    - ~300 future registration dates
    - ~5,000 city-name inconsistencies
"""

from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd
from faker import Faker

from .config import (
    DATASET_COUNTS,
    DATASET_OUTPUT_DIRS,
    DATA_END_DATE,
    GENERATED_DATA_DIR,
    OUTPUT_FORMAT,
    RANDOM_SEED,
)
from .utils import (
    assert_required_columns,
    assert_row_count,
    assert_unique,
    generate_random_ic,
    generate_random_phone,
    generate_random_postcode,
    get_rng,
    log_dataset_written,
    make_id_series,
    random_city_for_state,
    random_state,
    sample_indices,
    write_dataframe,
)

# ============================================================
# CONFIG
# ============================================================

DATASET_NAME = "customers"

CUSTOMER_COUNT = int(DATASET_COUNTS.get(DATASET_NAME, 250_000))

DUPLICATE_IC_COUNT = 500
INVALID_EMAIL_COUNT = 2_000
MIXED_CASE_STATUS_COUNT = 1_000
INVALID_POSTCODE_COUNT = 500
FUTURE_REGISTRATION_COUNT = 300
CITY_INCONSISTENCY_COUNT = 5_000


CUSTOMER_TYPES = [
    "residential",
    "sme",
]

CUSTOMER_TYPE_PROBABILITIES = [
    0.90,
    0.10,
]

STATUSES = [
    "active",
    "terminated",
    "suspended",
]

STATUS_PROBABILITIES = [
    0.82,
    0.13,
    0.05,
]

DWELLING_TYPES = [
    "mdu",
    "sdu",
]

DWELLING_PROBABILITIES = [
    0.58,
    0.42,
]


EXPECTED_COLUMNS = [
    "customer_id",
    "first_name",
    "last_name",
    "email",
    "phone_number",
    "ic_number",
    "customer_type",
    "registration_date",
    "status",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "postcode",
    "dwelling_type",
    "referral_code",
    "created_at",
    "updated_at",
]


# ============================================================
# HELPERS
# ============================================================


def slugify_name(value: str) -> str:
    """Convert a person name into an email-safe token."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", ".", value)
    value = re.sub(r"\.+", ".", value)
    return value.strip(".")


def generate_email(
    first_name: str,
    last_name: str,
    customer_number: int,
    rng: np.random.Generator,
) -> str:
    """Generate a synthetic email address."""
    first = slugify_name(first_name)
    last = slugify_name(last_name)

    domains = [
        "gmail.com",
        "outlook.com",
        "yahoo.com",
        "example.my",
        "mail.my",
    ]

    domain = str(rng.choice(domains))

    return f"{first}.{last}.{customer_number}@{domain}"


def generate_address_line_1(
    rng: np.random.Generator,
) -> str:
    """Generate a synthetic Malaysian-style address."""
    street_types = [
        "Jalan",
        "Lorong",
        "Persiaran",
    ]

    developments = [
        "Taman Melur",
        "Taman Mutiara",
        "Taman Harmoni",
        "Taman Indah",
        "Taman Seri",
        "Residensi Damai",
        "Residensi Murni",
        "Condominium Anggerik",
        "Condominium Cempaka",
        "Apartment Bestari",
        "Apartment Perdana",
        "Pangsapuri Seri",
    ]

    street_type = str(rng.choice(street_types))

    development = str(rng.choice(developments))

    street_number = int(rng.integers(1, 250))

    # Generate a mixture of landed and high-rise-looking addresses.
    if rng.random() < 0.45:
        floor = int(rng.integers(1, 31))

        unit = int(rng.integers(1, 15))

        return (
            f"Unit {floor:02d}-{unit:02d}, "
            f"{development}, "
            f"{street_type} {street_number}"
        )

    return f"No. {street_number}, " f"{street_type} {development}"


def generate_address_line_2(
    rng: np.random.Generator,
) -> str | pd.NA:
    """Generate an optional second address line."""
    if rng.random() < 0.40:
        return pd.NA

    values = [
        "Bandar Baru",
        "Seksyen 9",
        "Seksyen 13",
        "Pusat Bandar",
        "Taman Perindustrian",
        "Bandar Utama",
        "Bukit Jelutong",
        "Kawasan Perniagaan",
    ]

    return str(rng.choice(values))


def generate_referral_code(
    rng: np.random.Generator,
) -> str | pd.NA:
    """Generate an optional synthetic referral code."""
    if rng.random() < 0.30:
        return pd.NA

    letters = rng.choice(
        list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        size=3,
    )

    digits = rng.integers(
        0,
        10,
        size=3,
    )

    letter_part = "".join(str(value) for value in letters)

    digit_part = "".join(str(value) for value in digits)

    return f"REF-{letter_part}{digit_part}"


def generate_random_datetime_series(
    rng: np.random.Generator,
    start_date: date,
    end_date: date,
    size: int,
) -> pd.Series:
    """Generate random timestamps between two dates."""
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    total_seconds = int((end_ts - start_ts).total_seconds())

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


# ============================================================
# DQ INJECTION
# ============================================================


def inject_duplicate_ic_numbers(
    df: pd.DataFrame,
    count: int,
) -> None:
    """
    Create duplicate IC numbers while keeping customer_id unique.

    The first `count` customers are copied onto the final `count`
    customers' IC values.
    """
    source_indices = np.arange(
        0,
        count,
        dtype=np.int64,
    )

    target_indices = np.arange(
        len(df) - count,
        len(df),
        dtype=np.int64,
    )

    df.loc[
        target_indices,
        "ic_number",
    ] = df.loc[
        source_indices,
        "ic_number",
    ].to_numpy()


def inject_invalid_emails(
    df: pd.DataFrame,
    rng: np.random.Generator,
    count: int,
) -> None:
    """Inject intentionally invalid email formats."""
    indices = sample_indices(
        rng=rng,
        row_count=len(df),
        issue_count=count,
    )

    invalid_values = [
        "invalid-email",
        "missing-at.example.com",
        "user@@example.com",
        "user.example.com",
        "user@",
        "@example.com",
        "user..name@example.com",
    ]

    for index in indices:
        df.at[
            df.index[index],
            "email",
        ] = str(rng.choice(invalid_values))


def inject_mixed_case_statuses(
    df: pd.DataFrame,
    rng: np.random.Generator,
    count: int,
) -> None:
    """Inject inconsistent status casing."""
    indices = sample_indices(
        rng=rng,
        row_count=len(df),
        issue_count=count,
    )

    for index in indices:
        row_index = df.index[index]

        current_value = str(
            df.at[
                row_index,
                "status",
            ]
        )

        df.at[
            row_index,
            "status",
        ] = str(
            rng.choice(
                [
                    current_value.upper(),
                    current_value.capitalize(),
                ]
            )
        )


def inject_invalid_postcodes(
    df: pd.DataFrame,
    rng: np.random.Generator,
    count: int,
) -> None:
    """Inject invalid postcode values."""
    indices = sample_indices(
        rng=rng,
        row_count=len(df),
        issue_count=count,
    )

    invalid_values = [
        "0000",
        "00000",
        "ABCDE",
        "123",
        "",
    ]

    for index in indices:
        df.at[
            df.index[index],
            "postcode",
        ] = str(rng.choice(invalid_values))


def inject_future_registration_dates(
    df: pd.DataFrame,
    rng: np.random.Generator,
    count: int,
) -> None:
    """
    Inject registration dates after the project's observation window.

    The canonical data window ends on 2025-06-30.
    """
    indices = sample_indices(
        rng=rng,
        row_count=len(df),
        issue_count=count,
    )

    future_start = pd.Timestamp(DATA_END_DATE) + pd.Timedelta(days=1)

    future_end = future_start + pd.Timedelta(days=180)

    future_values = generate_random_datetime_series(
        rng=rng,
        start_date=future_start.date(),
        end_date=future_end.date(),
        size=count,
    )

    df.loc[
        df.index[indices],
        "registration_date",
    ] = future_values.to_numpy()


def inject_city_inconsistencies(
    df: pd.DataFrame,
    rng: np.random.Generator,
    count: int,
) -> None:
    """
    Inject:
        Selangor -> PJ
        Kuala Lumpur -> KL

    These are the exact city inconsistencies specified in the source
    specification.
    """
    eligible_mask = df["state"].isin(
        [
            "Selangor",
            "Kuala Lumpur",
        ]
    )

    eligible_indices = df.index[eligible_mask].to_numpy()

    if len(eligible_indices) < count:
        raise ValueError(
            "Not enough Selangor/Kuala Lumpur "
            "customers to inject city inconsistencies."
        )

    selected_indices = rng.choice(
        eligible_indices,
        size=count,
        replace=False,
    )

    for index in selected_indices:
        state = str(df.at[index, "state"])

        if state == "Selangor":
            df.at[index, "city"] = "PJ"

        elif state == "Kuala Lumpur":
            df.at[index, "city"] = "KL"


# ============================================================
# GENERATOR
# ============================================================


def generate_customers() -> pd.DataFrame:
    """Generate the complete src_customers dataframe."""
    rng = get_rng(RANDOM_SEED)

    fake = Faker("en_GB")
    fake.seed_instance(RANDOM_SEED)

    # --------------------------------------------------------
    # IDs
    # --------------------------------------------------------

    customer_ids = make_id_series(
        prefix="CUST",
        start=1,
        count=CUSTOMER_COUNT,
        width=6,
    )

    # --------------------------------------------------------
    # Names
    # --------------------------------------------------------

    first_names = [str(fake.first_name()) for _ in range(CUSTOMER_COUNT)]

    last_names = [str(fake.last_name()) for _ in range(CUSTOMER_COUNT)]

    # --------------------------------------------------------
    # Geography
    # --------------------------------------------------------

    states = random_state(
        rng=rng,
        size=CUSTOMER_COUNT,
    )

    cities = np.empty(
        CUSTOMER_COUNT,
        dtype=object,
    )

    for i, state in enumerate(states):
        cities[i] = random_city_for_state(
            rng=rng,
            state=str(state),
        )

    # --------------------------------------------------------
    # Customer attributes
    # --------------------------------------------------------

    customer_type = rng.choice(
        CUSTOMER_TYPES,
        size=CUSTOMER_COUNT,
        p=CUSTOMER_TYPE_PROBABILITIES,
    )

    status = rng.choice(
        STATUSES,
        size=CUSTOMER_COUNT,
        p=STATUS_PROBABILITIES,
    )

    dwelling_type = rng.choice(
        DWELLING_TYPES,
        size=CUSTOMER_COUNT,
        p=DWELLING_PROBABILITIES,
    )

    # --------------------------------------------------------
    # Registration dates
    # --------------------------------------------------------

    registration_date = generate_random_datetime_series(
        rng=rng,
        start_date=date(2021, 1, 1),
        end_date=DATA_END_DATE,
        size=CUSTOMER_COUNT,
    )

    # --------------------------------------------------------
    # Contact data
    # --------------------------------------------------------

    emails = [
        generate_email(
            first_name=first_names[i],
            last_name=last_names[i],
            customer_number=i + 1,
            rng=rng,
        )
        for i in range(CUSTOMER_COUNT)
    ]

    phones = [generate_random_phone(rng) for _ in range(CUSTOMER_COUNT)]

    ic_numbers = [generate_random_ic(rng) for _ in range(CUSTOMER_COUNT)]

    postcodes = [generate_random_postcode(rng) for _ in range(CUSTOMER_COUNT)]

    # --------------------------------------------------------
    # Addresses
    # --------------------------------------------------------

    address_line_1 = [generate_address_line_1(rng) for _ in range(CUSTOMER_COUNT)]

    address_line_2 = [generate_address_line_2(rng) for _ in range(CUSTOMER_COUNT)]

    referral_codes = [generate_referral_code(rng) for _ in range(CUSTOMER_COUNT)]

    # --------------------------------------------------------
    # System timestamps
    # --------------------------------------------------------

    created_at = registration_date.copy()

    update_offsets = rng.integers(
        0,
        121,
        size=CUSTOMER_COUNT,
    )

    updated_at = created_at + pd.to_timedelta(
        update_offsets,
        unit="D",
    )

    # --------------------------------------------------------
    # Build dataframe
    # --------------------------------------------------------

    df = pd.DataFrame(
        {
            "customer_id": customer_ids,
            "first_name": pd.Series(
                first_names,
                dtype="string",
            ),
            "last_name": pd.Series(
                last_names,
                dtype="string",
            ),
            "email": pd.Series(
                emails,
                dtype="string",
            ),
            "phone_number": pd.Series(
                phones,
                dtype="string",
            ),
            "ic_number": pd.Series(
                ic_numbers,
                dtype="string",
            ),
            "customer_type": pd.Series(
                customer_type,
                dtype="string",
            ),
            "registration_date": pd.to_datetime(registration_date),
            "status": pd.Series(
                status,
                dtype="string",
            ),
            "address_line_1": pd.Series(
                address_line_1,
                dtype="string",
            ),
            "address_line_2": pd.Series(
                address_line_2,
                dtype="string",
            ),
            "city": pd.Series(
                cities,
                dtype="string",
            ),
            "state": pd.Series(
                states,
                dtype="string",
            ),
            "postcode": pd.Series(
                postcodes,
                dtype="string",
            ),
            "dwelling_type": pd.Series(
                dwelling_type,
                dtype="string",
            ),
            "referral_code": pd.Series(
                referral_codes,
                dtype="string",
            ),
            "created_at": pd.to_datetime(created_at),
            "updated_at": pd.to_datetime(updated_at),
        }
    )

    # ========================================================
    # APPLY EXACT SOURCE DQ ISSUES
    # ========================================================

    inject_duplicate_ic_numbers(
        df=df,
        count=DUPLICATE_IC_COUNT,
    )

    inject_invalid_emails(
        df=df,
        rng=rng,
        count=INVALID_EMAIL_COUNT,
    )

    inject_mixed_case_statuses(
        df=df,
        rng=rng,
        count=MIXED_CASE_STATUS_COUNT,
    )

    inject_invalid_postcodes(
        df=df,
        rng=rng,
        count=INVALID_POSTCODE_COUNT,
    )

    inject_future_registration_dates(
        df=df,
        rng=rng,
        count=FUTURE_REGISTRATION_COUNT,
    )

    inject_city_inconsistencies(
        df=df,
        rng=rng,
        count=CITY_INCONSISTENCY_COUNT,
    )

    # ========================================================
    # VALIDATION
    # ========================================================

    assert_row_count(
        df=df,
        expected=CUSTOMER_COUNT,
        dataset_name="src_customers",
    )

    assert_required_columns(
        df=df,
        required_columns=EXPECTED_COLUMNS,
        dataset_name="src_customers",
    )

    # customer_id is the PK and MUST remain unique.
    assert_unique(
        df=df,
        column="customer_id",
        dataset_name="src_customers",
    )

    # Enforce exact schema ordering.
    df = df[EXPECTED_COLUMNS]

    return df


# ============================================================
# OUTPUT
# ============================================================


def main() -> None:
    """Generate src_customers and write it to disk."""
    df = generate_customers()

    output_dir = DATASET_OUTPUT_DIRS.get(
        DATASET_NAME,
        GENERATED_DATA_DIR / DATASET_NAME,
    )

    output_path = write_dataframe(
        df=df,
        output_dir=GENERATED_DATA_DIR,
        dataset_name=DATASET_NAME,
        part_number=0,
        output_format=OUTPUT_FORMAT,
    )

    log_dataset_written(
        dataset_name="src_customers",
        rows=len(df),
        path=output_path,
    )

    print()
    print("Customer generation complete.")
    print()

    print(df.head(10).to_string(index=False))

    print()
    print("Schema:")
    print(df.dtypes)

    print()
    print("DQ injection targets:")
    print(f"  duplicate IC numbers  : " f"{DUPLICATE_IC_COUNT:,}")
    print(f"  invalid emails        : " f"{INVALID_EMAIL_COUNT:,}")
    print(f"  mixed-case statuses   : " f"{MIXED_CASE_STATUS_COUNT:,}")
    print(f"  invalid postcodes     : " f"{INVALID_POSTCODE_COUNT:,}")
    print(f"  future registrations  : " f"{FUTURE_REGISTRATION_COUNT:,}")
    print(f"  city inconsistencies  : " f"{CITY_INCONSISTENCY_COUNT:,}")

    # print()
    # print("Actual validation checks:")

    # duplicate_ic_count = int(df["ic_number"].duplicated().sum())

    # invalid_email_mask = ~df["email"].str.contains(
    #     r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    #     regex=True,
    #     na=False,
    # )

    # invalid_postcode_mask = ~df["postcode"].str.fullmatch(
    #     r"\d{5}",
    #     na=False,
    # )

    # mixed_case_status_count = int((df["status"] != df["status"].str.lower()).sum())

    # future_registration_count = int(
    #     (df["registration_date"] > pd.Timestamp(DATA_END_DATE)).sum()
    # )

    # city_inconsistency_count = int(df["city"].isin(["PJ", "KL"]).sum())

    # print(f"  duplicate IC values    : " f"{duplicate_ic_count:,}")
    # print(f"  invalid email values   : " f"{int(invalid_email_mask.sum()):,}")
    # print(f"  mixed-case statuses    : " f"{mixed_case_status_count:,}")
    # print(f"  invalid postcodes      : " f"{int(invalid_postcode_mask.sum()):,}")
    # print(f"  future registrations   : " f"{future_registration_count:,}")
    # print(f"  PJ / KL city values    : " f"{city_inconsistency_count:,}")


if __name__ == "__main__":
    main()
