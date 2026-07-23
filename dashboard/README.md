# TechSolve Support Ticket Dashboard — User Guide

A dashboard for reviewing support ticket performance: what customers are contacting
support about, how the queue is being handled, how fast tickets get resolved, and
where operations should focus attention next. Covers **2024–2025** ticket data by
default (2023 data is also available if you widen the date filter).

## Opening the dashboard

If it's not already running, start it from the project folder:

```
python -m streamlit run dashboard/Home.py
```

Then open the link it prints — usually **http://localhost:8501** — in your browser.
(If `streamlit` doesn't work as a bare command in your terminal, use `python -m streamlit`
as shown above.)

## Pages

Use the sidebar on the left to move between pages:

| Page | What it shows |
|---|---|
| 🏠 **Overview** (Home) | Headline KPIs (ticket volume, resolution time, SLA breach rate, CSAT, escalation rate, current backlog), a daily volume trend with holidays marked, and a category breakdown |
| 🗂️ **Ticket Issues** | What customers are contacting support about — category breakdown, drill-down into sub-categories, trend over time, and how issue types relate to priority and region |
| 📊 **Status and Workload** | Where tickets currently stand (Open/In Progress/Pending/Resolved/Closed), escalation rates by team, team workload, and the oldest unresolved tickets |
| ⏱️ **Resolution and SLA** | How long tickets take to resolve, SLA breach rates by priority/team, and trends over time |
| 🌐 **Holiday Impact** | Whether NZ public holidays or regional anniversary days affect ticket volume or performance (spoiler: in this dataset, they don't meaningfully — see the note on that page) |
| 💡 **Ops Insights** | Repeat customers, satisfaction by category, and a data-quality summary (what's excluded from the numbers above and why) |
| 🤖 **AI Agent** | Ask questions about the ticket data in plain English — see below |

## Filters (sidebar)

The same filter panel appears on every page and applies everywhere at once — set it
once, it stays applied as you switch pages:

- **Date range** — defaults to 2024 onward; widen it to include 2023 data
- **Category group, Priority, Region, Team, Account type** — narrow down to a slice
- **Exclude duplicate submissions** (on by default) — some tickets were submitted twice
  by mistake; this keeps them from double-counting your volume numbers
- **Exclude flagged-date rows** (on by default) — a small number of tickets (8) have
  corrupted dates and would break the time-based charts if included

The sidebar always shows how many tickets are currently in view out of the total.

## Using the AI Operations Assistant (🤖 AI Agent page)

Type a question in plain English about the tickets currently in view, or click one of
the four example questions to try it immediately:

- *What are the top ticket issues?*
- *Which issues have the longest resolution time?*
- *How has ticket volume changed?*
- *What operational improvements should we consider?*

The assistant reads the same filtered data the rest of the dashboard is showing — if
you've filtered down to one team or one quarter, it answers about that slice, not the
whole dataset. It analyses the data live (it does not have a fixed script of answers),
so you can ask follow-up questions or phrase things your own way.

**A few things to know:**
- Answers can take **10 seconds to a couple of minutes** — simple questions ("top
  issues") are quick; broad ones ("give recommendations") take longer because it's
  genuinely running the analysis, not looking up a cached answer. A spinner shows
  while it's working — let it finish.
- If it can't complete a question, it says so clearly rather than guessing — try
  rephrasing or asking something more specific.
- It only uses the ticket data — it won't invent numbers that aren't in the dataset.
- The assistant needs a Claude API key configured to work (see below) — if you see an
  error about a missing key when opening this page, that's what's missing.

### First-time setup (one-time only)

If the AI Agent page shows "Couldn't start the AI assistant":

1. Copy `.env.example` (in the project root) to a new file named `.env`
2. Open `.env` and paste your Claude API key after `CLAUDE_API_KEY=`
3. Reload the page

## A note on data trust

This dashboard reads from an already-cleaned dataset
(`data/clean/tickets_analytics_ready.parquet`) where known data-quality issues were
already identified and handled — inconsistent category spellings, a fake SLA-breach
flag, unreliable satisfaction scores on unresolved tickets, and more. The full
writeup of what was found and how it was handled is in
[`docs/dq-findings.md`](../docs/dq-findings.md). You don't need to read that to use
the dashboard — it's there if you want to understand *why* a number is calculated the
way it is.
