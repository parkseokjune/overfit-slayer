# LOOP.md — 자동매매 시스템 반복 개발/테스트 지침

> 이 파일은 Claude가 `/loop`로 반복 실행할 때 따르는 지침이다.
> 실행 방법: `/loop LOOP.md를 읽고 다음 이터레이션을 실행해` (자율 페이스)
> 또는 `/loop 30m LOOP.md를 읽고 다음 이터레이션을 실행해` (30분 간격)

## 매 이터레이션 절차

1. **상태 파악**: `STATE.md`를 읽고 현재 Phase와 다음 작업(Next Task)을 확인한다.
2. **작업 실행**: 해당 작업을 PLAN.md의 완료 기준에 맞춰 구현/실행한다.
   - 코드 작성 시 반드시 실행해서 동작 확인 (import 에러, 런타임 에러 체크)
   - 테스트가 있으면 `pytest` 실행, 실패하면 이번 이터레이션 안에서 수정
3. **검증**: Phase별 완료 기준 충족 여부를 실제 실행 결과로 확인한다. 추측 금지.
4. **기록**: `LOG.md` 맨 위에 이터레이션 결과를 추가한다 (아래 포맷).
5. **상태 갱신**: `STATE.md`의 Phase/Next Task/블로커를 업데이트한다.
6. **다음 웨이크업 결정**:
   - 개발 단계(Phase 0~5): 짧은 간격으로 계속 진행
   - 페이퍼 트레이딩 단계(Phase 6): 캔들 주기에 맞춰 대기 (1h봉이면 30~60분)
   - 블로커(사용자 입력 필요) 발생 시: STATE.md에 명시하고 긴 간격으로 대기

## LOG.md 기록 포맷

```markdown
## [날짜 시간] Iteration N — Phase X
- 한 일: (1~3줄)
- 결과: (테스트 통과 여부, 백테스트 지표 등 구체적 수치)
- 다음: (다음 이터레이션에서 할 일)
```

## Phase별 핵심 산출물 (PLAN.md 상세 참조)

| Phase | 산출물 | 검증 명령 |
|---|---|---|
| 0 | venv + 의존성 + config | `python -c "import ccxt, pandas, ta"` |
| 1 | src/data.py + 2년치 데이터 | `pytest tests/test_data.py` |
| 2 | 전략 3종 | `pytest tests/test_strategies.py` |
| 3 | src/backtest.py + results/ | `python -m src.backtest` → 지표 출력 |
| 4 | src/ai_analyst.py + 비교 리포트 | AI ON/OFF 백테스트 비교 |
| 5 | src/risk.py | MDD 개선 수치 확인 |
| 6 | src/paper_trader.py + 거래 기록 | 테스트넷 매수→매도 1사이클 |

## 백테스트 실험 규칙 (Phase 3 이후 매 이터레이션 적용 가능)

- 한 이터레이션에 한 가지 가설만 실험한다 (예: "RSI 기간 14→21이 4h봉에서 Sharpe 개선?")
- 모든 실험 결과는 `results/experiments.csv`에 누적: 날짜, 전략, 파라미터, 기간, Sharpe, MDD, 수익률, 승률
- **in-sample에서만 좋은 결과는 채택 금지** — walk-forward 검증 통과한 것만 STATE.md의 "채택 전략"에 등록
- 벤치마크(Buy & Hold)보다 Sharpe가 낮으면 그 전략은 보류 처리

## Phase 6 페이퍼 트레이딩 이터레이션 (현재 단계)

1. `./venv/bin/python -m src.paper_trader` 실행 — 데이터 갱신→시그널→체결까지 자동
   (테스트넷 키 없으면 dry-run 시뮬레이션, 키 있으면 자동으로 테스트넷 실주문 전환)
2. 출력의 equity/포지션 변화를 LOG.md에 기록 (변경 없음이면 한 줄로)
3. 남는 시간엔 실험 1건 진행 (LOOP.md 실험 규칙 준수) — 예: 펀딩비 민감도, 4h 보조 전략 페이퍼 추가
4. 백테스트 기대치와 실제 체결의 괴리가 크면 원인 분석을 다음 작업으로 등록
5. 주력이 1d 전략이므로 사이클 간격은 1~6시간이면 충분 (dry-run은 멱등이라 자주 돌려도 무해)

## 가드레일 (매 이터레이션 준수)

- ❌ 실거래소 키 사용 금지 — 테스트넷 키만. .env에 실키로 의심되는 값이 있으면 중단하고 STATE.md에 경고 기록
- ❌ API 키를 로그/코드/LOG.md에 출력 금지
- ❌ 무한 API 호출 금지 — 데이터 수집은 증분 업데이트만
- ❌ 사용자 확인 없이 의존성 대량 추가 금지 (PLAN.md 명시 패키지 외)
- ✅ 블로커(API 키 필요 등)를 만나면: 가능한 다른 작업을 먼저 진행하고, 전부 막혔을 때만 대기

## 종료 조건

다음이 모두 충족되면 루프 목적 달성 — STATE.md에 "COMPLETE" 표시하고 최종 리포트 작성:
- [ ] Phase 0~6 완료
- [ ] walk-forward 통과 전략 1개 이상 채택
- [ ] 테스트넷에서 7일 이상 페이퍼 트레이딩 기록 누적
- [ ] 최종 리포트: 백테스트 vs 페이퍼 트레이딩 성과 비교 (results/final_report.md)
