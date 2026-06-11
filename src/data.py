"""OHLCV 수집/캐싱 모듈.

ccxt 공개 API로 OHLCV를 수집해 data/ 아래 parquet으로 캐싱한다.
이미 캐시가 있으면 마지막 캔들 이후만 증분 수집한다.
"""
import time
from pathlib import Path

import ccxt
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def load_config(path: Path = ROOT / "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def make_exchange(exchange_id: str = "binance") -> ccxt.Exchange:
    cls = getattr(ccxt, exchange_id)
    return cls({"enableRateLimit": True})


def cache_path(symbol: str, timeframe: str) -> Path:
    safe = symbol.replace("/", "_")
    return DATA_DIR / f"{safe}_{timeframe}.parquet"


def _fetch_ohlcv_paged(exchange, symbol: str, timeframe: str, since_ms: int) -> pd.DataFrame:
    """since_ms부터 현재까지 페이지네이션으로 전부 수집."""
    limit = 1000
    tf_ms = TIMEFRAME_MS[timeframe]
    rows = []
    cursor = since_ms
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=limit)
        if not batch:
            break
        rows.extend(batch)
        last_ts = batch[-1][0]
        next_cursor = last_ts + tf_ms
        if next_cursor <= cursor or len(batch) < limit:
            break
        cursor = next_cursor
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df


def clean_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """중복 제거, 정렬, 미완성 마지막 캔들 제거."""
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    # 진행 중인 캔들(현재 시각이 캔들 종료 전)은 제거
    tf_ms = TIMEFRAME_MS[timeframe]
    now_ms = int(time.time() * 1000)
    df = df[df["timestamp"] + tf_ms <= now_ms].reset_index(drop=True)
    return df


def validate_ohlcv(df: pd.DataFrame, timeframe: str) -> dict:
    """무결성 검사: NaN, 중복, 시간 갭. 결과 dict 반환."""
    tf_ms = TIMEFRAME_MS[timeframe]
    diffs = df["timestamp"].diff().dropna()
    gaps = int((diffs != tf_ms).sum())
    return {
        "rows": len(df),
        "nans": int(df[COLUMNS].isna().sum().sum()),
        "dup_timestamps": int(df["timestamp"].duplicated().sum()),
        "gaps": gaps,
    }


def fetch_data(symbol: str, timeframe: str, history_days: int = 730,
               exchange: ccxt.Exchange = None) -> pd.DataFrame:
    """캐시 우선 로드 + 증분 업데이트. 항상 정제된 전체 DataFrame 반환."""
    DATA_DIR.mkdir(exist_ok=True)
    path = cache_path(symbol, timeframe)
    exchange = exchange or make_exchange()

    cached = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=COLUMNS)

    if len(cached):
        since_ms = int(cached["timestamp"].iloc[-1]) + TIMEFRAME_MS[timeframe]
    else:
        since_ms = int(time.time() * 1000) - history_days * 86_400_000

    fresh = _fetch_ohlcv_paged(exchange, symbol, timeframe, since_ms)
    parts = [d for d in (cached, fresh) if len(d)]
    df = pd.concat(parts, ignore_index=True) if parts else cached
    df = clean_ohlcv(df, timeframe)
    df.to_parquet(path, index=False)
    return df


def load_data(symbol: str, timeframe: str) -> pd.DataFrame:
    """캐시에서만 로드 (네트워크 없음). datetime 인덱스 부여."""
    df = pd.read_parquet(cache_path(symbol, timeframe))
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("datetime")


def main():
    cfg = load_config()
    symbol = cfg["market"]["symbol"]
    days = cfg["market"]["history_days"]
    exchange = make_exchange(cfg["exchange"]["id"])
    for tf in cfg["market"]["timeframes"]:
        df = fetch_data(symbol, tf, days, exchange)
        report = validate_ohlcv(df, tf)
        first = pd.to_datetime(df["timestamp"].iloc[0], unit="ms")
        last = pd.to_datetime(df["timestamp"].iloc[-1], unit="ms")
        print(f"{symbol} {tf}: {report} | {first} ~ {last}")


if __name__ == "__main__":
    main()


def heal_gaps(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """거래소 다운타임 갭을 합성 플랫 캔들로 치유 (close=직전 종가, volume=0).

    지표의 롤링 윈도우가 시간축에서 어긋나지 않게 한다. synthetic 컬럼으로 식별 가능.
    """
    tf_ms = TIMEFRAME_MS[timeframe]
    full_ts = pd.Series(range(int(df["timestamp"].iloc[0]),
                              int(df["timestamp"].iloc[-1]) + tf_ms, tf_ms),
                        name="timestamp", dtype="int64")
    out = pd.DataFrame({"timestamp": full_ts}).merge(df, on="timestamp", how="left")
    out["synthetic"] = out["close"].isna()
    prev_close = out["close"].ffill()
    for col in ("open", "high", "low", "close"):
        out[col] = out[col].fillna(prev_close)
    out["volume"] = out["volume"].fillna(0.0)
    return out
