"""
ALIGN Layer — Transformation Module
Tidy, rename columns, and normalise values before schema extraction.
"""
import json
import pathlib
import pandas as pd
from typing import Dict

_CONFIG_DIR = pathlib.Path(__file__).parent.parent / "config"
_ALIAS_FILE = _CONFIG_DIR / "column_alias.json"


def _load_alias_config() -> dict:
    if _ALIAS_FILE.exists():
        return json.loads(_ALIAS_FILE.read_text())
    return {}


def tidy_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standardise a DataFrame before schema hashing and quality evaluation:
      - Cast date-like columns to datetime64
      - Strip whitespace and lowercase all string columns
    """
    for col in df.columns:
        if "date" in col.lower():
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip()
    return df


def apply_column_aliases(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename columns using the mapping in config/column_alias.json.
    Example: '1. open' -> 'open_price'
    """
    config = _load_alias_config()
    aliases: Dict[str, str] = config.get("column_aliases", {})
    if aliases:
        df = df.rename(columns=aliases)
        renamed = {k: v for k, v in aliases.items() if k in df.columns or v in df.columns}
        if renamed:
            print(f"[Align] Renamed columns: {renamed}")
    return df


def apply_value_maps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise column values using the value_maps in config/column_alias.json.
    Example: 'uk' -> 'GB', 'a+' -> 'A+'
    """
    config = _load_alias_config()
    value_maps: dict = config.get("value_maps", {})
    for col, mapping in value_maps.items():
        if col in df.columns and df[col].dtype == object:
            before = df[col].copy()
            df[col] = df[col].str.strip().str.lower().map(mapping).fillna(before)
    return df


def align(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run the full ALIGN pipeline: tidy -> rename -> normalise.
    Call this once after the DataFrame is loaded.
    """
    df = tidy_dataframe(df)
    df = apply_column_aliases(df)
    df = apply_value_maps(df)
    return df
