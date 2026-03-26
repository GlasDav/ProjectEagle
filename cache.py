from __future__ import annotations

from pathlib import Path

import pandas as pd


CACHE_DIR = Path.home() / ".fund-tracker" / "cache"


def get_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def build_cache_key(source: str, identifier: str, cache_date: pd.Timestamp | None = None) -> str:
    safe_identifier = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in identifier)
    day = (cache_date or pd.Timestamp.today()).strftime("%Y-%m-%d")
    return f"{source}_{safe_identifier}_{day}.parquet"


def cache_path(source: str, identifier: str, cache_date: pd.Timestamp | None = None) -> Path:
    return get_cache_dir() / build_cache_key(source, identifier, cache_date=cache_date)


def load_cached_frame(source: str, identifier: str, cache_date: pd.Timestamp | None = None) -> pd.DataFrame | None:
    path = cache_path(source, identifier, cache_date=cache_date)
    if not path.exists():
        return None

    frame = pd.read_parquet(path)
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.set_index("date")
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, errors="coerce")
    return frame.sort_index()


def save_cached_frame(frame: pd.DataFrame, source: str, identifier: str, cache_date: pd.Timestamp | None = None) -> Path:
    path = cache_path(source, identifier, cache_date=cache_date)
    serializable = frame.copy()
    serializable.index = pd.to_datetime(serializable.index)
    serializable = serializable.reset_index().rename(columns={"index": "date"})
    serializable.to_parquet(path, index=False)
    return path
