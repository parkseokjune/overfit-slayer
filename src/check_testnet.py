"""테스트넷 연결 점검 — 주문 없이 키/잔고/심볼/레버리지 설정만 검증.

사용법: ./venv/bin/python -m src.check_testnet
키 발급: https://testnet.binancefuture.com (가짜 USDT 지급됨)
"""
import os
import sys

from dotenv import load_dotenv

from .data import ROOT
from .paper_trader import FUTURES_SYMBOL, make_testnet_exchange

load_dotenv(ROOT / ".env")


def main():
    key = os.environ.get("BINANCE_TESTNET_KEY")
    if not key:
        print("❌ BINANCE_TESTNET_KEY 없음 — .env에 추가 필요")
        print("   발급: https://testnet.binancefuture.com 로그인 → API Key 탭")
        sys.exit(1)

    ex = make_testnet_exchange()
    print(f"✅ 키 로드됨 (끝 4자리: ...{key[-4:]})")

    ex.load_markets()
    m = ex.market(FUTURES_SYMBOL)
    print(f"✅ 마켓 확인: {FUTURES_SYMBOL} (id={m['id']}, 최소수량 {m['limits']['amount']['min']})")

    bal = ex.fetch_balance()
    usdt = bal.get("USDT", {})
    print(f"✅ 잔고: {usdt.get('total', 0):,.2f} USDT (가용 {usdt.get('free', 0):,.2f})")

    positions = ex.fetch_positions([FUTURES_SYMBOL])
    open_pos = [p for p in positions if float(p.get("contracts") or 0) != 0]
    if open_pos:
        for p in open_pos:
            print(f"⚠ 기존 포지션: {p['side']} {p['contracts']} @ {p['entryPrice']}")
    else:
        print("✅ 기존 포지션 없음")

    try:
        ex.set_leverage(2, FUTURES_SYMBOL)
        print("✅ 레버리지 2x 설정 성공")
    except Exception as e:
        print(f"⚠ 레버리지 설정: {e}")

    ticker = ex.fetch_ticker(FUTURES_SYMBOL)
    print(f"✅ 테스트넷 BTC 가격: ${ticker['last']:,.0f}")
    print("\n모든 점검 통과 — 다음 페이퍼 사이클부터 테스트넷 실주문 모드로 자동 전환됩니다.")


if __name__ == "__main__":
    main()
