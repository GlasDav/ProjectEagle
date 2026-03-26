from __future__ import annotations

import pandas as pd

import cache


def test_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    frame = pd.DataFrame({"nav": [100.0, 101.0], "distribution": [0.0, 0.1]}, index=pd.to_datetime(["2024-01-01", "2024-01-02"]))

    cache.save_cached_frame(frame, "csv", "test_fund", cache_date=pd.Timestamp("2024-05-01"))
    cached = cache.load_cached_frame("csv", "test_fund", cache_date=pd.Timestamp("2024-05-01"))

    assert cached is not None
    assert cached.equals(frame)


def test_cache_returns_none_for_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    assert cache.load_cached_frame("csv", "missing", cache_date=pd.Timestamp("2024-05-01")) is None
