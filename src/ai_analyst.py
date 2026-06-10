"""AI 시장 분석 — Claude API로 시장 레짐 분류 후 시그널 필터링.

ANTHROPIC_API_KEY가 없으면 레짐 'unknown'을 반환하고 필터는 무동작(시그널 통과).
백테스트용으로는 캐싱된 레짐을 사용해 API 비용을 줄인다.
"""
import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .data import ROOT, load_config

load_dotenv(ROOT / ".env")

REGIMES = ["uptrend", "downtrend", "ranging", "high_volatility"]

# 레짐별 허용 포지션: 추세장엔 추세방향만, 횡보장엔 양방향(평균회귀), 고변동엔 관망
REGIME_POLICY = {
    "uptrend": {1},
    "downtrend": {-1},
    "ranging": {1, -1},
    "high_volatility": set(),
    "unknown": {1, -1},  # AI 불가 시 필터 무동작
}


def summarize_market(df: pd.DataFrame, lookback: int = 100) -> str:
    """최근 캔들을 LLM 프롬프트용 통계 요약으로 변환."""
    w = df.tail(lookback)
    close = w["close"]
    ret_total = close.iloc[-1] / close.iloc[0] - 1
    vol = close.pct_change().std()
    sma20 = close.rolling(20).mean().iloc[-1]
    sma60 = close.rolling(60).mean().iloc[-1] if lookback >= 60 else float("nan")
    above_sma20_pct = (close > close.rolling(20).mean()).mean()
    mdd = (close / close.cummax() - 1).min()
    return (
        f"최근 {lookback}캔들 BTC/USDT 요약:\n"
        f"- 기간 수익률: {ret_total:+.2%}\n"
        f"- 캔들 수익률 표준편차: {vol:.4f}\n"
        f"- 현재가/SMA20: {close.iloc[-1] / sma20:.4f}, SMA20/SMA60: {sma20 / sma60:.4f}\n"
        f"- SMA20 위에 있던 비율: {above_sma20_pct:.1%}\n"
        f"- 기간 내 최대 낙폭: {mdd:.2%}\n"
        f"- 최근 10캔들 종가: {[round(c, 1) for c in close.tail(10).tolist()]}"
    )


def classify_regime(df: pd.DataFrame, lookback: int = 100,
                    model: str = None) -> str:
    """Claude로 레짐 분류. 키 없거나 실패 시 'unknown'."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "unknown"
    import anthropic
    cfg = load_config()
    model = model or cfg["ai"]["model"]
    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        "다음 비트코인 시장 요약을 보고 현재 레짐을 분류하라.\n\n"
        f"{summarize_market(df, lookback)}\n\n"
        f"다음 중 하나만 JSON으로 답하라: {REGIMES}\n"
        '형식: {"regime": "<값>", "confidence": 0.0~1.0, "reason": "<한줄>"}'
    )
    try:
        resp = client.messages.create(
            model=model, max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text
        start, end = text.find("{"), text.rfind("}") + 1
        regime = json.loads(text[start:end])["regime"]
        return regime if regime in REGIMES else "unknown"
    except Exception:
        return "unknown"


def filter_signals(signals: pd.Series, regime: str) -> pd.Series:
    """레짐 정책에 맞지 않는 방향의 시그널을 0으로 마스킹."""
    allowed = REGIME_POLICY.get(regime, {1, -1})
    out = signals.copy()
    if 1 not in allowed:
        out[out > 0] = 0
    if -1 not in allowed:
        out[out < 0] = 0
    return out


def rule_based_regime(df: pd.DataFrame, lookback: int = 100) -> str:
    """LLM 없이 쓰는 규칙 기반 레짐 (백테스트 기본값, AI와 비교 기준).

    고변동: 캔들 변동성이 장기 평균의 1.5배 초과
    추세: SMA20 vs SMA60 괴리 1% 초과
    """
    w = df.tail(lookback)
    close = w["close"]
    vol_recent = close.pct_change().tail(20).std()
    vol_long = close.pct_change().std()
    sma20 = close.rolling(20).mean().iloc[-1]
    sma60 = close.rolling(60).mean().iloc[-1]
    if vol_long > 0 and vol_recent / vol_long > 1.5:
        return "high_volatility"
    if sma20 / sma60 > 1.01:
        return "uptrend"
    if sma20 / sma60 < 0.99:
        return "downtrend"
    return "ranging"


def regime_series(df: pd.DataFrame, lookback: int = 100,
                  classifier=rule_based_regime) -> pd.Series:
    """각 시점의 레짐을 롤링 계산 (classifier는 미래를 보지 않음)."""
    regimes = []
    for i in range(len(df)):
        if i < lookback:
            regimes.append("unknown")
        else:
            regimes.append(classifier(df.iloc[i - lookback:i], lookback))
    return pd.Series(regimes, index=df.index)


def apply_regime_filter(df: pd.DataFrame, signals: pd.Series,
                        lookback: int = 100,
                        classifier=rule_based_regime) -> pd.Series:
    """시점별 레짐에 따라 시그널 마스킹 (벡터화된 백테스트용)."""
    regs = regime_series(df, lookback, classifier)
    out = signals.copy()
    for regime in set(regs):
        allowed = REGIME_POLICY.get(regime, {1, -1})
        mask = regs == regime
        if 1 not in allowed:
            out[mask & (out > 0)] = 0
        if -1 not in allowed:
            out[mask & (out < 0)] = 0
    return out
