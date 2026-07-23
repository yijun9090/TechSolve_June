"""Module 1: Load & structural validation.

Reads the raw ticket xlsx, asserts its structure matches expectations, and
writes a raw profiling summary (dtype / null count / unique count per column)
to outputs/profile_raw.txt.
"""

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "data" / "raw" / "TechSolve-Ticket_Data.xlsx"
PROFILE_PATH = ROOT / "outputs" / "profile_raw.txt"

EXPECTED_ROWS = 100_851
EXPECTED_COLS = 36
CUSTOMER_ID_PATTERN = re.compile(r"^ACC-\d{5}$")


def load_raw(path: Path = RAW_PATH) -> pd.DataFrame:
    cache = path.with_suffix(".parquet")
    if cache.exists():
        return pd.read_parquet(cache)
    df = pd.read_excel(path, engine="openpyxl")
    df.to_parquet(cache)   # needs: pip install pyarrow
    return df


def run_assertions(df: pd.DataFrame) -> None:
    assert len(df) == EXPECTED_ROWS, f"expected {EXPECTED_ROWS} rows, got {len(df)}"
    assert len(df.columns) == EXPECTED_COLS, f"expected {EXPECTED_COLS} columns, got {len(df.columns)}"
    assert df["ticket_id"].is_unique, "ticket_id is not unique"

    valid_customer_id = df["customer_id"].astype(str).str.match(CUSTOMER_ID_PATTERN)
    assert valid_customer_id.all(), (
        f"{(~valid_customer_id).sum()} customer_id values do not match ^ACC-\\d{{5}}$"
    )


def write_profile(df: pd.DataFrame, path: Path = PROFILE_PATH) -> None:
    lines = [f"Raw profile: {len(df)} rows x {len(df.columns)} columns", ""]
    for col in df.columns:
        lines.append(
            f"{col}: dtype={df[col].dtype}, nulls={df[col].isna().sum()}, unique={df[col].nunique()}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    df = load_raw()
    run_assertions(df)
    write_profile(df)
    print(f"Loaded {len(df)} rows, {len(df.columns)} columns")
    print(f"Assertions passed. Profile written to {PROFILE_PATH}")
