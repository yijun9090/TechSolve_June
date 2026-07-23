import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from utils import CATEGORICAL_PALETTE, COLOR_PRIMARY, PRIORITY_ORDER, load_data, render_sidebar_filters

st.set_page_config(page_title="Ticket Issues — TechSolve", page_icon="🗂️", layout="wide")
st.title("🗂️ Ticket Issues Analysis")
st.caption("What customers are actually contacting support about.")

df_all = load_data()
df = render_sidebar_filters(df_all)
if df.empty:
    st.warning("No tickets match the current filters.")
    st.stop()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Volume by category group (top level)")
    grp = df["category_group"].value_counts()
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(grp.index, grp.values, color=CATEGORICAL_PALETTE[: len(grp)])
    ax.set_ylabel("Tickets")
    ax.spines[["top", "right"]].set_visible(False)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    st.pyplot(fig)

with col2:
    st.subheader("Drill down: sub-category")
    group_choice = st.selectbox("Category group", sorted(df["category_group"].unique()))
    sub = df[df["category_group"] == group_choice]["category_clean"].value_counts()
    fig2, ax2 = plt.subplots(figsize=(6, 4))
    ax2.barh(sub.index[::-1], sub.values[::-1], color=COLOR_PRIMARY)
    ax2.spines[["top", "right"]].set_visible(False)
    for i, v in enumerate(sub.values[::-1]):
        ax2.text(v, i, f" {v:,}", va="center", fontsize=9)
    st.pyplot(fig2)

st.divider()

st.subheader("Category volume trend over time (monthly)")
monthly = (
    df.assign(month=df["ticket_created_date"].dt.to_period("M").dt.to_timestamp())
    .groupby(["month", "category_group"])
    .size()
    .unstack(fill_value=0)
)
fig3, ax3 = plt.subplots(figsize=(12, 4.5))
bottom = np.zeros(len(monthly))
for i, col in enumerate(monthly.columns):
    ax3.bar(monthly.index, monthly[col], bottom=bottom, label=col, color=CATEGORICAL_PALETTE[i % len(CATEGORICAL_PALETTE)], width=20)
    bottom += monthly[col].values
ax3.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
ax3.spines[["top", "right"]].set_visible(False)
ax3.set_ylabel("Tickets")
fig3.autofmt_xdate()
st.pyplot(fig3)

st.divider()

col3, col4 = st.columns(2)

with col3:
    st.subheader("Sub-category × priority")
    pivot = pd.crosstab(df["category_clean"], df["priority"])[
        [p for p in PRIORITY_ORDER if p in df["priority"].unique()]
    ]
    fig4, ax4 = plt.subplots(figsize=(6, 5))
    im = ax4.imshow(pivot.values, cmap="Blues", aspect="auto")
    ax4.set_xticks(range(len(pivot.columns)))
    ax4.set_xticklabels(pivot.columns, rotation=30, ha="right")
    ax4.set_yticks(range(len(pivot.index)))
    ax4.set_yticklabels(pivot.index)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            ax4.text(j, i, pivot.values[i, j], ha="center", va="center", fontsize=8)
    fig4.colorbar(im, ax=ax4, shrink=0.7, label="Tickets")
    st.pyplot(fig4)

with col4:
    st.subheader("Category group × region")
    pivot2 = pd.crosstab(df["region"], df["category_group"])
    st.dataframe(pivot2, width='stretch')
