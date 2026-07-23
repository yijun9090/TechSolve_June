"""Module 2: Clean raw ticket data — 14-rule pipeline (R01-R14).

Every rule was verified against the raw data before being encoded here (see
docs/dq-findings.md for the full narrative, F01-F18, and
notebooks/TechSolve_Data_Quality.ipynb for the profiling run that produced them).
Outputs:
  - data/clean/tickets_clean.parquet  (cleaned dataset)
  - outputs/dq_log.csv                (one row per rule: rule_id, description,
                                        rows_affected, action)
"""

from pathlib import Path

import pandas as pd

from m1_load import load_raw
from m1_load import run_assertions as run_load_assertions

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "category_mapping.csv"
DQ_LOG_PATH = ROOT / "outputs" / "dq_log.csv"
CLEAN_PATH = ROOT / "data" / "clean" / "tickets_clean.parquet"

RESOLVED_STATUSES = ["Resolved", "Closed"]
PRIORITY_SLA_CANON = {"Urgent": 4, "High": 8, "Medium": 24, "Low": 48}
UNRELIABLE_COLUMNS = [
    "customer_segment",
    "customer_tenure_months",
    "previous_tickets",
    "resolution_notes",
    "issue_description",
]

_dq_entries = []


def log_dq(rule_id: str, description: str, rows_affected: int, action: str) -> None:
    _dq_entries.append(
        {"rule_id": rule_id, "description": description, "rows_affected": rows_affected, "action": action}
    )


def flush_dq_log() -> None:
    log_df = pd.DataFrame(_dq_entries).sort_values("rule_id").reset_index(drop=True)
    DQ_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_df.to_csv(DQ_LOG_PATH, index=False)
    _dq_entries.clear()


def rule_r01_flag_invalid_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Business rule: ticket_resolved_date must be later than ticket_created_date.
    Uses strict '<' (not '<=') because these dates are date-only (no time-of-day
    component, ~550 distinct calendar days across 100k+ rows) — same-day resolution
    is normal and common (6,814 rows), not a violation. Only resolved-before-created
    (53 rows) is a real impossibility. Also flags the 8 known sentinel
    ticket_created_date values (5x 1970-01-01, 3x 2099-12-31) — placeholder/corrupted
    timestamps, not real ticket dates.

    Per stakeholder decision: these rows are NOT dropped. They're tagged for manual
    review so the underlying records stay available for investigation, rather than
    silently disappearing from the dataset."""
    sentinel_mask = df["ticket_created_date"].dt.year.isin([1970, 2099])
    order_invalid_mask = df["ticket_resolved_date"] < df["ticket_created_date"]

    df["sentinel_date_flag"] = sentinel_mask
    df["date_order_invalid"] = order_invalid_mask
    df["date_needs_review"] = sentinel_mask | order_invalid_mask

    n_sentinel = int(sentinel_mask.sum())
    n_order = int(order_invalid_mask.sum())
    n_total = int(df["date_needs_review"].sum())
    flagged_ids = sorted(df.loc[df["date_needs_review"], "ticket_id"].tolist())
    ids_preview = flagged_ids if len(flagged_ids) <= 50 else f"{flagged_ids[:50]} ... ({len(flagged_ids)} total)"
    log_dq(
        "R01", f"Flagged (not dropped) {n_total} rows needing date review: "
        f"{n_sentinel} rows with sentinel ticket_created_date (1970-01-01 or "
        f"2099-12-31), {n_order} rows violating the business rule "
        "ticket_resolved_date > ticket_created_date (strict: same-day resolution is "
        "not a violation given date-only granularity). New columns "
        "sentinel_date_flag, date_order_invalid, date_needs_review added; rows kept "
        f"in the dataset for manual investigation; ticket_ids={ids_preview}", n_total, "flag",
    )
    return df


def rule_r05_flag_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """43 rows are exact duplicates of an earlier row across every column except
    ticket_id (86 rows total across 43 duplicate pairs). Flag both members of each
    pair — do not delete, so duplicate-submission behavior stays analyzable."""
    df = df.sort_values("ticket_id").reset_index(drop=True)
    dup_mask = df.drop(columns=["ticket_id"]).duplicated(keep=False)
    extra_rows = int(df.drop(columns=["ticket_id"]).duplicated(keep="first").sum())
    df["is_duplicate"] = dup_mask
    log_dq(
        "R05", "Flagged is_duplicate=True for rows identical on every column except "
        "ticket_id (43 duplicate pairs / 86 rows flagged; 43 is the count of rows "
        "beyond the first occurrence in each pair). Not dropped, to preserve "
        "duplicate-submission analysis", extra_rows, "flag",
    )
    return df


def rule_r02_r03_category(df: pd.DataFrame) -> pd.DataFrame:
    """32 raw category values are case/format variants of 10 canonical categories
    (e.g. 'BUG', 'bug_report', 'Bug report' -> 'Bug Report'). Map via
    config/category_mapping.csv (stripped before matching) into category_clean (10)
    -> category_group (5). Unmatched values are a hard error, never silently kept.

    issue_description was verified independent of category: each of the 10 template
    sentences spreads ~10% (i.e. uniformly) across all 10 canonical categories, so it
    carries no category signal and must never be used to derive sub-categories."""
    mapping = pd.read_csv(CONFIG_PATH)
    mapping["category_raw"] = mapping["category_raw"].str.strip()

    key = df["category"].astype(str).str.strip()
    before = df["category"]
    df = df.merge(mapping, left_on=key, right_on="category_raw", how="left").drop(columns=["category_raw"])

    unmapped = df["category_clean"].isna()
    if unmapped.any():
        bad = sorted(df.loc[unmapped, "category"].unique().tolist())
        raise ValueError(
            f"Unmapped category values found: {bad}. Add them to config/category_mapping.csv "
            "before proceeding — unmapped categories must never pass silently."
        )

    non_canonical = int((before.astype(str).str.strip() != df["category_clean"]).sum())
    log_dq(
        "R02", "Mapped 32 raw category spellings to 10 canonical values via "
        "config/category_mapping.csv (case/whitespace-insensitive match); new column "
        "category_clean added, original category column kept", non_canonical, "remap",
    )
    log_dq(
        "R03", "Added category_group (5 groups) from the taxonomy defined in "
        "config/category_mapping.csv. issue_description verified statistically "
        "independent of category: each of the 10 template sentences appears in all "
        "10 categories at ~10% each — demoted to issue_description_unreliable (R09), "
        "must not be used to derive sub-categories", len(df), "derive+flag",
    )
    return df


def rule_r04_fix_priority_sla(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical mapping Urgent=4 / High=8 / Medium=24 / Low=48 holds for 99.23% of
    rows. The remaining 779 rows have an sla_target_hours value that belongs to a
    different priority tier, roughly evenly spread across the 3 off-diagonal values
    for each priority — overwrite to the canonical target.

    Certification (see notebook §5.4): touches 293/5,976 customers; mismatch rate is
    near-identical across account_type (0.76% vs 0.80%, no clustering); mismatch
    count correlates at r=0.97 with each customer's total ticket volume (the
    signature of independent per-row noise, not a customer-specific negotiated SLA,
    which would decouple mismatch count from volume); even the highest-volume
    mismatched customer shows its off-diagonal values scattered across all 3 wrong
    options per priority tier, not one consistent alternate mapping. This is
    statistical evidence, not certainty — in production this would be confirmed with
    the account team before overwriting, since bespoke SLAs can't be fully excluded
    from data alone."""
    canonical = df["priority"].map(PRIORITY_SLA_CANON)
    mismatch = df["sla_target_hours"] != canonical
    n = int(mismatch.sum())
    df.loc[mismatch, "sla_target_hours"] = canonical[mismatch]
    log_dq(
        "R04", "Overwrote sla_target_hours to the canonical priority->SLA mapping "
        "(Urgent=4, High=8, Medium=24, Low=48); 779 rows (0.77%) deviated pre-fix, "
        "touching 293/5,976 customers with mismatch count correlating r=0.97 to "
        "customer ticket volume (independent per-row noise, not a customer-specific "
        "SLA) and no account_type clustering — treated as data entry error, not a "
        "real business exception",
        n, "overwrite",
    )
    return df


def rule_r06_sla_breached(df: pd.DataFrame) -> pd.DataFrame:
    """sla_breached is fake: crosstab against (resolution_time_hours >
    sla_target_hours) is flat across all four cells — statistically independent of
    actual handling time. Rename the original column and derive the real flag,
    restricted to Resolved/Closed tickets (using the R04-corrected sla_target_hours)."""
    df = df.rename(columns={"sla_breached": "sla_breached_source"})
    resolved_mask = df["status"].isin(RESOLVED_STATUSES)
    df["sla_breached_calc"] = pd.array([pd.NA] * len(df), dtype="boolean")
    df.loc[resolved_mask, "sla_breached_calc"] = (
        df.loc[resolved_mask, "resolution_time_hours"] > df.loc[resolved_mask, "sla_target_hours"]
    )
    log_dq(
        "R06", "Renamed sla_breached to sla_breached_source (crosstab vs recomputed "
        "breach flag is uniform across cells, confirming it's unrelated to actual "
        "handling time) and derived sla_breached_calc = resolution_time_hours > "
        "sla_target_hours for Resolved/Closed tickets only; NA otherwise",
        int(resolved_mask.sum()), "rename+derive",
    )
    return df


def rule_r07_duration_source(df: pd.DataFrame) -> pd.DataFrame:
    """resolution_time_hours is authoritative for duration. ticket_resolved_date
    correlates at r=0.003 with it, is 100% populated even for tickets that are still
    Open, and has rows where resolved predates created — rename with _unreliable
    suffix so it can never be mistaken for a duration source."""
    diff_hours = (df["ticket_resolved_date"] - df["ticket_created_date"]).dt.total_seconds() / 3600
    corr = diff_hours.corr(df["resolution_time_hours"])
    negative = int((diff_hours < 0).sum())
    open_notna_rate = df.loc[~df["status"].isin(RESOLVED_STATUSES), "ticket_resolved_date"].notna().mean()

    df = df.rename(columns={"ticket_resolved_date": "ticket_resolved_date_unreliable"})
    log_dq(
        "R07", f"Renamed ticket_resolved_date to ticket_resolved_date_unreliable: "
        f"corr with resolution_time_hours = {corr:.4f}, {negative} rows resolved "
        f"before created, {open_notna_rate:.0%} populated for non-Resolved/Closed "
        "tickets. resolution_time_hours is the sole duration source of truth; never "
        "compute durations from this date difference", len(df), "rename",
    )
    return df


def rule_r08_flag_response_anomaly(df: pd.DataFrame) -> pd.DataFrame:
    """14,750 rows have first_response_time_hours > resolution_time_hours — the
    response logged after the resolution. Flag, don't alter values."""
    anomaly = df["first_response_time_hours"] > df["resolution_time_hours"]
    df["flag_response_anomaly"] = anomaly
    log_dq(
        "R08", "Flagged flag_response_anomaly where first_response_time_hours > "
        "resolution_time_hours (response logged after resolution); raw values left "
        "unchanged", int(anomaly.sum()), "flag",
    )
    return df


def rule_r09_demote_unreliable(df: pd.DataFrame) -> pd.DataFrame:
    """Rename known-unreliable columns with an _unreliable suffix so they can't be
    used downstream by accident. Evidence per column:
      - customer_segment: contradicts account_type (9,953 Residential rows labeled
        Corporate segment)
      - customer_tenure_months: 3,625/5,976 customers (61%) have >1 distinct value
        across their own tickets — per-ticket noise, not a stable attribute
      - previous_tickets: capped 0-20, uncorrelated (r=-0.005) with actual ticket
        order; violates monotonicity for 48% of customers (2,887) — a running count
        can never decrease, so the permitted violation rate is zero
      - resolution_notes: only 10 templated strings, each spread evenly across all
        32 raw categories and with near-identical mean resolution_time_hours
        (~120h regardless of note) — no informational content
      - issue_description: independent of category (see R03)
    """
    df = df.rename(columns={c: f"{c}_unreliable" for c in UNRELIABLE_COLUMNS})
    log_dq(
        "R09", "Demoted columns with _unreliable suffix (excluded from downstream "
        "modeling): customer_segment (contradicts account_type on 9,953 rows), "
        "customer_tenure_months (61% of customers have inconsistent per-ticket "
        "values), previous_tickets (r=-0.005 vs actual ticket order, capped 0-20, "
        "violates monotonicity for 48% of customers), resolution_notes (10 templated "
        "strings, uniform across categories/outcomes), issue_description (independent "
        "of category, see R03)", len(df), "rename",
    )
    return df


def rule_r10_tenure_calc(df: pd.DataFrame) -> pd.DataFrame:
    """tenure_months_calc = months(ticket_created_date - account_created_date).
    Invalid (nulled + flagged) when account_created_date postdates
    ticket_created_date (impossible: account created after its own ticket), or when
    ticket_created_date is itself a sentinel value (R01) — a 2099 sentinel would
    otherwise produce a nonsense multi-century tenure."""
    created = df["ticket_created_date"]
    opened = df["account_created_date"]
    invalid = (opened > created) | df["sentinel_date_flag"]
    months = (created.dt.year - opened.dt.year) * 12 + (created.dt.month - opened.dt.month)

    df["tenure_calc_invalid"] = invalid
    df["tenure_months_calc"] = months.where(~invalid)
    n = int(invalid.sum())
    log_dq(
        "R10", "Recomputed tenure_months_calc as months(ticket_created_date - "
        f"account_created_date); {n} rows nulled and flagged via tenure_calc_invalid "
        "(account_created_date postdates ticket_created_date, and/or "
        "ticket_created_date is a R01 sentinel value)",
        n, "derive+flag",
    )
    return df


def rule_r11_previous_tickets_calc(df: pd.DataFrame) -> pd.DataFrame:
    """previous_tickets_calc = cumulative count of a customer's earlier tickets,
    ordered by ticket_created_date (ticket_id as tiebreak for same-day tickets). A
    running count can never decrease, so by construction this rebuild is exactly
    monotonic per customer (verified in run_assertions) — unlike the raw column,
    which violated monotonicity for 48% of customers.

    Caveat: the 8 rows flagged sentinel_date_flag by R01 are kept (not dropped),
    so a sentinel ticket_created_date can distort the ordering position — and
    therefore the count — for that customer's other tickets. This is an accepted
    side effect of choosing to retain rather than drop those rows; check
    date_needs_review before trusting previous_tickets_calc near a flagged row."""
    order = df.sort_values(["customer_id", "ticket_created_date", "ticket_id"])
    seq = order.groupby("customer_id").cumcount()
    df["previous_tickets_calc"] = seq.reindex(df.index)
    log_dq(
        "R11", "Recomputed previous_tickets_calc as the ordinal count of a "
        "customer's prior tickets sorted by ticket_created_date (ticket_id as "
        "tiebreak); by construction this is exactly monotonic per customer, unlike "
        "the raw previous_tickets column which violated monotonicity for 48% of "
        "customers", len(df), "derive",
    )
    return df


def rule_r12_csat_valid(df: pd.DataFrame) -> pd.DataFrame:
    """csat_valid = csat_score where status is Resolved/Closed, else null. Raw
    csat_score is ~98% populated even for unresolved tickets, which isn't plausible
    — a ticket can't be rated before it's finished."""
    resolved_mask = df["status"].isin(RESOLVED_STATUSES)
    df["csat_valid"] = df["csat_score"].where(resolved_mask)
    nulled = int((df["csat_score"].notna() & ~resolved_mask).sum())
    log_dq(
        "R12", "Derived csat_valid = csat_score where status in (Resolved, Closed), "
        "else null; raw csat_score is populated at ~98% even for unresolved "
        "tickets, which is not plausible. Satisfaction metrics must only use "
        "csat_valid", nulled, "derive",
    )
    return df


def rule_r13_unassigned_bucket(df: pd.DataFrame) -> pd.DataFrame:
    """team/assigned_to are jointly null on 2,017 rows. Fill both with
    'Unassigned' rather than leaving null. Note: these 2,017 rows span every
    status roughly evenly, including Resolved and Closed — a ticket can't be
    resolved by nobody, which is itself a data quality contradiction worth
    flagging alongside the fill."""
    joint_null = df["team"].isna() & df["assigned_to"].isna()
    n = int(joint_null.sum())
    resolved_among_null = int((joint_null & df["status"].isin(RESOLVED_STATUSES)).sum())
    df.loc[joint_null, ["team", "assigned_to"]] = "Unassigned"
    log_dq(
        "R13", f"Filled team/assigned_to with 'Unassigned' where both were jointly "
        f"null ({n} rows, spread ~evenly across all 5 statuses). Contradiction: "
        f"{resolved_among_null} of those rows are already status Resolved/Closed "
        "with no team/assignee on record", n, "fill",
    )
    return df


def rule_r14_structural_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """company_name/industry are null for ~97.6%/100% of Residential accounts —
    legitimate structural nulls (individuals don't have a company or industry),
    not missing data. Left untouched; documented only. No imputation anywhere
    in this pipeline."""
    residential = df["account_type"] == "Residential"
    n = int((residential & df["company_name"].isna()).sum())
    log_dq(
        "R14", "Documented (no mutation): company_name/industry null for "
        "~97.6%/100% of Residential-account rows respectively — legitimate "
        "structural nulls (individuals have no company/industry), not missing "
        "data. Left null; no imputation performed anywhere in this pipeline",
        n, "documented_only",
    )
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = rule_r01_flag_invalid_dates(df)
    df = rule_r05_flag_duplicates(df)
    df = rule_r02_r03_category(df)
    df = rule_r04_fix_priority_sla(df)
    df = rule_r06_sla_breached(df)
    df = rule_r07_duration_source(df)
    df = rule_r08_flag_response_anomaly(df)
    df = rule_r09_demote_unreliable(df)
    df = rule_r10_tenure_calc(df)
    df = rule_r11_previous_tickets_calc(df)
    df = rule_r12_csat_valid(df)
    df = rule_r13_unassigned_bucket(df)
    df = rule_r14_structural_nulls(df)
    return df


def run_assertions(df: pd.DataFrame) -> None:
    assert len(df) == 100_851, f"expected 100,851 rows (no rows dropped), got {len(df)}"

    assert df["sentinel_date_flag"].sum() == 8, f"expected 8 sentinel-date rows flagged, got {df['sentinel_date_flag'].sum()}"
    assert df.loc[df["sentinel_date_flag"], "ticket_created_date"].dt.year.isin([1970, 2099]).all(), (
        "sentinel_date_flag rows must actually carry a sentinel year"
    )
    order_check = df["ticket_resolved_date_unreliable"] < df["ticket_created_date"]
    assert (df["date_order_invalid"] == order_check).all(), "date_order_invalid out of sync with its own rule"
    assert (df["date_needs_review"] == (df["sentinel_date_flag"] | df["date_order_invalid"])).all(), (
        "date_needs_review must be the OR of sentinel_date_flag and date_order_invalid"
    )

    assert df["is_duplicate"].sum() == 86, f"expected 86 rows flagged as duplicates, got {df['is_duplicate'].sum()}"

    assert df["category_clean"].nunique() == 10, f"expected 10 category_clean values, got {df['category_clean'].nunique()}"
    assert df["category_group"].nunique() == 5, f"expected 5 category_group values, got {df['category_group'].nunique()}"
    assert df["category_clean"].notna().all(), "unmapped category values"

    canonical = df["priority"].map(PRIORITY_SLA_CANON)
    assert (df["sla_target_hours"] == canonical).all(), "sla_target_hours not fully conformed to canonical mapping"

    assert "sla_breached_source" in df.columns, "sla_breached_source missing"
    unresolved_mask = ~df["status"].isin(RESOLVED_STATUSES)
    assert df.loc[unresolved_mask, "sla_breached_calc"].isna().all(), "sla_breached_calc must be NA for unresolved tickets"

    assert "ticket_resolved_date_unreliable" in df.columns, "ticket_resolved_date not demoted"

    for col in UNRELIABLE_COLUMNS:
        assert f"{col}_unreliable" in df.columns, f"{col} not demoted"

    assert (df["tenure_months_calc"].dropna() >= 0).all(), "negative tenure_months_calc"
    assert df.loc[df["tenure_calc_invalid"], "tenure_months_calc"].isna().all(), "invalid tenure rows should be null"
    assert df.loc[df["sentinel_date_flag"], "tenure_calc_invalid"].all(), (
        "sentinel-date rows must also be marked tenure_calc_invalid"
    )

    assert (df["previous_tickets_calc"] >= 0).all(), "negative previous_tickets_calc"
    mono = (
        df.sort_values(["customer_id", "ticket_created_date", "ticket_id"])
        .groupby("customer_id")["previous_tickets_calc"]
        .apply(lambda s: s.is_monotonic_increasing)
    )
    assert mono.all(), "previous_tickets_calc must be monotonically increasing per customer by construction"

    valid_csat = df["csat_valid"].notna()
    assert df.loc[valid_csat, "status"].isin(RESOLVED_STATUSES).all(), "csat_valid set on a non-Resolved/Closed ticket"

    assert df["team"].isna().sum() == 0, "team still has nulls after Unassigned fill"
    assert df["assigned_to"].isna().sum() == 0, "assigned_to still has nulls after Unassigned fill"

    assert len(df.columns) == 48, f"expected 48 columns, got {len(df.columns)}"


if __name__ == "__main__":
    raw = load_raw()
    run_load_assertions(raw)
    cleaned = clean(raw)
    run_assertions(cleaned)

    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_parquet(CLEAN_PATH, index=False)
    flush_dq_log()

    print(f"Cleaned {len(cleaned)} rows, {len(cleaned.columns)} columns")
    print(f"Clean dataset written to {CLEAN_PATH}")
    print(f"DQ log written to {DQ_LOG_PATH} ({len(pd.read_csv(DQ_LOG_PATH))} rules)")
