"""ML 전략 — 기술지표 피처로 다음 캔들 방향을 학습 (walk-forward, 룩어헤드 차단).

피처: 수익률 래그, RSI, MACD 히스토그램, 볼린저 %B, 변동성, SMA 비율, 거래량 z
라벨: 다음 캔들 수익률 부호
학습: HistGradientBoosting, 롤링 재학습 (train_window 캔들 → 다음 retrain_every 캔들 예측)
시그널: P(상승) > long_th → 롱 / < short_th → 숏
"""
import numpy as np
import pandas as pd
import ta

FEATURES = ["ret1", "ret3", "ret7", "rsi", "macd_hist", "bb_pctb",
            "vol20", "sma_ratio", "vol_z", "hl_range"]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    f = pd.DataFrame(index=df.index)
    f["ret1"] = c.pct_change()
    f["ret3"] = c.pct_change(3)
    f["ret7"] = c.pct_change(7)
    f["rsi"] = ta.momentum.RSIIndicator(c, window=14).rsi() / 100
    macd = ta.trend.MACD(c)
    f["macd_hist"] = (macd.macd_diff() / c).fillna(0)
    bb = ta.volatility.BollingerBands(c, window=20)
    rng = (bb.bollinger_hband() - bb.bollinger_lband()).replace(0, np.nan)
    f["bb_pctb"] = ((c - bb.bollinger_lband()) / rng).clip(-1, 2)
    f["vol20"] = c.pct_change().rolling(20).std()
    f["sma_ratio"] = c.rolling(20).mean() / c.rolling(60).mean() - 1
    f["vol_z"] = (v - v.rolling(20).mean()) / v.rolling(20).std().replace(0, np.nan)
    f["hl_range"] = (h - l) / c
    f["target"] = (c.pct_change().shift(-1) > 0).astype(int)  # 다음 캔들 방향
    return f


def ml_signals(df: pd.DataFrame, train_window: int = 400, retrain_every: int = 30,
               long_th: float = 0.55, short_th: float = 0.45,
               seed: int = 42) -> pd.Series:
    """롤링 walk-forward 예측 시그널. 학습은 항상 과거 데이터만 사용."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    f = build_features(df)
    X = f[FEATURES].to_numpy()
    y = f["target"].to_numpy()
    sig = np.zeros(len(df))

    start = train_window + 60  # 지표 워밍업 여유
    t = start
    while t < len(df):
        end = min(t + retrain_every, len(df))
        X_tr, y_tr = X[t - train_window:t], y[t - train_window:t]
        mask = ~np.isnan(X_tr).any(axis=1)
        if mask.sum() < 100:
            t = end
            continue
        model = HistGradientBoostingClassifier(
            max_iter=120, max_depth=3, learning_rate=0.05,
            l2_regularization=1.0, random_state=seed)
        model.fit(X_tr[mask], y_tr[mask])
        X_te = X[t:end]
        ok = ~np.isnan(X_te).any(axis=1)
        if ok.any():
            proba = np.full(len(X_te), 0.5)
            proba[ok] = model.predict_proba(X_te[ok])[:, 1]
            chunk = np.zeros(len(X_te))
            chunk[proba > long_th] = 1
            chunk[proba < short_th] = -1
            sig[t:end] = chunk
        t = end
    return pd.Series(sig, index=df.index)
