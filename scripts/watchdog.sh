#!/bin/bash
# 데드맨 스위치 (DESIGN_NEXT #2) — 러너와 별도 프로세스로 하트비트 감시.
# 사용: nohup bash scripts/watchdog.sh --restart >/dev/null 2>&1 &
DIR="$(cd "$(dirname "$0")/.." && pwd)"
HB="$DIR/results/heartbeat.txt"
LOG="$DIR/logs/watchdog.log"
RESTART="${1:-}"
FAILS=0
mkdir -p "$DIR/logs"
while true; do
  sleep 60
  NOW=$(date +%s)
  LAST=$(cat "$HB" 2>/dev/null || echo 0)
  AGE=$((NOW - LAST))
  if [ "$AGE" -gt 300 ]; then
    echo "[$(date '+%F %T')] 하트비트 정체 ${AGE}s — 러너 이상" >> "$LOG"
    "$DIR/venv/bin/python" -c "from src.notify import notify; notify('DEADMAN', '러너 하트비트 ${AGE}s 정체')" 2>/dev/null
    if [ "$RESTART" = "--restart" ] && [ "$FAILS" -lt 3 ]; then
      pkill -f "runner.py" 2>/dev/null; sleep 3
      (cd "$DIR" && nohup ./venv/bin/python runner.py >/dev/null 2>&1 &)
      FAILS=$((FAILS+1))
      echo "[$(date '+%F %T')] 러너 재기동 (시도 $FAILS/3)" >> "$LOG"
      sleep 120
    elif [ "$FAILS" -ge 3 ]; then
      echo "[$(date '+%F %T')] 연속 3회 실패 — 수동 개입 필요" >> "$LOG"
      "$DIR/venv/bin/python" -c "from src.notify import notify; notify('CRITICAL', '러너 재기동 3회 실패 — 수동 개입 필요')" 2>/dev/null
      sleep 600
    fi
  else
    FAILS=0
  fi
done
