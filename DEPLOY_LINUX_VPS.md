# 가상서버(VPS) 24시간 운영 가이드 — 권장 방식

노트북 없이 클라우드 서버에서 무인 운용. 월 $5 안팎, 셋업 약 20분.

---

## 1. 어떤 서버를 빌릴까

| 업체 | 비용 | 비고 |
|---|---|---|
| **Vultr** (권장) | $5~6/월 | 도쿄/서울 리전, 가입 간단, 시간당 과금 |
| DigitalOcean | $6/월 | 싱가포르 리전, 문서 친절 |
| Oracle Cloud Free Tier | **평생 무료** | 무료지만 가입 거절 잦고 설정 복잡 — 되면 최고 |
| AWS Lightsail | $5/월 | 도쿄 리전 |

**스펙은 최소면 충분**: 1 vCPU / 1GB RAM / Ubuntu 22.04 이상 (시간당 계산 몇 초뿐이라 가장 싼 등급 OK)

> ⚠ **리전(서버 위치) 중요**: 바이낸스는 **미국 IP를 차단**합니다. 반드시 **도쿄/서울/싱가포르** 리전 선택. 미국 리전(버지니아 등) 선택하면 API가 거부됩니다.

## 2. 서버 접속 (가입 후 IP/비밀번호 받으면)

맥/윈도우 터미널에서:
```bash
ssh root@서버IP
```

## 3. 설치 (전부 복사-붙여넣기)

```bash
# 기본 도구
apt update && apt install -y python3 python3-venv python3-pip git

# 코드 받기 (프라이빗 저장소라 깃허브 로그인 필요)
cd /opt
git clone https://github.com/parkseokjune/btc-auto-trader.git finance
cd finance

# 가상환경 + 의존성
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 키 입력
cp .env.example .env
nano .env    # demo.binance.com에서 발급한 키 입력 후 Ctrl+O, Enter, Ctrl+X
```

> 프라이빗 저장소 클론 시 Username = 깃허브 아이디, Password = **Personal Access Token**
> (github.com → Settings → Developer settings → Personal access tokens → Generate, repo 권한 체크)

## 4. 검증

```bash
venv/bin/python -m src.check_testnet   # "모든 점검 통과" 확인
venv/bin/python runner.py --once       # 1사이클 테스트
```

## 5. 24시간 서비스 등록 (systemd — 부팅 자동시작 + 죽으면 자동 재시작)

```bash
cat > /etc/systemd/system/btc-trader.service << 'EOF'
[Unit]
Description=BTC Auto Trader
After=network-online.target

[Service]
WorkingDirectory=/opt/finance
ExecStart=/opt/finance/venv/bin/python /opt/finance/runner.py
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now btc-trader
```

## 6. 운영 명령어 모음

```bash
systemctl status btc-trader            # 상태 확인
tail -f /opt/finance/logs/runner.log   # 실시간 로그
systemctl stop btc-trader              # 중지
systemctl restart btc-trader           # 재시작
cd /opt/finance && git pull && systemctl restart btc-trader   # 코드 업데이트
```

## 7. 모니터링 (어디서든)

- 서버 접속해서 `tail logs/runner.log` 한 줄이면 현황 확인
- `results/ALERT.txt` 생기면 전략 열화 경고 → 재학습 필요
- 주간 자동 재검증은 러너가 알아서 함 (`results/revalidation.csv`)

## ⚠ 중복 실행 금지

같은 데모 키로 **서버 + 노트북 동시 가동 금지** — 주문이 2배로 나갑니다.
서버 가동 확인 후 다른 곳의 러너는 모두 꺼야 합니다.
