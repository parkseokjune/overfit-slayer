"""24시간 무인 운영 러너 (Windows/Mac/Linux 공용).

동작:
- 1시간마다 페이퍼/테스트넷 사이클 실행 (시그널 → 주문 → 기록)
- 매주 일요일 1회 자동 재검증 (walk-forward 건강도 체크 → results/revalidation.csv)
- 모든 동작을 logs/runner.log에 기록, 에러가 나도 죽지 않고 다음 사이클 재시도

사용:
    python runner.py            # 무한 루프 (Task Scheduler/터미널에 띄워두기)
    python runner.py --once     # 1사이클만 (설치 검증용)
"""
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

CYCLE_SEC = 3600  # 1시간 (1d 전략이라 충분)
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "runner.log"


def log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def one_cycle(last_reval_date, last_drift_date):
    from src.paper_trader import run_once
    out = run_once()
    log(f"사이클 {out['cycles']} [{out['mode']}] equity=${out['equity']:,.2f} "
        f"price=${out['price']:,.0f} actions={out['actions']}"
        + (" ⚠ KILL-SWITCH 발동 중" if out.get("halted") else ""))

    today = datetime.now()
    if last_drift_date != today.date():  # 일 1회 드리프트 체크
        from src.drift_monitor import drift_check
        st = drift_check()
        log(f"드리프트: {json.dumps(st, ensure_ascii=False)}")
        last_drift_date = today.date()
    if today.weekday() == 6 and last_reval_date != today.date():  # 일요일 재검증
        from src.revalidate import revalidate
        row = revalidate()
        log(f"주간 재검증: {json.dumps(row, ensure_ascii=False)}")
        last_reval_date = today.date()
    return last_reval_date, last_drift_date


def main():
    once = "--once" in sys.argv
    log(f"러너 시작 (간격 {CYCLE_SEC}s{', 1회 모드' if once else ''})")
    last_reval, last_drift = None, None
    while True:
        try:
            last_reval, last_drift = one_cycle(last_reval, last_drift)
        except KeyboardInterrupt:
            log("수동 종료")
            break
        except Exception:
            log("에러 (다음 사이클에 재시도):\n" + traceback.format_exc())
        if once:
            break
        time.sleep(CYCLE_SEC)


if __name__ == "__main__":
    main()
