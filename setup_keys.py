"""대화형 API 키 설정 — 파일 위치를 몰라도 됩니다.

실행: (맥/리눅스) venv/bin/python setup_keys.py
      (윈도우)   venv\\Scripts\\python setup_keys.py

하는 일: 키를 물어보고 → .env 파일을 알아서 만들고 → 연결 점검까지 실행.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"


def read_existing() -> dict:
    vals = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    return vals


def mask(v: str) -> str:
    return f"{'*' * 8}{v[-4:]}" if len(v) > 4 else "(없음)"


def ask(label: str, key: str, existing: dict) -> str:
    cur = existing.get(key, "")
    hint = f" [현재: {mask(cur)} — 엔터=유지]" if cur else ""
    val = input(f"{label}{hint}: ").strip()
    return val or cur


def main():
    print("=" * 60)
    print("  Overfit Slayer — API 키 설정 도우미")
    print("=" * 60)
    print("""
키 발급 방법 (무료, 가짜 돈):
  1. https://demo.binance.com 접속 → 바이낸스 계정으로 로그인
  2. 우측 상단 계정 아이콘 → API Management → Create API
  3. 발급된 API Key / Secret Key를 아래에 붙여넣기

⚠ 주의: testnet.binance.vision (현물 테스트넷) 키는 작동하지 않습니다!
⚠ 절대 실거래소 본계정 키를 넣지 마세요.
""")
    existing = read_existing()
    key = ask("API Key 붙여넣기", "BINANCE_TESTNET_KEY", existing)
    secret = ask("Secret Key 붙여넣기", "BINANCE_TESTNET_SECRET", existing)
    anthropic = ask("(선택) Anthropic API Key — 없으면 엔터", "ANTHROPIC_API_KEY", existing)

    if not key or not secret:
        print("\n❌ Key/Secret이 비어있습니다. 다시 실행해서 입력해주세요.")
        sys.exit(1)

    ENV_FILE.write_text(
        "# 자동 생성됨 (setup_keys.py) — 실거래소 키 입력 금지!\n"
        f"ANTHROPIC_API_KEY={anthropic}\n"
        f"BINANCE_TESTNET_KEY={key}\n"
        f"BINANCE_TESTNET_SECRET={secret}\n"
    )
    print(f"\n✅ 키 저장 완료: {ENV_FILE}")
    print("\n연결 점검 중...\n" + "-" * 40)
    os.environ["BINANCE_TESTNET_KEY"] = key
    os.environ["BINANCE_TESTNET_SECRET"] = secret
    try:
        from src.check_testnet import main as check
        check()
        print("-" * 40)
        print("🎉 설정 끝! 이제 실행하세요:")
        print("   (맥/리눅스) venv/bin/python runner.py")
        print("   (윈도우)   venv\\Scripts\\python runner.py")
    except SystemExit:
        raise
    except Exception as e:
        print("-" * 40)
        print(f"❌ 연결 실패: {str(e)[:150]}")
        print("→ 키가 demo.binance.com에서 발급된 게 맞는지 확인 후 다시 실행해주세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
