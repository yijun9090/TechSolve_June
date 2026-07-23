# TechSolve Ticket Data — Data Quality Findings

**Dataset**: 100,851 tickets × 36 raw columns (MSP support ticket data)

**Companion artefacts**:
- [`notebooks/TechSolve_Data_Quality.ipynb`](../notebooks/TechSolve_Data_Quality.ipynb) — the profiling & discovery notebook that produced these findings
- [`src/m2_clean.py`](../src/m2_clean.py) — the treatment pipeline that implements every fix below (rules R01–R14)
- [`outputs/dq_log.csv`](../outputs/dq_log.csv) — machine-readable audit trail: one row per cleaning rule, rows affected, action taken
- [`outputs/dq_findings.csv`](../outputs/dq_findings.csv) — this document's findings table, exported from the notebook
- [`config/category_mapping.csv`](../config/category_mapping.csv) — the category standardization table (F06)

---

## Methodology

Two-phase audit. Phase 1 profiles each column in isolation (distinct values, ranges,
null rates, distribution shape) — this catches surface issues like inconsistent labels and
sentinel dates, but nothing deeper: every column here is individually plausible. Phase 2 tests
pairs of columns against four business-logic patterns that a column can't fake in isolation:

1. **Two recordings of one fact must agree** (e.g. a duration column vs. a date difference) — checked with correlation and crosstabs.
2. **Lifecycle constraints govern field existence** (e.g. a resolution date can't exist before resolution) — checked with null rates grouped by status.
3. **Per-entity attributes must be stable across rows** (e.g. a customer's region shouldn't change ticket-to-ticket) — checked with group-by + nunique.
4. **Row-wise ordering and business rules** (e.g. response time can't exceed resolution time) — checked with direct boolean comparison.

This is where every major unreliable column was actually caught — 10 of the 18 findings below
came from phase 2, not phase 1.

---

## Findings

### F01 — `sla_breached` is disconnected from the business [HIGH]

The provided SLA-breach flag doesn't track actual handling time. Flag rate is 50.3%
while recalculating from `resolution_time_hours > sla_target_hours` gives 91.8% — a 41-point
gap. An exhaustive sweep against five different timing definitions (resolution vs target,
first-response vs target, first-response vs target/2, resolution vs 2×target, date-diff vs
target) found agreement ≈ 0.50 against every one of them — indistinguishable from a coin flip.
Flag rate is also flat (spread < 0.05) across priority, status, team, category, region, and
escalation — a real flag would vary with at least one of these.

**Detection**: crosstab + exhaustive hypothesis sweep.

**Treatment**: the true breach history is unrecoverable from a disconnected flag, so rebuild
rather than repair. Original column renamed `sla_breached_source` (kept, never used for
metrics); `sla_breached_calc = resolution_time_hours > sla_target_hours` computed fresh,
restricted to Resolved/Closed tickets (a ticket can't have breached or not breached its SLA
while still open).

---

### F02 — `ticket_resolved_date` decoupled from `resolution_time_hours` [HIGH]

These two fields claim to record the same fact (how long a ticket took) but correlate
at r = 0.0032 — essentially zero, when a genuine second recording should correlate near 1.0.
`ticket_resolved_date` is also populated for 100% of tickets regardless of status, including
ones still Open or In Progress, and 53 rows have a resolved date earlier than the created date
(a temporal impossibility).

**Detection**: correlation of two recordings of the same fact + lifecycle null-rate check + row-wise ordering.

**Treatment**: `resolution_time_hours` ruled the sole duration source of truth (internally
consistent with the priority/SLA system at 99.2%+ conformance, see F11).
`ticket_resolved_date` renamed `ticket_resolved_date_unreliable` and must never be used to
compute a duration.

---

### F03 — Lifecycle axiom violated: CSAT and resolution notes exist before resolution [HIGH]

Certain fields should only exist once a ticket is Resolved/Closed. `csat_score` is
present on ~98% of tickets regardless of status — including unresolved ones (~59,400 rows
where a satisfaction score exists for a ticket nobody has finished handling, which is not
plausible). `resolution_notes` shows the inverse pattern: 100% populated on open tickets but
3% *missing* on closed ones.

**Detection**: null rates grouped by status.

**Treatment**: `csat_valid = csat_score` where status is Resolved/Closed, else null (40,217+
valid rows) — satisfaction metrics must only ever read this column, never raw `csat_score`.
`resolution_notes` demoted (see F08).

---

### F04 — `customer_segment` contradicts `account_type` [MED]

9,953 rows have `account_type = Residential` but `customer_segment = Corporate` — a
logically impossible combination (a residential/individual account cannot simultaneously be a
corporate segment). `account_type`'s null structure aligns exactly with `industry`'s null count
(31,767 rows both), which is independent corroborating evidence that `account_type` is the
reliable field.

**Detection**: crosstab of the two columns + cross-check against F03's null-structure alignment.

**Treatment**: `account_type` ruled the sole customer-type source of truth; `customer_segment`
demoted, excluded from every metric.

---

### F05 — `customer_tenure_months` is random [MED]

This column should track how long a customer has held their account, but correlates at
r = -0.003 with the actual account age (`ticket_created_date − account_created_date`) — i.e.
zero relationship. Separately, 3,625 of 5,976 customers (61%) have more than one distinct
tenure value across their own tickets, which is impossible for a single stable attribute of a
customer.

**Detection**: correlation vs. an independently derivable ground truth + per-customer stability check (groupby + nunique).

**Treatment**: demoted to `customer_tenure_months_unreliable`; recomputed fresh as
`tenure_months_calc = months(ticket_created_date − account_created_date)` per ticket.

---

### F06 — `category` fractured into 32 spellings [MED]

32 distinct raw values collapse into 10 canonical categories once case, snake_case, and
abbreviations are normalized (e.g. `Bug Report` / `bug_report` / `BUG` / `Bug report` are the
same category). This affects 20,831 rows (20.7% of the dataset). The frequency distribution is
cleanly two-tiered — 10 canonical spellings at ~8,000 rows each, 22 variant spellings at ~1,000
rows each — which is what made the pattern obvious.

**Detection**: `value_counts()` two-tier frequency structure.

**Treatment**: externalized to a maintainable mapping table
(`config/category_mapping.csv`, never hardcoded) with two levels:
`category_clean` (10 canonical values) → `category_group` (5 designed groups). The join hard-
asserts zero unmapped values — an unrecognized spelling must raise an error, never pass silently.

---

### F07 — `issue_description` independent of `category` [MED]

Only 10 distinct description templates exist across the entire dataset, and each one
appears in all 10 canonical categories at a near-uniform ~10% share (top-counterpart share
range 0.081–0.086) — meaning knowing the description text tells you nothing about the category.
A refund-request-sounding description can appear under `Bug Report`.

**Detection**: crosstab top-share test (for each text value, what fraction of its rows share the
same counterpart value — near 1.0 means linked, near 1/k means random for k categories).

**Treatment**: demoted to `issue_description_unreliable`. Category hierarchy is a designed
taxonomy (`category_group`/`category_clean`, see F06), never derived from text.

---

### F08 — `resolution_notes` independent of description/category + inverted lifecycle [MED]

Same pattern as F07 — only 10 templated note strings exist, each spread ~8-9% across
all 32 raw categories, with near-identical mean `resolution_time_hours` (~120h) regardless of
which note appears. Combined with the inverted lifecycle null pattern from F03 (100% present
on Open tickets, missing on 3% of Closed ones), this is fabricated text, not merely dirty text
— the information it appears to carry never existed.

**Detection**: crosstab top-share test (same method as F07) + status-grouped null rates (same method as F03).

**Treatment**: demoted to `resolution_notes_unreliable`; excluded from any downstream AI-agent
schema so it can never be quoted as a factual resolution summary.

---

### F09 — `monthly_contract_value` contradicts `subscription_type` [MED]

67% of `Free`-tier rows show a non-zero monthly charge, while 27% of `Premium`/
`Enterprise` rows show zero — both directions of the pair contradict what the subscription tier
implies about billing.

**Detection**: zero-share of `monthly_contract_value` grouped by `subscription_type`.

**Treatment**: the two columns are never used together; no revenue analysis is derived from
this pairing in this pipeline.

---

### F10 — 8 sentinel dates + 53 resolved-before-created rows [LOW]

`ticket_created_date` contains 8 sentinel/placeholder values (5× `1970-01-01`, the Unix
epoch; 3× `2099-12-31`, a far-future placeholder) — clearly not real ticket dates. Separately,
53 rows have `ticket_resolved_date` strictly earlier than `ticket_created_date` (a genuine
temporal impossibility; 50 of these are exactly -24h, a systematic-shift signature — see F14 —
not random noise). These two checks overlap on 3 rows, for 58 total rows flagged. Scope note:
excluding sentinels, valid data runs Jul 2023–Dec 2024 (5.4–5.8k tickets/month) with an
isolated 10 rows in Mar 2025, while the assessment brief references a "2024–2025" dashboard.

**Detection**: min/max date range + monthly volume counts + row-wise ordering check
(`resolved < created`, strict, not `<=`, since same-day resolution is normal given date-only
granularity — see the R01 implementation note below).

**Treatment (stakeholder decision): flag, don't drop.** Deleting these rows would destroy the
underlying record permanently; flagging keeps them available for manual investigation (was
this a migration artifact? a bad default? a timezone bug at a date boundary?) without letting
them corrupt any metric that depends on the dates. Three new boolean columns:
`sentinel_date_flag` (the 8 sentinel rows), `date_order_invalid` (the 53 order-violation rows),
`date_needs_review` (their union, 58 rows). Anything downstream that depends on
`ticket_created_date` still has to treat these rows as unusable —
`tenure_months_calc` explicitly nulls and flags them via `tenure_calc_invalid`, otherwise a
2099 sentinel would silently produce a multi-century tenure — but the raw rows themselves stay
in the dataset. The reporting-scope question (which calendar range a dashboard defaults to) is
a separate, later decision from data validity: keep all valid history, default the report to
2024 onward, retain 2023 as comparison baseline.

---

### F11 — 779 priority/SLA mismatches [LOW]

The canonical mapping (`Urgent`→4h, `High`→8h, `Medium`→24h, `Low`→48h) holds for
99.23% of rows. The remaining 779 rows (0.77%) have an `sla_target_hours` value belonging to a
different priority tier, roughly evenly spread across the 3 off-diagonal values for each
priority — consistent with a data-entry error, not a real business exception.

**Detection**: `priority` × `sla_target_hours` crosstab.

**Treatment**: `sla_target_hours` overwritten to the canonical value for its priority. This must
run *before* the SLA-breach recalculation (F01), since that calculation depends on
`sla_target_hours` being correct.

---

### F12 — 14,750 rows respond after resolving [LOW]

`first_response_time_hours > resolution_time_hours` on 14,750 rows — a temporal
impossibility (you can't log your first response after the ticket is already resolved).

**Detection**: direct row-wise boolean comparison.

**Treatment**: flagged via `flag_response_anomaly`; values left untouched (not nulled, not
corrected) since there's no way to know which of the two numbers is wrong.

---

### F13 — 674 accounts created after their own ticket [LOW]

`account_created_date > ticket_created_date` on 674 rows — an account can't be created
after a ticket that references it already exists.

**Detection**: direct row-wise boolean comparison.

**Treatment**: `tenure_months_calc` nulled and flagged (`tenure_calc_invalid`) for these rows,
since tenure is meaningless when the reference account-creation date is itself invalid for that
ticket.

---

### F14 — 50/53 negative resolutions exactly -24h [LOW]

Of the 53 resolved-before-created rows from F02/F10, 50 have a diff of *exactly* -24
hours. An exact constant repeated across many rows is a systematic-shift signature (e.g. a
date-truncation or timezone-boundary bug), not random data entry error — in a production
setting this class would be recoverable by adding one day back. Documented alongside F02; not
separately corrected in this pipeline (kept flagged via `date_order_invalid`, see F10).

**Detection**: distribution of violation magnitudes, not just the violation count.

**Treatment**: documented as a distinct sub-pattern of F02/F10; no additional mutation beyond
the F10 flagging.

---

### F15 — 43 near-duplicate tickets [LOW]

43 rows are exact duplicates of an earlier row across every column except `ticket_id`
(86 rows total across the 43 pairs) — same customer, same category, same created date,
resolution time matching to two decimal places.

**Detection**: `duplicated()` with the primary key excluded first (with the key included,
duplicate count is always zero by definition, so it must be dropped before checking). Must run
before any order-dependent derived column is created — a cumulative count column (see F16)
breaks exact row equality within a duplicate pair even though the pair is a genuine duplicate.

**Treatment**: flagged via `is_duplicate` (both rows in each pair), never deleted — volume
metrics can filter them out while the duplicate-submission rate itself stays available as an
operational signal (e.g. "customers who double-submit the same ticket").

---

### F16 — `previous_tickets` non-monotonic random fill [LOW]

A running count of a customer's prior tickets must be monotonically increasing when
sorted by ticket date, by definition. Sorting each customer's tickets by
`ticket_created_date` and checking, only 51.7% of customers have a monotonically increasing
`previous_tickets` sequence — for the other 48.3%, this is structurally impossible for a real
running count. Separately, the raw column is suspiciously capped at exactly 0–20 with mean
10.0, and correlates at r = -0.005 with the true ordinal position of a ticket in its customer's
history — both signatures of a random fill rather than a real counter.

**Detection**: per-customer monotonicity check (`groupby` + `is_monotonic_increasing`) +
correlation vs. the true ordinal position.

**Treatment**: demoted to `previous_tickets_unreliable`; rebuilt as
`previous_tickets_calc` = the true ordinal count of a customer's earlier tickets, computed by
sorting on `ticket_created_date` (ticket_id as tiebreak for same-day tickets).

---

### F17 — 60% of accounts show multiple names/emails; account attributes stable [INFO]

3,594 of 5,976 customer IDs (60%) have more than one distinct `customer_name`/
`customer_email` value across their tickets — but `region`, `account_type`, and
`monthly_contract_value` never vary for the same `customer_id` (0 customers with >1 distinct
value on any of these three). This is *not* an error — it's evidence that `customer_name`/
`customer_email` are ticket-level contact fields (whoever filed that particular ticket), not
customer-level identity fields. Recognizing what is NOT a bug matters as much as finding what
is — no fix is applied; these two fields are simply excluded from the customer dimension of any
analysis.

**Detection**: per-`customer_id` groupby + nunique, contrasting a volatile field pair against a
stable one.

**Treatment**: none — informational reclassification only. `customer_name`/`customer_email`
excluded from customer-level (as opposed to ticket-level) analysis.

---

### F18 — Uniform distributions across status/escalation/CSAT: synthetic fingerprint [INFO]

`status` splits ~20% each across 5 values, `escalated` is ~50/50, `csat_score` is
~20% each across 5 star ratings, `priority` is ~25% each across 4 values, `channel` and
`operating_system` show the same pattern. Real operational support data is never this uniform
— e.g. `Closed` should dominate over `Open` in a mature ticket system, and escalation rate
should typically sit well under 15%, not 50%. This is a fingerprint of synthetic/randomly-
generated categorical data. Implication for the rest of this exercise: any commercial insight
derived from these distributions (e.g. "escalation is a major problem") would be an artifact of
the generation process, not a real finding — the value of this dataset for this assessment is
methodological (can the data-quality process be executed correctly), not commercial.

**Detection**: `value_counts(normalize=True)` on each categorical column, checking for
suspiciously flat distributions.

**Treatment**: none — a caution for interpretation, not a data-cleaning action. Recorded so
downstream analysis doesn't over-read distributional "findings" that are actually generation
artifacts.

---

## Trustworthy Skeleton & Conclusion

After all 18 findings, the columns that can be trusted as-is (no rebuild, no demotion,
no flagging required) are: `ticket_id`, `customer_id`, `account_type`, `region`,
`service_area`, `priority`, `status`, `channel`, `operating_system`, and `created_date`
(with the 8 F10-flagged rows excluded from date-dependent calculations). Every headline metric
that matters for a support-operations dashboard — SLA breach, ticket duration, customer tenure,
ticket history depth, and satisfaction — required rebuilding or explicit rescoping from
internally consistent inputs; none of them could be taken from the raw column as provided.

The audit is considered complete not because no further issues could theoretically turn up, but
because every applicable test pattern (dual recordings, lifecycle constraints, entity
stability, row-wise ordering) has been systematically applied against every eligible column
pair — a fixed, repeatable checklist rather than an open-ended search. All 14 treatment rules
derived from these 18 findings are implemented and independently re-verified (via assertions
that re-run on every pipeline execution) in `src/m2_clean.py`.
