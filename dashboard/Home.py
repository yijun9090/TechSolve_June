"""TechSolve Support Ticket Dashboard — Overview.

Run with: streamlit run dashboard/Home.py
"""

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from utils import (
    COLOR_ACCENT,
    COLOR_PRIMARY,
    RESOLVED_STATUSES,
    avg_csat,
    escalation_rate,
    load_data,
    render_sidebar_filters,
    sla_breach_rate,
)

st.set_page_config(page_title="TechSolve Support Dashboard", page_icon="🎫", layout="wide")

st.title("🎫 TechSolve Support Ticket Dashboard")
st.caption("Support operations overview — 2024-2025. Source: `tickets_analytics_ready.parquet` (analytics-ready, pre-cleaned).")

df_all = load_data()
df = render_sidebar_filters(df_all)

if df.empty:
    st.warning("No tickets match the current filters.")
    st.stop()

# ---------------------------------------------------------------- KPI row
backlog = df[~df["status"].isin(RESOLVED_STATUSES)]

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Total tickets", f"{len(df):,}")
k2.metric("Avg resolution time", f"{df['resolution_time_hours'].mean():.1f} h")
k3.metric("SLA breach rate", f"{sla_breach_rate(df):.1%}")
k4.metric("Avg CSAT", f"{avg_csat(df):.2f} / 5")
k5.metric("Escalation rate", f"{escalation_rate(df):.1%}")
k6.metric("Current backlog", f"{len(backlog):,}")

st.divider()

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Daily ticket volume")
    daily = df.groupby(df["ticket_created_date"].dt.date).size()
    holidays_daily = df.groupby(df["ticket_created_date"].dt.date)["is_public_holiday"].max()

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(daily.index, daily.values, color=COLOR_PRIMARY, linewidth=1.2)
    holiday_days = holidays_daily[holidays_daily].index
    for d in holiday_days:
        ax.axvline(d, color=COLOR_ACCENT, alpha=0.35, linewidth=1)
    ax.set_ylabel("Tickets")
    ax.set_xlabel("")
    ax.spines[["top", "right"]].set_visible(False)
    fig.autofmt_xdate()
    st.pyplot(fig)
    st.caption("Orange lines mark national holidays / regional anniversary days in scope.")

with col2:
    st.subheader("Volume by category group")
    grp = df["category_group"].value_counts()
    fig2, ax2 = plt.subplots(figsize=(5, 4))
    ax2.barh(grp.index[::-1], grp.values[::-1], color=COLOR_PRIMARY)
    ax2.spines[["top", "right"]].set_visible(False)
    for i, v in enumerate(grp.values[::-1]):
        ax2.text(v, i, f" {v:,}", va="center", fontsize=9)
    st.pyplot(fig2)

st.divider()
st.info(
    "Use the sidebar to filter by date range, category, priority, region, team, and "
    "account type. Duplicate submissions and date-quality-flagged rows are excluded "
    "by default — see **Ops Insights** for details."
)
