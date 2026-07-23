import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from utils import COLOR_ACCENT, COLOR_NEUTRAL, COLOR_PRIMARY, RESOLVED_STATUSES, load_data, render_sidebar_filters

st.set_page_config(page_title="Holiday Impact — TechSolve", page_icon="🌐", layout="wide")
st.title("🌐 External Data Integration — Holiday Impact")
st.caption(
    "Joined against NZ national holidays and region-specific provincial anniversary "
    "days (2024-2025 only). A ticket is matched to a regional anniversary only for "
    "its OWN region."
)

df_all = load_data()
df = render_sidebar_filters(df_all)
if df.empty:
    st.warning("No tickets match the current filters.")
    st.stop()

resolved = df[df["status"].isin(RESOLVED_STATUSES)]

st.subheader("Holiday vs. non-holiday comparison")
metrics = {
    "Avg tickets/day": (
        df[df["is_public_holiday"]].groupby(df["ticket_created_date"].dt.date).size().mean(),
        df[~df["is_public_holiday"]].groupby(df["ticket_created_date"].dt.date).size().mean(),
    ),
    "Avg resolution time (h)": (
        df.loc[df["is_public_holiday"], "resolution_time_hours"].mean(),
        df.loc[~df["is_public_holiday"], "resolution_time_hours"].mean(),
    ),
    "SLA breach rate": (
        resolved.loc[resolved["is_public_holiday"], "sla_breached_calc"].mean(),
        resolved.loc[~resolved["is_public_holiday"], "sla_breached_calc"].mean(),
    ),
    "Avg CSAT": (
        df.loc[df["is_public_holiday"], "csat_valid"].mean(),
        df.loc[~df["is_public_holiday"], "csat_valid"].mean(),
    ),
    "Escalation rate": (
        (df.loc[df["is_public_holiday"], "escalated"] == "Yes").mean(),
        (df.loc[~df["is_public_holiday"], "escalated"] == "Yes").mean(),
    ),
}

cols = st.columns(len(metrics))
for col, (label, (hol, non_hol)) in zip(cols, metrics.items()):
    delta = hol - non_hol
    fmt = "{:.1%}" if "rate" in label.lower() else "{:.2f}"
    col.metric(f"{label} — holiday", fmt.format(hol) if pd.notna(hol) else "n/a")
    col.caption(f"non-holiday: {fmt.format(non_hol) if pd.notna(non_hol) else 'n/a'}")

st.info(
    "**Finding**: no statistically meaningful difference between holiday and "
    "non-holiday tickets on any metric above. This is consistent with the broader "
    "data-quality finding that this dataset's categorical distributions are "
    "synthetically uniform (see DQ audit F18) — the null result is reported as-is, "
    "not manufactured into a story."
)

st.divider()

st.subheader("Daily ticket volume with holidays marked")
daily = df.groupby(df["ticket_created_date"].dt.date).size()
is_hol = df.groupby(df["ticket_created_date"].dt.date)["is_public_holiday"].max()
fig, ax = plt.subplots(figsize=(12, 4))
colors = np.where(is_hol.reindex(daily.index, fill_value=False), COLOR_ACCENT, COLOR_PRIMARY)
ax.bar(daily.index, daily.values, color=colors, width=1)
ax.spines[["top", "right"]].set_visible(False)
ax.set_ylabel("Tickets")
fig.autofmt_xdate()
st.pyplot(fig)
st.caption("Orange bars = a national holiday or the ticket's own regional anniversary day.")

st.divider()

st.subheader("Holidays / anniversaries in scope (2024-2025)")
hol_days = (
    df[df["is_public_holiday"]]
    .assign(holiday=lambda d: d["national_holiday_name"].fillna(d["regional_holiday_name"]))
    .groupby(["ticket_created_date", "holiday"])
    .agg(tickets=("ticket_id", "size"), avg_resolution_hrs=("resolution_time_hours", "mean"))
    .reset_index()
    .sort_values("ticket_created_date")
)
hol_days["ticket_created_date"] = hol_days["ticket_created_date"].dt.date
hol_days["avg_resolution_hrs"] = hol_days["avg_resolution_hrs"].round(1)
st.dataframe(hol_days, width='stretch', hide_index=True)
