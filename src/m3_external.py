"""Module 3: External data enrichment + reporting-category finalization.

Joins the M2-cleaned ticket dataset against two NZ calendar reference files:
  - data/external/nz_holidays_national.xlsx   (18 rows: date, holiday_name)
  - data/external/nz_region_anniversaries.xlsx (24 rows: region, date, holiday_name)

and confirms the category_group(5) -> category_clean(10) hierarchy (built in M2)
is intact and reporting-ready. Outputs:
  - data/clean/tickets_analytics_ready.parquet + .csv (enriched dataset)
  - outputs/dq_log.csv  (appends E01-E04 to the existing R01-R14 entries from M2 —
                          never overwrites them; each module runs standalone)
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEAN_PATH = ROOT / "data" / "clean" / "tickets_clean.parquet"
HOLIDAYS_PATH = ROOT / "data" / "external" / "nz_holidays_national.xlsx"
ANNIVERSARIES_PATH = ROOT / "data" / "external" / "nz_region_anniversaries.xlsx"
OUT_PARQUET = ROOT / "data" / "clean" / "tickets_analytics_ready.parquet"
OUT_CSV = ROOT / "data" / "clean" / "tickets_analytics_ready.csv"
DQ_LOG_PATH = ROOT / "outputs" / "dq_log.csv"

EXPECTED_CATEGORY_GROUPS = 5
EXPECTED_CATEGORY_CLEAN = 10
HOLIDAY_SCOPE_YEARS = [2024, 2025]

_dq_entries = []


def log_dq(rule_id: str, description: str, rows_affected: int, action: str) -> None:
    _dq_entries.append(
        {"rule_id": rule_id, "description": description, "rows_affected": rows_affected, "action": action}
    )


def flush_dq_log() -> None:
    """Append this module's entries to dq_log.csv without clobbering M2's R01-R14
    rows. Rerunning replaces this module's own prior entries (by rule_id) rather
    than duplicating them, so the module stays safely re-runnable on its own."""
    new_entries = pd.DataFrame(_dq_entries)
    if DQ_LOG_PATH.exists():
        existing = pd.read_csv(DQ_LOG_PATH)
        existing = existing[~existing["rule_id"].isin(new_entries["rule_id"])]
        combined = pd.concat([existing, new_entries], ignore_index=True)
    else:
        combined = new_entries
    combined = combined.sort_values("rule_id").reset_index(drop=True)
    DQ_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(DQ_LOG_PATH, index=False)
    _dq_entries.clear()


def load_clean() -> pd.DataFrame:
    return pd.read_parquet(CLEAN_PATH)


def load_holidays() -> pd.DataFrame:
    return pd.read_excel(HOLIDAYS_PATH)


def load_anniversaries() -> pd.DataFrame:
    return pd.read_excel(ANNIVERSARIES_PATH)


def rule_e01_national_holidays(df: pd.DataFrame, holidays: pd.DataFrame) -> pd.DataFrame:
    """Flag tickets created on an NZ national public holiday. Scoped to 2024-2025
    only (per stakeholder decision) — the source file also has 4 rows from 2023
    (Matariki, Labour Day, Christmas Day, Boxing Day) which are excluded here.
    Join key is the calendar date only (ticket_created_date is already date-only,
    no time component). sentinel_date_flag rows (R01) naturally never match, since
    1970/2099 aren't in the holiday table."""
    holidays = holidays[holidays["date"].dt.year.isin(HOLIDAY_SCOPE_YEARS)]
    created = df["ticket_created_date"].dt.normalize()
    hit = created.isin(holidays["date"])
    name_map = holidays.set_index("date")["holiday_name"]
    df["is_national_holiday"] = hit
    df["national_holiday_name"] = created.map(name_map).where(hit)

    n = int(hit.sum())
    log_dq(
        "E01", f"Flagged is_national_holiday where ticket_created_date matches "
        f"data/external/nz_holidays_national.xlsx, scoped to {HOLIDAY_SCOPE_YEARS} "
        f"only ({len(holidays)}/18 source dates used; 4 rows from 2023 excluded per "
        "stakeholder decision). national_holiday_name added for matched rows. "
        "Holiday table doesn't cover the 10 stray Mar-2025 rows (see F10) — those "
        "cannot be flagged and are left False, not imputed", n, "derive",
    )
    return df


def rule_e02_regional_anniversaries(df: pd.DataFrame, anniversaries: pd.DataFrame) -> pd.DataFrame:
    """Flag tickets created on their OWN region's provincial anniversary day (not
    any region's — a ticket from Auckland shouldn't be flagged for Wellington's
    anniversary). Scoped to 2024-2025 only, same as E01 (source file is already
    2024/2025-only, so this filter is a no-op here — kept for explicitness and
    consistency with E01, in case the source file ever gains other years). Join
    key is (region, date)."""
    anniversaries = anniversaries[anniversaries["date"].dt.year.isin(HOLIDAY_SCOPE_YEARS)]
    created = df["ticket_created_date"].dt.normalize()
    ann_pairs = set(zip(anniversaries["region"], anniversaries["date"]))
    name_lookup = anniversaries.set_index(["region", "date"])["holiday_name"]

    keys = list(zip(df["region"], created))
    hit = pd.Series([k in ann_pairs for k in keys], index=df.index)
    names = pd.Series(
        [name_lookup.get(k) for k in keys], index=df.index
    ).where(hit)

    df["is_regional_anniversary"] = hit
    df["regional_holiday_name"] = names

    n = int(hit.sum())
    log_dq(
        "E02", f"Flagged is_regional_anniversary where (region, ticket_created_date) "
        f"matches data/external/nz_region_anniversaries.xlsx, scoped to "
        f"{HOLIDAY_SCOPE_YEARS} ({len(anniversaries)}/24 source rows used — source "
        "file was already 2024/2025-only, filter is a no-op but kept for "
        "explicitness) across the same 12 regions present in the ticket data. "
        "Matched strictly on the ticket's own region — a ticket is never flagged "
        "for another region's anniversary. "
        "regional_holiday_name added for matched rows", n, "derive",
    )
    return df


def rule_e03_public_holiday_combined(df: pd.DataFrame) -> pd.DataFrame:
    """is_public_holiday = national OR own-region anniversary. The two calendars
    are disjoint in this data (0 rows match both on the same date), so this is a
    simple OR with no double-counting to worry about."""
    df["is_public_holiday"] = df["is_national_holiday"] | df["is_regional_anniversary"]
    overlap = int((df["is_national_holiday"] & df["is_regional_anniversary"]).sum())
    n = int(df["is_public_holiday"].sum())
    log_dq(
        "E03", f"Derived is_public_holiday = is_national_holiday OR "
        f"is_regional_anniversary; the two source calendars are disjoint in this "
        f"data ({overlap} same-date overlaps found)", n, "derive",
    )
    return df


def rule_e04_confirm_category_hierarchy(df: pd.DataFrame) -> pd.DataFrame:
    """No mutation — certifies the category_group(5) -> category_clean(10)
    hierarchy built in M2 (R02/R03) is intact and reporting-ready: every
    category_clean value rolls up to exactly one category_group, and the counts
    match the CLAUDE.md convention (5 groups, 10 sub-categories)."""
    n_groups = df["category_group"].nunique()
    n_clean = df["category_clean"].nunique()
    rollup = df.groupby("category_clean")["category_group"].nunique()
    assert n_groups == EXPECTED_CATEGORY_GROUPS, f"expected {EXPECTED_CATEGORY_GROUPS} category_group values, got {n_groups}"
    assert n_clean == EXPECTED_CATEGORY_CLEAN, f"expected {EXPECTED_CATEGORY_CLEAN} category_clean values, got {n_clean}"
    assert (rollup == 1).all(), "a category_clean value rolls up to more than one category_group"

    log_dq(
        "E04", f"Confirmed reporting-ready category hierarchy: category_group "
        f"({n_groups}) -> category_clean ({n_clean}), every sub-category rolls up "
        "to exactly one top-level group. No mutation — this hierarchy was built in "
        "M2 (R02/R03); this rule only certifies it for reporting use", len(df), "documented_only",
    )
    return df


def transform(df: pd.DataFrame, holidays: pd.DataFrame, anniversaries: pd.DataFrame) -> pd.DataFrame:
    df = rule_e01_national_holidays(df, holidays)
    df = rule_e02_regional_anniversaries(df, anniversaries)
    df = rule_e03_public_holiday_combined(df)
    df = rule_e04_confirm_category_hierarchy(df)
    return df


def run_assertions(df: pd.DataFrame) -> None:
    assert len(df) == 100_851, f"expected 100,851 rows (enrichment must not drop/add rows), got {len(df)}"

    assert df["is_national_holiday"].sum() > 0, "no national holiday matches found — check date alignment"
    assert df.loc[df["is_national_holiday"], "national_holiday_name"].notna().all(), (
        "is_national_holiday=True rows must have a holiday name"
    )
    assert df.loc[~df["is_national_holiday"], "national_holiday_name"].isna().all(), (
        "is_national_holiday=False rows must not have a holiday name"
    )

    assert df["is_regional_anniversary"].sum() > 0, "no regional anniversary matches found — check region/date alignment"
    assert df.loc[df["is_regional_anniversary"], "regional_holiday_name"].notna().all(), (
        "is_regional_anniversary=True rows must have a holiday name"
    )

    assert (df["is_public_holiday"] == (df["is_national_holiday"] | df["is_regional_anniversary"])).all(), (
        "is_public_holiday must equal the OR of its two source flags"
    )

    assert df["category_group"].nunique() == EXPECTED_CATEGORY_GROUPS
    assert df["category_clean"].nunique() == EXPECTED_CATEGORY_CLEAN
    assert (df.groupby("category_clean")["category_group"].nunique() == 1).all(), (
        "category hierarchy broken: a sub-category maps to more than one group"
    )


if __name__ == "__main__":
    clean_df = load_clean()
    holidays = load_holidays()
    anniversaries = load_anniversaries()

    enriched = transform(clean_df, holidays, anniversaries)
    run_assertions(enriched)

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_parquet(OUT_PARQUET, index=False)
    enriched.to_csv(OUT_CSV, index=False)
    flush_dq_log()

    print(f"Enriched {len(enriched)} rows, {len(enriched.columns)} columns")
    print(f"Analytics-ready dataset written to {OUT_PARQUET} and {OUT_CSV}")
    print(f"DQ log updated at {DQ_LOG_PATH} ({len(pd.read_csv(DQ_LOG_PATH))} total rules)")
