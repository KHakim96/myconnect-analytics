"""
Shared utility functions for the MyConnect synthetic data generator.

This module contains reusable helpers for:
- deterministic random generation
- ID creation
- dates and timestamps
- weighted random selection
- chunked output writing
- common synthetic Malaysian data
- controlled data-quality issue injection

Individual dataset generators should import helpers from this module
instead of reimplementing the same logic.
"""

from __future__ import annotations

import math
import random
import re
import string
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence, TypeVar

import numpy as np
import pandas as pd

T = TypeVar("T")


# ---------------------------------------------------------------------------
# RANDOMNESS
# ---------------------------------------------------------------------------


def get_rng(seed: int | None = None) -> np.random.Generator:
    """
    Return a NumPy random generator.

    Using an explicit seed makes the synthetic dataset reproducible.
    """
    return np.random.default_rng(seed)


def seed_python_random(seed: int) -> None:
    """Seed Python's built-in random module."""
    random.seed(seed)


# ---------------------------------------------------------------------------
# ID GENERATION
# ---------------------------------------------------------------------------


def make_id(prefix: str, number: int, width: int) -> str:
    """
    Create a deterministic prefixed identifier.

    Example:
        make_id("CUST", 1, 6) -> CUST-000001
    """
    if number < 0:
        raise ValueError("number must be >= 0")

    if width <= 0:
        raise ValueError("width must be > 0")

    return f"{prefix}-{number:0{width}d}"


def make_id_series(
    prefix: str,
    start: int,
    count: int,
    width: int,
) -> pd.Series:
    """
    Create a pandas Series of deterministic IDs.

    Example:
        make_id_series("CUST", 1, 3, 6)

        CUST-000001
        CUST-000002
        CUST-000003
    """
    if start < 0:
        raise ValueError("start must be >= 0")

    if count < 0:
        raise ValueError("count must be >= 0")

    if width <= 0:
        raise ValueError("width must be > 0")

    numbers = np.arange(start, start + count, dtype=np.int64)

    return pd.Series(
        [f"{prefix}-{number:0{width}d}" for number in numbers],
        dtype="string",
    )


# ---------------------------------------------------------------------------
# DATE / TIMESTAMP HELPERS
# ---------------------------------------------------------------------------


def parse_date(value: str | date | datetime) -> date:
    """Convert a date-like value to datetime.date."""
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_datetime(value: str | date | datetime) -> datetime:
    """Convert a date-like value to datetime.datetime."""
    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    return datetime.fromisoformat(value)


def random_date(
    rng: np.random.Generator,
    start_date: date,
    end_date: date,
) -> date:
    """Generate a random date between start_date and end_date inclusive."""
    start = parse_date(start_date)
    end = parse_date(end_date)

    if end < start:
        raise ValueError("end_date must be >= start_date")

    day_range = (end - start).days

    offset = int(rng.integers(0, day_range + 1))

    return start + timedelta(days=offset)


def random_dates(
    rng: np.random.Generator,
    start_date: date,
    end_date: date,
    size: int,
) -> np.ndarray:
    """
    Generate an array of random dates.

    Returns numpy datetime64[D].
    """
    if size < 0:
        raise ValueError("size must be >= 0")

    start = np.datetime64(parse_date(start_date), "D")
    end = np.datetime64(parse_date(end_date), "D")

    if end < start:
        raise ValueError("end_date must be >= start_date")

    day_range = int((end - start) / np.timedelta64(1, "D"))

    offsets = rng.integers(
        0,
        day_range + 1,
        size=size,
    )

    return start + offsets.astype("timedelta64[D]")


def random_timestamp(
    rng: np.random.Generator,
    start_datetime: datetime,
    end_datetime: datetime,
) -> datetime:
    """Generate a random timestamp between two datetimes."""
    start = parse_datetime(start_datetime)
    end = parse_datetime(end_datetime)

    if end < start:
        raise ValueError("end_datetime must be >= start_datetime")

    seconds = int((end - start).total_seconds())

    offset = int(rng.integers(0, seconds + 1))

    return start + timedelta(seconds=offset)


def random_timestamps(
    rng: np.random.Generator,
    start_datetime: datetime,
    end_datetime: datetime,
    size: int,
) -> pd.Series:
    """Generate a pandas Series of random UTC-naive timestamps."""
    if size < 0:
        raise ValueError("size must be >= 0")

    start = parse_datetime(start_datetime)
    end = parse_datetime(end_datetime)

    if end < start:
        raise ValueError("end_datetime must be >= start_datetime")

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    total_seconds = int((end_ts - start_ts).total_seconds())

    offsets = rng.integers(
        0,
        total_seconds + 1,
        size=size,
    )

    timestamps = start_ts + pd.to_timedelta(offsets, unit="s")

    return pd.Series(timestamps)


def add_random_days(
    rng: np.random.Generator,
    values: Sequence[date],
    min_days: int,
    max_days: int,
) -> list[date]:
    """
    Add a random number of days to each input date.

    Useful for generating subscription end dates, due dates, etc.
    """
    if min_days < 0:
        raise ValueError("min_days must be >= 0")

    if max_days < min_days:
        raise ValueError("max_days must be >= min_days")

    offsets = rng.integers(
        min_days,
        max_days + 1,
        size=len(values),
    )

    return [
        parse_date(value) + timedelta(days=int(offset))
        for value, offset in zip(values, offsets)
    ]


# ---------------------------------------------------------------------------
# RANDOM SELECTION
# ---------------------------------------------------------------------------


def weighted_choice(
    rng: np.random.Generator,
    values: Sequence[T],
    probabilities: Sequence[float],
    size: int = 1,
) -> np.ndarray:
    """
    Choose values according to supplied probabilities.
    """
    if len(values) == 0:
        raise ValueError("values cannot be empty")

    if len(values) != len(probabilities):
        raise ValueError("values and probabilities must have the same length")

    probabilities_array = np.asarray(probabilities, dtype=float)

    if np.any(probabilities_array < 0):
        raise ValueError("probabilities cannot be negative")

    probability_sum = probabilities_array.sum()

    if not math.isclose(probability_sum, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError(f"probabilities must sum to 1.0; got {probability_sum}")

    return rng.choice(
        np.asarray(values, dtype=object),
        size=size,
        p=probabilities_array,
    )


def random_choice(
    rng: np.random.Generator,
    values: Sequence[T],
    size: int = 1,
) -> np.ndarray:
    """Uniform random choice from a sequence."""
    if len(values) == 0:
        raise ValueError("values cannot be empty")

    return rng.choice(
        np.asarray(values, dtype=object),
        size=size,
    )


# ---------------------------------------------------------------------------
# TEXT / STRING HELPERS
# ---------------------------------------------------------------------------


def random_string(
    rng: np.random.Generator,
    length: int,
    alphabet: str | None = None,
) -> str:
    """Generate a random string."""
    if length < 1:
        raise ValueError("length must be >= 1")

    characters = alphabet or (
        string.ascii_uppercase + string.ascii_lowercase + string.digits
    )

    return "".join(rng.choice(list(characters), size=length))


def normalize_whitespace(value: str) -> str:
    """Collapse repeated whitespace and trim the string."""
    return re.sub(r"\s+", " ", value).strip()


# ---------------------------------------------------------------------------
# MALAYSIAN SYNTHETIC DATA HELPERS
# ---------------------------------------------------------------------------

MALAYSIAN_STATES = [
    "Johor",
    "Kedah",
    "Kelantan",
    "Melaka",
    "Negeri Sembilan",
    "Pahang",
    "Penang",
    "Perak",
    "Perlis",
    "Sabah",
    "Sarawak",
    "Selangor",
    "Terengganu",
    "Kuala Lumpur",
    "Putrajaya",
    "Labuan",
]


MALAYSIAN_STATE_WEIGHTS = [
    0.105,
    0.055,
    0.035,
    0.045,
    0.050,
    0.045,
    0.080,
    0.075,
    0.010,
    0.035,
    0.050,
    0.225,
    0.035,
    0.140,
    0.005,
    0.010,
]


MALAYSIAN_CITIES_BY_STATE: dict[str, list[str]] = {
    "Johor": [
        "Johor Bahru",
        "Batu Pahat",
        "Muar",
        "Kluang",
        "Kulai",
    ],
    "Kedah": [
        "Alor Setar",
        "Sungai Petani",
        "Kulim",
        "Langkawi",
    ],
    "Kelantan": [
        "Kota Bharu",
        "Pasir Mas",
        "Tumpat",
    ],
    "Melaka": [
        "Melaka",
        "Alor Gajah",
        "Jasin",
    ],
    "Negeri Sembilan": [
        "Seremban",
        "Port Dickson",
        "Nilai",
    ],
    "Pahang": [
        "Kuantan",
        "Temerloh",
        "Bentong",
    ],
    "Penang": [
        "George Town",
        "Bayan Lepas",
        "Butterworth",
        "Bukit Mertajam",
    ],
    "Perak": [
        "Ipoh",
        "Taiping",
        "Teluk Intan",
        "Manjung",
    ],
    "Perlis": [
        "Kangar",
    ],
    "Sabah": [
        "Kota Kinabalu",
        "Sandakan",
        "Tawau",
    ],
    "Sarawak": [
        "Kuching",
        "Miri",
        "Sibu",
        "Bintulu",
    ],
    "Selangor": [
        "Petaling Jaya",
        "Shah Alam",
        "Subang Jaya",
        "Klang",
        "Kajang",
        "Puchong",
        "Rawang",
    ],
    "Terengganu": [
        "Kuala Terengganu",
        "Kemaman",
        "Dungun",
    ],
    "Kuala Lumpur": [
        "Kuala Lumpur",
    ],
    "Putrajaya": [
        "Putrajaya",
    ],
    "Labuan": [
        "Victoria",
    ],
}


def random_state(
    rng: np.random.Generator,
    size: int = 1,
) -> np.ndarray:
    """Generate Malaysian states using approximate portfolio weights."""
    return rng.choice(
        np.asarray(MALAYSIAN_STATES, dtype=object),
        size=size,
        p=np.asarray(MALAYSIAN_STATE_WEIGHTS),
    )


def random_city_for_state(
    rng: np.random.Generator,
    state: str,
) -> str:
    """Generate a city belonging to a given Malaysian state."""
    cities = MALAYSIAN_CITIES_BY_STATE.get(state)

    if not cities:
        raise ValueError(f"Unknown Malaysian state: {state}")

    return str(rng.choice(cities))


def generate_random_postcode(
    rng: np.random.Generator,
) -> str:
    """
    Generate a five-digit Malaysian-style postcode.

    This generates plausible synthetic values; it does not attempt
    to validate against a real postal database.
    """
    return f"{int(rng.integers(10000, 99999)):05d}"


def generate_random_phone(
    rng: np.random.Generator,
) -> str:
    """Generate a Malaysian mobile number in +60 format."""
    prefixes = ["10", "11", "12", "13", "14", "15", "16", "17", "18", "19"]

    prefix = str(rng.choice(prefixes))
    remaining = int(rng.integers(10_000_000, 99_999_999))

    return f"+60{prefix}{remaining}"


def generate_random_ic(
    rng: np.random.Generator,
) -> str:
    """
    Generate a synthetic Malaysian IC-like value.

    Format: YYMMDD-PB-####

    The value is synthetic and is not intended to represent a real person.
    """
    year = int(rng.integers(60, 100))
    month = int(rng.integers(1, 13))

    # Keep day safely within a valid-looking range without
    # attempting full calendar validation.
    day = int(rng.integers(1, 29))

    place = int(rng.integers(1, 17))
    serial = int(rng.integers(0, 10_000))

    return f"{year:02d}{month:02d}{day:02d}-{place:02d}-{serial:04d}"


# ---------------------------------------------------------------------------
# CHUNKING / FILE OUTPUT
# ---------------------------------------------------------------------------


def ensure_directory(path: Path | str) -> Path:
    """Create a directory if needed and return it as a Path."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def chunk_ranges(
    total_rows: int,
    chunk_size: int,
) -> Iterable[tuple[int, int]]:
    """
    Yield half-open row ranges.

    Example:
        total_rows=250, chunk_size=100

        (0, 100)
        (100, 200)
        (200, 250)
    """
    if total_rows < 0:
        raise ValueError("total_rows must be >= 0")

    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")

    for start in range(0, total_rows, chunk_size):
        end = min(start + chunk_size, total_rows)
        yield start, end


def write_dataframe(
    df: pd.DataFrame,
    output_dir: Path | str,
    dataset_name: str,
    part_number: int,
    output_format: str = "parquet",
) -> Path:
    """
    Write one dataframe chunk to disk.

    Files are written as:

        <output_dir>/<dataset_name>/part-00000.parquet

    or:

        <output_dir>/<dataset_name>/part-00000.csv
    """
    if output_format not in {"parquet", "csv"}:
        raise ValueError("output_format must be 'parquet' or 'csv'")

    dataset_dir = ensure_directory(Path(output_dir) / dataset_name)

    filename = f"part-{part_number:05d}.{output_format}"
    output_path = dataset_dir / filename

    if output_format == "parquet":
        df.to_parquet(
            output_path,
            index=False,
            engine="pyarrow",
        )
    else:
        df.to_csv(
            output_path,
            index=False,
        )

    return output_path


# ---------------------------------------------------------------------------
# DATA QUALITY INJECTION HELPERS
# ---------------------------------------------------------------------------


def sample_indices(
    rng: np.random.Generator,
    row_count: int,
    issue_count: int,
) -> np.ndarray:
    """
    Return unique row indices for intentional DQ injection.
    """
    if row_count < 0:
        raise ValueError("row_count must be >= 0")

    if issue_count < 0:
        raise ValueError("issue_count must be >= 0")

    if issue_count > row_count:
        raise ValueError(
            f"issue_count ({issue_count}) cannot exceed " f"row_count ({row_count})"
        )

    if issue_count == 0:
        return np.array([], dtype=np.int64)

    return rng.choice(
        row_count,
        size=issue_count,
        replace=False,
    )


def inject_mixed_case(
    values: pd.Series,
    rng: np.random.Generator,
    count: int,
) -> pd.Series:
    """
    Intentionally alter selected string values to inconsistent casing.
    """
    result = values.astype("string").copy()

    indices = sample_indices(
        rng=rng,
        row_count=len(result),
        issue_count=count,
    )

    if len(indices) == 0:
        return result

    for index in indices:
        value = result.iloc[index]

        if pd.isna(value):
            continue

        text = str(value)

        variants = [
            text.lower(),
            text.upper(),
            text.capitalize(),
        ]

        result.iloc[index] = str(rng.choice(variants))

    return result


def inject_nulls(
    values: pd.Series,
    rng: np.random.Generator,
    count: int,
) -> pd.Series:
    """Replace selected values with NULL."""
    result = values.copy()

    indices = sample_indices(
        rng=rng,
        row_count=len(result),
        issue_count=count,
    )

    if len(indices) > 0:
        result.iloc[indices] = pd.NA

    return result


def inject_invalid_email(
    values: pd.Series,
    rng: np.random.Generator,
    count: int,
) -> pd.Series:
    """
    Replace selected emails with intentionally invalid formats.
    """
    result = values.astype("string").copy()

    indices = sample_indices(
        rng=rng,
        row_count=len(result),
        issue_count=count,
    )

    invalid_patterns = [
        "invalid-email",
        "missing-at.example.com",
        "user@@example.com",
        "user.example.com",
        "user@",
        "@example.com",
        "user..name@example.com",
    ]

    for index in indices:
        result.iloc[index] = str(rng.choice(invalid_patterns))

    return result


def inject_invalid_postcodes(
    values: pd.Series,
    rng: np.random.Generator,
    count: int,
) -> pd.Series:
    """Replace selected postcodes with intentionally invalid values."""
    result = values.astype("string").copy()

    indices = sample_indices(
        rng=rng,
        row_count=len(result),
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
        result.iloc[index] = str(rng.choice(invalid_values))

    return result


def inject_duplicate_values(
    values: pd.Series,
    rng: np.random.Generator,
    count: int,
) -> pd.Series:
    """
    Create duplicate values by copying existing values onto other rows.

    Useful for simulating duplicate natural/business keys.
    """
    result = values.copy()

    if count == 0:
        return result

    if len(result) < 2:
        raise ValueError("At least 2 rows are required to inject duplicates.")

    target_indices = sample_indices(
        rng=rng,
        row_count=len(result),
        issue_count=count,
    )

    source_indices = rng.integers(
        0,
        len(result),
        size=count,
    )

    for target, source in zip(target_indices, source_indices):
        result.iloc[target] = result.iloc[source]

    return result


# ---------------------------------------------------------------------------
# VALIDATION HELPERS
# ---------------------------------------------------------------------------


def assert_row_count(
    df: pd.DataFrame,
    expected: int,
    dataset_name: str,
) -> None:
    """Raise an error when a dataframe has an unexpected row count."""
    actual = len(df)

    if actual != expected:
        raise ValueError(
            f"{dataset_name}: expected {expected:,} rows, " f"got {actual:,}"
        )


def assert_required_columns(
    df: pd.DataFrame,
    required_columns: Sequence[str],
    dataset_name: str,
) -> None:
    """Validate that all required columns exist."""
    missing = [column for column in required_columns if column not in df.columns]

    if missing:
        raise ValueError(f"{dataset_name}: missing required columns: " f"{missing}")


def assert_unique(
    df: pd.DataFrame,
    column: str,
    dataset_name: str,
) -> None:
    """Validate uniqueness of a column."""
    duplicate_count = int(df[column].duplicated().sum())

    if duplicate_count > 0:
        raise ValueError(
            f"{dataset_name}: column '{column}' contains "
            f"{duplicate_count:,} duplicate values."
        )


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------


def log_dataset_written(
    dataset_name: str,
    rows: int,
    path: Path,
) -> None:
    """Print a standard dataset-write message."""
    print(f"[generated] {dataset_name:<22} " f"{rows:>12,} rows  →  {path}")
