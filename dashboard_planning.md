# MYConnect Analytics — Looker Dashboard Planning (Canonical)

**Status:** FINAL — this is the authoritative reference for the Looker dashboard build.
**Scope:** 6 dashboard pages, built on the existing Gold + Mart layers.
**Rule:** Do not redesign or reinterpret the decisions in this document. If something here conflicts with the original project specification (`/Users/luqman/time-dotcom-portfolio-project-spec.md`), **this document wins** — it reflects later decisions made with knowledge of the actual implemented schemas.

---

## 1. ARCHITECTURE — WHAT LOOKER MAY CONSUME

```text
Bronze ─→ Silver ─→ GOLD ─────────────┐
                     dim_* / fct_*    ├──→ LOOKER
                   └─→ MART ──────────┘
                        mart_*
```

| Layer | Looker access | Role |
|---|---|---|
| **GOLD** (`dim_*`, `fct_*`) | ✅ Yes | Detailed, filterable, sliceable, drillable analysis |
| **MART** (`mart_*`) | ✅ Yes | Headline KPIs and precomputed monthly trends |
| **SILVER** (`stg_*`, `int_*`) | ❌ **NEVER** | Not exposed to Looker under any circumstance |
| **BRONZE** | ❌ Never | Not exposed to Looker |

**Explore rule — prevents fan-out:** build **one Explore per fact**, never a mega-Explore. Each Explore joins **only many:1 dimensions** (`dim_subscriptions`, `dim_plans`, `dim_geography`, `dim_customers`).

**Four joins that must never be built:**

1. `fct_billing` ⋈ `fct_payments` — 1:many, inflates every invoice amount. Not needed: `fct_billing.total_paid` already carries the invoice-level payment total.
2. `fct_billing` ⋈ `fct_support_tickets` ⋈ `fct_churn_events` on `customer_id` — many×many×many. Use `mart_customer_360` (pre-aggregated to 1 row/customer).
3. `dim_customers` ⋈ `dim_subscriptions` counted naively — 1:many, inflates customer counts. Use `dim_customers.current_plan_name`, or `COUNT(DISTINCT customer_id)`.
4. `fct_network_events` ⋈ anything customer-related — **impossible**: network events carry no customer/subscription FK by design.

**Mart array caveat:** UNNEST-ing a Mart array (`revenue_by_plan`, `churn_by_reason`, `incidents_by_severity`, `tickets_by_category`) repeats the parent month row per element. `SUM(mrr)` *after* an UNNEST double-counts. Use UNNESTed arrays only in dedicated breakdown tiles, never alongside scalar month measures in the same query.

---

## 2. LOCKED BUSINESS DECISIONS

These were agreed explicitly and must not be re-litigated during the build.

| # | Decision |
|---|---|
| 1 | **Cohort retention** = % of customers from a registration-month cohort who still have ≥1 active subscription at month-end. *(Definition locked and preserved; the tile itself is deferred — see Page 4 removals.)* |
| 2 | **Customer lifetime** = registration date → churn date for churned customers; registration date → **2025-06-30** for customers who have not churned. |
| 3 | **SLA Compliance** = unsupported / not available. Do not build. |
| 4 | **FCR (First-Call Resolution)** = unsupported / not available. Do not build. |
| 5 | "Top 10 Issue Subcategories" is **replaced by "Top 10 Support Categories"** (`subcategory` was never carried into Gold). |
| 6 | "Promotion Impact" is **replaced by "Discount Impact"** (reliable promo attribution is unavailable; `promo_id` is absent from Gold). |
| 7 | Page 1's date filter may be global; **State / Dwelling / Plan filters apply only to tiles whose Gold source supports those dimensions.** |
| 8 | **ARPU target removed** — no target definition exists anywhere. |
| 9 | Revenue Assurance **may use a new Gold bill-line-item fact** to support charge_type analysis. ⚠️ **This fact does not exist yet — see Section 9.** |

---

## 3. LAYOUT CONSTRAINTS (apply to all 6 pages)

```text
Canvas ........ 1600 × 1240 px  (fixed, no scrolling)
Outer margin .. 32px            Content width = 1536px
Gutter ........ 24px            (the only gap value used — never mix)

VERTICAL STACK                  HEIGHT    Y-RANGE
  Top margin                      32      0    – 32
  Header band                     88      32   – 120
  gap                             24
  Filter bar                      72      144  – 216
  gap                             24
  KPI row                        140      240  – 380
  gap                             24
  MAIN visual row                420      404  – 824
  gap                             24
  SECONDARY visual row           360      848  – 1208
  Bottom margin                   32      1208 – 1240
                                ─────
                                1240 ✓

HORIZONTAL PATTERNS (content = 1536px)
  4 KPI cards ....... 366 each + 3 gutters
  2 equal panels .... 756 each + 1 gutter
  60 / 40 panels .... 916 + 596 + 1 gutter
```

### Hard caps per page

| Element | Maximum |
|---|---|
| KPI cards | **4** |
| Filters | **4** |
| Main visual panels (charts/tables) | **4** |

If content exceeds these caps, **remove lower-value items** — never compress the layout.

### Consistent page skeleton

```text
HEADER (88)  →  FILTER BAR (72)  →  KPI ROW (140, ×4)
             →  MAIN ROW (420, 60/40 or 50/50)
             →  SECONDARY ROW (360, 50/50)
```

The only permitted variation is whether the main row splits **916/596** (Pages 1, 3, 6 — one hero trend dominates) or **756/756** (Pages 2, 4, 5 — two views of equal weight).

---

## 4. PAGE 1 — EXECUTIVE OVERVIEW

**Purpose:** Is the business growing, and is revenue healthy? Board/C-suite. One screen, headline numbers and direction only.

### Layout

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│  EXECUTIVE OVERVIEW                                  Data through 30 Jun 2025    │
├──────────────────────────────────────────────────────────────────────────────────┤
│  [ Month range ▼ ]  [ Plan ▼ ]         ⓘ Plan affects the Net Adds tile only     │
├─────────────────┬─────────────────┬─────────────────┬────────────────────────────┤
│ ① MRR           │ ② ACTIVE SUBS   │ ③ ARPU          │ ④ GROSS CHURN RATE         │
│   MART          │   GOLD          │   MART          │   MART                     │
├─────────────────┴─────────────────┴────────┬────────┴────────────────────────────┤
│ ⑤ MRR TREND — 18 MONTHS (line)             │ ⑥ REVENUE BY PLAN (h-bar)           │
│   916 × 420 · MART                         │   596 × 420 · MART                  │
├────────────────────────────────────────────┴────────────────────────────────────┤
│ ⑦ CHURN RATE TREND (line ×3)               │ ⑧ NEW vs CHURNED (grouped bar+line) │
│   756 × 360 · MART                         │   756 × 360 · GOLD                  │
└────────────────────────────────────────────┴────────────────────────────────────┘
```

### Items

| # | Item | Viz | Source | Model | Measure |
|---|---|---|---|---|---|
| ① | MRR | KPI + delta | MART | `mart_revenue` | `mrr` |
| ② | Active Subscribers | KPI + delta | **GOLD** | `dim_subscriptions` | `COUNT WHERE is_active` |
| ③ | ARPU | KPI | MART | `mart_revenue` | `arpu` |
| ④ | Gross Churn Rate | KPI + delta | MART | `mart_churn` | `gross_churn_rate` |
| ⑤ | MRR Trend (18 mo) | Line | MART | `mart_revenue` | `mrr` by `revenue_month` |
| ⑥ | Revenue by Plan | Horizontal bar | MART | `mart_revenue` | UNNEST `revenue_by_plan` |
| ⑦ | Churn Rate Trend | Line, 3 series | MART | `mart_churn` | gross / voluntary / involuntary |
| ⑧ | New vs Churned Subscribers | Grouped bar + net line | **GOLD** | `dim_subscriptions` + `fct_churn_events` | `COUNT(start_date)` / `COUNT(churn_date)` |

> **Tile ⑧ implementation note:** aggregate the two facts **separately**, then merge results. Never join them.

**Why ② is Gold:** `mart_revenue` computes `active_subscriber_count` in a CTE but **does not output it**. Gold is the only route.

**Why ⑧ is Gold:** `mart_churn` outputs **rates only, no raw counts**.

### Filters

| Filter | Control | Scope |
|---|---|---|
| Month range | Date range picker (month granularity) | **Global** |
| Plan | Dropdown, multi-select | **Tile ⑧ only** — mark inline with ⓘ |

### Removed (do not build)

| Removed | Reason |
|---|---|
| Collection Rate KPI | Belongs on Page 3 |
| Net Subscriber Additions KPI | Expressed as tile ⑧ instead |
| ARPU vs **target** reference line | **Decision 8** — no target defined |
| Subscriber growth **waterfall** | Replaced by grouped bar (more reliable in Looker, same story) |
| **State / Dwelling filters** | Only 2 of 8 tiles could respond (Marts carry no state/dwelling). Dead filters on the most-viewed page are worse than none. Link to Page 2 instead |
| "Plan **tier**" | No speed-tier boundaries defined → rendered by plan **name** |

### FINAL PAGE CONTENT
```text
KPI:      MRR · Active Subscribers · ARPU · Gross Churn Rate
Filters:  Month range (global) · Plan (scoped to tile ⑧)
Charts:   MRR Trend · Revenue by Plan · Churn Rate Trend · New vs Churned Subscribers
Source:   mart_revenue, mart_churn, dim_subscriptions, fct_churn_events
```

---

## 5. PAGE 2 — CUSTOMER & SUBSCRIBER ANALYTICS

**Purpose:** Who are our customers, where are they, what do they buy, how long do they stay?
**Note:** the only page where **every filter works on every tile** — the natural self-service home.

### Layout

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│  CUSTOMER & SUBSCRIBER ANALYTICS                     Data through 30 Jun 2025    │
├──────────────────────────────────────────────────────────────────────────────────┤
│ [ Registration date ▼ ] [ State ▼ ] [ Dwelling ▼ ] [ Plan ▼ ]  ✅ all global     │
├─────────────────┬─────────────────┬─────────────────┬────────────────────────────┤
│ ① TOTAL         │ ② ACTIVE        │ ③ AVG TENURE    │ ④ SDU / MDU SPLIT          │
│   CUSTOMERS     │   SUBSCRIPTIONS │                 │                            │
├─────────────────┴─────────────────┴────────┬────────┴────────────────────────────┤
│ ⑤ ACQUISITION — MDU vs SDU (stacked bar)   │ ⑥ CUSTOMERS BY STATE (h-bar, top 10)│
│   916 × 420 · GOLD                         │   596 × 420 · GOLD                  │
├────────────────────────────────────────────┴────────────────────────────────────┤
│ ⑦ PLAN MIX (donut)                         │ ⑧ TENURE DISTRIBUTION (histogram)   │
│   756 × 360 · GOLD                         │   756 × 360 · GOLD                  │
└────────────────────────────────────────────┴────────────────────────────────────┘
```

### Items — all GOLD

| # | Item | Viz | Model | Dimension / Measure |
|---|---|---|---|---|
| ① | Total Customers | KPI | `dim_customers` | `COUNT(customer_id)` |
| ② | Active Subscriptions | KPI | `dim_subscriptions` | `COUNT WHERE is_active` |
| ③ | Avg Tenure | KPI | `dim_customers` | `AVG(tenure_months)` |
| ④ | SDU/MDU Split | KPI (dual %) | `dim_customers` | `dwelling_type` % of COUNT |
| ⑤ | Acquisition — MDU vs SDU | Stacked bar | `dim_customers` | reg. month × `dwelling_type` |
| ⑥ | Customers by State | Horizontal bar, top 10 | `dim_customers` | `state` × COUNT |
| ⑦ | Plan Mix | Donut | `dim_customers` | `current_plan_name` × COUNT |
| ⑧ | Tenure Distribution | Histogram | `dim_customers` | bucketed `tenure_months` |

> **⑦ uses `current_plan_name` (1 row/customer) — no fan-out.**
> **⑥ is a bar, not a map** — no lat/long exists in the model.

### Filters — all TRULY GLOBAL

| Filter | Control | Note |
|---|---|---|
| Registration date range | Date range picker (daily) | Arbitrary ranges fully supported |
| State | Dropdown, multi-select | 16 values |
| Dwelling | Dropdown / toggle | Only 2 values — toggle beats multi-select |
| Plan | Dropdown, multi-select | 18 plans via `current_plan_name` |

### Caveats

- ③ `tenure_months` is `CURRENT_DATE()`-relative → inflated vs. the 2025-06-30 data end. **Label the tile "as of today."** Same caveat applies to ⑧.

### Removed (do not build)

| Removed | Reason |
|---|---|
| Cohort size by registration month | Mathematically identical to ⑤'s totals — pure duplication |
| Separate "MDU vs SDU growth" chart | Merged into ⑤ as the stack |
| `mart_customer_360` as a panel source | Lacks `state` / `city` / `registration_date`. Reserve for a drill-through detail table |

### FINAL PAGE CONTENT
```text
KPI:      Total Customers · Active Subscriptions · Avg Tenure · SDU/MDU Split
Filters:  Registration date · State · Dwelling · Plan  (all global)
Charts:   Acquisition MDU vs SDU · Customers by State · Plan Mix · Tenure Distribution
Source:   dim_customers, dim_subscriptions  (all Gold)
```

---

## 6. PAGE 3 — REVENUE & BILLING

**Purpose:** How much are we recognising, and are customers paying on time?
**Design decision:** all four panels are **Gold (`fct_billing`)** so all four filters work everywhere. Only the Collection Rate KPI is Mart-sourced and is date-only.

### Layout

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│  REVENUE & BILLING                                   Data through 30 Jun 2025    │
├──────────────────────────────────────────────────────────────────────────────────┤
│ [ Invoice date ▼ ] [ Plan ▼ ] [ Payment status ▼ ] [ State ▼ ]  ⓘ ② date only   │
├─────────────────┬─────────────────┬─────────────────┬────────────────────────────┤
│ ① TOTAL REVENUE │ ② COLLECTION    │ ③ DSO           │ ④ OVERDUE AMOUNT           │
│   GOLD          │   RATE · MART ⓘ │   GOLD          │   GOLD                     │
├─────────────────┴─────────────────┴────────┬────────┴────────────────────────────┤
│ ⑤ REVENUE TREND BY MONTH (bar)             │ ⑥ REVENUE BY PLAN (h-bar)           │
│   916 × 420 · GOLD                         │   596 × 420 · GOLD ⋈ dim_plans      │
├────────────────────────────────────────────┴────────────────────────────────────┤
│ ⑦ INVOICE AGING (bar, 4 buckets)           │ ⑧ DISCOUNT IMPACT (dual line)       │
│   756 × 360 · GOLD                         │   756 × 360 · GOLD                  │
└────────────────────────────────────────────┴────────────────────────────────────┘
```

### Items

| # | Item | Viz | Source | Model | Measure |
|---|---|---|---|---|---|
| ① | Total Revenue | KPI | **GOLD** | `fct_billing` | `SUM(total_amount)` |
| ② | Collection Rate | KPI | **MART** | `mart_revenue` | `collection_rate` ⓘ date-only |
| ③ | DSO | KPI | **GOLD** | `fct_billing` | `AVG(days_to_payment)` |
| ④ | Overdue Amount | KPI | **GOLD** | `fct_billing` | `SUM(total_amount) WHERE is_overdue` |
| ⑤ | Revenue Trend by Month | Bar | **GOLD** | `fct_billing` | `SUM(total_amount)` by `invoice_date` month |
| ⑥ | Revenue by Plan | Horizontal bar | **GOLD** | `fct_billing` ⋈ `dim_subscriptions` ⋈ `dim_plans` | `SUM(total_amount)` |
| ⑦ | Invoice Aging | Bar, 4 buckets | **GOLD** | `fct_billing` | COUNT + SUM by `due_date` age |
| ⑧ | Discount Impact | Dual-series line | **GOLD** | `fct_billing` | `SUM(total_amount)` vs `SUM(discount_amount)` |

> **② must stay Mart.** `mart_revenue.collection_rate` correctly excludes the 6,859 orphan payments. **Do not rebuild it naively from `fct_payments`** — a naive sum inflates the numerator.
> **⑦ buckets (0-30 / 31-60 / 61-90 / 90+) are spec-defined**, not invented.
> **⑧ is Discount Impact, not Promotion Impact** (Decision 6) — `promo_id` is absent from Gold.

### Filters

| Filter | Control | Scope |
|---|---|---|
| Invoice date range | Date range picker (daily) | Global |
| Plan | Dropdown, multi-select | Gold tiles |
| **Payment status** | Dropdown, multi-select | Gold tiles |
| State | Dropdown, multi-select | Gold tiles (via `fct_billing.customer_id` ⋈ `dim_customers`) |

> ⚠️ **Label the third filter "Payment status", NOT "Billing status."** `fct_billing` does not carry the raw 4-value invoice status (paid/unpaid/overdue/void). Source it from `payment_reconciliation_status` (unpaid / full_payment / underpayment / overpayment).

### Removed (do not build)

| Removed | Reason |
|---|---|
| Payment Method Distribution | Requires `payment_date` → would force a **second date filter** and break the clean single-filter design. Belongs in a payments Explore |
| Overdue Invoices **Count** | Overdue **Amount** carries the same story in RM |
| Avg Invoice Value | Low executive value; derivable in an Explore |
| Collection Rate **trend panel** | KPI card is enough; a panel ignoring 3 of 4 filters would look broken |

### FINAL PAGE CONTENT
```text
KPI:      Total Revenue · Collection Rate · DSO · Overdue Amount
Filters:  Invoice date · Plan · Payment status · State
Charts:   Revenue Trend · Revenue by Plan · Invoice Aging · Discount Impact
Source:   fct_billing (+ dim_subscriptions, dim_plans, dim_customers); mart_revenue for ② only
```

---

## 7. PAGE 4 — CHURN & RETENTION

**Purpose:** Why are customers leaving, which segments leave most, are save-offers working?

### Layout

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│  CHURN & RETENTION                                   Data through 30 Jun 2025    │
├──────────────────────────────────────────────────────────────────────────────────┤
│ [ Churn date ▼ ] [ Churn type ▼ ] [ Plan ▼ ] [ State ▼ ]   ⓘ ⑤ date only        │
├─────────────────┬─────────────────┬─────────────────┬────────────────────────────┤
│ ① GROSS CHURN   │ ② VOLUNTARY     │ ③ RETENTION     │ ④ AVG CUSTOMER LIFETIME    │
│   MART          │   CHURN · MART  │   SUCCESS· MART │   GOLD                     │
├─────────────────┴─────────────────┴────────┬────────┴────────────────────────────┤
│ ⑤ CHURN RATE TREND (line ×3)               │ ⑥ CHURN REASONS (h-bar)             │
│   916 × 420 · MART                         │   596 × 420 · GOLD                  │
├────────────────────────────────────────────┴────────────────────────────────────┤
│ ⑦ CHURN BY DWELLING TYPE (bar)             │ ⑧ CHURN BY PLAN (h-bar)             │
│   756 × 360 · GOLD ⋈ dim_customers         │   756 × 360 · GOLD ⋈ dim_plans      │
└────────────────────────────────────────────┴────────────────────────────────────┘
```

### Items

| # | Item | Viz | Source | Model | Note |
|---|---|---|---|---|---|
| ① | Gross Churn Rate | KPI | MART | `mart_churn` | Correct point-in-time denominator |
| ② | Voluntary Churn Rate | KPI | MART | `mart_churn` | The actionable half |
| ③ | Retention Success Rate | KPI | MART | `mart_churn` | `retention_rate` |
| ④ | Avg Customer Lifetime | KPI | **GOLD** | `dim_customers` + `fct_churn_events` | **Decision 2** |
| ⑤ | Churn Rate Trend | Line ×3 | MART | `mart_churn` | Date-only, marked |
| ⑥ | Churn Reasons | Horizontal bar | **GOLD** | `fct_churn_events` | Gold so it responds to all 4 filters |
| ⑦ | Churn by Dwelling | Bar (rate %) | **GOLD** | `fct_churn_events` ⋈ `dim_customers` | **No dwelling breakdown exists in `mart_churn`** |
| ⑧ | Churn by Plan | Horizontal bar | **GOLD** | `fct_churn_events` ⋈ `dim_subscriptions` ⋈ `dim_plans` | Many:1 joins only |

> ⚠️ **④ implementation note:** per Decision 2, lifetime = registration → churn (churned) or registration → 2025-06-30 (not churned). **Deduplicate churn events to customer grain first** (e.g. `MAX(churn_date)` per customer) — a customer can hold multiple churn events across different subscriptions. Failing to dedupe will fan out the average.
> **⑥ note:** ~500 NULL churn reasons render as an honest "(unspecified)" bucket. Do not impute.

### Filters

| Filter | Control | Scope |
|---|---|---|
| Churn date range | Date range picker | Global (month for ⑤, daily for Gold tiles) |
| Churn type | Dropdown (voluntary / involuntary) | **Gold tiles only** — Mart stores these as separate columns, not a dimension |
| Plan | Dropdown, multi-select | Gold tiles |
| State | Dropdown, multi-select | Gold tiles — no `state` in `mart_churn` |

### Drilldown
`⑥ churn reason` → detail table (`fct_churn_events` ⋈ `dim_customers` ⋈ `dim_plans`) showing state / dwelling / plan / tenure / ETF per churned customer.

### Removed (do not build)

| Removed | Reason |
|---|---|
| **Cohort retention curves** | **Deliberately deferred despite Decision 1.** The definition is locked and preserved (Section 2), but a cohort-month × months-since matrix needs a derived table — the heaviest Looker modeling in the project, and it would consume the 4-panel budget. **Build as a dedicated Cohort Explore later**, not a tile here |
| Involuntary Churn Rate KPI | Visible as the third series in ⑤ |
| Churn by tenure band | Band boundaries remain an undefined-by-spec assumption; ⑦ and ⑧ are stronger |
| Retention offer acceptance trend | KPI ③ already carries it |
| "Segment" filter / drill | No segment field or crosswalk defined anywhere |
| Net churn rate | No formula defined anywhere |

### FINAL PAGE CONTENT
```text
KPI:      Gross Churn Rate · Voluntary Churn Rate · Retention Success Rate · Avg Customer Lifetime
Filters:  Churn date · Churn type · Plan · State
Charts:   Churn Rate Trend · Churn Reasons · Churn by Dwelling · Churn by Plan
Source:   mart_churn, fct_churn_events, dim_customers, dim_subscriptions, dim_plans
```

---

## 8. PAGE 5 — SERVICE QUALITY & CUSTOMER SUPPORT

**Purpose:** How reliable is the network, and how well do we support customers?

> ⚠️ **CRITICAL CONSTRAINT:** `fct_network_events` carries **no customer or subscription FK by design**. There is **no key** joining network events to support tickets. This page is built as **two visually separated zones, each with its own filters and its own Explore**. Filters must never cross the divider.

### Layout

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│  SERVICE QUALITY & CUSTOMER SUPPORT                  Data through 30 Jun 2025    │
├────────────────────────────────────┬─────────────────────────────────────────────┤
│ ═ NETWORK ═ [Event date ▼][Severity ▼] │ ═ SUPPORT ═ [Ticket date ▼][Category ▼] │
│        ⚠ Network and Support share no join key — filters never cross             │
├─────────────────┬─────────────────┬─────────────────┬────────────────────────────┤
│ ① TOTAL OUTAGES │ ② AVG OUTAGE    │ ③ CSAT AVERAGE  │ ④ OPEN TICKETS             │
│   MART          │   DURATION·GOLD │   MART          │   GOLD                     │
├─────────────────┴─────────────────┼─────────────────┴────────────────────────────┤
│ ╔══════ NETWORK ══════════════════╗│╔══════ SUPPORT ═════════════════════════════╗│
│ ║ ⑤ OUTAGE TREND BY SEVERITY      ║│║ ⑥ TOP 10 SUPPORT CATEGORIES                ║│
│ ║   756 × 420 · GOLD              ║│║   756 × 420 · GOLD                         ║│
│ ╠═════════════════════════════════╣│╠════════════════════════════════════════════╣│
│ ║ ⑦ NETWORK EVENTS BY REGION      ║│║ ⑧ AVG RESOLUTION TIME TREND                ║│
│ ║   756 × 360 · MART              ║│║   756 × 360 · MART                         ║│
│ ╚═════════════════════════════════╝│╚════════════════════════════════════════════╝│
└────────────────────────────────────┴─────────────────────────────────────────────┘
```

### Items

| # | Item | Viz | Source | Model | Note |
|---|---|---|---|---|---|
| ① | Total Outages | KPI | MART | `mart_service_quality` | `SUM(outage_count)` — already outage-specific |
| ② | Avg Outage Duration | KPI | **GOLD** | `fct_network_events` | ⚠️ **Must be Gold** — see warning below |
| ③ | CSAT Average | KPI | MART | `mart_customer_support` | `csat_avg` |
| ④ | Open Tickets | KPI | **GOLD** | `fct_support_tickets` | `COUNT WHERE status IN ('open','in_progress')` |
| ⑤ | Outage Trend by Severity | Stacked bar | **GOLD** | `fct_network_events` | Filter `event_type='outage'`, group by `severity` |
| ⑥ | Top 10 Support Categories | Horizontal bar | **GOLD** | `fct_support_tickets` | **Decision 5** |
| ⑦ | Network Events by Region | Horizontal bar | MART | `mart_service_quality` | Month + region grain |
| ⑧ | Avg Resolution Time Trend | Line | MART | `mart_customer_support` | `avg_resolution_hours` |

> ⚠️ **② must be GOLD, not Mart.** `mart_service_quality.avg_duration_hours` averages **all event types** (outage / degradation / maintenance / restoration), not outages only. Using the Mart value would answer a different question than the card's label. Gold filters `event_type = 'outage'`.
> ⚠️ **⑤ must be GOLD, not Mart.** The Mart's `incidents_by_severity` array counts all event types, not outages only.
> ⚠️ **⑦ region label:** this is the *network* region taxonomy (Klang Valley / Northern / Southern / East Coast / Sabah / Sarawak) — **a different scheme from `dim_geography`'s** customer region (Central / Northern / East Coast / Southern / Borneo / Other). **Label it "Network region."** Do not cross-map the two.
> **③ note:** ~68% of tickets have a NULL satisfaction score — a data characteristic, not a defect.

### Filters — deliberately zoned, two per side

| Filter | Control | Scope |
|---|---|---|
| Event date range | Date range picker | **Network tiles only** (① ② ⑤ ⑦) |
| Severity | Dropdown, multi-select (3 values) | **Network tiles only** |
| Ticket date range | Date range picker | **Support tiles only** (③ ④ ⑥ ⑧) |
| Ticket category | Dropdown, multi-select | **Support tiles only** |

### Removed (do not build)

| Removed | Reason |
|---|---|
| **SLA Compliance %** KPI | **Decision 3** — unsupported. `sla_met` is NULL for every ticket; no threshold and no first-response timestamp exist |
| **First-Call Resolution Rate** KPI | **Decision 4** — unsupported. No first-interaction field exists |
| Top 10 issue **subcategories** | **Decision 5** — `subcategory` was never carried into `fct_support_tickets`. Replaced by Top 10 **Categories** |
| CSAT distribution chart | KPI ③ carries the headline; distribution is Explore-level detail |
| Ticket channel distribution | Lowest business value of the support charts; cut to respect the 4-panel cap |

### FINAL PAGE CONTENT
```text
KPI:      Total Outages · Avg Outage Duration · CSAT Average · Open Tickets
Filters:  Event date + Severity (network zone) · Ticket date + Category (support zone)
Charts:   Outage Trend by Severity · Top 10 Support Categories
          · Network Events by Region · Avg Resolution Time Trend
Source:   fct_network_events, fct_support_tickets, mart_service_quality, mart_customer_support
```

---

## 9. PAGE 6 — REVENUE ASSURANCE

**Purpose:** Are we losing revenue, and exactly where? The portfolio differentiator (the JD's "added advantage").

> ## ⚠️ BUILD PREREQUISITE — READ BEFORE STARTING THIS PAGE
>
> **Tile ⑥ ("Leakage by Charge Type") and the "Charge type" filter require a NEW Gold fact: `fct_bill_line_items`.**
>
> **This fact DOES NOT EXIST TODAY.** Verified: `charge_type` is **absent from every current Gold model**. It exists only at Silver line-item grain (`stg_bill_line_items.charge_type`).
>
> **`fct_bill_line_items` must be created in Gold before the charge-type analysis or filter can be built.** Decision 9 authorises creating it; it has not been created.
>
> **Workaround if you want to start Page 6 sooner:** build the page **without** tile ⑥ and **without** the Charge type filter. The other seven items (① ② ③ ④ ⑤ ⑦ ⑧ and three filters) are fully buildable today. Add ⑥ and its filter once the fact lands.

### Layout

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│  REVENUE ASSURANCE                                   Data through 30 Jun 2025    │
├──────────────────────────────────────────────────────────────────────────────────┤
│ [ Invoice date ▼ ] [ Plan ▼ ] [ Charge type ▼ ⚠ ] [ Mismatch threshold: RM ___ ] │
├─────────────────┬─────────────────┬─────────────────┬────────────────────────────┤
│ ① BILLING       │ ② MISMATCH      │ ③ REVENUE       │ ④ ORPHAN PAYMENTS          │
│   MISMATCHES    │   AMOUNT        │   LEAKAGE %     │                            │
│   MART          │   MART          │   MART          │   MART                     │
├─────────────────┴─────────────────┴────────┬────────┴────────────────────────────┤
│ ⑤ BILLING MISMATCH TREND (dual-axis line)  │ ⑥ LEAKAGE BY CHARGE TYPE ⚠ PREREQ   │
│   916 × 420 · MART                         │   596 × 420 · GOLD fct_bill_line_… │
├────────────────────────────────────────────┴────────────────────────────────────┤
│ ⑦ TOP 10 INVOICES BY DISCREPANCY (table)   │ ⑧ MISMATCH RATE BY PLAN (bar)       │
│   756 × 360 · GOLD fct_billing             │   756 × 360 · GOLD ⋈ dim_plans      │
└────────────────────────────────────────────┴────────────────────────────────────┘
```

### Items

| # | Item | Viz | Source | Model | Buildable today? |
|---|---|---|---|---|---|
| ① | Billing Mismatch Count | KPI | MART | `mart_revenue_assurance.billing_mismatch_count` | ✅ Yes |
| ② | Billing Mismatch Amount | KPI | MART | `mart_revenue_assurance.billing_mismatch_amount` | ✅ Yes |
| ③ | Revenue Leakage % | KPI | MART | `mart_revenue_assurance.leakage_pct` | ✅ Yes |
| ④ | Orphan Payments | KPI | MART | `mart_revenue_assurance.orphan_payments` | ✅ Yes |
| ⑤ | Billing Mismatch Trend | Dual-axis line | MART | `mart_revenue_assurance` | ✅ Yes |
| ⑥ | **Leakage by Charge Type** | Horizontal bar | **GOLD** | **`fct_bill_line_items`** | ❌ **NO — fact must be created first** |
| ⑦ | Top 10 Invoices by Discrepancy | Table | **GOLD** | `fct_billing` (`ABS(total_amount − line_item_total)`) | ✅ Yes |
| ⑧ | Mismatch Rate by Plan | Bar | **GOLD** | `fct_billing` ⋈ `dim_subscriptions` ⋈ `dim_plans` | ✅ Yes |

### Filters

| Filter | Control | Scope | Buildable today? |
|---|---|---|---|
| Invoice date range | Date range picker | Global | ✅ Yes |
| Plan | Dropdown, multi-select | Gold tiles ⑦ ⑧ | ✅ Yes |
| **Charge type** | Dropdown, multi-select | Tile ⑥ only | ❌ **NO — depends on `fct_bill_line_items`** |
| Mismatch threshold | **Numeric input / Looker parameter** | Tile ⑦ | ✅ Yes |

### Architecture note — spec override

The original spec (Section 13, Page 6) listed `int_billing_reconciliation` and `int_payment_reconciliation` as sources. **Do not use them — Silver is never exposed to Looker.** Gold now carries everything needed:

```text
int_billing_reconciliation  →  fct_billing.line_item_total, reconciliation_flag
int_payment_reconciliation  →  fct_billing.total_paid, payment_reconciliation_status
orphan payments             →  fct_payments.is_orphan_payment
```

Verified equivalent to the Silver baselines: overpayments 18,037; mismatch amount RM 427,279.77; leakage ≈ 0.079%.

### Removed (do not build)

| Removed | Reason |
|---|---|
| Payment reconciliation **waterfall** | Fragile Looker viz; ① – ④ plus ⑦ tell the story more reliably |
| Overpayment **Amount** KPI | 4-card cap reached; leakage % is more central. Available in an Explore (`SUM(total_paid − total_amount) WHERE payment_reconciliation_status='overpayment'`) |

### FINAL PAGE CONTENT
```text
KPI:      Billing Mismatches · Mismatch Amount · Revenue Leakage % · Orphan Payments
Filters:  Invoice date · Plan · Charge type ⚠PREREQ · Mismatch threshold
Charts:   Mismatch Trend · Leakage by Charge Type ⚠PREREQ · Top 10 Invoices · Mismatch Rate by Plan
Source:   mart_revenue_assurance, fct_billing, dim_subscriptions, dim_plans,
          fct_bill_line_items  ← MUST BE CREATED IN GOLD FIRST
```

---

## 10. DESIGN SYSTEM

### Spacing
```text
Outer margin ......... 32px all sides
Gutter (h & v) ....... 24px  — the only gap value used; never mix
Card inner padding ... 24px
Panel inner padding .. 24px (32px top for the title)
Title → content gap .. 16px
```

### Panel sizing — only these widths exist across all 6 pages
```text
366  KPI card (×4)
596  narrow panel (40%)
756  half panel (50%)
916  wide panel (60%)

Heights:  KPI 140  ·  Main row 420  ·  Secondary row 360
```

### KPI card anatomy
```text
┌─ 366 × 140 ──────────────────┐
│  LABEL            11px caps  │  ← 60% opacity, letter-spaced
│                              │
│  RM 32.0M         34px bold  │  ← the hero number
│  ▲ 1.4% vs prior mo   12px   │  ← delta, colour-coded
└──────────────────────────────┘
```
One number per card. **No sparklines inside cards** — trends belong in panels.

### Filter placement
Single 72px band directly under the header, left-aligned, ordered **date → highest-cardinality → lowest-cardinality**. Page 5 is the one exception: two labelled groups split left/right, mirroring its two data domains. **Any scoped filter carries an inline ⓘ note — never leave a dead filter unexplained.**

### Typography hierarchy
```text
Page title ......... 28px  semibold           Header band, left
Page subtitle ...... 14px  regular  60%       Directly under title
Panel title ........ 16px  semibold           Top-left of each panel
KPI label .......... 11px  semibold caps, letter-spacing 0.08em, 60%
KPI value .......... 34px  bold
KPI delta .......... 12px  medium, colour-coded
Axis / legend ...... 12px  regular  70%
Table header ....... 12px  semibold caps
Table body ......... 13px  regular, tabular numerals
```
Four sizes carry 90% of the design: **28 / 16 / 13 / 11**.

### Page title treatment
88px header band. Page title left; **"Data through 30 Jun 2025"** + refresh timestamp right-aligned, 12px at 60% opacity. **The data-through date is non-negotiable on every page** — this is an 18-month synthetic window ending 2025-06-30 and viewers must never mistake it for live data.

### Chart-type discipline
```text
Trend over time ............ line
Category comparison ........ horizontal bar (names stay readable)
Composition over time ...... stacked bar
Part-to-whole at a point ... donut  — used EXACTLY ONCE (Page 2 ⑦)
Ranked detail .............. table  — used EXACTLY ONCE (Page 6 ⑦)
```
**No waterfalls, no heatmaps, no scatter.** Every chart in this set is a Looker default that renders reliably.

---

## 11. RECOMMENDED BUILD ORDER

| # | Page | Difficulty | Why this position |
|---|---|---|---|
| **1** | **Page 2 — Customer & Subscriber** | ⭐ Easiest | Single source (`dim_customers`), all 4 filters truly global, zero gaps, zero fan-out risk. Build here to settle conventions (colours, card anatomy, filter behaviour), then reuse |
| **2** | **Page 3 — Revenue & Billing** | ⭐⭐ Easy | Four panels from one fact (`fct_billing`) → all filters work everywhere. Introduces many:1 dimension joins in the safest setting |
| **3** | **Page 1 — Executive Overview** | ⭐⭐ Easy | Mostly Mart reads, but built **third, not first** — its numbers should be validated against Pages 2 and 3 before executives see them. Only tile ⑧ needs the two-fact merge |
| **4** | **Page 4 — Churn & Retention** | ⭐⭐⭐ Moderate | Real Mart/Gold split; KPI ④ needs careful churn-to-customer deduplication before it's trustworthy |
| **5** | **Page 5 — Service Quality & Support** | ⭐⭐⭐ Moderate | Not technically hard, but the two-zone layout and dual filter groups need the most careful UX work — highest risk of users misreading scope |
| **6** | **Page 6 — Revenue Assurance** | ⭐⭐⭐⭐ Last | **Blocked on the `fct_bill_line_items` prerequisite.** Build the other five pages while that Gold fact is added |

**Sequencing note:** Pages 1–5 are buildable **today** with zero changes to Gold or Mart. Page 6 can also be started today **minus tile ⑥ and the Charge type filter**; add those once `fct_bill_line_items` exists.

---

## 12. MASTER LIST — UNSUPPORTED & REMOVED ITEMS

Nothing in this list may be presented in a dashboard as if it were available.

### Permanently unsupported — no source data exists
| Item | Page | Reason |
|---|---|---|
| SLA Compliance % | 5 | `sla_met` NULL for all tickets; no threshold, no first-response timestamp (Decision 3) |
| First-Call Resolution Rate | 5 | No first-interaction field exists anywhere (Decision 4) |
| Take-Up Rate | — | No `premises_passed` field exists anywhere |
| Ticket subcategories | 5 | `subcategory` never carried into `fct_support_tickets` (Decision 5) |
| Promotion attribution | 3 | `promo_id` absent from Gold; **discount** amount works (Decision 6) |
| Billing status (raw 4-value) | 3 | `fct_billing` carries no raw `status`; use `payment_reconciliation_status` |

### Blocked on a prerequisite
| Item | Page | Unblocked by |
|---|---|---|
| Leakage by Charge Type | 6 | Creating **`fct_bill_line_items`** in Gold |
| Charge type filter | 6 | Same |

### Specification gaps — business rules never defined (do not invent)
| Item | Note |
|---|---|
| ARPU target | No target value anywhere (Decision 8) |
| Plan **tier** boundaries | `speed_tier` NULL everywhere → render by plan **name** |
| Revenue by segment / "segment" | No segment field or crosswalk defined |
| Net churn rate | No formula defined (unlike gross/voluntary/involuntary) |
| Churn risk flags | No scoring rule defined |
| Resolution rate | No locked formula |
| Tenure band boundaries | Undefined by spec |

### Removed for layout/value reasons (data exists, deliberately cut)
| Item | Page | Where it lives instead |
|---|---|---|
| Collection Rate KPI | 1 | Page 3 |
| Subscriber growth waterfall | 1 | Replaced by grouped bar (tile ⑧) |
| Cohort size by registration month | 2 | Duplicate of tile ⑤ |
| Payment Method Distribution | 3 | Payments Explore |
| Overdue Invoices Count, Avg Invoice Value | 3 | Explore |
| **Cohort retention curves** | 4 | **Definition locked (Decision 1); build as a dedicated Cohort Explore later** |
| Churn by tenure band, Retention offer trend | 4 | Explore |
| CSAT distribution, Ticket channel distribution | 5 | Explore |
| Payment reconciliation waterfall | 6 | Covered by KPIs + tile ⑦ |
| Overpayment Amount KPI | 6 | Explore (`SUM(total_paid − total_amount)` where status = overpayment) |

---

## 13. QUICK REFERENCE — VERIFIED SCHEMA FACTS

Field-level facts confirmed against the actual SQLX. Consult before assuming a field exists.

**Gold dimensions**
```text
dim_customers      customer_id, name, type, dwelling_type, state, city, registration_date,
                   tenure_months, lifecycle_stage, has_active_subscription,
                   current_subscription_id, current_plan_id, current_plan_name
dim_subscriptions  subscription_id, customer_id, plan_id, plan_name, speed_tier(NULL),
                   monthly_charge, contract_months, start_date, end_date, is_active
dim_plans          plan_id, plan_name, speed_mbps, monthly_price, category,
                   speed_tier(NULL), is_current
dim_date           date_key, day, month, quarter, year, day_of_week, is_weekend,
                   is_holiday_my(NULL), month_name, fiscal_quarter(NULL)
dim_geography      state, city, region, dwelling_mix
```

**Gold facts**
```text
fct_billing         invoice_id, subscription_id, customer_id, invoice_date, due_date,
                    total_amount, tax_amount, discount_amount, line_item_total,
                    reconciliation_flag, is_overdue, days_to_payment, total_paid,
                    payment_reconciliation_status, created_at
                    ⚠ NO raw `status`; NO billing_period_start/end
fct_payments        payment_id, invoice_id, customer_id, payment_date, payment_amount,
                    payment_method, is_successful, is_orphan_payment,
                    days_after_due_date, created_at
fct_usage_daily     usage_id, subscription_id, usage_date, download_gb, upload_gb,
                    total_gb, peak_speed, avg_speed, speed_achievement_pct, created_at
fct_support_tickets ticket_id, customer_id, subscription_id, created_date, category,
                    priority, status, channel, resolution_hours, satisfaction_score,
                    sla_met(NULL), is_repeat_ticket
                    ⚠ NO subcategory; NO resolved_date
fct_churn_events    churn_event_id, customer_id, subscription_id, churn_date, churn_type,
                    churn_reason, contract_remaining, etf_amount, retention_attempted,
                    retention_success
fct_network_events  event_id, event_type, severity, start_time, end_time,
                    affected_subscribers, region, duration_minutes, affected_subscriber_hours
                    ⚠ NO customer/subscription FK (by design)
```

**Mart models — all month-grain, NO slicing dimensions**
```text
mart_revenue          revenue_month, mrr, total_revenue, arpu, revenue_by_plan[],
                      revenue_by_segment[](NULL), revenue_growth_pct, collection_rate
                      ⚠ active_subscriber_count computed internally but NOT output
mart_customer_360     customer_id, tenure, cltv, total_revenue, avg_monthly_spend,
                      total_tickets, churn_risk_flags(NULL), plan, dwelling, region
                      ⚠ NO state, city, or registration_date
mart_churn            churn_month, segment(NULL), gross/voluntary/involuntary_churn_rate,
                      net_churn_rate(NULL), churn_by_reason[], churn_by_plan[],
                      churn_by_tenure_band[], retention_rate
                      ⚠ rates only — NO raw counts; NO dwelling breakdown
mart_service_quality  event_month, region, outage_count, avg_duration_hours,
                      affected_subscriber_hours, incidents_by_severity[], mean_time_to_restore
                      ⚠ avg_duration_hours covers ALL event types, not outages only
mart_customer_support ticket_month, total_tickets, resolution_rate(NULL),
                      avg_resolution_hours, sla_compliance_pct(NULL), csat_avg,
                      tickets_by_category[]
mart_revenue_assurance assurance_month, billing_mismatch_count, billing_mismatch_amount,
                      orphan_payments, overpayments(COUNT), underpayments(COUNT), leakage_pct
                      ⚠ overpayments/underpayments are COUNTS, not amounts
```

**Data window:** 2024-01-01 → 2025-06-30 (18 months). `dim_date` = 547 rows.

**Not yet built:** `fct_bill_line_items` (Gold) — required for Page 6 tile ⑥ and the Charge type filter.
