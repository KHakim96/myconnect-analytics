# MYConnect Analytics — Bronze Data Profile

**GCP Project:** `myconnect-analytics` | **Dataset:** `myconnect_bronze` | **Region:** `asia-southeast1`

---

## 1. Bronze Overview

| Table | Rows | Grain | PK |
|---|---|---|---|
| `customers` | 250,000 | 1 row per customer | `customer_id` |
| `subscriptions` | 350,000 | 1 row per subscription | `subscription_id` |
| `plans` | 18 | 1 row per plan | `plan_id` |
| `billing` | 3,000,000 | 1 row per invoice | `invoice_id` |
| `bill_line_items` | 5,000,000 | 1 row per line item | `line_item_id` |
| `payments` | 2,800,000 | 1 row per payment | `payment_id` |
| `usage_daily` | 4,500,000 | 1 row per (subscription, date) | `usage_id` |
| `support_tickets` | 180,000 | 1 row per ticket | `ticket_id` |
| `network_events` | 2,000,000 | 1 row per event | `event_id` |
| `promotions` | 30 | 1 row per promotion | `promo_id` |
| `churn_events` | 35,000 | 1 row per churn event | `churn_event_id` |

---

## 2. Per-Table DQ Profile

### 2.1 `customers`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| `ic_number` | Duplicate IDs | ~500 duplicates | 510 duplicate records | Deduplicated: keep latest `updated_at`; Bronze row count drops to 249,490 |
| `email` | Invalid format | ~2% invalid | 1,704 invalid emails | `is_valid_email` flag (REGEXP check); rows retained |
| `city` | Abbreviated values | Present | ~5,562 `PJ`/`KL` records | Standardized: `PJ`→`Petaling Jaya`, `KL`→`Kuala Lumpur` |
| `registration_date` | Future dates | ~100 future dates | 0 observed at query time | Capped to `CURRENT_DATE()` if future |
| `registration_date`, `created_at`, `updated_at` | INT64 epoch-nanoseconds (not TIMESTAMP) | Physical type issue | Confirmed INT64 in Bronze | Converted: `TIMESTAMP_MICROS(DIV(col, 1000))` |

### 2.2 `subscriptions`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| `customer_id` | Orphan FK | ~1% orphans | 800 orphan records | Filtered out via `IN (SELECT customer_id FROM stg_customers)`; Silver drops to 349,200 |
| `start_date` / `end_date` | Date inversions | ~400 inversions | 400 inversions | Swapped: `LEAST`/`GREATEST` |
| `monthly_rate_charged` | Mismatches plan MRC | ~18,000 discrepancies | 18,000 non-promo discrepancies | `is_mrc_matching_plan` flag; source MRC preserved |
| Active subscriptions | Overlapping active subs | ~1,682 overlaps | 1,682 overlapping records | `is_overlapping_active` window flag; rows retained |
| `created_at`, `updated_at` | INT64 epoch-nanoseconds | Physical type issue | Confirmed INT64 | Converted: `TIMESTAMP_MICROS(DIV(col, 1000))` |

### 2.3 `plans`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| — | No DQ issues specified | — | No anomalies observed | Pass-through; all 18 rows retained |

### 2.4 `billing`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| `(subscription_id, billing_period_start)` | Duplicate invoices for same subscription + billing period | ~5,000 duplicates | ~5,000 duplicate records | Deduplicated: keep earliest `created_at` per `(subscription_id, billing_period_start)`; contributes to Silver row reduction |
| `total_amount`, `status` | Zero-amount non-void invoices | ~3,000 records | ~3,000 invoices with `total_amount = 0` and `status != 'void'` | Filtered out: `WHERE NOT (total_amount = 0 AND status != 'void')`; contributes to Silver row reduction |
| `status` | Mixed casing | Present | Mixed case observed | Standardized to `LOWER()` |
| `created_at` | INT64 epoch-nanoseconds | Physical type issue | Confirmed INT64 | Converted: `TIMESTAMP_MICROS(DIV(col, 1000))` |

### 2.5 `bill_line_items`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| `charge_type` | NULL values | ~50,000 NULLs | 50,000 NULL records | `COALESCE(charge_type, 'unclassified')`; rows retained |
| `amount` | Negative values (credits/adjustments) | Legitimate — preserve | Present | **Preserved as-is**; not treated as errors |
| `created_at` | INT64 epoch-nanoseconds | Physical type issue | Confirmed INT64 | Converted: `TIMESTAMP_MICROS(DIV(col, 1000))` |

### 2.6 `payments`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| `invoice_id`, `payment_date`, `payment_amount` | Duplicate retry payments | ~3,000 duplicates | 3,000 duplicate records | Deduplicated: keep earliest `created_at` per `(invoice_id, payment_date, payment_amount)`; Silver drops to ~2,797,000 |
| `invoice_id` | Orphan FK | ~5,000 orphans | 5,000 orphan invoice references | `is_orphan_payment` flag; rows retained |
| `payment_status` | Mixed casing | Present | Mixed case observed | Standardized to `LOWER()` |
| `created_at` | INT64 epoch-nanoseconds | Physical type issue | Confirmed INT64 | Converted: `TIMESTAMP_MICROS(DIV(col, 1000))` |

### 2.7 `usage_daily`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| `(subscription_id, usage_date)` | Duplicate composite key | ~1,000 duplicates | 1,000 duplicate records | Deduplicated: keep earliest `created_at`; Silver drops to ~4,499,000 |
| `download_gb`, `upload_gb` | Negative values | Present | Negative volumes present | Clamped to 0: `CASE WHEN col < 0 THEN 0 ELSE col END` |
| `peak_download_mbps`, `avg_download_mbps` | Outlier speeds | Present | Values > 2,000 Mbps present | Capped at 2,000 Mbps |
| Late-arriving records | Incremental late arrivals | Present | Possible late delivery | 3-day lookback window on incremental runs: `> MAX(created_at) - INTERVAL 3 DAY` |
| `created_at` | INT64 epoch-nanoseconds | Physical type issue | Confirmed INT64 | Converted: `TIMESTAMP_MICROS(DIV(col, 1000))` |

### 2.8 `support_tickets`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| `created_date` / `resolved_date` | Date inversions | Present | Inversions present | Two-step CTE: convert INT64→TIMESTAMP first, then swap inverted pairs |
| `customer_id` | NULL values | Legitimate (anonymous/walk-in) | Present | **Preserved as-is**; not treated as invalid |
| `category` | Mixed casing | Present | Mixed case observed | Standardized to `LOWER()` |
| `created_date`, `resolved_date`, `created_at` | INT64 epoch-nanoseconds | Physical type issue | Confirmed INT64 | Converted: `TIMESTAMP_MICROS(DIV(col, 1000))` |

### 2.9 `network_events`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| `start_time` / `end_time` | Timestamp inversions | Present | Inversions present | Two-step CTE: convert INT64→TIMESTAMP first, then swap inverted pairs |
| `region` | Inconsistent values | Present | `KLANGVALLEY`, `Klang valley`, `South`, `Southern`, `North`, `Northern` | Standardized to canonical region names |
| `customer_id`, `subscription_id` | No FK to customers/subscriptions | By design (telemetry) | Confirmed absent | **Not a DQ defect**; network events are infrastructure-level |
| `start_time`, `end_time`, `created_at` | INT64 epoch-nanoseconds | Physical type issue | Confirmed INT64 | Converted: `TIMESTAMP_MICROS(DIV(col, 1000))` |

### 2.10 `promotions`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| `start_date` / `end_date` | Date inversions | 2 inversions | `PROMO-005`, `PROMO-015` inverted | Swapped: `LEAST`/`GREATEST` |
| `eligible_plans` | CSV string (not normalized) | By design | Present | Parsed: `SPLIT(eligible_plans, ',')` converts CSV to array of plan IDs; all 30 rows retained |

### 2.11 `churn_events`

| Column | Issue | Specified DQ | Actual Observed | Silver Staging Handling |
|---|---|---|---|---|
| `subscription_id` (status) | Active subscriptions at churn | ~1,000 anomalies | 1,000 churn events where subscription is still active | `is_subscription_terminated` flag (LEFT JOIN to subscriptions); rows retained |
| `churn_reason` | NULL for involuntary churn | ~500 NULLs | 500 NULL churn_reason records | **NULLs preserved** (see Section 6) |
| `created_at` | INT64 epoch-nanoseconds | Physical type issue | Confirmed INT64 | Converted: `TIMESTAMP_MICROS(DIV(col, 1000))` |

---

## 3. Bronze Physical Type Findings

All timestamp-type columns across 9 of 11 tables are stored as **INT64 epoch-nanoseconds**, not BigQuery TIMESTAMP.

| Table | INT64 Timestamp Columns |
|---|---|
| `customers` | `registration_date`, `created_at`, `updated_at` |
| `subscriptions` | `created_at`, `updated_at` |
| `billing` | `created_at` |
| `bill_line_items` | `created_at` |
| `payments` | `created_at` |
| `usage_daily` | `created_at` |
| `support_tickets` | `created_date`, `resolved_date`, `created_at` |
| `network_events` | `start_time`, `end_time`, `created_at` |
| `churn_events` | `created_at` |
| `promotions` | *(DATE type — no INT64 timestamps)* |
| `plans` | *(DATE type — no INT64 timestamps)* |

**Conversion pattern used in all Silver models:**
```sql
TIMESTAMP_MICROS(DIV(col, 1000))
```
Divides nanoseconds by 1,000 to obtain microseconds for BigQuery's `TIMESTAMP_MICROS()`.

> **Note:** For `support_tickets` and `network_events`, inversion-swap logic depends on TIMESTAMP comparison. A two-step CTE is required: convert INT64→TIMESTAMP in step 1, then swap in step 2.

---

## 4. Bronze → Silver Row Count Mapping

| Bronze Table | Bronze Rows | Silver Model | Silver Rows | Delta | Reason |
|---|---|---|---|---|---|
| `customers` | 250,000 | `stg_customers` | 249,490 | −510 | IC number deduplication |
| `subscriptions` | 350,000 | `stg_subscriptions` | 349,200 | −800 | Orphan customer_id filter |
| `plans` | 18 | `stg_plans` | 18 | 0 | Pass-through |
| `billing` | 3,000,000 | `stg_billing` | 2,995,000 | −5,000 | Duplicate invoice deduplication + zero-amount non-void filter (combined) |
| `bill_line_items` | 5,000,000 | `stg_bill_line_items` | 5,000,000 | 0 | No row removal (NULL → 'unclassified') |
| `payments` | 2,800,000 | `stg_payments` | 2,797,000 | −3,000 | Duplicate retry deduplication |
| `usage_daily` | 4,500,000 | `stg_usage_daily` | 4,499,000 | −1,000 | Duplicate composite key deduplication |
| `support_tickets` | 180,000 | `stg_support_tickets` | 180,000 | 0 | No row removal |
| `network_events` | 2,000,000 | `stg_network_events` | 2,000,000 | 0 | No row removal |
| `promotions` | 30 | `stg_promotions` | 30 | 0 | Pass-through |
| `churn_events` | 35,000 | `stg_churn_events` | 35,000 | 0 | No row removal |

---

## 5. Bronze Issues Requiring Downstream Handling

The following anomalies are **flagged but not removed** at Silver Staging. They must be handled in Silver Intermediate or Gold.

| Flag Column | Table | Issue | Downstream Action Needed |
|---|---|---|---|
| `is_valid_email` | `stg_customers` | Invalid email format | Filter or segment in Gold/Mart |
| `is_mrc_matching_plan` | `stg_subscriptions` | MRC ≠ plan rate (non-promo) | Revenue reconciliation in Gold |
| `is_overlapping_active` | `stg_subscriptions` | Multiple active subs per customer | De-overlap logic in `int_customer_subscriptions` |
| `is_orphan_payment` | `stg_payments` | Payment references unknown invoice | Exclude from revenue reconciliation |
| `is_subscription_terminated` | `stg_churn_events` | Churn event on active subscription | Data quality flag for churn model |

---

## 6. Specification-to-Implementation Notes

| Item | Specification | Current Silver Implementation | Status |
|---|---|---|---|
| `churn_events.churn_reason` NULL imputation | Spec states NULLs (involuntary churn) **should be imputed as `'non_payment'`** | `stg_churn_events` preserves NULLs; no imputation applied | ⚠️ **Discrepancy** — imputation not implemented |
| `usage_daily` negative volumes + outlier speeds | Spec notes negative `download_gb`/`upload_gb` and outlier speed values | Negative volumes clamped to 0; `peak_download_mbps`/`avg_download_mbps` capped at 2,000 Mbps | ✅ Compliant |
| `usage_daily` incremental late arrivals | Spec requires late-arriving records to be captured | 3-day lookback window applied on incremental runs | ✅ Compliant |
| `subscriptions` orphan filter | Spec requires orphan customer_ids to be removed | Implemented as FK check against `stg_customers` | ✅ Compliant |
| `billing` deduplication order | Spec requires earliest occurrence kept | `ASC` order by `created_at` — keeps first | ✅ Compliant |
| `payments` deduplication key | Spec business key is `invoice_id + payment_date + payment_amount` | Dedup PARTITION BY `(invoice_id, payment_date, payment_amount)` — correct key applied | ✅ Compliant |
| `bill_line_items` negative amounts | Spec states credits/adjustments are legitimate | Preserved as-is; no sign filtering applied | ✅ Compliant |
| `support_tickets` NULL customer_id | Spec describes as anonymous/walk-in inquiries | Preserved as-is; not flagged as invalid | ✅ Compliant |
| `network_events` absent customer FK | By design (infrastructure-level events) | No FK check applied | ✅ Compliant |
