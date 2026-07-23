import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from utils import CATEGORICAL_PALETTE, COLOR_DANGER, COLOR_PRIMARY, RESOLVED_STATUSES, STATUS_ORDER, load_data, render_sidebar_filters

st.set_page_config(page_title="Status & Workload — TechSolve", page_icon="📊", layout="wide")
st.title("📊 Ticket Status Reporting")
st.caption("Where tickets stand right now, and who's carrying the load.")

df_all = load_data()
df = render_sidebar_filters(df_all)
if df.empty:
    st.warning("No tickets match the current filters.")
    st.stop()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Status distribution")
    counts = df["status"].value_counts().reindex(STATUS_ORDER).fillna(0)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(counts.index, counts.values, color=CATEGORICAL_PALETTE[: len(counts)])
    ax.spines[["top", "right"]].set_visible(False)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    ax.set_ylabel("Tickets")
    st.pyplot(fig)

with col2:
    st.subheader("Escalation rate by team")
    esc = df.groupby("team")["escalated"].apply(lambda s: (s == "Yes").mean()).sort_values()
    fig2, ax2 = plt.subplots(figsize=(6, 4))
    ax2.barh(esc.index, esc.values, color=COLOR_DANGER)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.set_xlabel("Escalation rate")
    for i, v in enumerate(esc.values):
        ax2.text(v, i, f" {v:.1%}", va="center", fontsize=9)
    st.pyplot(fig2)

st.divider()

st.subheader("Workload: status by team")
pivot = pd.crosstab(df["team"], df["status"])[
    [s for s in STATUS_ORDER if s in df["status"].unique()]
]
fig3, ax3 = plt.subplots(figsize=(10, 4.5))
bottom = None
import numpy as np
bottom = np.zeros(len(pivot))
for i, col in enumerate(pivot.columns):
    ax3.barh(pivot.index, pivot[col], left=bottom, label=col, color=CATEGORICAL_PALETTE[i % len(CATEGORICAL_PALETTE)])
    bottom += pivot[col].values
ax3.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
ax3.spines[["top", "right"]].set_visible(False)
st.pyplot(fig3)

st.divider()

st.subheader("Backlog aging (Open / In Progress / Pending Customer)")
backlog = df[~df["status"].isin(RESOLVED_STATUSES)].copy()
report_date = df["ticket_created_date"].max()
backlog["days_open"] = (report_date - backlog["ticket_created_date"]).dt.days
backlog = backlog.sort_values("days_open", ascending=False)
st.caption(f"Aged as of the latest date in the filtered data ({report_date.date()}).")
st.dataframe(
    backlog[["ticket_id", "customer_id", "status", "priority", "team", "category_clean", "days_open"]].head(25),
    width='stretch',
    hide_index=True,
)

st.divider()

st.subheader("Unassigned contradiction")
contradiction = df[(df["team"] == "Unassigned") & (df["status"].isin(RESOLVED_STATUSES))]
st.metric("Resolved/Closed tickets with no team on record", f"{len(contradiction):,}")
st.caption(
    "A ticket can't be resolved by nobody — this count comes from the R13 cleaning "
    "rule's null-fill and is a genuine data-quality contradiction worth investigating, "
    "not a dashboard bug."
)
