# MYConnect — Looker Studio Prototype → Looker Migration Plan

**Purpose:** build the six MYConnect dashboards in **Looker Studio** now (free), designed so they can be **recreated in Looker** later with minimal redesign.

**Source of truth:** `dashboard_planning.md` (locked decisions, page content), `architecture diagram.md` (layer flow), and the current Dataform models under `definitions/gold/` and `definitions/mart/`.

> **These are two different products.** Looker Studio is a free BI/reporting tool that queries BigQuery directly and has no semantic layer. Looker is a governed platform with a LookML semantic layer, Explores, and centrally-defined metrics. This document never treats them as equivalent — it defines what maps cleanly and what does not.

---

## ⚠️ Read this first — the nested-array constraint

Six Mart columns are BigQuery `ARRAY<STRUCT<...>>` (built with `ARRAY_AGG(STRUCT(...))`):

| Mart | Nested column |
|---|---|
| `mart_revenue` | `revenue_by_plan`, `revenue_by_segment` |
| `mart_churn` | `churn_by_reason`, `churn_by_plan`, `churn_by_tenure_band` |
| `mart_customer_support` | `tickets_by_category` |
| `mart_service_quality` | `incidents_by_severity` |

**Looker Studio cannot chart nested/repeated BigQuery fields.** It either hides them or errors. **Looker handles them** via `UNNEST` in a derived table or an unnest join.

**Consequence for the prototype:** every breakdown chart that would read a Mart array must instead be built from **Gold** in Looker Studio. This is already the recommended source for most of them in `dashboard_planning.md`, so the impact is small — but it must be a deliberate choice, not a surprise mid-build. Each affected tile is flagged in §5.

---

## 1. Current vs. Future Architecture

**Now — Looker Studio prototype (no semantic layer):**

```
BigQuery
  myconnect_gold  (5 dims · 6 facts)
  myconnect_mart  (6 marts)
        │
        ▼
Looker Studio Data Sources        ← one per table; metric logic lives in each report
        │
        ▼
6 Report Pages
```
Metric definitions live **inside each report**. Two reports can disagree. That is the core limitation the prototype accepts.

**Later — Looker (governed semantic layer):**

```
BigQuery
  myconnect_gold · myconnect_mart
        │
        ▼
Looker Connection  (service account, single BigQuery connection)
        │
        ▼
LookML Project → views (1 per table) → Explores (scoped, per subject area)
        │
        ▼
6 Dashboards built from Explores
```
Metric definitions live **once in LookML**, are version-controlled in Git, and every dashboard inherits them.

**Constant across both:** `Gold → BI` for detailed/filterable/drillable analysis, `Mart → BI` for headline KPIs and monthly trends, **`Silver → NEVER` exposed to either tool.**

---

## 2. Looker Studio → Looker Mapping

| Looker Studio concept | Looker equivalent | Migration notes for MYConnect |
|---|---|---|
| **Data source** (one per BQ table) | **View** (`.view.lkml`) + connection | 1:1. 17 data sources → 17 views. Keep data source names identical to table names. |
| **BigQuery connection** (per data source) | **Connection** (one, project-level) | Looker uses a single connection; Studio re-authenticates per source. |
| **Field** (dimension) | `dimension:` | Direct. Use the same names — `total_amount` stays `total_amount`. |
| **Field** (metric, auto-aggregated) | `measure:` with `type: sum/count/average` | Studio auto-aggregates numerics; LookML requires you to declare it. |
| **Calculated field** (row-level) | `dimension:` with `sql:` | Portable if written in BigQuery SQL. |
| **Calculated field** (aggregate, e.g. `SUM(x)/SUM(y)`) | `measure:` `type: number` with `sql: ${a}/${b}` | Studio's `SUM(x)/SUM(y)` maps cleanly. Avoid Studio-only functions. |
| **Date range control** | Dashboard filter on a `dimension_group` | Declare `dimension_group: type: time` in the view to get date/week/month/quarter grains free. |
| **Filter control** (dropdown) | Dashboard filter → Explore field | Direct. |
| **Chart-level filter** | Tile-level filter / `filters:` in the LookML measure | Studio chart filters → Looker tile filters. |
| **Scorecard** | Single Value tile | Direct. |
| **Time series / bar / donut / table** | Line / Column / Pie / Table tile | Direct. |
| **Drill-down** (field hierarchy in chart) | `drill_fields:` on dimension or measure | Studio drilldowns are per-chart; Looker's are defined once in LookML and inherited. |
| **Blended data** (left-join in UI) | **Explore join** (`sql_on` + `relationship`) | ⚠️ The riskiest mapping. Studio blends are opaque and fan out silently. **Use blending only where §4 defines a safe `many_to_one` join.** |
| **Data control** | Not applicable | Studio's data control (user swaps data source) has no Looker equivalent — don't use it. |
| **Report page** | Dashboard | 6 pages → 6 dashboards. Keep the same names. |
| **Report-level default date range** | Dashboard filter default value | Direct. |
| **Extract data** (materialized snapshot) | PDT (persistent derived table) | Not needed here — Gold/Mart are already materialized tables. |

---

## 3. LookML Modeling Plan

One view per physical table. **17 views total.** `PK` = the field to mark `primary_key: yes`.

### 3.1 Gold dimension views

| View | Base table | Primary key | Date field | Key dimensions | Key measures | Role |
|---|---|---|---|---|---|---|
| `dim_customers` | `myconnect_gold.dim_customers` | `customer_id` | `registration_date` (TIMESTAMP) | `name`, `type`, `dwelling_type`, `state`, `city`, `tenure_months`, `lifecycle_stage`, `has_active_subscription`, `current_plan_id`, `current_plan_name` | `count`, `average_tenure_months` | **Explore base** (Page 2) + joined view elsewhere |
| `dim_subscriptions` | `myconnect_gold.dim_subscriptions` | `subscription_id` | `start_date`, `end_date` (DATE) | `customer_id`, `plan_id`, `plan_name`, `monthly_charge`, `contract_months`, `is_active` | `count`, `total_monthly_charge` (MRR input), `active_count` | **Explore base** (Page 1 subs) + joined view |
| `dim_plans` | `myconnect_gold.dim_plans` | `plan_id` | — | `plan_name`, `speed_mbps`, `monthly_price`, `category`, `is_current` | `count` | Joined view only |
| `dim_geography` | `myconnect_gold.dim_geography` | `concat(state, city)` (composite) | — | `state`, `city`, `region`, `dwelling_mix` | `count` | Joined view only |
| `dim_date` | `myconnect_gold.dim_date` | `date_key` | `date_key` (DATE) | `day`, `month`, `quarter`, `year`, `day_of_week`, `is_weekend`, `month_name` | `count` | Joined view only |

> `dim_geography` has no single-column PK — use `primary_key: yes` on a concatenated dimension `${state} || '-' || ${city}`.
> **Do not model** `speed_tier` (dims/subs), `is_holiday_my`, `fiscal_quarter` (dim_date) — all are `NULL` by design (no spec definition). Omit them from LookML rather than shipping empty fields.

### 3.2 Gold fact views

| View | Base table | Primary key | Date field | Key dimensions | Key measures | Role |
|---|---|---|---|---|---|---|
| `fct_billing` | `myconnect_gold.fct_billing` | `invoice_id` | `invoice_date`, `due_date` | `subscription_id`, `customer_id`, `is_overdue`, `reconciliation_flag`, `payment_reconciliation_status` | `total_revenue` (SUM total_amount), `invoice_count`, `avg_invoice_value`, `overdue_amount`, `dso` (AVG days_to_payment), `mismatch_count`, `mismatch_amount`, `leakage_pct` | **Explore base** (Pages 3, 6) |
| `fct_payments` | `myconnect_gold.fct_payments` | `payment_id` | `payment_date` | `invoice_id`, `customer_id`, `payment_method`, `is_successful`, `is_orphan_payment` | `payment_count`, `total_payment_amount`, `successful_payment_amount`, `orphan_payment_count` | **Explore base** (payments detail) |
| `fct_usage_daily` | `myconnect_gold.fct_usage_daily` | `concat(subscription_id, usage_date)` | `usage_date` | `subscription_id` | `total_gb`, `avg_speed`, `avg_speed_achievement_pct` | **Explore base** (usage) |
| `fct_support_tickets` | `myconnect_gold.fct_support_tickets` | `ticket_id` | `created_date` | `customer_id`, `subscription_id`, `category`, `priority`, `status`, `channel`, `is_repeat_ticket` | `ticket_count`, `avg_resolution_hours`, `csat_average`, `open_ticket_count` | **Explore base** (Page 5 support) |
| `fct_churn_events` | `myconnect_gold.fct_churn_events` | `churn_event_id` | `churn_date` | `customer_id`, `subscription_id`, `churn_type`, `churn_reason` | `churn_count`, `voluntary_count`, `involuntary_count`, `retention_attempted_count`, `retention_success_count`, `retention_rate` | **Explore base** (Page 4 detail) |
| `fct_network_events` | `myconnect_gold.fct_network_events` | `event_id` | `start_time` (TIMESTAMP) | `event_type`, `severity`, `region` | `event_count`, `outage_count`, `avg_duration_minutes` (**MTTR**), `total_affected_subscriber_hours` | **Explore base** (Page 5 network) — **isolated** |

> **Do not model** `fct_support_tickets.sla_met` as a usable measure — it is `NULL` for every row (no SLA threshold defined). Keep the field documented as unsupported.
> `fct_usage_daily` and `fct_network_events` have no single-column PK / need care: usage PK is the composite `(subscription_id, usage_date)`.

### 3.3 Mart views

All six are month-grain aggregates. **Nested array columns must be excluded from the base view** and exposed (if needed) through a separate unnested derived table.

| View | Base table | Primary key | Date field | Scalar dimensions/measures to model | Nested — exclude from base view |
|---|---|---|---|---|---|
| `mart_revenue` | `myconnect_mart.mart_revenue` | `revenue_month` | `revenue_month` | `mrr`, `total_revenue`, `arpu`, `revenue_growth_pct`, `collection_rate` | `revenue_by_plan`, `revenue_by_segment` |
| `mart_churn` | `myconnect_mart.mart_churn` | `churn_month` | `churn_month` | `gross_churn_rate`, `voluntary_churn_rate`, `involuntary_churn_rate`, `retention_rate` | `churn_by_reason`, `churn_by_plan`, `churn_by_tenure_band` |
| `mart_customer_360` | `myconnect_mart.mart_customer_360` | `customer_id` | — | `tenure`, `cltv`, `total_revenue`, `avg_monthly_spend`, `total_tickets`, `plan`, `dwelling`, `region` | — (no arrays) |
| `mart_service_quality` | `myconnect_mart.mart_service_quality` | `concat(event_month, region)` | `event_month` | `region`, `outage_count`, `avg_duration_hours`, `affected_subscriber_hours`, `mean_time_to_restore` | `incidents_by_severity` |
| `mart_customer_support` | `myconnect_mart.mart_customer_support` | `ticket_month` | `ticket_month` | `total_tickets`, `avg_resolution_hours`, `csat_avg` | `tickets_by_category` |
| `mart_revenue_assurance` | `myconnect_mart.mart_revenue_assurance` | `assurance_month` | `assurance_month` | `billing_mismatch_count`, `billing_mismatch_amount`, `orphan_payments`, `overpayments`, `underpayments`, `leakage_pct` | — (no arrays) |

> **Do not model as usable:** `mart_churn.net_churn_rate`, `mart_customer_360.churn_risk_flags`, `mart_customer_support.resolution_rate`, `mart_customer_support.sla_compliance_pct`, `mart_revenue.revenue_by_segment`. All are `NULL` — undefined business rules, not missing data.
> `mart_revenue_assurance.overpayments`/`underpayments` are **counts, not amounts**. Name the LookML measures `overpayment_count` / `underpayment_count` to prevent misuse.

---

## 4. Explore Plan

**Rule: one Explore per fact/subject area. Never one giant Explore.** Eight focused Explores.

| # | Explore | Base view | Safe joins (`many_to_one` unless noted) | Serves |
|---|---|---|---|---|
| 1 | `billing` | `fct_billing` | `dim_subscriptions` on `subscription_id`; `dim_plans` on `subscription_id→plan_id`; `dim_customers` on `customer_id`; `dim_date` on `invoice_date` | Pages 3, 6 |
| 2 | `payments` | `fct_payments` | `dim_customers` on `customer_id`; `dim_date` on `payment_date` | Page 3 detail, Page 6 orphans |
| 3 | `customers` | `dim_customers` | `dim_geography` on `state`+`city`; `mart_customer_360` on `customer_id` (**one_to_one**) | Page 2 |
| 4 | `subscriptions` | `dim_subscriptions` | `dim_plans` on `plan_id`; `dim_customers` on `customer_id` | Page 1 (active subs), Page 2 |
| 5 | `churn_events` | `fct_churn_events` | `dim_customers` on `customer_id`; `dim_subscriptions` on `subscription_id`; `dim_plans` via subscription; `dim_date` on `churn_date` | Page 4 slicing |
| 6 | `support_tickets` | `fct_support_tickets` | `dim_customers` on `customer_id`; `dim_date` on `created_date` | Page 5 (support half) |
| 7 | `network_events` | `fct_network_events` | `dim_date` on `start_time` **only** | Page 5 (network half) |
| 8 | `usage_daily` | `fct_usage_daily` | `dim_subscriptions` on `subscription_id`; `dim_plans` via subscription; `dim_date` on `usage_date` | Speed Achievement analysis |

Plus **four Mart Explores** with no joins (single-table, month-grain): `mart_revenue`, `mart_churn`, `mart_service_quality`, `mart_customer_support`, `mart_revenue_assurance`.

### 4.1 Joins that must NEVER be built

| Forbidden join | Why | Use instead |
|---|---|---|
| `fct_billing` ⋈ `fct_payments` | 1:many — multiplies every invoice amount by its payment count | `fct_billing.total_paid` (already invoice-level) |
| `fct_billing` ⋈ `fct_support_tickets` ⋈ `fct_churn_events` on `customer_id` | many×many×many explosion | `mart_customer_360` (pre-aggregated 1 row/customer) |
| `dim_customers` ⋈ `dim_subscriptions` then `COUNT(customers)` | 1:many — inflates customer counts | `dim_customers.current_plan_name`, or `COUNT(DISTINCT customer_id)` |
| `fct_network_events` ⋈ anything customer/subscription | **No key exists** — infrastructure telemetry by design | Keep Explores 6 and 7 permanently separate |

### 4.2 When to use Mart instead of Gold

Use **Mart** when the metric embeds logic a dashboard user would get wrong:

| Metric | Must come from | Why |
|---|---|---|
| Gross / Voluntary / Involuntary Churn Rate | `mart_churn` | Correct point-in-time "active at start of month" denominator |
| Collection Rate | `mart_revenue` | Correctly excludes the 6,859 orphan payments; a naive `fct_payments` sum inflates it |
| MRR / ARPU | `mart_revenue` | Point-in-time subscription reconstruction |
| Everything sliceable (state, plan, dwelling, severity, channel, category) | **Gold** | Marts carry no slicing dimensions — month grain only |

---

## 5. Page-by-Page Translation

Content is fixed by `dashboard_planning.md` (max 4 KPIs / 4 filters / 4 charts per page). This section only translates it into the two tools.

### Page 1 — Executive Overview
**Purpose:** Is the business growing, is revenue healthy?
**Studio sources:** `mart_revenue`, `mart_churn`, `dim_subscriptions`, `fct_churn_events`
**Future Explores:** `mart_revenue`, `mart_churn`, `subscriptions`, `churn_events`

| Item | Studio prototype | Looker implementation |
|---|---|---|
| KPI: MRR | Scorecard, `mart_revenue.mrr` | `mart_revenue.mrr` measure |
| KPI: Active Subscribers | Scorecard on `dim_subscriptions`, filter `is_active = true` | `subscriptions.active_count` measure |
| KPI: ARPU | Scorecard, `mart_revenue.arpu` | `mart_revenue.arpu` measure |
| KPI: Gross Churn Rate | Scorecard, `mart_churn.gross_churn_rate` | `mart_churn.gross_churn_rate` measure |
| Chart: MRR Trend | Time series on `revenue_month` | Line tile, `mart_revenue` Explore |
| Chart: Revenue by Plan | ⚠️ **`revenue_by_plan` is a nested array — unusable in Studio.** Build from Gold: `fct_billing` ⋈ `dim_plans`, bar by `plan_name` | Either Gold Explore, or unnest the Mart array in a derived table |
| Chart: Churn Rate Trend | Time series, 3 series from `mart_churn` | Line tile, 3 measures |
| Chart: New vs Churned | Two separate charts, or two Studio sources — **do not blend** | Two tiles, or a merged result |
| Filter: Month range | Date range control on `revenue_month` | Dashboard filter on `dimension_group` |
| Filter: Plan | Applies to the Gold-sourced tile only | Tile-scoped filter |

> ARPU target line is **removed** (Decision 8 — no target defined). State/Dwelling filters are **not** on this page (Marts have no such columns).

### Page 2 — Customer & Subscriber Analytics
**Purpose:** Who are our customers, where, on what plan, how long.
**Studio source:** `dim_customers` (+ `dim_geography` blend for region)
**Future Explore:** `customers`
**The cleanest page — 100% Gold, all filters global.**

| Item | Studio prototype | Looker implementation |
|---|---|---|
| KPI: Total Customers | Scorecard `COUNT(customer_id)` | `dim_customers.count` |
| KPI: Active Subscriptions | Scorecard on `dim_subscriptions` | `subscriptions.active_count` |
| KPI: Avg Tenure | Scorecard `AVG(tenure_months)` | `average_tenure_months` measure |
| KPI: SDU/MDU Split | Scorecard/pie on `dwelling_type` | `count` by `dwelling_type` |
| Chart: Acquisition MDU vs SDU | Stacked column by `registration_date` month × `dwelling_type` | Column tile |
| Chart: Customers by State | Bar by `state`, top 10 | Bar tile with row limit |
| Chart: Plan Mix | Donut by `current_plan_name` | Pie tile |
| Chart: Tenure Distribution | Bar on bucketed `tenure_months` | `tier`-type dimension |
| Filters ×4 | Registration date, State, City, Dwelling — all global | 4 dashboard filters |
| Drill | State → City → customer table | `drill_fields: [state, city, customer_id, name]` |

> Region requires a **blend** `dim_customers` ⋈ `dim_geography` on `state`+`city`. This is the one blend I recommend — it is a genuine `many_to_one` and maps directly to a LookML join.

### Page 3 — Revenue & Billing
**Purpose:** How much revenue, are customers paying on time?
**Studio source:** `fct_billing` (primary) + `mart_revenue` (collection rate only)
**Future Explore:** `billing`

| Item | Studio prototype | Looker implementation |
|---|---|---|
| KPI: Total Revenue | `SUM(total_amount)` | `total_revenue` measure |
| KPI: Collection Rate | Scorecard from `mart_revenue` (date-only) | `mart_revenue.collection_rate` |
| KPI: DSO | `AVG(days_to_payment)` | `dso` measure |
| KPI: Overdue Amount | `SUM(total_amount)` filtered `is_overdue` | measure with `filters: [is_overdue: "yes"]` |
| Chart: Revenue Trend | Column by `invoice_date` month | Column tile |
| Chart: Revenue by Plan | Bar via `dim_subscriptions`→`dim_plans` blend | Native Explore join |
| Chart: Invoice Aging | Calculated field bucketing `due_date` age into 0-30/31-60/61-90/90+ | `tier`-type dimension (buckets are spec-defined) |
| Chart: Discount Impact | Dual series `total_amount` vs `discount_amount` | Two measures on one tile |
| Filters ×4 | Invoice date, Plan, Payment status, State | Dashboard filters |

> Label the status filter **"Payment status"** from `payment_reconciliation_status` — `fct_billing` carries no raw 4-value invoice status.
> **Promo attribution is not available** (`promo_id` absent from Gold) — Decision 6, discount only.

### Page 4 — Churn & Retention
**Purpose:** Why are customers leaving, are save-offers working?
**Studio sources:** `mart_churn` (rates) + `fct_churn_events` (slicing)
**Future Explores:** `mart_churn`, `churn_events`

| Item | Studio prototype | Looker implementation |
|---|---|---|
| KPI: Gross / Voluntary Churn Rate | Scorecards from `mart_churn` | Mart measures |
| KPI: Retention Success Rate | Scorecard `mart_churn.retention_rate` | Mart measure |
| KPI: Avg Customer Lifetime | ⚠️ Needs `dim_customers` ⋈ `fct_churn_events`, **deduped to customer grain first** (a customer can churn on multiple subscriptions) | LookML measure over a derived table that takes `MAX(churn_date)` per customer |
| Chart: Churn Rate Trend | Time series from `mart_churn` | Line tile |
| Chart: Churn Reasons | ⚠️ **`churn_by_reason` is nested.** Build from `fct_churn_events` bar by `churn_reason` | Gold Explore (preferred — responds to filters) |
| Chart: Churn by Dwelling | `fct_churn_events` ⋈ `dim_customers` blend | Explore join — **not in `mart_churn`** |
| Chart: Churn by Plan | `fct_churn_events` ⋈ `dim_subscriptions` ⋈ `dim_plans` | Explore join |
| Filters ×4 | Churn date, Churn type, Plan, State | Churn type filters Gold tiles only (Mart stores it as columns) |
| Drill | Churn reason → customer attributes | `drill_fields: [churn_reason, state, dwelling_type, plan_name]` |

> **Cohort retention curves are deferred** (Decision 1 definition is locked, but the cohort×month matrix needs a derived table — build it in Looker later, not in the Studio prototype).
> `net_churn_rate` is **NULL/undefined** — do not chart it.

### Page 5 — Service Quality & Customer Support
**Purpose:** Network reliability + support performance.
**Studio sources:** `fct_network_events`, `fct_support_tickets`, `mart_service_quality`, `mart_customer_support`
**Future Explores:** `network_events` **and** `support_tickets` — permanently separate

| Item | Studio prototype | Looker implementation |
|---|---|---|
| KPI: Total Outages | `mart_service_quality.outage_count` | Mart measure |
| KPI: Avg Outage Duration | ⚠️ **Use Gold** — `fct_network_events` filtered `event_type='outage'`. The Mart's `avg_duration_hours` averages *all* event types | measure with `filters: [event_type: "outage"]` |
| KPI: CSAT Average | `mart_customer_support.csat_avg` | Mart measure |
| KPI: Open Tickets | `fct_support_tickets` filtered `status in (open, in_progress)` | filtered measure |
| Chart: Outage Trend by Severity | Stacked column, Gold `fct_network_events` | Column tile |
| Chart: Network Events by Region | Bar from `mart_service_quality` | Mart Explore |
| Chart: Top 10 Support Categories | Bar by `category` (Decision 5 — categories, not subcategories) | Bar tile, row limit 10 |
| Chart: Avg Resolution Time Trend | Time series `mart_customer_support` | Line tile |
| Filters ×4 | **Zoned:** Event date + Severity (network) / Ticket date + Category (support) | Two filter groups; never cross-apply |

> **SLA Compliance % and FCR are unsupported** (Decisions 3 & 4) — omit the tiles entirely rather than showing empty scorecards.
> Network `region` is a **different taxonomy** from `dim_geography.region` — label it "Network region".

### Page 6 — Revenue Assurance
**Purpose:** Where are we losing revenue?
**Studio sources:** `mart_revenue_assurance` (KPIs) + `fct_billing` (detail)
**Future Explores:** `mart_revenue_assurance`, `billing`

| Item | Studio prototype | Looker implementation |
|---|---|---|
| KPI: Billing Mismatch Count / Amount | Scorecards from `mart_revenue_assurance` | Mart measures |
| KPI: Revenue Leakage % | Scorecard `leakage_pct` | Mart measure |
| KPI: Orphan Payments | Scorecard `orphan_payments` | Mart measure |
| Chart: Mismatch Trend | Time series on `assurance_month` | Line tile |
| Chart: Top 10 Invoices by Discrepancy | Table on `fct_billing`, sorted by `ABS(total_amount - line_item_total)` | Table tile + row limit |
| Chart: Mismatch Rate by Plan | Bar, `fct_billing` ⋈ `dim_plans` | Explore join |
| Filters | Invoice date, Plan, Mismatch threshold (numeric input) | Threshold → LookML **parameter** |

> ⚠️ **"Leakage by Charge Type" cannot be built in either tool yet.** `charge_type` lives only at Silver (`stg_bill_line_items`); a Gold `fct_bill_line_items` is a documented prerequisite (Decision 9) that **is not implemented**. Omit the tile and the Charge type filter.
> The prototype must use **Gold/Mart only** — do not point Studio at `int_billing_reconciliation` even though the original spec named it. Gold now carries `total_paid`, `payment_reconciliation_status`, `line_item_total`.

---

## 6. Looker Features to Learn — Prioritized for MYConnect

### Level 1 — Before you build anything
| Concept | Why, for MYConnect |
|---|---|
| Looker **connection** to BigQuery | One service account → `myconnect-analytics`, `asia-southeast1` |
| **LookML project** + Git backing | Your models are already in Git; LookML follows the same workflow |
| **View** = one table | 17 views: 5 dims, 6 facts, 6 marts |
| **dimension** vs **measure** | Studio blurs this; LookML forces the distinction |
| `primary_key: yes` | **Critical** — Looker uses it for symmetric aggregates to prevent fan-out. `fct_usage_daily` needs a composite PK |
| **Explore** | The unit a dashboard queries. You need 12, not 1 |

### Level 2 — While modeling
| Concept | Why |
|---|---|
| `join:` + `sql_on:` | The 8 Gold Explores in §4 |
| `relationship: many_to_one` | Every Gold fact→dim join. Getting this wrong causes silent double-counting |
| `dimension_group: type: time` | Gives date/week/month/quarter free on `invoice_date`, `payment_date`, `churn_date`, `created_date`, `start_time`, `usage_date` |
| `type: tier` dimension | Invoice aging buckets, tenure bands |
| Filtered measures (`filters:`) | Overdue Amount, Outage-only duration, Open Tickets |
| `sql_distinct_key` / symmetric aggregates | Understand *why* Looker can safely `SUM` across a join when Studio cannot |

### Level 3 — While building dashboards
| Concept | Why |
|---|---|
| Dashboard **filters** + `listens_to_filters` | Zoned filters on Page 5 (network vs support) |
| **Tile-scoped filters** | Page 1's Plan filter hitting only one tile |
| `drill_fields:` | Page 2 state→city, Page 4 churn reason→attributes |
| **Pivots** | Severity across months, plan across months |
| Row limits / sorts | Top 10 invoices, top 10 categories |
| **Parameters** | Page 6 mismatch threshold |

### Level 4 — Optional / advanced
| Concept | Why |
|---|---|
| **Derived tables** (NDT/SQL) | Cohort retention matrix; unnesting Mart arrays; customer-grain churn dedup |
| **PDTs** + datagroups | Not needed — Gold/Mart are already materialized |
| `access_filter` / row-level security | Portfolio talking point only |
| LookML **tests** (`test:` blocks) | Mirrors your 5 Dataform assertions |
| Liquid templating | Conditional formatting, dynamic links |

---

## 7. Build Sequence (when Looker access arrives)

1. **BigQuery connection** — service account with `roles/bigquery.dataViewer` on `myconnect_gold` + `myconnect_mart` only. **Explicitly do not grant `myconnect_silver`** — enforce the architecture at the permission layer, not just by convention.
2. **LookML project**, Git-backed.
3. **Views — dimensions first** (`dim_date`, `dim_plans`, `dim_geography`, `dim_customers`, `dim_subscriptions`). They're small, join-heavy, and validate your PK understanding cheaply.
4. **Views — facts** (6). Add `primary_key`, `dimension_group`, and core measures.
5. **Views — marts** (6). Scalar columns only; **exclude the nested arrays**.
6. **Explore 1: `customers`** — build and validate this first. It's the simplest (Page 2) and proves your join syntax.
7. **Remaining Explores** (§4), one subject area at a time.
8. **Validate every Explore** before any dashboard: run a row count and confirm it matches BigQuery directly. **This is the fan-out checkpoint** — if `billing` row count ≠ 2,995,000, a join is wrong.
9. **Dashboards** in the build order from `dashboard_planning.md`: Page 2 → 3 → 1 → 4 → 5 → 6.
10. **Filters**, then **drills**.
11. **Final validation** — reconcile each KPI against the known baselines (MRR ≈ RM32.0M, leakage ≈ 0.079%, mismatch amount ≈ RM427,280, orphan payments = 6,859).

> Steps 3–5 are the reusable asset. Even if you never build the Looker dashboards, having the views + Explores designed is the portfolio artifact.

---

## 8. Looker Studio Design Rules (build for migration)

1. **One data source per BigQuery table.** Never a custom-SQL source that pre-joins tables — that logic must live in LookML later, not be re-derived.
2. **Never rename fields in Studio.** `total_amount` stays `total_amount`. Renames become manual remapping work later.
3. **Use the exact page names** from `dashboard_planning.md` — they become dashboard names.
4. **Use the exact chart titles** planned for Looker.
5. **Write calculated fields in portable BigQuery SQL.** `SUM(a)/SUM(b)` maps to a LookML measure; Studio-only functions do not.
6. **Cap blending at the joins in §4.1.** Only `dim_customers`⋈`dim_geography`, fact⋈dimension. **Never blend two facts.**
7. **Keep KPI definitions identical to the MYConnect KPI dictionary.** If Collection Rate excludes orphan payments in the Mart, do not recompute it differently in a Studio calculated field.
8. **Respect Gold/Mart boundaries** — Mart for headline KPIs and monthly trends, Gold for anything sliceable. Never connect Studio to `myconnect_silver`.
9. **Document every calculated field** in a comment or a companion note — this becomes your LookML `description:`.
10. **Avoid Studio "Extract data"** — it snapshots and drifts from BigQuery.
11. **Prefix data sources** `gold_` / `mart_` so the layer is visible in the UI.
12. **Don't build tiles for unsupported metrics.** SLA Compliance, FCR, Take-Up Rate, net churn, charge-type leakage — omit them, don't ship empty scorecards.

---

## 9. Portfolio / Interview Positioning

### ✅ Accurate things you can say

> "I built the end-to-end pipeline in BigQuery with Dataform — Bronze through Silver, Gold, and Mart — then prototyped the six dashboards in Looker Studio, because I didn't have Looker access. I designed the Gold layer as a galaxy schema with five conformed dimensions and six fact tables, and produced a full LookML modeling plan: which views to build, their primary keys, and twelve scoped Explores rather than one monolithic model."

> "I deliberately kept metric logic in the warehouse rather than the BI tool, so migrating from Looker Studio to Looker is a modeling exercise, not a rebuild. The Marts hold the metrics that are easy to get wrong — like the point-in-time churn denominator and the orphan-payment-excluded collection rate."

> "I designed the Explores to avoid fan-out. `fct_billing` joined to `fct_payments` is one-to-many and would multiply invoice amounts, so `fct_billing` carries an invoice-level `total_paid` instead. And `fct_network_events` has no customer key by design, so network and support analysis stay in separate Explores."

> "I understand the architectural difference: Looker Studio has no semantic layer, so metric definitions live per-report and can drift. Looker centralizes them in version-controlled LookML. My prototype is built to Looker's constraints so the definitions survive the move."

### ❌ Never say
- "I built dashboards in Looker" — you built them in **Looker Studio**.
- "I wrote LookML" — you wrote a **modeling plan**, unless/until you actually write it.
- "I have production Looker experience."

### The honest framing that lands well
> "Looker Studio was the tool I had; Looker was the architecture I designed for."

That demonstrates semantic-layer understanding, fan-out awareness, and pragmatism about constraints — which is what the modeling questions in an interview are actually probing for.

---

## 10. Final Checklist

**When Looker trial/access becomes available, I should be able to:**

**X — Connect and model (≈ half a day)**
- Create the BigQuery connection, scoped to `myconnect_gold` + `myconnect_mart` only (never Silver)
- Generate the 17 views from §3, add `primary_key`, `dimension_group`, and the listed measures
- Exclude the six nested-array Mart columns from base views

**Y — Build and validate Explores (≈ half a day)**
- Build the 8 Gold Explores + 4 Mart Explores from §4 with `many_to_one` joins
- Never build any of the four forbidden joins in §4.1
- Validate each Explore's row count against BigQuery before touching a dashboard

**Z — Recreate the dashboards (≈ 1–2 days)**
- Rebuild the six pages in the order Page 2 → 3 → 1 → 4 → 5 → 6
- Port each Studio calculated field to the LookML measure named in §5
- Reconcile KPIs against known baselines (MRR ≈ RM32.0M, leakage ≈ 0.079%, orphan payments = 6,859)
- Add drills (§5) and zoned filters (Page 5)

**Still blocked regardless of Looker access:**
- Leakage by Charge Type — needs `fct_bill_line_items` in Gold (Decision 9, not implemented)
- SLA Compliance %, FCR, Take-Up Rate — no source data exists
- Net churn rate, churn risk flags, resolution rate, revenue by segment — no business definition exists

---

*Sources: `dashboard_planning.md`, `architecture diagram.md`, `definitions/gold/**`, `definitions/mart/**`. No project files were modified to produce this plan.*

---

## 11. Future Looker Git / LookML Project File Structure

**Documentation only.** Nothing in this section exists in the MYConnect repository, and no `.lkml` files should be created from it until Looker access is available. It describes what the future Looker project *would* look like as a separate Git repository, derived entirely from Sections 1–10.

> ### 📌 Erratum — Explore count
> §4 says "Plus **four** Mart Explores" but then enumerates **five** (`mart_revenue`, `mart_churn`, `mart_service_quality`, `mart_customer_support`, `mart_revenue_assurance`). §6, §7 and §10 repeat the same "4 Mart / 12 total" figure.
> **The correct count is 13 Explores: 8 Gold + 5 Mart.** No Explore is being added here — the enumerated list was always right; only the summary count was wrong. Section 11 uses **13** throughout.

### 11.1 Repository Tree

The Looker project is a **separate Git repository** from `myconnect-analytics`. Looker requires its own repo, connected to the Looker instance via deploy key.

```text
looker-myconnect/
├── README.md                              # project overview, conventions
├── .gitignore                             # optional; LookML projects need very little
├── manifest.lkml                          # project name, constants, dependencies
├── myconnect.model.lkml                   # connection + includes + Explore wiring
│
├── views/
│   ├── gold/
│   │   ├── dim_customers.view.lkml        → myconnect_gold.dim_customers
│   │   ├── dim_subscriptions.view.lkml    → myconnect_gold.dim_subscriptions
│   │   ├── dim_plans.view.lkml            → myconnect_gold.dim_plans
│   │   ├── dim_geography.view.lkml        → myconnect_gold.dim_geography
│   │   ├── dim_date.view.lkml             → myconnect_gold.dim_date
│   │   ├── fct_billing.view.lkml          → myconnect_gold.fct_billing
│   │   ├── fct_payments.view.lkml         → myconnect_gold.fct_payments
│   │   ├── fct_usage_daily.view.lkml      → myconnect_gold.fct_usage_daily
│   │   ├── fct_support_tickets.view.lkml  → myconnect_gold.fct_support_tickets
│   │   ├── fct_churn_events.view.lkml     → myconnect_gold.fct_churn_events
│   │   └── fct_network_events.view.lkml   → myconnect_gold.fct_network_events
│   └── mart/
│       ├── mart_revenue.view.lkml         → myconnect_mart.mart_revenue
│       ├── mart_churn.view.lkml           → myconnect_mart.mart_churn
│       ├── mart_customer_360.view.lkml    → myconnect_mart.mart_customer_360
│       ├── mart_service_quality.view.lkml → myconnect_mart.mart_service_quality
│       ├── mart_customer_support.view.lkml→ myconnect_mart.mart_customer_support
│       └── mart_revenue_assurance.view.lkml → myconnect_mart.mart_revenue_assurance
│
├── explores/                              # 9 files holding the 13 Explores
│   ├── billing.explore.lkml
│   ├── payments.explore.lkml
│   ├── customers.explore.lkml
│   ├── subscriptions.explore.lkml
│   ├── churn_events.explore.lkml
│   ├── support_tickets.explore.lkml
│   ├── network_events.explore.lkml
│   ├── usage_daily.explore.lkml
│   └── marts.explore.lkml                 # all 5 Mart Explores (no joins)
│
├── dashboards/                            # OPTIONAL — see §11.8
│   ├── 01_executive_overview.dashboard.lookml
│   ├── 02_customer_subscriber.dashboard.lookml
│   ├── 03_revenue_billing.dashboard.lookml
│   ├── 04_churn_retention.dashboard.lookml
│   ├── 05_service_quality_support.dashboard.lookml
│   └── 06_revenue_assurance.dashboard.lookml
│
└── tests/
    └── data_tests.lkml                    # LookML data tests (mirror Dataform assertions)
```

**Counts:** 17 views · 9 explore files (13 Explores) · 6 dashboards · 1 test file · 4 config/doc files.

> **Why `explores/` is a separate folder:** Explores can legally live inside `myconnect.model.lkml`. With 13 of them the model file becomes ~400 lines and every Explore change touches one file — bad for code review. Splitting them into `.explore.lkml` files and `include:`-ing them keeps diffs small and reviewable. This is a real Looker convention, not a requirement.

### 11.2 File-by-File Breakdown

#### `README.md`
1. **Filename:** `README.md`
2. **Contains:** project purpose, BigQuery connection name, layer boundaries (Gold/Mart only, never Silver), the forbidden-joins list from §4.1, naming conventions.
3. **Why:** the forbidden joins are the single most dangerous thing a new developer could get wrong; it must be written down where they'll see it.
4. **Used by:** humans only.
5. **Connects to:** nothing programmatically.
6. **Required?** Optional — but treat as mandatory for a portfolio repo.
7. **Git?** ✅ Yes.

#### `manifest.lkml`
1. **Filename:** `manifest.lkml` (must be at project root, exact name)
2. **Contains:** `project_name`, optional `constant:` blocks (e.g. the GCP project id so table names aren't hardcoded 17 times), and `local_dependency`/`remote_dependency` if importing other projects.
3. **Why:** declares project identity; constants remove repetition across views.
4. **Used by:** the Looker compiler, at project load.
5. **Connects to:** every view file that references `@{CONSTANT_NAME}`.
6. **Required?** Optional for a single simple project; **recommended here** because 17 views all repeat `myconnect-analytics`.
7. **Git?** ✅ Yes.

#### `myconnect.model.lkml`
1. **Filename:** `myconnect.model.lkml` (name before `.model` becomes the model name in URLs)
2. **Contains:** `connection:`, `include:` statements, `datagroup:` caching policy, and (in this layout) no Explores — they're included from `explores/`.
3. **Why:** the model is the **binding layer** — it's what ties a database connection to a set of views and Explores. Without it, views are inert files.
4. **Used by:** Looker at query time; every dashboard references `model: myconnect`.
5. **Connects to:** all views (via `include`), all explore files (via `include`), and the Looker-side connection (by name).
6. **Required?** ✅ **Mandatory.** A project with no model file exposes nothing.
7. **Git?** ✅ Yes.

#### Connection definition
1. **Filename:** **none — this is not a file.**
2. **Contains:** BigQuery project, service-account JSON key, default dataset, region (`asia-southeast1`).
3. **Why:** credentials must never be in Git.
4. **Used by:** the model file, which references it *by name only* (`connection: "myconnect_bigquery"`).
5. **Connects to:** the model file by string name.
6. **Required?** ✅ Mandatory.
7. **Git?** ❌ **No — configured in Looker Admin UI.** This is the cleanest example of the Git/Looker split.

#### `views/gold/*.view.lkml` (11 files)
1. **Filename:** matches the table, e.g. `fct_billing.view.lkml`
2. **Contains:** `view:` block, `sql_table_name:`, dimensions, `dimension_group:`s, measures, `primary_key: yes`, `drill_fields:`, `description:`s.
3. **Why:** a view is the LookML representation of one physical table — the reusable unit.
4. **Used by:** Explore files (as base or joined view).
5. **Connects to:** its BigQuery table below; Explores above. Views never reference each other directly — joins live in Explores.
6. **Required?** ✅ Mandatory for anything queryable.
7. **Git?** ✅ Yes.

#### `views/mart/*.view.lkml` (6 files)
Same as above, with one MYConnect-specific rule: **the six `ARRAY<STRUCT<>>` columns are deliberately not exposed** (see the warning at the top of this document). Each mart view carries a comment saying which array was excluded and which Gold Explore to use instead.

#### `explores/*.explore.lkml` (9 files)
1. **Filename:** `<explore_name>.explore.lkml`
2. **Contains:** `explore:` block, `view_name:`, `join:` blocks with `sql_on:` + `relationship:` + `type:`, `label:`, `description:`.
3. **Why:** Explores define *what a user can query and how tables are safely joined*. This is where fan-out is prevented.
4. **Used by:** dashboards, Looks, and ad-hoc users.
5. **Connects to:** views (below), model file (above, via `include`).
6. **Required?** ✅ At least one is mandatory.
7. **Git?** ✅ Yes.

#### `dashboards/*.dashboard.lookml` (6 files, optional)
1. **Filename:** `01_executive_overview.dashboard.lookml` — note the extension is **`.dashboard.lookml`**, not `.lkml`. (A genuine Looker quirk; using `.lkml` silently fails to register the dashboard.)
2. **Contains:** YAML-style dashboard definition — `title`, `layout`, `filters:`, `elements:` with model/explore/fields/visualization config.
3. **Why:** makes dashboards version-controlled and code-reviewable instead of clickable-only.
4. **Used by:** end users.
5. **Connects to:** Explores by name, and the model by name.
6. **Required?** ❌ **Optional** — see §11.8 for which approach fits this project.
7. **Git?** ✅ Yes (if used).

#### `tests/data_tests.lkml`
1. **Filename:** `data_tests.lkml`
2. **Contains:** `test:` blocks with `explore_source:` and `assert:` expressions.
3. **Why:** mirrors the 5 Dataform assertions at the semantic layer — catches a broken join, which Dataform cannot see.
4. **Used by:** the `LookML Validator` / CI.
5. **Connects to:** Explores.
6. **Required?** ❌ Optional — but a strong portfolio differentiator.
7. **Git?** ✅ Yes.

### 11.3 Dependency Mapping Table

| File | Purpose | Contains | Depends on | Used by |
|---|---|---|---|---|
| `README.md` | Orientation | Conventions, forbidden joins | — | Humans |
| `manifest.lkml` | Project identity | `project_name`, constants | — | Compiler, all views |
| `myconnect.model.lkml` | Binding layer | `connection`, `include`, `datagroup` | Looker connection (UI), all views, all explores | Every dashboard & Explore URL |
| *Looker connection* | DB credentials | BQ project, service acct, region | — | Model file |
| `views/gold/dim_*.view.lkml` (5) | Dimension definitions | dimensions, PK, `count` measure | Gold tables | Explores (as joined views) |
| `views/gold/fct_*.view.lkml` (6) | Fact definitions | dimensions, `dimension_group`, measures, PK | Gold tables | Explores (as bases) |
| `views/mart/mart_*.view.lkml` (6) | Pre-aggregated metrics | month dimension, KPI measures | Mart tables | Mart Explores |
| `explores/*.explore.lkml` (9) | Query surfaces | `explore:`, `join:`, `relationship:` | View files | Dashboards, ad-hoc users |
| `dashboards/*.dashboard.lookml` (6) | Presentation | filters, elements, viz config | Explores, model | End users |
| `tests/data_tests.lkml` | Semantic QA | `test:` + `assert:` | Explores | LookML Validator / CI |

**Dependency direction (never circular):**
```text
BigQuery table → view → explore → dashboard
                   ↑        ↑
              manifest    model (connection + includes)
```

### 11.4 Project Configuration Detail

**`manifest.lkml`** — declares the project and hoists repeated values into constants. With 17 views all pointing at `myconnect-analytics`, a constant means a project rename is a one-line change.

**`myconnect.model.lkml`** — three responsibilities:
- **`connection:`** — names the Looker-side connection. String only; no credentials.
- **`include:`** — pulls views and explores into scope. Order doesn't matter; Looker resolves the graph.
- **`datagroup:`** — caching policy. For MYConnect, `fct_billing.created_at` is a sensible cache trigger since it advances when new invoices load.

**Model vs. view — the distinction that matters:**

| | View file | Model file |
|---|---|---|
| Describes | **One table** — its fields | **A queryable universe** — connection + Explores + joins |
| Knows about the database? | Only its own table name | Yes — owns the `connection` |
| Knows about other tables? | ❌ No | ✅ Yes — defines all joins |
| Reusable? | ✅ One view, many Explores | Model is the top-level container |
| Count in MYConnect | 17 | 1 |

A view is a **noun** (what a table is). A model is a **sentence** (how tables relate and where they live). Putting a join inside a view is the most common LookML beginner mistake — joins belong to Explores because the *same* view joins differently in different Explores. `dim_customers` is the base of `customers` but a joined dimension in `billing`, `churn_events`, and `support_tickets`.

### 11.5 View File Contents

Every MYConnect view uses this skeleton:

| Element | Purpose | MYConnect notes |
|---|---|---|
| `view:` | Names the view | Match the table name exactly |
| `sql_table_name:` | Points at BigQuery | Fully-qualified: `` `myconnect-analytics.myconnect_gold.X` `` |
| `dimension:` | A column | `type: string / number / yesno / date` |
| `primary_key: yes` | Grain declaration | **Critical for symmetric aggregates.** Composite PKs needed for `fct_usage_daily` and `dim_geography` |
| `dimension_group:` | Time field → many grains | Gives date/week/month/quarter free |
| `measure:` | An aggregate | `type: count / sum / average / number` |
| `filters:` on a measure | Pre-filtered aggregate | Overdue Amount, Open Tickets, Outage-only duration |
| `drill_fields:` | Click-through path | Page 2 and Page 4 drills |
| `description:` | Documentation | Where the `CURRENT_DATE()` tenure caveat and NULL-field warnings live |
| `hidden: yes` | Hide from users | FK columns like `customer_id` on facts |

**Physical table mapping:** all `views/gold/*` → `myconnect-analytics.myconnect_gold.<name>`; all `views/mart/*` → `myconnect-analytics.myconnect_mart.<name>`. **No view points at `myconnect_silver`.**

> ⚠️ **Mart measure caveat.** Mart rows are already monthly aggregates. Declaring `measure: mrr { type: sum }` and then viewing an 18-month range **sums 18 monthly MRR values** — meaningless. For Mart KPI scorecards spanning multiple months, use `type: average` or `type: max`, or force the tile to a single month. This is a real trap that does not exist in the Gold views.

### 11.6 Explore Structure — 13 Explores across 9 files

| Explore | File | Base view | Joins (all `many_to_one` unless noted) | Serves |
|---|---|---|---|---|
| `billing` | `billing.explore.lkml` | `fct_billing` | `dim_subscriptions`, `dim_plans` (via subscription), `dim_customers`, `dim_date` | Pages 3, 6 |
| `payments` | `payments.explore.lkml` | `fct_payments` | `dim_customers`, `dim_date` | Page 3, Page 6 |
| `customers` | `customers.explore.lkml` | `dim_customers` | `dim_geography`, `mart_customer_360` (**one_to_one**) | Page 2 |
| `subscriptions` | `subscriptions.explore.lkml` | `dim_subscriptions` | `dim_plans`, `dim_customers` | Pages 1, 2 |
| `churn_events` | `churn_events.explore.lkml` | `fct_churn_events` | `dim_customers`, `dim_subscriptions`, `dim_plans`, `dim_date` | Page 4 |
| `support_tickets` | `support_tickets.explore.lkml` | `fct_support_tickets` | `dim_customers`, `dim_date` | Page 5 (support) |
| `network_events` | `network_events.explore.lkml` | `fct_network_events` | `dim_date` **only** | Page 5 (network) |
| `usage_daily` | `usage_daily.explore.lkml` | `fct_usage_daily` | `dim_subscriptions`, `dim_plans`, `dim_date` | Speed Achievement |
| `mart_revenue` | `marts.explore.lkml` | `mart_revenue` | none | Pages 1, 3 |
| `mart_churn` | `marts.explore.lkml` | `mart_churn` | none | Pages 1, 4 |
| `mart_service_quality` | `marts.explore.lkml` | `mart_service_quality` | none | Page 5 |
| `mart_customer_support` | `marts.explore.lkml` | `mart_customer_support` | none | Page 5 |
| `mart_revenue_assurance` | `marts.explore.lkml` | `mart_revenue_assurance` | none | Page 6 |

The five Mart Explores share one file because none has joins — each is ~5 lines.

**Structurally enforced:** there is no file in which `fct_billing` and `fct_payments` are joined, and no file in which `fct_network_events` joins anything customer-related. The forbidden joins from §4.1 are prevented by *absence*, which is stronger than a comment.

### 11.7 View → Explore Reuse

`dim_customers` appears in **5** Explores (base in one, joined in four). `dim_date` appears in **8**. `dim_plans` in **4**. This is exactly why joins live in Explores rather than views — one view definition, many join contexts.

### 11.8 Dashboard Files — Two Approaches

| | **User-defined dashboards** | **LookML dashboards** |
|---|---|---|
| Built in | Looker UI, drag-and-drop | Code (`.dashboard.lookml`) |
| Stored in | Looker's internal database | Git |
| Version-controlled | ❌ No | ✅ Yes |
| Editable by non-developers | ✅ Yes | ❌ Requires LookML |
| Speed to build | Fast | Slower |
| Code review | ❌ | ✅ |
| Portable across instances | ❌ Manual | ✅ Deploy the repo |

**A LookML dashboard file contains:** `title`, `layout` (`newspaper`), `preferred_viewer`, a `filters:` list (each with `type: field_filter`, `explore`, `field`, `default_value`), and an `elements:` list where each tile declares `model`, `explore`, `type` (visualization), `dimensions`/`measures`/`fields`, `sorts`, `limit`, viz options, and a `listen:` block wiring dashboard filters to that tile's fields.

**How this maps to MYConnect:** the `listen:` block is exactly how the **tile-scoped filters** from `dashboard_planning.md` are implemented. Page 1's Plan filter listens only on the New-vs-Churned tile; Page 5's Severity filter listens only on network tiles and is simply absent from the `listen:` block of every support tile. A user-defined dashboard achieves the same via per-tile filter settings in the UI.

**Recommendation for this portfolio: start user-defined, then convert Pages 2 and 3 to LookML.**

Reasoning: you are migrating a Looker Studio prototype, so the layouts are already decided — building them in the UI first is faster and lets you validate numbers against the baselines. But converting two dashboards to LookML gives you the artifact that actually demonstrates the skill: a Git-diffable dashboard. Converting all six is repetitive work that shows nothing the first two didn't. Pages 2 and 3 are the right two — Page 2 is the cleanest (all-Gold, all-global filters) and Page 3 exercises tile-scoped filters and a `tier` dimension.

### 11.9 Git Workflow

```text
Looker IDE (or VS Code + Looker extension)
        ↓  edit LookML in a personal dev branch
Git branch  (feature/add-billing-explore)
        ↓  LookML Validator + data tests must pass
commit
        ↓
push  → remote (GitHub)
        ↓
Pull Request  → review (especially: any new join + its relationship)
        ↓
merge to main
        ↓
"Deploy to Production" in Looker
        ↓
Production model  → dashboards refresh with new logic
```

**Version-controlled (in Git):** `manifest.lkml`, the model file, all 17 views, all 9 explore files, LookML dashboards, data tests, README.

**Configured in Looker, NOT in Git:** the BigQuery connection and its service-account key; user/group permissions and content access; schedules and alerts; user-defined dashboards and personal Looks; the Git deploy key itself.

**Dev vs. production:** every developer works in a personal branch with their own dev-mode session. In dev mode Looker compiles *your* branch; end users always see the last deployed production commit. Nothing you write affects users until the merge + deploy. Practically: you can restructure all 13 Explores without breaking a single live dashboard, then deploy once.

**Two-repo relationship:** `myconnect-analytics` (Dataform — builds the tables) and `looker-myconnect` (LookML — exposes them). They are independent repos with a **contract at the table boundary**: renaming `fct_billing.total_amount` in Dataform silently breaks the LookML view. In practice, changes to Gold/Mart column names should be treated as breaking changes requiring a matching LookML PR.

---

## 11.10 What I Would Actually Write in Each File

Small, realistic examples using genuine MYConnect tables and fields.

### `manifest.lkml`
```lookml
project_name: "looker-myconnect"

constant: GCP_PROJECT {
  value: "myconnect-analytics"
  export: override_optional
}
```

### `myconnect.model.lkml`
```lookml
connection: "myconnect_bigquery"

include: "/views/gold/*.view.lkml"
include: "/views/mart/*.view.lkml"
include: "/explores/*.explore.lkml"

datagroup: myconnect_default {
  sql_trigger: SELECT MAX(created_at) FROM `myconnect-analytics.myconnect_gold.fct_billing` ;;
  max_cache_age: "12 hours"
}

persist_with: myconnect_default
```

### `views/gold/dim_customers.view.lkml`
```lookml
view: dim_customers {
  sql_table_name: `@{GCP_PROJECT}.myconnect_gold.dim_customers` ;;

  dimension: customer_id {
    primary_key: yes
    type: string
    sql: ${TABLE}.customer_id ;;
  }

  dimension: state       { type: string sql: ${TABLE}.state ;; }
  dimension: city        { type: string sql: ${TABLE}.city ;; }
  dimension: dwelling_type { type: string sql: ${TABLE}.dwelling_type ;; }
  dimension: current_plan_name { type: string sql: ${TABLE}.current_plan_name ;; }

  dimension: has_active_subscription {
    type: yesno
    sql: ${TABLE}.has_active_subscription ;;
  }

  dimension: tenure_months {
    type: number
    sql: ${TABLE}.tenure_months ;;
    description: "Months since first subscription. CURRENT_DATE()-relative, so inflated versus the 2025-06-30 data window."
  }

  dimension_group: registration {
    type: time
    timeframes: [raw, date, week, month, quarter, year]
    sql: ${TABLE}.registration_date ;;
  }

  measure: count {
    type: count
    drill_fields: [customer_id, state, city, current_plan_name]
  }

  measure: average_tenure_months {
    type: average
    sql: ${tenure_months} ;;
    value_format_name: decimal_1
  }
}
```

### `views/gold/fct_billing.view.lkml` (fact with filtered measures)
```lookml
view: fct_billing {
  sql_table_name: `@{GCP_PROJECT}.myconnect_gold.fct_billing` ;;

  dimension: invoice_id {
    primary_key: yes
    type: string
    sql: ${TABLE}.invoice_id ;;
  }

  dimension: customer_id     { type: string hidden: yes sql: ${TABLE}.customer_id ;; }
  dimension: subscription_id { type: string hidden: yes sql: ${TABLE}.subscription_id ;; }
  dimension: is_overdue         { type: yesno sql: ${TABLE}.is_overdue ;; }
  dimension: reconciliation_flag { type: yesno sql: ${TABLE}.reconciliation_flag ;; }

  dimension: payment_reconciliation_status {
    label: "Payment Status"
    type: string
    sql: ${TABLE}.payment_reconciliation_status ;;
    description: "unpaid / full_payment / underpayment / overpayment. NOT the raw invoice status."
  }

  dimension_group: invoice {
    type: time
    timeframes: [raw, date, week, month, quarter, year]
    sql: ${TABLE}.invoice_date ;;
  }

  dimension: invoice_age_band {
    label: "Invoice Aging"
    type: tier
    tiers: [0, 31, 61, 91]
    style: integer
    sql: DATE_DIFF(CURRENT_DATE(), ${TABLE}.due_date, DAY) ;;
  }

  measure: invoice_count  { type: count }
  measure: total_revenue  { type: sum sql: ${TABLE}.total_amount ;; }
  measure: avg_invoice_value { type: average sql: ${TABLE}.total_amount ;; }

  measure: dso {
    label: "DSO (days)"
    type: average
    sql: ${TABLE}.days_to_payment ;;
  }

  measure: overdue_amount {
    type: sum
    sql: ${TABLE}.total_amount ;;
    filters: [is_overdue: "yes"]
  }

  measure: mismatch_count {
    type: count
    filters: [reconciliation_flag: "yes"]
  }
}
```

### `views/mart/mart_revenue.view.lkml` (array exclusion + aggregation caveat)
```lookml
view: mart_revenue {
  sql_table_name: `@{GCP_PROJECT}.myconnect_mart.mart_revenue` ;;

  # EXCLUDED: revenue_by_plan and revenue_by_segment are ARRAY<STRUCT<>>.
  # For plan-level revenue use the `billing` Explore (fct_billing -> dim_plans).

  dimension: revenue_month {
    primary_key: yes
    type: date
    datatype: date
    sql: ${TABLE}.revenue_month ;;
  }

  # NOTE: rows are already monthly aggregates. AVERAGE (not SUM) across a
  # multi-month range; SUM would add 18 monthly MRR values together.
  measure: mrr             { type: average sql: ${TABLE}.mrr ;; }
  measure: arpu            { type: average sql: ${TABLE}.arpu ;; }
  measure: collection_rate { type: average sql: ${TABLE}.collection_rate ;; value_format_name: percent_1 }
}
```

### `explores/billing.explore.lkml`
```lookml
explore: billing {
  view_name: fct_billing
  label: "Billing"
  description: "Invoice-grain billing facts. 1 row per invoice. Do NOT join fct_payments here."

  join: dim_subscriptions {
    type: left_outer
    relationship: many_to_one
    sql_on: ${fct_billing.subscription_id} = ${dim_subscriptions.subscription_id} ;;
  }

  join: dim_plans {
    type: left_outer
    relationship: many_to_one
    sql_on: ${dim_subscriptions.plan_id} = ${dim_plans.plan_id} ;;
  }

  join: dim_customers {
    type: left_outer
    relationship: many_to_one
    sql_on: ${fct_billing.customer_id} = ${dim_customers.customer_id} ;;
  }
}
```

### `explores/network_events.explore.lkml` (deliberate isolation)
```lookml
explore: network_events {
  view_name: fct_network_events
  label: "Network Events"
  description: "Infrastructure telemetry. No customer or subscription FK exists by design — never join customer data here."

  join: dim_date {
    type: left_outer
    relationship: many_to_one
    sql_on: DATE(${fct_network_events.start_time}) = ${dim_date.date_key} ;;
  }
}
```

### `dashboards/03_revenue_billing.dashboard.lookml` (excerpt)
```lookml
- dashboard: revenue_billing
  title: Revenue & Billing
  layout: newspaper
  preferred_viewer: dashboards-next

  filters:
  - name: invoice_date
    title: Invoice Date
    type: field_filter
    default_value: 18 months
    model: myconnect
    explore: billing
    field: fct_billing.invoice_date

  - name: plan
    title: Plan
    type: field_filter
    model: myconnect
    explore: billing
    field: dim_plans.plan_name

  elements:
  - title: Total Revenue
    name: total_revenue
    model: myconnect
    explore: billing
    type: single_value
    measures: [fct_billing.total_revenue]
    listen:
      invoice_date: fct_billing.invoice_date
      plan: dim_plans.plan_name

  - title: Invoice Aging
    name: invoice_aging
    model: myconnect
    explore: billing
    type: looker_column
    dimensions: [fct_billing.invoice_age_band]
    measures: [fct_billing.invoice_count]
    listen:
      invoice_date: fct_billing.invoice_date
      plan: dim_plans.plan_name
```

### `tests/data_tests.lkml`
```lookml
test: dim_customers_primary_key_is_unique {
  explore_source: customers {
    column: customer_id { field: dim_customers.customer_id }
    column: row_count   { field: dim_customers.count }
    sorts: [row_count: desc]
    limit: 1
  }
  assert: customer_id_is_unique {
    expression: ${row_count} = 1 ;;
  }
}

test: billing_explore_does_not_fan_out {
  explore_source: billing {
    column: invoice_count { field: fct_billing.invoice_count }
  }
  assert: invoice_count_matches_source {
    expression: ${invoice_count} = 2995000 ;;
  }
}
```

> The second test is the LookML equivalent of the row-count checkpoint in §7 step 8 — it fails the build if a join starts multiplying invoices. Dataform assertions cannot catch this, because the fan-out is introduced by the semantic layer, not the warehouse.
