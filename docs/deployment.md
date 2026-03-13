# 배포 가이드

## Docker (권장)

```bash
docker compose up -d
```

보안 강화 설정 적용:
- non-root 유저 실행
- `cap_drop: ALL` (권한 최소화)
- `read_only` 파일시스템
- `no-new-privileges`

### 로그 확인

```bash
docker compose logs -f cryptolight
```

### 재시작

```bash
docker compose restart
```

## systemd user service

호스트 재부팅 시 자동 복구되는 systemd 서비스 설정.

### 서비스 파일 생성

```bash
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/cryptolight.service << 'EOF'
[Unit]
Description=cryptolight trading bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/projects/cryptolight
ExecStart=%h/projects/cryptolight/.venv/bin/python -m cryptolight.main
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
```

> `WorkingDirectory`와 `ExecStart` 경로를 실제 설치 경로에 맞게 수정하세요.

### 서비스 등록 및 시작

```bash
systemctl --user daemon-reload
systemctl --user enable cryptolight.service
systemctl --user start cryptolight.service

# 재부팅 후에도 user service가 실행되도록 linger 설정
loginctl enable-linger $(whoami)
```

### 운영 명령어

```bash
# 상태 확인
systemctl --user status cryptolight.service

# 실시간 로그
journalctl --user -u cryptolight.service -f

# 재시작
systemctl --user restart cryptolight.service

# 중지
systemctl --user stop cryptolight.service
```

## 웹 대시보드 설정

`.env`에 아래 항목을 추가하면 봇 실행 시 웹 대시보드가 함께 시작됩니다.

```bash
ENABLE_WEB=true
WEB_PORT=8090
WEB_USERNAME=admin
WEB_PASSWORD=your_password_here
```

`WEB_USERNAME`/`WEB_PASSWORD`를 설정하면 HTTP Basic Auth로 대시보드 접근이 보호됩니다. 미설정 시 인증 없이 접근 가능하므로 외부 노출 환경에서는 반드시 설정하세요.

대시보드 기능:
- 종목별 실시간 가격, RSI 게이지, 시그널 상태
- 포트폴리오 현황 (총자산, 손익률, 보유 포지션)
- 시장 국면 표시 (추세/횡보/변동)
- 최근 거래 내역
- 봇 상태 모니터링
