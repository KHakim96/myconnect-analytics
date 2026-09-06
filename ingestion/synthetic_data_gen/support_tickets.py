"""
MYConnect synthetic support ticket generator.

SOURCE CONTRACT: src_support_tickets
Expected rows: 180,000
Columns: 14 (exact order)
1. ticket_id           VARCHAR(20), PK
2. customer_id         VARCHAR(20), FK -> src_customers (nullable)
3. subscription_id     VARCHAR(20), FK -> src_subscriptions (nullable)
4. created_date        TIMESTAMP
5. resolved_date       TIMESTAMP (nullable)
6. category            VARCHAR(50)
7. subcategory         VARCHAR(50)
8. priority            VARCHAR(10)
9. status              VARCHAR(20)
10. channel            VARCHAR(20)
11. assigned_agent     VARCHAR(100)
12. resolution_notes   TEXT (nullable)
13. satisfaction_score INT (nullable, 1-5 scale)
14. created_at         TIMESTAMP

Contractual Data Quality Targets:
- ~500 tickets with resolved_date < created_date (chronological violation)
- Category inconsistencies: Billing vs billing vs BILLING
- ~3,000 tickets with customer_id IS NULL (walk-in / anonymous inquiries)
- ~2,000 tickets with resolved_date IS NOT NULL but status = 'open'

Explicit Synthetic Assumption:
- 3,000 category inconsistency records (1,500 'Billing' and 1,500 'BILLING')

Architecture & Performance:
- Fully vectorized NumPy array operations.
- Mutually disjoint DQ populations preventing cross-contamination.
- Valid customer and subscription referential integrity.
- Streaming to Snappy-compressed Parquet with atomic replacement.
"""

from __future__ import annotations

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

OUTPUT_DIR = GENERATED_DATA_DIR / "support_tickets"
OUTPUT_PATH = OUTPUT_DIR / "part-00000.parquet"

RANDOM_SEED = 42

TICKET_COUNT = 180_000

# Contractual DQ targets
INVALID_RESOLVED_DATE_COUNT = 500
ANONYMOUS_TICKET_COUNT = 3_000
RESOLVED_BUT_OPEN_COUNT = 2_000

# Explicit synthetic assumption for category inconsistency count
CATEGORY_INCONSISTENCY_COUNT = 3_000

# Realistic proportion of customer tickets without a specific subscription linked
CUSTOMER_ONLY_TICKET_COUNT = 15_000

ALLOWED_PRIORITIES = ("low", "medium", "high", "critical")
ALLOWED_CHANNELS = ("phone", "chat", "app", "email", "social_media")
ALLOWED_STATUSES = ("open", "in_progress", "resolved", "closed", "escalated")
ALLOWED_CATEGORIES = (
    "connectivity",
    "billing",
    "Billing",
    "BILLING",
    "installation",
    "speed",
    "equipment",
)

OUTPUT_SCHEMA = pa.schema(
    [
        ("ticket_id", pa.string()),
        ("customer_id", pa.string()),
        ("subscription_id", pa.string()),
        ("created_date", pa.timestamp("ns")),
        ("resolved_date", pa.timestamp("ns")),
        ("category", pa.string()),
        ("subcategory", pa.string()),
        ("priority", pa.string()),
        ("status", pa.string()),
        ("channel", pa.string()),
        ("assigned_agent", pa.string()),
        ("resolution_notes", pa.string()),
        ("satisfaction_score", pa.int64()),
        ("created_at", pa.timestamp("ns")),
    ]
)


# ---------------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------------


def generate_support_tickets() -> None:
    """Generate the synthetic src_support_tickets dataset with exact contractual DQ requirements."""
    rng = np.random.default_rng(RANDOM_SEED)

    if not CUSTOMERS_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {CUSTOMERS_PATH}")

    if not SUBSCRIPTIONS_PATH.exists():
        raise FileNotFoundError(f"Missing required input: {SUBSCRIPTIONS_PATH}")

    # 1. Load customers and subscriptions
    print("[load] Reading customers table...")
    cust_tbl = pq.read_table(CUSTOMERS_PATH, columns=["customer_id"])
    cust_ids = cust_tbl["customer_id"].to_pylist()
    valid_cust_set = set(cust_ids)

    print("[load] Reading subscriptions table...")
    sub_tbl = pq.read_table(SUBSCRIPTIONS_PATH, columns=["subscription_id", "customer_id"])
    sub_ids = sub_tbl["subscription_id"].to_pylist()
    sub_custs = sub_tbl["customer_id"].to_pylist()

    # Filter subscriptions to only those linked to valid customers to prevent orphan FKs
    print("[filter] Filtering valid customer/subscription pairs...")
    valid_sub_indices = [i for i, c in enumerate(sub_custs) if c in valid_cust_set]
    valid_sub_ids = [sub_ids[i] for i in valid_sub_indices]
    valid_sub_custs = [sub_custs[i] for i in valid_sub_indices]

    print(f"[filter] Loaded {len(cust_ids):,} customers and {len(valid_sub_ids):,} valid subscriptions.")

    # 2. Assign customer_id and subscription_id relationships
    # - 3,000 anonymous tickets: customer_id = None, subscription_id = None
    # - 15,000 customer-only tickets: customer_id = valid, subscription_id = None
    # - 162,000 subscription-linked tickets: customer_id = sub's customer, subscription_id = sub_id
    print("[sample] Assigning customer and subscription relationships...")
    sub_linked_count = TICKET_COUNT - ANONYMOUS_TICKET_COUNT - CUSTOMER_ONLY_TICKET_COUNT  # 162,000

    sampled_sub_idx = rng.choice(len(valid_sub_ids), size=sub_linked_count, replace=True)
    sub_linked_sub_ids = [valid_sub_ids[i] for i in sampled_sub_idx]
    sub_linked_cust_ids = [valid_sub_custs[i] for i in sampled_sub_idx]

    sampled_cust_idx = rng.choice(len(cust_ids), size=CUSTOMER_ONLY_TICKET_COUNT, replace=True)
    cust_only_cust_ids = [cust_ids[i] for i in sampled_cust_idx]
    cust_only_sub_ids = [None] * CUSTOMER_ONLY_TICKET_COUNT

    anon_cust_ids = [None] * ANONYMOUS_TICKET_COUNT
    anon_sub_ids = [None] * ANONYMOUS_TICKET_COUNT

    # Partition indices across the 180,000 rows:
    # anonymous:          0 .. 2,999      (3,000 rows)
    # invalid_resolved:   3,000 .. 3,499  (500 rows)
    # resolved_but_open:  3,500 .. 5,499  (2,000 rows)
    # customer_only:      5,500 .. 20,499 (15,000 rows)
    # standard:           20,500 .. 179,999 (159,500 rows)
    print("[partition] Allocating mutually disjoint DQ populations...")
    all_customer_ids = np.array(
        anon_cust_ids
        + sub_linked_cust_ids[:INVALID_RESOLVED_DATE_COUNT]
        + sub_linked_cust_ids[INVALID_RESOLVED_DATE_COUNT : INVALID_RESOLVED_DATE_COUNT + RESOLVED_BUT_OPEN_COUNT]
        + cust_only_cust_ids
        + sub_linked_cust_ids[INVALID_RESOLVED_DATE_COUNT + RESOLVED_BUT_OPEN_COUNT :],
        dtype=object,
    )

    all_subscription_ids = np.array(
        anon_sub_ids
        + sub_linked_sub_ids[:INVALID_RESOLVED_DATE_COUNT]
        + sub_linked_sub_ids[INVALID_RESOLVED_DATE_COUNT : INVALID_RESOLVED_DATE_COUNT + RESOLVED_BUT_OPEN_COUNT]
        + cust_only_sub_ids
        + sub_linked_sub_ids[INVALID_RESOLVED_DATE_COUNT + RESOLVED_BUT_OPEN_COUNT :],
        dtype=object,
    )

    if len(all_customer_ids) != TICKET_COUNT or len(all_subscription_ids) != TICKET_COUNT:
        raise ValueError("Relationship array length mismatch.")

    # 3. Timestamps across 2024-01-01 to 2025-06-30
    print("[generate] Generating ticket creation timestamps...")
    start_s = int(pd.Timestamp("2024-01-01 08:00:00").timestamp())
    end_s = int(pd.Timestamp("2025-06-30 20:00:00").timestamp())
    sec_offsets = rng.integers(0, end_s - start_s, size=TICKET_COUNT).astype("timedelta64[s]")
    base_start = np.datetime64("2024-01-01T08:00:00", "s")

    created_dates = (base_start + sec_offsets).astype("datetime64[ns]")
    created_at = (
        base_start + sec_offsets + rng.integers(0, 60, size=TICKET_COUNT).astype("timedelta64[s]")
    ).astype("datetime64[ns]")

    # 4. Categories and Subcategories
    print("[generate] Generating categories and subcategories...")
    categories_list = ["connectivity", "speed", "billing", "equipment", "installation"]
    cat_probs = [0.35, 0.25, 0.20, 0.12, 0.08]

    subcats = {
        "connectivity": ["intermittent_connection", "no_connection", "packet_loss", "high_latency"],
        "billing": ["invoice_query", "payment_issue", "incorrect_charge", "refund_request"],
        "installation": [
            "installation_delay",
            "installation_request",
            "technician_issue",
            "reschedule_installation",
        ],
        "speed": ["slow_speed", "speed_fluctuation", "throughput_issue", "wifi_speed_drop"],
        "equipment": ["router_issue", "mesh_issue", "modem_issue", "power_adapter_fault"],
    }

    assigned_categories = rng.choice(categories_list, size=TICKET_COUNT, p=cat_probs)
    assigned_subcategories = np.empty(TICKET_COUNT, dtype=object)

    for cat, sub_list in subcats.items():
        mask = assigned_categories == cat
        assigned_subcategories[mask] = rng.choice(sub_list, size=int(mask.sum()))

    # Inject Category Inconsistency DQ: 1,500 'Billing' and 1,500 'BILLING'
    print(f"[dq] Injecting {CATEGORY_INCONSISTENCY_COUNT:,} category inconsistency records...")
    billing_indices = np.flatnonzero(assigned_categories == "billing")
    if len(billing_indices) < CATEGORY_INCONSISTENCY_COUNT:
        raise ValueError("Not enough billing tickets for category inconsistency.")

    inconsistent_idx = rng.choice(billing_indices, size=CATEGORY_INCONSISTENCY_COUNT, replace=False)
    half = CATEGORY_INCONSISTENCY_COUNT // 2
    assigned_categories[inconsistent_idx[:half]] = "Billing"
    assigned_categories[inconsistent_idx[half:]] = "BILLING"

    # 5. Priorities, Channels, Agents
    print("[generate] Generating priorities, channels, and assigned agents...")
    priorities = rng.choice(
        list(ALLOWED_PRIORITIES),
        size=TICKET_COUNT,
        p=[0.25, 0.45, 0.22, 0.08],
    )
    channels = rng.choice(
        list(ALLOWED_CHANNELS),
        size=TICKET_COUNT,
        p=[0.40, 0.25, 0.20, 0.10, 0.05],
    )
    agent_names = [f"Agent-{i:03d}" for i in range(1, 101)]
    assigned_agents = rng.choice(agent_names, size=TICKET_COUNT)

    # 6. Status and Resolved Date Lifecycle & DQ Injections
    print("[lifecycle] Constructing ticket lifecycle, resolutions, and satisfaction scores...")
    statuses = np.empty(TICKET_COUNT, dtype=object)
    resolved_dates = np.full(TICKET_COUNT, None, dtype=object)
    resolution_notes = np.full(TICKET_COUNT, None, dtype=object)
    satisfaction_scores = np.full(TICKET_COUNT, None, dtype=object)

    notes_templates = [
        "Router restarted remotely and confirmed sync.",
        "Reconfigured customer ONT and verified optical power levels.",
        "Billing adjustment applied to next billing cycle.",
        "Technician visit scheduled for onsite fiber inspection.",
        "Replaced faulty Wi-Fi 6 router and tested throughput.",
        "Escalated to L2 network engineering team for exchange port check.",
        "Resolved intermittent connectivity after line profile reset.",
        "Assisted customer with 5GHz Wi-Fi channel optimization.",
        "Payment verified with finance team and restriction lifted.",
        "Firmware upgraded remotely and connection verified stable.",
    ]

    # DQ 1: Invalid resolved date (500 rows)
    # Indices: 3,000 .. 3,499
    invalid_idx = np.arange(3000, 3500)
    statuses[invalid_idx] = rng.choice(["resolved", "closed"], size=INVALID_RESOLVED_DATE_COUNT, p=[0.70, 0.30])
    invalid_delays = rng.integers(3600, 2 * 86400, size=INVALID_RESOLVED_DATE_COUNT).astype("timedelta64[s]")
    resolved_dates[invalid_idx] = (
        created_dates[invalid_idx].astype("datetime64[s]") - invalid_delays
    ).astype("datetime64[ns]")
    resolution_notes[invalid_idx] = rng.choice(notes_templates, size=INVALID_RESOLVED_DATE_COUNT)

    # DQ 2: Resolved-but-open (2,000 rows)
    # Indices: 3,500 .. 5,499
    resolved_open_idx = np.arange(3500, 5500)
    statuses[resolved_open_idx] = "open"
    open_delays = rng.integers(1800, 3 * 86400, size=RESOLVED_BUT_OPEN_COUNT).astype("timedelta64[s]")
    resolved_dates[resolved_open_idx] = (
        created_dates[resolved_open_idx].astype("datetime64[s]") + open_delays
    ).astype("datetime64[ns]")
    resolution_notes[resolved_open_idx] = rng.choice(notes_templates, size=RESOLVED_BUT_OPEN_COUNT)

    # Normal population: indices 0..2999 (anonymous) and 5500..179999 (rest)
    normal_idx = np.concatenate([np.arange(0, 3000), np.arange(5500, TICKET_COUNT)])
    normal_count = len(normal_idx)

    normal_statuses = rng.choice(
        list(ALLOWED_STATUSES),
        size=normal_count,
        p=[0.10, 0.06, 0.55, 0.25, 0.04],
    )
    statuses[normal_idx] = normal_statuses

    # Normal resolved / closed tickets get resolved_date > created_date and notes
    is_resolved_closed = np.isin(normal_statuses, ["resolved", "closed"])
    rc_indices = normal_idx[is_resolved_closed]
    rc_count = len(rc_indices)

    rc_delays = rng.integers(1800, 3 * 86400, size=rc_count).astype("timedelta64[s]")
    resolved_dates[rc_indices] = (
        created_dates[rc_indices].astype("datetime64[s]") + rc_delays
    ).astype("datetime64[ns]")
    resolution_notes[rc_indices] = rng.choice(notes_templates, size=rc_count)

    # Satisfaction score: ~40% of resolved/closed tickets receive a score between 1 and 5
    all_resolved_indices = np.concatenate([invalid_idx, resolved_open_idx, rc_indices])
    score_mask = rng.uniform(0.0, 1.0, size=len(all_resolved_indices)) < 0.40
    scored_idx = all_resolved_indices[score_mask]
    satisfaction_scores[scored_idx] = rng.choice(
        [1, 2, 3, 4, 5],
        size=len(scored_idx),
        p=[0.03, 0.05, 0.12, 0.35, 0.45],
    )

    # 7. Unique Ticket IDs
    print("[assemble] Generating globally unique ticket IDs...")
    ticket_ids = [f"TKT-{n:06d}" for n in range(1, TICKET_COUNT + 1)]

    # 8. Assemble PyArrow Table
    print("[assemble] Assembling PyArrow Table...")
    table = pa.Table.from_arrays(
        [
            pa.array(ticket_ids, type=pa.string()),
            pa.array(all_customer_ids, type=pa.string()),
            pa.array(all_subscription_ids, type=pa.string()),
            pa.array(created_dates, type=pa.timestamp("ns")),
            pa.array(resolved_dates, type=pa.timestamp("ns")),
            pa.array(assigned_categories, type=pa.string()),
            pa.array(assigned_subcategories, type=pa.string()),
            pa.array(priorities, type=pa.string()),
            pa.array(statuses, type=pa.string()),
            pa.array(channels, type=pa.string()),
            pa.array(assigned_agents, type=pa.string()),
            pa.array(resolution_notes, type=pa.string()),
            pa.array(satisfaction_scores, type=pa.int64()),
            pa.array(created_at, type=pa.timestamp("ns")),
        ],
        schema=OUTPUT_SCHEMA,
    )

    # 9. Safely write output to Parquet
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temp_output_path = OUTPUT_DIR / f"{OUTPUT_PATH.name}.tmp"

    if temp_output_path.exists():
        temp_output_path.unlink()

    print(f"[write] Writing Parquet to {OUTPUT_PATH}...")
    pq.write_table(table, temp_output_path, compression="snappy")

    # Atomically replace final file
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()
    temp_output_path.replace(OUTPUT_PATH)
    print(f"[write] Successfully saved {OUTPUT_PATH}")

    # 10. Final validation of written Parquet dataset
    print("\n[validate] Validating final Parquet dataset...")
    output_reader = pq.ParquetFile(OUTPUT_PATH)
    output_rows = output_reader.metadata.num_rows

    if output_rows != TICKET_COUNT:
        raise AssertionError(f"Expected {TICKET_COUNT:,} rows, found {output_rows:,}.")

    schema_arrow = output_reader.schema_arrow
    expected_col_names = [f.name for f in OUTPUT_SCHEMA]
    actual_col_names = list(schema_arrow.names)
    if actual_col_names != expected_col_names:
        raise AssertionError(
            f"Columns mismatch: expected {expected_col_names}, got {actual_col_names}"
        )

    if schema_arrow.field("ticket_id").type != pa.string():
        raise AssertionError("ticket_id physical type must be string.")
    if schema_arrow.field("created_date").type != pa.timestamp("ns"):
        raise AssertionError("created_date physical type must be timestamp[ns].")
    if schema_arrow.field("resolved_date").type != pa.timestamp("ns"):
        raise AssertionError("resolved_date physical type must be timestamp[ns].")
    if schema_arrow.field("satisfaction_score").type != pa.int64():
        raise AssertionError("satisfaction_score physical type must be int64.")
    if schema_arrow.field("created_at").type != pa.timestamp("ns"):
        raise AssertionError("created_at physical type must be timestamp[ns].")

    # Read output table with pandas for content validations
    output = pd.read_parquet(OUTPUT_PATH)

    # 1. Uniqueness of ticket_id
    duplicate_ticket_id = int(output["ticket_id"].duplicated().sum())
    if duplicate_ticket_id != 0:
        raise AssertionError(f"Found {duplicate_ticket_id:,} duplicate ticket IDs.")

    # 2. Anonymous customer tickets
    anonymous_customer_count = int(output["customer_id"].isna().sum())
    if anonymous_customer_count != ANONYMOUS_TICKET_COUNT:
        raise AssertionError(
            f"Expected {ANONYMOUS_TICKET_COUNT:,} anonymous tickets, found {anonymous_customer_count:,}."
        )

    # Anonymous tickets must also have NULL subscription_id
    anon_sub_count = int(output.loc[output["customer_id"].isna(), "subscription_id"].notna().sum())
    if anon_sub_count != 0:
        raise AssertionError(f"Found {anon_sub_count} anonymous tickets with non-NULL subscription_id.")

    # 3. Orphan customer IDs
    non_null_custs = output["customer_id"].dropna().unique()
    orphan_custs = set(non_null_custs) - valid_cust_set
    orphan_customer_count = len(orphan_custs)
    if orphan_customer_count != 0:
        raise AssertionError(f"Found {orphan_customer_count} orphan customer IDs.")

    # 4. Orphan subscription IDs
    all_valid_sub_set = set(sub_ids)
    non_null_subs = output["subscription_id"].dropna().unique()
    orphan_subs = set(non_null_subs) - all_valid_sub_set
    orphan_subscription_count = len(orphan_subs)
    if orphan_subscription_count != 0:
        raise AssertionError(f"Found {orphan_subscription_count} orphan subscription IDs.")

    # 5. Customer / Subscription relationship consistency
    sub_to_cust = dict(zip(sub_ids, sub_custs))
    linked_mask = output["subscription_id"].notna()
    matched_cust = output.loc[linked_mask, "subscription_id"].map(sub_to_cust)
    cust_sub_mismatches = int((output.loc[linked_mask, "customer_id"] != matched_cust).sum())
    if cust_sub_mismatches != 0:
        raise AssertionError(f"Found {cust_sub_mismatches} customer/subscription mismatches.")

    # 6. Invalid resolved dates (resolved_date < created_date)
    invalid_resolved_dates_count = int(
        (output["resolved_date"].notna() & (output["resolved_date"] < output["created_date"])).sum()
    )
    if invalid_resolved_dates_count != INVALID_RESOLVED_DATE_COUNT:
        raise AssertionError(
            f"Expected {INVALID_RESOLVED_DATE_COUNT:,} invalid resolved dates, found {invalid_resolved_dates_count:,}."
        )

    # 7. Resolved-but-open tickets (resolved_date IS NOT NULL & status = 'open')
    resolved_but_open_count = int(
        (output["resolved_date"].notna() & (output["status"] == "open")).sum()
    )
    if resolved_but_open_count != RESOLVED_BUT_OPEN_COUNT:
        raise AssertionError(
            f"Expected {RESOLVED_BUT_OPEN_COUNT:,} resolved-but-open tickets, found {resolved_but_open_count:,}."
        )

    # 8. Category inconsistency
    actual_cats = set(output["category"].unique())
    if not actual_cats.issubset(set(ALLOWED_CATEGORIES)):
        raise AssertionError(f"Unexpected categories found: {actual_cats - set(ALLOWED_CATEGORIES)}")

    category_inconsistency_count = int(output["category"].isin(["Billing", "BILLING"]).sum())
    if category_inconsistency_count != CATEGORY_INCONSISTENCY_COUNT:
        raise AssertionError(
            f"Expected {CATEGORY_INCONSISTENCY_COUNT:,} category inconsistencies, found {category_inconsistency_count:,}."
        )

    # 9. Satisfaction score validity (only 1-5 or NULL)
    valid_scores = set(output["satisfaction_score"].dropna().astype(int).unique())
    invalid_scores = valid_scores - {1, 2, 3, 4, 5}
    invalid_satisfaction_scores = len(invalid_scores)
    if invalid_satisfaction_scores != 0:
        raise AssertionError(f"Found invalid satisfaction scores: {invalid_scores}")

    # 10. Priority, channel, and status sets
    if not set(output["priority"].unique()).issubset(set(ALLOWED_PRIORITIES)):
        raise AssertionError("Unexpected priority values found.")
    if not set(output["channel"].unique()).issubset(set(ALLOWED_CHANNELS)):
        raise AssertionError("Unexpected channel values found.")
    if not set(output["status"].unique()).issubset(set(ALLOWED_STATUSES)):
        raise AssertionError("Unexpected status values found.")

    # 11. Print formatted summary
    print(f"\n[generated] src_support_tickets {output_rows:,} rows  →  {OUTPUT_PATH}")
    print("\nSupport ticket generation complete.")

    print("\nSchema:")
    print(output_reader.schema_arrow)

    print("\nDQ expectations:")
    print(f"  invalid resolved dates       : ~{INVALID_RESOLVED_DATE_COUNT:,}")
    print(f"  category inconsistencies     : controlled synthetic population ({CATEGORY_INCONSISTENCY_COUNT:,})")
    print(f"  anonymous customer tickets   : ~{ANONYMOUS_TICKET_COUNT:,}")
    print(f"  resolved-but-open tickets    : ~{RESOLVED_BUT_OPEN_COUNT:,}")

    print("\nDQ validation:")
    print(f"  row count                    : {output_rows:,}")
    print(f"  duplicate ticket_id          : {duplicate_ticket_id:,}")
    print(f"  orphan customer IDs          : {orphan_customer_count:,}")
    print(f"  orphan subscription IDs      : {orphan_subscription_count:,}")
    print(f"  customer/subscription mismatches: {cust_sub_mismatches:,}")
    print(f"  invalid resolved dates       : {invalid_resolved_dates_count:,}")
    print(f"  anonymous customer count     : {anonymous_customer_count:,}")
    print(f"  resolved-but-open count      : {resolved_but_open_count:,}")
    print(f"  category inconsistency count : {category_inconsistency_count:,}")
    print(f"  invalid satisfaction scores  : {invalid_satisfaction_scores:,}")

    print("\nOutput:")
    print(f"  {OUTPUT_PATH}")


def main() -> None:
    generate_support_tickets()


if __name__ == "__main__":
    main()
