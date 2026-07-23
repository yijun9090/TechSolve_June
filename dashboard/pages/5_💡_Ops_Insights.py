import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from utils import CATEGORICAL_PALETTE, COLOR_DANGER, COLOR_PRIMARY, load_data, render_sidebar_filters

st.set_page_config(page_title="Ops Insights — TechSolve", page_icon="💡", layout="wide")
st.title("💡 Additional Insights for Operations")

df_all = load_data()
df = render_sidebar_filters(df_all)
if df.empty:
    st.warning("No tickets match the current filters.")
    st.stop()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Tenure vs. ticket frequency")
    st.caption("`tenure_months_calc` (recomputed; raw `customer_tenure_months` is unreliable, see DQ log R05/F05).")
    tenure_valid = df.dropna(subset=["tenure_months_calc"])
    bins = pd.cut(tenure_valid["tenure_months_calc"], bins=[0, 6, 12, 24, 36, 48, 60, 200])
    by_bin = tenure_valid.groupby(bins, observed=True).size()
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar([str(b) for b in by_bin.index], by_bin.values, color=COLOR_PRIMARY)
    ax.set_ylabel("Tickets")
    ax.set_xlabel("Tenure (months)")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    ax.spines[["top", "right"]].set_visible(False)
    st.pyplot(fig)

with col2:
    st.subheader("CSAT by category group")
    csat_by_grp = df.groupby("category_group")["csat_valid"].mean().sort_values()
    fig2, ax2 = plt.subplots(figsize=(6, 4))
    colors = [COLOR_DANGER if v < csat_by_grp.mean() else COLOR_PRIMARY for v in csat_by_grp.values]
    ax2.barh(csat_by_grp.index, csat_by_grp.values, color=colors)
    ax2.set_xlabel("Avg CSAT (1-5)")
    ax2.spines[["top", "right"]].set_visible(False)
    for i, v in enumerate(csat_by_grp.values):
        ax2.text(v, i, f" {v:.2f}", va="center", fontsize=9)
    st.pyplot(fig2)

st.divider()

st.subheader("Top repeat customers")
st.caption("Ranked by `previous_tickets_calc` (recomputed, monotonic ordinal count) — candidates for account-health follow-up.")
top_repeat = (
    df.sort_values("previous_tickets_calc", ascending=False)
    .drop_duplicates("customer_id")
    [["customer_id", "region", "account_type", "previous_tickets_calc", "tenure_months_calc"]]
    .head(15)
)
st.dataframe(top_repeat, width='stretch', hide_index=True)

st.divider()

k1, k2, k3 = st.columns(3)
with k1:
    dupe_rate = df_all["is_duplicate"].mean()
    st.metric("Duplicate submission rate (full dataset)", f"{dupe_rate:.2%}")
    st.caption("Same ticket submitted twice — a UX/confirmation-feedback signal, not deleted from the data.")
with k2:
    review_rate = df_all["date_needs_review"].mean()
    st.metric("Rows flagged for date review", f"{int(df_all['date_needs_review'].sum()):,}")
    st.caption("Sentinel dates or resolved-before-created rows — flagged, not dropped, per stakeholder decision.")
with k3:
    unassigned_resolved = ((df_all["team"] == "Unassigned") & df_all["status"].isin(["Resolved", "Closed"])).sum()
    st.metric("Resolved tickets with no team on record", f"{unassigned_resolved:,}")
    st.caption("A resolved ticket can't have been resolved by nobody — worth investigating upstream.")

st.divider()

with st.expander("📋 Data quality & methodology notes"):
    st.markdown(
        """
        This dashboard reads `tickets_analytics_ready.parquet` directly and performs
        no cleaning of its own — all cleaning happened upstream in the pipeline
        (`m1_load.py` → `m2_clean.py` → `m3_external.py`), documented in
        `docs/dq-findings.md` and `outputs/dq_log.csv`.

        **Columns this dashboard reads** (trustworthy): `resolution_time_hours`,
        `sla_breached_calc`, `category_group`/`category_clean`, `account_type`,
        `tenure_months_calc`, `previous_tickets_calc`, `csat_valid`,
        `is_national_holiday`/`is_regional_anniversary`/`is_public_holiday`.

        **Columns this dashboard never reads** (demoted as unreliable upstream):
        raw `category`, `customer_segment_unreliable`,
        `customer_tenure_months_unreliable`, `previous_tickets_unreliable`,
        `resolution_notes_unreliable`, `issue_description_unreliable`,
        `sla_breached_source`, `ticket_resolved_date_unreliable`, raw `csat_score`.

        **Default exclusions** (toggle in the sidebar): duplicate submissions
        (`is_duplicate`), and rows flagged `sentinel_date_flag` (corrupted
        placeholder dates from 1970/2099) are excluded from date-based charts.
        """
    )
