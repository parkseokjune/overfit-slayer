# ⚔️ Overfit Slayer

**A Bitcoin futures trading bot that killed its own best strategy — because the data said so.**

Most trading bots show you a beautiful 2-year backtest. This one found its own +86% strategy,
re-tested it on 9 years of data, watched it collapse to -27%, **publicly executed it**, and
rebuilt itself from the survivors. Fully automated, self-learning, long/short BTC perpetual
futures — with the statistical honesty most retail bots avoid:

- 🧪 **Walk-forward validation** over 9 years (99 windows), parameter *plateaus* not cherry-picked optima
- 📉 **Deflated Sharpe Ratio** self-audit: we report that our own Sharpe 0.92 is *not* statistically distinguishable from selection luck (DSR 0.41–0.75) — live track record is the only real evidence
- 🤖 **Self-learning with anti-overfit guardrails**: monthly re-calibration that *refuses* marginal improvements
- ⚡ 60-second risk loop (real-time stops), 15-min signal cycle, maker-first execution
- 💀 Graveyard included: famous strategies (Turtle, Larry Williams), ML direction prediction (-90%), funding carry — all tested, all rejected, all documented in [LOG.md](LOG.md)

> Runs on Binance **Demo Trading** (fake money). Educational/research project — see disclaimer below.

---

## 한국어 소개

완전 자동화 + 자가학습하는 비트코인 무기한 선물 롱/숏 트레이딩 시스템.
Binance **데모 트레이딩**(가상자금) 기준으로 개발·검증됨.

> ⚠ **실거래 키 사용 금지.** 이 시스템은 데모/테스트 환경 전용으로 설계·검증되었습니다.
> 백테스트·데모 성과는 미래 수익을 보장하지 않습니다.

---

## 운용 전략

**"9년 생존자 듀얼"** — 2017~2026 풀 히스토리에서 walk-forward 99윈도우를 통과한 두 전략에 자본 배분:

| 북 | 전략 | 비중 | 설정 |
|---|---|---|---|
| `sma_slow` | SMA 크로스 (10/200) | 50% | 1d, 2x, 양방향 |
| `supertrend` | 슈퍼트렌드 (14, 1.5) | 50% | 1d, 2x, 양방향 |

공통: 손절 4% / 트레일링 8% (실시간 발동), 변동성 타게팅 연 40% (0.25 계단 분수 포지션),
재난 백스톱 킬스위치 (고점 -40% — 9년 역사에서 무발동, 역사 밖 시나리오 전용 보험).

**기대 성과 — 검증 계층별** (상세: [docs/RATIONALE.md](docs/RATIONALE.md)):
| 증거 계층 | 결과 | 비고 |
|---|---|---|
| **프로세스 OOS** (6개월 롤링 재선택, 선택편향 0) | **CAGR 18.1%, Sharpe 0.69, MDD -25.2%** | ⭐ 기본 시나리오 |
| 9년 백테스트 (실측 펀딩 반영) | CAGR 26.4%, Sharpe 0.92, MDD -30.1% | 낙관 시나리오 |
| 역사 스트레스 (2018/코로나/LUNA·FTX) | 전 위기 구간 플러스 | 숏이 폭락에서 수익 |
| 블록 부트스트랩 2,000회 | P(손실) 0.8%, P(MDD<-50%) 12.6% | 역사 수준 꼬리 가정 |
| DSR (다중검정 보정) | 0.41~0.75 — 비유의 | 최종 심판은 라이브 기록 |

한계 조건(정직): 일중 -12% 초과 적대적 갭이 연 1회+ 반복되는 체제로 바뀌면 생존 불가 (9년간 0회).

## 아키텍처

```
runner.py (24시간 무인)
├─ 60초   고속 리스크 틱 — 실시간 가격으로 손절/트레일링/킬스위치 즉시 집행
├─ 15분   신호 사이클 — 캔들 갱신 → 시그널 → maker 지정가 주문 (미체결 시 시장가 폴백)
├─ 매일   드리프트 체크 — 라이브 곡선이 백테스트 분포 하위 5% 이탈 시 ALERT
├─ 일요일 walk-forward 재검증 → results/revalidation.csv
└─ 매월/ALERT  자가학습 — 파라미터 재탐색, 가드레일 통과 시만 자동 채택
```

자가학습 가드레일 (과적합 방지): 검증된 패밀리 내 탐색만, 고원(이웃 양수) 요구,
개선폭 +0.15 미만이면 유지, 레버리지/스탑 학습 금지, 전 결정 기록.

## 빠른 시작

상세 가이드: **[DEPLOY_LINUX_VPS.md](DEPLOY_LINUX_VPS.md)** (VPS 권장) / **[DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md)** / **[DEPLOY_MAC.md](DEPLOY_MAC.md)**

```bash
git clone https://github.com/parkseokjune/overfit-slayer.git finance
cd finance
python3 -m venv venv && venv/bin/pip install -r requirements.txt

venv/bin/python setup_keys.py        # 키 설정 도우미 (물어보면 붙여넣기 — 연결 점검까지 자동)
venv/bin/python runner.py --once       # 1사이클 테스트
venv/bin/python runner.py              # 무한 가동
```

**API 키**: https://demo.binance.com (바이낸스 데모 트레이딩) 로그인 → API Management → Create API
→ `setup_keys.py`가 물어볼 때 붙여넣기. 구 테스트넷(testnet.binance.vision / testnet.binancefuture.com) 키는 작동하지 않음.

⚠ **같은 키로 두 머신 동시 가동 금지** (이중 주문 발생).

## 프로젝트 구조

```
src/
├── data.py            # OHLCV 수집/캐싱/갭치유 (Binance, parquet)
├── backtest.py        # 선물 백테스트 엔진 (레버리지/숏/청산/펀딩, walk-forward)
├── strategies/        # 전략 10종 (채택 2 + 검증 후 기각 8)
├── risk.py            # 손절/트레일링 (재진입 블록)
├── paper_trader.py    # 집행 엔진 (데모 실주문/dry-run, maker 집행, 고속 리스크)
├── self_learn.py      # 자가학습 (월간/경고 트리거 재보정)
├── drift_monitor.py   # 라이브 vs 백테스트 분포 이탈 감지
├── revalidate.py      # 주간 walk-forward 건강도
├── stats_validation.py# PSR / Deflated Sharpe Ratio
└── ai_analyst.py      # 시장 레짐 분류 (rule 기반 + Claude API 옵션)
tests/                 # pytest 58개
runner.py              # 24시간 무인 러너
config.yaml            # 전략/북/집행 설정 (자가학습이 자동 갱신)
LOG.md / STATE.md      # 전체 개발·실험 기록 (이터레이션 22회, 실험 460+건)
```

## 모니터링

아래 파일들은 저장소에 없으며 **가동 후 자동 생성**됩니다 (`data/`, `results/`, `logs/`는 머신별 로컬 기록):

| 파일 | 내용 |
|---|---|
| `logs/runner.log` | 사이클별 한 줄 요약 |
| `results/paper_state.json` | 현재 포지션/자산 |
| `results/paper_trades.csv` | 체결 내역 (첫 체결 후 생성) |
| `results/equity_history.csv` | 자산 곡선 |
| `results/ALERT.txt` | ⚠ 생기면 전략 열화 경고 (자가학습 자동 트리거) |

## 검증 과정에서 배운 것 (요약)

전체 기록은 [LOG.md](LOG.md), 상세 리포트는 results/interim_report.md (로컬 생성).

1. **2년 백테스트는 거짓말을 한다** — 첫 채택 전략은 2y +86% → 9y -27% (과적합)
2. **유명 기법 원형 복제는 전부 실패** (터틀/래리 윌리엄스/슈퍼트렌드/MACD 원형 OOS 음수)
3. **ML 방향예측 참패** (-90%) — 캔들 데이터는 신호 대비 노이즈가 압도적
4. **수익의 원천은 기법이 아니라 구조** — 느린 추세 + 트레일링 스탑 + 변동성 타게팅 + 숏의 펀딩 수취
5. **무방비 레버리지 = 전멸** — 3x 스탑 없이 전 전략 -80~-100%, 손절이 생사의 분기점

## 면책

이 소프트웨어는 교육·연구 목적입니다. 암호화폐 파생상품 거래는 원금 전액 손실 위험이 있으며,
레버리지는 손실을 증폭합니다. 실거래 적용으로 인한 손실은 전적으로 사용자 책임입니다.
