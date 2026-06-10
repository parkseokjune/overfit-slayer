"""data.py 단위 테스트 — 네트워크 없이 캐시/정제/검증 로직 확인."""
import time

import pandas as pd
import pytest

from src.data import (TIMEFRAME_MS, cache_path, clean_ohlcv, load_data,
                      validate_ohlcv)


def make_df(n=10, tf="1h", start_ms=None):
    tf_ms = TIMEFRAME_MS[tf]
    if start_ms is None:
        # 충분히 과거라 미완성 캔들 제거에 안 걸리도록
        start_ms = int(time.time() * 1000) - (n + 10) * tf_ms
        start_ms -= start_ms % tf_ms
    ts = [start_ms + i * tf_ms for i in range(n)]
    return pd.DataFrame({
        "timestamp": ts,
        "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0,
        "volume": 1.0,
    })


def test_clean_removes_duplicates_and_sorts():
    df = make_df(10)
    dup = pd.concat([df, df.iloc[[3]]], ignore_index=True).sample(frac=1, random_state=0)
    out = clean_ohlcv(dup, "1h")
    assert len(out) == 10
    assert out["timestamp"].is_monotonic_increasing


def test_clean_drops_incomplete_last_candle():
    tf_ms = TIMEFRAME_MS["1h"]
    now = int(time.time() * 1000)
    current_open = now - now % tf_ms  # 진행 중인 캔들 시작 시각
    df = make_df(5, start_ms=current_open - 4 * tf_ms)
    out = clean_ohlcv(df, "1h")
    assert current_open not in out["timestamp"].values
    assert len(out) == 4


def test_validate_detects_gap():
    df = make_df(10)
    gapped = df.drop(index=5).reset_index(drop=True)
    report = validate_ohlcv(gapped, "1h")
    assert report["gaps"] == 1
    assert report["nans"] == 0


def test_validate_clean_data():
    report = validate_ohlcv(make_df(20), "1h")
    assert report == {"rows": 20, "nans": 0, "dup_timestamps": 0, "gaps": 0}


def test_cache_path_safe_name():
    assert cache_path("BTC/USDT", "1h").name == "BTC_USDT_1h.parquet"


def test_load_data_real_cache():
    """실제 수집된 캐시 검증 (data/가 있을 때만)."""
    path = cache_path("BTC/USDT", "1h")
    if not path.exists():
        pytest.skip("캐시 없음 — python -m src.data 먼저 실행")
    df = load_data("BTC/USDT", "1h")
    assert len(df) > 17000  # 2년치 1h
    assert df.index.tz is not None
    report = validate_ohlcv(df.reset_index(), "1h")
    assert report["nans"] == 0 and report["dup_timestamps"] == 0 and report["gaps"] == 0
