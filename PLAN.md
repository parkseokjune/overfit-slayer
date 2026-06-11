> ⚠ **역사적 설계 문서** — 프로젝트 최초 계획서로 보존 중. 이후 방향이 크게 바뀌었습니다
> (선물 전환, 9년 검증, 전략 교체, 자가학습). **현재 상태는 [README.md](README.md)와 [STATE.md](STATE.md) 참조.**

# 자동매매 시스템 구축 플랜

## 목표
주식/비트코인 자동매매 시스템을 만들고, AI 분석 + 백테스팅으로 전략을 검증한 뒤,
**가상자금(테스트넷/페이퍼 트레이딩)** 으로 실전 환경 테스트까지 진행한다.

## 왜 크립토(비트코인)부터 시작하는가
- 24시간 시장 → 루프 테스트에 최적 (주식은 장 시간 제약)
- Binance Testnet = 가짜 돈으로 실제 주문 API 테스트 가능
- 무료 공개 데이터 (API 키 없이 OHLCV 수집 가능)
- 주식(한국투자증권 KIS API 모의투자 / Alpaca paper trading)은 Phase 7에서 확장

## 기술 스택
| 영역 | 선택 | 이유 |
|---|---|---|
| 언어 | Python 3.11+ (venv) | 생태계 |
| 거래소 연동 | ccxt | Binance/Upbit 등 통합 인터페이스, testnet 지원 |
| 데이터 처리 | pandas + pyarrow | OHLCV 캐싱(parquet) |
| 지표 | ta (technical analysis) | RSI, MACD, BB 등 |
| 백테스트 | 자체 엔진 (벡터화) | 수수료/슬리피지 직접 제어, 의존성 최소화 |
| AI 분석 | Claude API (claude-sonnet-4-6) | 시장 레짐 분류, 뉴스/심리 분석 |
| 설정 | .env + config.yaml | 키 분리 |

## 디렉토리 구조 (목표)
```
finance/
├── PLAN.md / LOOP.md / STATE.md / LOG.md
├── config.yaml              # 심볼, 타임프레임, 수수료, 전략 파라미터
├── .env                     # API 키 (git 제외, 테스트넷 키만)
├── src/
│   ├── data.py              # OHLCV 수집/캐싱 (ccxt → parquet)
│   ├── indicators.py        # 기술 지표 계산
│   ├── strategies/          # 전략들 (BaseStrategy 상속)
│   │   ├── base.py
│   │   ├── sma_cross.py
│   │   ├── rsi_mean_revert.py
│   │   └── bb_breakout.py
│   ├── backtest.py          # 백테스트 엔진 + 성과지표
│   ├── ai_analyst.py        # Claude API 시장 분석 (레짐/신호 보정)
│   ├── paper_trader.py      # Binance Testnet 주문 실행
│   └── risk.py              # 포지션 사이징, 손절, 일일 손실 한도
├── data/                    # parquet 캐시
├── results/                 # 백테스트 결과 (json/csv)
└── tests/                   # pytest 단위 테스트
```

## 단계별 계획

### Phase 0 — 환경 셋업
- venv 생성, requirements.txt (ccxt, pandas, pyarrow, ta, anthropic, pytest, pyyaml, python-dotenv)
- config.yaml 골격, .gitignore (.env, data/, results/)
- **완료 기준**: `python -c "import ccxt"` 성공

### Phase 1 — 데이터 파이프라인
- ccxt로 Binance BTC/USDT OHLCV 수집 (1h, 4h, 1d)
- parquet 캐싱 + 증분 업데이트 (마지막 캔들 이후만 추가 수집)
- 데이터 무결성 검증 (갭, 중복, NaN)
- **완료 기준**: 2년치 1h 데이터 수집, pytest 통과

### Phase 2 — 전략 프레임워크 + 기본 전략 3종
- BaseStrategy 인터페이스: `generate_signals(df) -> Series[-1, 0, 1]`
- SMA 골든크로스, RSI 평균회귀, 볼린저 돌파
- **완료 기준**: 각 전략이 시그널 생성, 단위 테스트 통과

### Phase 3 — 백테스트 엔진
- 벡터화 백테스트: 수수료(0.1%) + 슬리피지(0.05%) 반영
- 성과지표: 총수익률, CAGR, Sharpe, Sortino, MDD, 승률, Profit Factor
- Buy & Hold 벤치마크 비교
- **Walk-forward 검증** (과적합 방지): 학습 6개월 → 검증 1개월 롤링
- **완료 기준**: 3개 전략 × 3개 타임프레임 결과가 results/에 저장

### Phase 4 — AI 분석 레이어
- Claude API로 최근 N캔들 + 지표 요약 → 시장 레짐 분류 (상승추세/하락추세/횡보/고변동)
- 레짐별 전략 스위칭 또는 신호 필터링 (예: 횡보장엔 평균회귀만 활성화)
- AI 필터 ON/OFF 백테스트 비교 → AI가 실제로 성과를 개선하는지 정량 검증
- **완료 기준**: AI 필터 적용 전후 성과 비교 리포트

### Phase 5 — 리스크 관리
- 포지션 사이징 (고정비율 / 변동성 역가중)
- 손절(-2%), 트레일링 스탑, 일일 손실 한도(-5% → 당일 중단)
- **완료 기준**: 리스크 룰 적용 백테스트에서 MDD 개선 확인

### Phase 6 — 페이퍼 트레이딩 (가상자금 실전 테스트)
- Binance Spot Testnet (https://testnet.binance.vision) API 키 발급 ← 유일하게 사용자 작업 필요
- paper_trader.py: 최고 성과 전략으로 testnet 실주문 (시장가/지정가)
- 주문 체결 확인, 잔고 추적, 거래 기록 → results/paper_trades.csv
- 백테스트 예측 vs 실제 체결 괴리(슬리피지) 분석
- **완료 기준**: 테스트넷에서 자동 매수→매도 사이클 1회 이상 성공

### Phase 7 — (확장) 주식
- 한국 주식: KIS API 모의투자 / 미국 주식: Alpaca paper trading
- 기존 전략 프레임워크 재사용

## 방향 변경 (2026-06-10, 사용자 지시)
- **비트코인 단일** 종목으로 한정 (다른 코인/주식 제외)
- **레버리지 선물** (Binance USDT-M 무기한) — 숏 포지션 + 레버리지 사용
- 백테스트에 펀딩비·청산(liquidation) 모델 반영, 테스트넷은 Binance Futures Testnet 사용
- 루프는 대기 없이 연속 진행

## 가드레일 (절대 규칙)
1. **실거래 금지** — 테스트넷/모의투자 키만 사용. 실계좌 키는 코드에 절대 입력하지 않음
2. .env는 .gitignore에 포함, 로그에 키 출력 금지
3. API rate limit 준수 (ccxt enableRateLimit=True)
4. 백테스트 성과 ≠ 미래 수익. 과적합 방지를 위해 walk-forward 필수

## 사용자가 해야 할 일 (그 외엔 전부 자동)
- [ ] Phase 4 전: `.env`에 `ANTHROPIC_API_KEY` 추가 (AI 분석용)
- [ ] Phase 6 전: Binance Testnet 키 발급 후 `.env`에 `BINANCE_TESTNET_KEY/SECRET` 추가
