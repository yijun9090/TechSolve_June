# TechSolve Support Ticket Analytics

An end-to-end pipeline and dashboard for TechSolve's support ticket data: raw data is
audited for quality issues, cleaned and enriched against documented rules, then served
through a Streamlit dashboard with an AI Operations Assistant for natural-language
Q&A over the results.

## Pipeline

```
data/raw/TechSolve-Ticket_Data.xlsx
        │
        ▼
src/m1_load.py     — structural validation (row/column counts, primary key, ID format)
        │
        ▼
src/m2_clean.py    — 14 cleaning rules (R01-R14): fixes/flags issues found during
        │             the data-quality audit; never silently drops data — see
        │             docs/dq-findings.md for what was found and why each rule
        │             does what it does
        ▼
src/m3_external.py — joins NZ public holiday + regional anniversary data,
        │             confirms the reporting category hierarchy
        ▼
data/clean/tickets_analytics_ready.parquet   ← the trusted, analytics-ready dataset
        │
        ▼
dashboard/          — Streamlit dashboard + AI Operations Assistant (Claude + LangChain)
```

Every cleaning/enrichment action is logged with a row count in
[`outputs/dq_log.csv`](outputs/dq_log.csv). The full narrative — what was found, how
it was verified, and why each fix was made — is in
[`docs/dq-findings.md`](docs/dq-findings.md). The original audit notebook is in
[`notebooks/TechSolve_Data_Quality.ipynb`](notebooks/TechSolve_Data_Quality.ipynb).

## Dashboard

See **[`dashboard/README.md`](dashboard/README.md)** for the full user guide (how to
run it, what each page shows, how to use the AI assistant).

Quick start:

```bash
pip install -r requirements.txt
cp .env.example .env   # then add your Claude API key
python -m streamlit run dashboard/Home.py
```

## Project layout

| Folder | Contents |
|---|---|
| `data/raw/` | Original ticket data + NZ holiday/anniversary reference files |
| `data/clean/` | Pipeline outputs — `tickets_clean.parquet` (M2) and `tickets_analytics_ready.parquet` (M3, final) |
| `data/external/` | NZ national holidays and regional anniversary calendars |
| `config/category_mapping.csv` | Maintainable mapping: 32 raw category spellings → 10 canonical categories → 5 groups |
| `src/` | The three pipeline modules (`m1_load.py`, `m2_clean.py`, `m3_external.py`) |
| `docs/dq-findings.md` | Full data-quality audit writeup (18 findings, F01-F18) |
| `notebooks/` | The profiling/discovery notebook that produced the findings |
| `outputs/` | `dq_log.csv` (machine-readable audit trail) and raw-data profile |
| `dashboard/` | Streamlit app: 6 analysis pages + AI Operations Assistant |

## Data conventions

Non-negotiable rules for which columns are trustworthy are documented in
[`CLAUDE.md`](CLAUDE.md) — e.g. `resolution_time_hours` (never
`ticket_resolved_date`), `sla_breached_calc` (never the raw `sla_breached`),
`category_group`/`category_clean` (never raw `category`). Every module downstream of
M2 follows these.
