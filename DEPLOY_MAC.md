# 맥(macOS) 24시간 운영 가이드

맥북/맥미니에서 무인 운용. 셋업 약 10분. (맥미니가 24시간용으론 최적)

---

## 1. 받기 + 설치 (터미널에 복사-붙여넣기)

```bash
cd ~ && git clone https://github.com/parkseokjune/overfit-slayer.git finance
cd finance
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## 2. API 키 설정 — 도우미가 알아서 해줍니다

```bash
venv/bin/python setup_keys.py
```

실행하면 키를 물어보고 → `.env` 파일을 알아서 만들고 → 연결 점검까지 해줍니다.
(키 발급: https://demo.binance.com 로그인 → API Management → Create API)

## 3. 동작 확인

```bash
venv/bin/python runner.py --once
```

## 4. 24시간 가동 (launchd — 부팅 자동시작 + 죽으면 자동 재시작)

터미널에 아래 블록을 통째로 붙여넣으세요 (경로 자동 처리):

```bash
cat > ~/Library/LaunchAgents/com.overfitslayer.trader.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.overfitslayer.trader</string>
    <key>ProgramArguments</key>
    <array>
        <string>$HOME/finance/venv/bin/python</string>
        <string>$HOME/finance/runner.py</string>
    </array>
    <key>WorkingDirectory</key><string>$HOME/finance</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$HOME/finance/logs/launchd.log</string>
    <key>StandardErrorPath</key><string>$HOME/finance/logs/launchd.err</string>
</dict>
</plist>
EOF
mkdir -p ~/finance/logs
launchctl load -w ~/Library/LaunchAgents/com.overfitslayer.trader.plist
```

> 폴더를 `~/finance`가 아닌 다른 곳에 클론했다면 plist 안의 경로 3곳을 그 경로로 바꾸세요.

## 5. 절전 끄기 (필수)

```bash
sudo pmset -a sleep 0 displaysleep 10
```
→ 디스플레이는 10분 후 꺼지지만 시스템은 안 잡니다. 맥북이면 **전원 어댑터 연결 + 뚜껑 열어두기**
(뚜껑 닫고 쓰려면 외장 모니터 연결 필요 — 클램셸 모드).

## 6. 운영 명령어

```bash
tail -f ~/finance/logs/runner.log                                        # 실시간 로그
launchctl list | grep overfitslayer                                      # 상태 확인
launchctl unload ~/Library/LaunchAgents/com.overfitslayer.trader.plist   # 중지
launchctl load -w ~/Library/LaunchAgents/com.overfitslayer.trader.plist  # 시작
cd ~/finance && git pull && launchctl kickstart -k gui/$(id -u)/com.overfitslayer.trader  # 업데이트+재시작
```

## ⚠ 중복 실행 금지

같은 데모 키로 **맥 + 윈도우/VPS 동시 가동 금지** — 주문이 2배로 나갑니다. 한 곳에서만 돌리세요.

모니터링 파일 안내는 [README.md](README.md#모니터링) 참조.
