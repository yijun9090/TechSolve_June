# TechSolve Assessment — Data Conventions (non-negotiable)

- SLA breach is ALWAYS `sla_breached_calc` (resolution_time_hours > sla_target_hours,
  Resolved/Closed only). The original column, renamed `sla_breached_source`, was verified
  to be unrelated to actual handling time. Never use it for any metric.
- Duration source of truth = `resolution_time_hours`. Never compute durations from
  `ticket_resolved_date`.
- Customer-type source of truth = `account_type`. `customer_segment` is unreliable; never use it.
- Tenure and previous-ticket counts always use the `*_calc` recomputed columns.
- Satisfaction metrics only use `csat_valid`.
- Category hierarchy = `category_group` (5) → `category_clean` (10). `issue_description` is
  independent of category (verified); never use it for classification.
- Mapping changes go in `config/category_mapping.csv` only — never hardcode.
- Every cleaning modification must be recorded in `outputs/dq_log.csv`
  (rule id, description, rows affected, action).
- Each module runs standalone; run its assertions after any change before proceeding.
