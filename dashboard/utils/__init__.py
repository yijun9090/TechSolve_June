"""Shared data loading and filtering for every dashboard page.

Reads data/clean/tickets_analytics_ready.parquet as-is — this module never
writes to it or mutates the source file. All aggregation happens in memory.
"""

from pathlib import Path

import pandas as pd
import streamlit as st


def find_project_root(marker: str = "CLAUDE.md") -> Path:
    p = Path(__file__).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / marker).exists():
            return candidate
    raise FileNotFoundError(f"Could not locate project root (no {marker} found above {p})")


ROOT = find_project_root()
DATA_PATH = ROOT / "data" / "clean" / "tickets_analytics_ready.parquet"

STATUS_ORDER = ["Open", "In Progress", "Pending Customer", "Resolved", "Closed"]
PRIORITY_ORDER = ["Low", "Medium", "High", "Urgent"]
RESOLVED_STATUSES = ["Resolved", "Closed"]

COLOR_PRIMARY = "#2563EB"
COLOR_ACCENT = "#F59E0B"
COLOR_NEUTRAL = "#94A3B8"
COLOR_DANGER = "#DC2626"
COLOR_GOOD = "#16A34A"
CATEGORICAL_PALETTE = ["#2563EB", "#F59E0B", "#16A34A", "#DC2626", "#7C3AED", "#0891B2", "#DB2777", "#65A30D"]


@st.cache_data
def load_data() -> pd.DataFrame:
    df = pd.read_parquet(DATA_PATH)
    df["ticket_created_date"] = pd.to_datetime(df["ticket_created_date"])
    return df


def render_sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Renders the shared sidebar filter set and returns the filtered dataframe.
    Uses widget keys (not local variables) so selections persist as the user
    navigates between pages."""
    st.sidebar.header("Filters")

    valid_dates = df.loc[~df["sentinel_date_flag"], "ticket_created_date"]
    min_d, max_d = valid_dates.min().date(), valid_dates.max().date()
    default_start = max(min_d, pd.Timestamp("2024-01-01").date())

    date_range = st.sidebar.date_input(
        "Date range", value=(default_start, max_d), min_value=min_d, max_value=max_d, key="f_date_range"
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = default_start, max_d

    groups = st.sidebar.multiselect(
        "Category group", sorted(df["category_group"].unique()), key="f_group"
    )
    priorities = st.sidebar.multiselect(
        "Priority", PRIORITY_ORDER, key="f_priority"
    )
    regions = st.sidebar.multiselect(
        "Region", sorted(df["region"].unique()), key="f_region"
    )
    teams = st.sidebar.multiselect(
        "Team", sorted(df["team"].unique()), key="f_team"
    )
    account_types = st.sidebar.multiselect(
        "Account type", sorted(df["account_type"].unique()), key="f_account_type"
    )

    st.sidebar.divider()
    exclude_dupes = st.sidebar.checkbox("Exclude duplicate submissions", value=True, key="f_exclude_dupes")
    exclude_baddates = st.sidebar.checkbox(
        "Exclude flagged-date rows from date charts", value=True, key="f_exclude_baddates"
    )

    mask = (df["ticket_created_date"].dt.date >= start_date) & (df["ticket_created_date"].dt.date <= end_date)
    if groups:
        mask &= df["category_group"].isin(groups)
    if priorities:
        mask &= df["priority"].isin(priorities)
    if regions:
        mask &= df["region"].isin(regions)
    if teams:
        mask &= df["team"].isin(teams)
    if account_types:
        mask &= df["account_type"].isin(account_types)
    if exclude_dupes:
        mask &= ~df["is_duplicate"]
    if exclude_baddates:
        mask &= ~df["sentinel_date_flag"]

    filtered = df[mask].copy()

    st.sidebar.divider()
    st.sidebar.caption(
        f"{len(filtered):,} of {len(df):,} tickets shown\n\n"
        f"Data quality: {int(df['date_needs_review'].sum())} rows flagged for date "
        f"review, {int(df['is_duplicate'].sum())} duplicate submissions in the full "
        "dataset (see Ops Insights page)."
    )
    return filtered


def sla_breach_rate(df: pd.DataFrame) -> float:
    resolved = df[df["status"].isin(RESOLVED_STATUSES)]
    if len(resolved) == 0:
        return float("nan")
    return resolved["sla_breached_calc"].mean()


def escalation_rate(df: pd.DataFrame) -> float:
    if len(df) == 0:
        return float("nan")
    return (df["escalated"] == "Yes").mean()


def avg_csat(df: pd.DataFrame) -> float:
    return df["csat_valid"].mean()
