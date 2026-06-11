# 윈도우 24시간 운영 가이드

이 폴더를 통째로 옮기면 됩니다. 아래 순서대로 하세요 (약 15분).

---

## 1. 파일 받기 — 깃허브에서 클론 (권장)

저장소: **https://github.com/parkseokjune/overfit-slayer** (공개)

1. https://git-scm.com/download/win 에서 Git 설치 (기본 옵션으로 Next 연타)
2. 명령 프롬프트(cmd)에서:

```bat
cd C:\
mkdir trading
cd trading
git clone https://github.com/parkseokjune/overfit-slayer.git finance
cd finance
```

> 공개 저장소라 로그인 없이 바로 클론됩니다.
> `data/`(9년 시세)와 `results/`(실험 기록)는 저장소에 없지만, 첫 실행 시 **자동으로 재수집**됩니다 (몇 분 소요).
> 이후 코드가 업데이트되면 `git pull` 한 줄로 받아옵니다.

### (대안) USB/클라우드로 폴더 복사
`finance` 폴더 전체 복사도 가능 — 단 `venv/`는 맥 전용이라 제외하고, `.env`는 키가 들어있으니 안전한 방법으로만 옮기세요.

## 2. Python 설치

1. https://www.python.org/downloads/ 에서 **Python 3.11 이상** 다운로드
2. 설치 시 **"Add python.exe to PATH" 체크 필수** ✅

## 3. 환경 구성 (명령 프롬프트에서)

```bat
cd C:\trading\finance
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

## 4. API 키 — 어디서 구하고, 어디에 넣는가

### 키 구하는 방법

| 키 | 발급처 | 방법 | 비용 |
|---|---|---|---|
| **BINANCE_TESTNET_KEY / SECRET** | binance.com **데모 트레이딩** | 아래 상세 절차 참고 ⬇ | 무료 (가짜 USDT 지급) |
| ANTHROPIC_API_KEY (선택) | https://console.anthropic.com | 가입 → Settings → API Keys → Create Key | 유료 (AI 레짐 분류용, 없어도 규칙 기반으로 동작) |

#### 바이낸스 데모 트레이딩 키 발급 상세 (2025년부터 구 테스트넷 폐쇄됨 ⚠)

> 구 선물 테스트넷(testnet.binancefuture.com)에서 만든 키는 **더 이상 작동하지 않습니다.**
> 본사이트의 "데모 트레이딩(Demo Trading / 모의 거래)" 환경에서 발급해야 합니다.

1. **https://demo.binance.com** 접속 (바이낸스 본계정 로그인, 입금 불필요 — 가짜 USDT 지급)
   (또는 binance.com에서 **[More] → [Demo Trading]** 메뉴)
2. 데모 환경 우측 상단 **계정(Account) 아이콘** → **API Management** → **Create API**
3. 발급된 Key/Secret을 `.env`에 입력 (Secret은 생성 직후 한 번만 표시 — 바로 복사)
4. ⚠ `testnet.binance.vision`(현물)이나 구 `testnet.binancefuture.com` 키는 작동하지 않음
   — 2026-06-11 검증: demo.binance.com 키로 잔고/레버리지/주문 전부 정상 확인됨

> 🔒 **절대 규칙**: 실거래소(binance.com) 키는 절대 넣지 마세요. 코드가 sandbox 모드를 강제하지만,
> 키 자체를 만들지 않는 게 가장 안전합니다. 테스트넷 키는 가짜 돈이라 유출돼도 손실이 없습니다.

### 키 넣는 곳

`finance` 폴더 안의 `.env` 파일을 메모장으로 열어서:

```
ANTHROPIC_API_KEY=sk-ant-...        ← 선택
BINANCE_TESTNET_KEY=발급받은키
BINANCE_TESTNET_SECRET=발급받은시크릿
```

저장 후 연결 점검:

```bat
venv\Scripts\python -m src.check_testnet
```

`모든 점검 통과` 가 나오면 준비 끝. 이후 자동으로 테스트넷 실주문 모드로 전환됩니다.

## 5. 24시간 돌리기

### 동작 확인 (1회 실행)

```bat
venv\Scripts\python runner.py --once
```

### 방법 A — 작업 스케줄러 등록 (권장: 부팅 시 자동 시작 + 죽으면 재시작)

관리자 명령 프롬프트에서:

```bat
schtasks /create /tn "BTC-AutoTrader" /tr "C:\trading\finance\venv\Scripts\python.exe C:\trading\finance\runner.py" /sc onstart /ru "%USERNAME%" /rl highest
schtasks /run /tn "BTC-AutoTrader"
```

추가 설정 (작업 스케줄러 GUI → BTC-AutoTrader → 속성):
- **설정 탭**: "작업이 실패하면 다시 시작" 체크, 간격 1분, 횟수 3회
- **조건 탭**: "컴퓨터의 AC 전원이 켜져 있을 때만" **해제**
- **일반 탭**: "사용자가 로그온했는지 여부에 관계없이 실행" 선택

### 방법 B — 그냥 터미널에 띄워두기 (간단)

```bat
venv\Scripts\python runner.py
```

창을 닫으면 멈춥니다. 24시간용으론 방법 A를 쓰세요.

### 절전 끄기 (필수)

설정 → 시스템 → 전원 → **화면/절전 모드: 안 함**. (모니터만 끄는 건 OK)

## 6. 러너가 자동으로 하는 일

| 주기 | 작업 |
|---|---|
| 1시간마다 | 최신 캔들 → 시그널 계산 → 주문(시그널 변화 시) → 자산 기록 |
| 매주 일요일 | **자동 재검증**: 새 데이터 포함 walk-forward → `results/revalidation.csv` 누적 |
| 상시 | 킬스위치 감시 (자산 고점 -15% → 전량 청산 + 거래 중단) |

## 7. 모니터링 — 뭘 보면 되는가

| 파일 | 내용 |
|---|---|
| `logs\runner.log` | 매 사이클 한 줄 요약 (이것만 봐도 됨) |
| `results\paper_state.json` | 현재 포지션/자산 |
| `results\paper_trades.csv` | 전체 체결 내역 |
| `results\equity_history.csv` | 자산 곡선 (엑셀로 열어 차트 가능) |
| `results\ALERT.txt` | ⚠ 이 파일이 생기면 전략 열화 경고 — 재학습 필요 |

## 8. 결과에 따른 계속 학습 전략

**자동 (러너가 함)**: 주간 재검증이 OOS Sharpe를 추적, 두 북 모두 음수면 `ALERT.txt` 생성.

**수동 (월 1회 권장, 또는 ALERT 발생 시)** — 윈도우에도 Claude Code를 설치하면 이 세션과 동일한 학습 루프를 돌릴 수 있습니다:
1. https://claude.com/claude-code 에서 설치 → `finance` 폴더에서 실행
2. `/loop LOOP.md를 읽고 다음 이터레이션을 실행해 (연속 백테스팅/학습 모드)` 입력
3. STATE.md/LOG.md에 모든 맥락이 기록돼 있어 어느 컴퓨터에서든 이어집니다

**학습 규칙** (과적합 방지 — 이 세션에서 비싸게 배운 것):
- 파라미터 변경은 **9년 walk-forward 고원**을 통과한 것만 채택 (단일 최고값 금지)
- 새 데이터 6개월 미만으로는 절대 재튜닝하지 않기
- 백테스트 성과가 좋아도 페이퍼/테스트넷 실체결과 괴리가 크면 보류
- 판단 기준 우선순위: ① 청산 안 당함 ② MDD ③ Sharpe ④ 수익률 (이 순서)

## 9. 멈추고 싶을 때

```bat
schtasks /end /tn "BTC-AutoTrader"        :: 중지
schtasks /delete /tn "BTC-AutoTrader" /f  :: 등록 삭제
```

킬스위치가 발동된 경우: `results\paper_state.json`에서 `"halted": true`를 `false`로 바꾸면 재개.
