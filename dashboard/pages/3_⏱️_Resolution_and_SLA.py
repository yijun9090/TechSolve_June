import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from utils import COLOR_DANGER, COLOR_GOOD, COLOR_PRIMARY, PRIORITY_ORDER, RESOLVED_STATUSES, load_data, render_sidebar_filters, sla_breach_rate

st.set_page_config(page_title="Resolution & SLA — TechSolve", page_icon="⏱️", layout="wide")
st.title("⏱️ Time to Resolution Analysis")
st.caption("Resolution performance and SLA compliance. Duration source of truth: `resolution_time_hours`.")

df_all = load_data()
df = render_sidebar_filters(df_all)
if df.empty:
    st.warning("No tickets match the current filters.")
    st.stop()

resolved = df[df["status"].isin(RESOLVED_STATUSES)]

k1, k2, k3 = st.columns(3)
k1.metric("Avg resolution time", f"{df['resolution_time_hours'].mean():.1f} h")
k2.metric("Median resolution time", f"{df['resolution_time_hours'].median():.1f} h")
k3.metric("SLA breach rate (Resolved/Closed)", f"{sla_breach_rate(df):.1%}")

st.divider()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Resolution time distribution by priority")
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    data = [df.loc[df["priority"] == p, "resolution_time_hours"].dropna() for p in PRIORITY_ORDER if p in df["priority"].unique()]
    labels = [p for p in PRIORITY_ORDER if p in df["priority"].unique()]
    ax.hist(data, bins=20, stacked=True, label=labels, color=["#16A34A", "#F59E0B", "#EA580C", "#DC2626"][: len(labels)])
    ax.set_xlabel("Resolution time (hours)")
    ax.set_ylabel("Tickets")
    ax.legend(fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    st.pyplot(fig)

with col2:
    st.subheader("SLA breach rate by priority")
    breach = resolved.groupby("priority")["sla_breached_calc"].mean().reindex(PRIORITY_ORDER).dropna()
    fig2, ax2 = plt.subplots(figsize=(6.5, 4.5))
    colors = [COLOR_DANGER if v > 0.5 else COLOR_GOOD for v in breach.values]
    ax2.bar(breach.index, breach.values, color=colors)
    ax2.axhline(breach.mean(), color="black", linestyle="--", linewidth=1, label="overall avg")
    ax2.set_ylabel("SLA breach rate")
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.legend(fontsize=8)
    for i, v in enumerate(breach.values):
        ax2.text(i, v, f" {v:.1%}", ha="center", va="bottom", fontsize=9)
    st.pyplot(fig2)

st.divider()

col3, col4 = st.columns(2)

with col3:
    st.subheader("SLA breach rate trend (monthly)")
    monthly_breach = (
        resolved.assign(month=resolved["ticket_created_date"].dt.to_period("M").dt.to_timestamp())
        .groupby("month")["sla_breached_calc"]
        .mean()
    )
    fig3, ax3 = plt.subplots(figsize=(6.5, 4))
    ax3.plot(monthly_breach.index, monthly_breach.values, marker="o", color=COLOR_PRIMARY)
    ax3.set_ylabel("SLA breach rate")
    ax3.spines[["top", "right"]].set_visible(False)
    fig3.autofmt_xdate()
    st.pyplot(fig3)

with col4:
    st.subheader("Resolution time by team")
    by_team = df.groupby("team")["resolution_time_hours"].apply(list)
    fig4, ax4 = plt.subplots(figsize=(6.5, 4))
    ax4.boxplot(by_team.values, tick_labels=by_team.index, showfliers=False)
    ax4.set_ylabel("Resolution time (hours)")
    ax4.spines[["top", "right"]].set_visible(False)
    plt.setp(ax4.get_xticklabels(), rotation=20, ha="right")
    st.pyplot(fig4)

st.divider()

anomaly_n = int(df["flag_response_anomaly"].sum())
st.warning(
    f"**Data caveat**: {anomaly_n:,} tickets in the current filter ({anomaly_n / len(df):.1%}) have "
    "`first_response_time_hours` logged *after* `resolution_time_hours` — a data artifact, not a real "
    "operational pattern. First-response and resolution metrics are reported separately above rather "
    "than compared per-ticket, to avoid amplifying this anomaly."
)
