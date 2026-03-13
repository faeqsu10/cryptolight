# cryptolight

업비트 기반 코인 자동매매 봇. 멀티팩터 스코어 전략, 시장 국면 감지, AI 어시스턴트, 자기개선 루프를 지원한다.

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

텔레그램 알림/명령 기능은 기본 의존성에 포함되어 있어 추가 extra 설치가 필요하지 않다.

## 환경 설정

`.env.example`을 복사하여 `.env`를 생성하고 값을 채운다.

```bash
cp .env.example .env
```

주요 설정 항목:

| 항목 | 설명 | 기본값 |
|------|------|--------|
| `UPBIT_ACCESS_KEY` | 업비트 API Access Key | (필수) |
| `UPBIT_SECRET_KEY` | 업비트 API Secret Key | (필수) |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | (필수) |
| `TELEGRAM_CHAT_ID` | 텔레그램 채팅 ID | (필수) |
| `TELEGRAM_POLL_TIMEOUT_SECONDS` | 텔레그램 long polling 대기 시간 | `20` |
| `TELEGRAM_POLL_BACKOFF_MAX_SECONDS` | 폴링 실패 시 최대 백오프 | `30.0` |
| `TRADE_MODE` | 거래 모드 (`paper` / `live`) | `paper` |
| `STRATEGY_NAME` | 매매 전략 | `score` |
| `TARGET_SYMBOLS` | 대상 종목 | `KRW-BTC,KRW-ETH` |
| `GOOGLE_API_KEY` | Gemini AI API 키 (/ask용) | (선택) |
| `GEMINI_MODEL` | Gemini 모델명 | `gemini-2.5-flash` |
| `ENABLE_WEB` | 웹 대시보드 활성화 | `false` |
| `WEB_PORT` | 웹 대시보드 포트 | `8090` |
| `APP_TIMEZONE` | 스케줄러 타임존 | `Asia/Seoul` |
| `ENABLE_AUTO_PARAMETER_TUNING` | 전략 파라미터 자동 조정 활성화 | `true` |
| `PARAMETER_TUNING_INTERVAL_HOURS` | 파라미터 자동 조정 주기 | `6` |
| `PARAMETER_TUNING_COOLDOWN_HOURS` | 파라미터 조정 후 재조정 대기 시간 | `12` |

전체 설정 항목은 `src/cryptolight/config/settings.py`를 참고.

> **보안 주의**: `.env` 파일에는 API 키가 포함됩니다. 절대 Git에 커밋하지 마세요. `.gitignore`에 이미 포함되어 있습니다.

## 실행

```bash
# 스케줄러 모드 (5분마다 자동 분석)
python -m cryptolight.main

# 1회 실행
python -m cryptolight.main --once
```

## 매매 전략

### Score (기본, 권장)

멀티팩터 스코어 기반 전략. 여러 지표가 동시에 같은 방향을 가리킬 때만 매매한다.

**매수/매도 팩터 (6개, 100점 만점)**:

| 팩터 | 매수 조건 | 매도 조건 | 점수 |
|------|----------|----------|------|
| RSI(14) | RSI <= 35 | RSI >= 65 | 25 |
| RSI 방향 | 반등 시작 | 하락 시작 | 10 |
| MACD | 골든크로스 | 데드크로스 | 25 |
| MACD 모멘텀 | 히스토그램 증가 | 히스토그램 감소 | 10 |
| 볼린저밴드 | 하단 터치 | 상단 터치 | 20 |
| 거래량 | 평균 이상 | 평균 이상 | 10 |

**시장 국면별 자동 조정**:

| 국면 | 특징 | MACD 가중치 | BB 가중치 | 매수/매도 임계값 |
|------|------|-----------|----------|----------------|
| 추세장 (trending) | ADX >= 25 | 1.5x | 0.5x | 40 / 35점 |
| 횡보장 (sideways) | ADX < 25, 변동 낮음 | 0.5x | 1.5x | 45 / 40점 |
| 변동장 (volatile) | BB 폭 >= 6% | 1.0x | 1.0x | 50 / 45점 |

**안전 장치**:
- confidence 게이트: 신뢰도 40% 미만 시 주문 자동 차단
- 거래량 부족 시 시그널 무시
- 매수/매도 임계값은 자동 튜닝 대상 (6시간마다 최적화)

### 기타 전략

```bash
STRATEGY_NAME=rsi python -m cryptolight.main        # RSI 단독
STRATEGY_NAME=macd python -m cryptolight.main       # MACD 단독
STRATEGY_NAME=bollinger python -m cryptolight.main  # 볼린저밴드
STRATEGY_NAME=ensemble python -m cryptolight.main   # 다수결 앙상블
```

## 텔레그램 명령어

| 명령어 | 설명 |
|--------|------|
| `/info` | 시장 상태 (RSI, 국면, 매수/매도 조건) + 초보자 해설 |
| `/criteria` | 현재 전략의 매수/매도 기준만 따로 설명 |
| `/tuning` | 최근 자동 조정 이력과 현재 적용 파라미터 조회 |
| `/ask <질문>` | AI에게 질문 (Gemini, 일일 10회 제한) |
| `/status` | 봇 상태 조회 |
| `/report` | 일일 요약 리포트 |
| `/mute` | 자동 알림 끄기 (시그널, 급등/급락) |
| `/unmute` | 자동 알림 켜기 |
| `/stop` | 긴급 거래 중지 (킬스위치) |
| `/help` | 명령어 목록 |

## 웹 대시보드

글래스모피즘 디자인의 실시간 모니터링 대시보드.

```bash
# 의존성 설치
pip install -e ".[web]"

# .env에 설정 추가
ENABLE_WEB=true
WEB_PORT=8090
WEB_USERNAME=admin
WEB_PASSWORD=changeme

# 실행 후 브라우저에서 http://localhost:8090 접속
python -m cryptolight.main
```

대시보드 기능:
- 종목별 실시간 가격, RSI 게이지, 시그널 상태
- 포트폴리오 현황 (총자산, 손익률, 보유 포지션)
- 시장 국면 표시 (추세/횡보/변동)
- 최근 거래 내역
- 봇 상태 모니터링
- HTTP Basic Auth 인증 (XSS/CORS 방어 포함)

## 백테스트

```bash
# BTC 1년 스코어 전략 백테스트
python -m cryptolight.backtest --symbol KRW-BTC --strategy score --days 365

# ETH MACD 백테스트 + 텔레그램 전송
python -m cryptolight.backtest --symbol KRW-ETH --strategy macd --days 180 --telegram

# Walk-Forward 검증 (과적합 방지)
python -m cryptolight.backtest --symbol KRW-BTC --strategy score --days 365 --walk-forward
```

## 자기개선 루프

기본값으로 전략 전환 루프는 매주 일요일 03:00 `APP_TIMEZONE` 기준에 실행되고, 파라미터 조정 루프는 6시간마다 실행됩니다.

1. **성과 평가** — Sharpe ratio, 승률, MDD 분석
2. **전략 경쟁** — 다중 전략 백테스트 비교 (Arena)
3. **자동 전환** — 전략 전환은 주 1회만 판단해 과최적화를 줄임
4. **자동 파라미터 조정** — 현재 전략의 기준값(RSI 기간, 매수/매도 임계값 등)은 더 짧은 주기로 미세 조정
5. **Walk-Forward 검증** — 시계열 순서를 보존하는 anchored 방식으로 과적합 방지
6. **텔레그램 알림** — 무엇이 왜 바뀌었는지 초보자용 설명과 함께 전송
7. **롤백** — 전환 후 성과 악화 시 이전 전략으로 복원

## 리스크 관리

- 1회 최대 주문 금액 제한 + Live 하드캡
- 동시 보유 종목 수 제한
- 일일 손실 한도 (초과 시 매수 차단)
- 자동 손절/익절/트레일링 스톱
- confidence 게이트 (낮은 신뢰도 시그널 차단)
- 중복 시그널 방지 + 매매 쿨다운
- API 장애 시 지수 백오프 재시도 (주문 API는 재시도 안 함)
- SQLite WAL 모드 + 스레드 안전 (전체 read/write 락 + busy_timeout)

## 초보자 친화 알림

텔레그램 알림은 초보자도 이해할 수 있도록 설계되었다:

- **매수/매도 체결 시**: 종목, 금액, 수량, 사유를 상세히 알림
- **지표 해설**: RSI, MACD, 볼린저밴드 값에 대한 쉬운 설명 (예: "RSI 28.5: 과매도 — 많이 떨어져서 반등 가능성")
- **일일 리포트**: 거래 내역, 용어 해설, 실현 손익 판단, 보유 코인별 수량/매수가/현재가/손익 포함
- **5분 현황**: 이번 주기에 실행된 매수/매도 내역 표시

## 서비스 관리

systemd user service로 관리하여 호스트 재부팅 시 자동 복구된다.

```bash
# 상태 확인
systemctl --user status cryptolight.service

# 로그 확인
journalctl --user -u cryptolight.service -f

# 재시작
systemctl --user restart cryptolight.service
```

## 프로젝트 구조

```
src/cryptolight/
  main.py                  # 진입점 (스케줄러, 전략 실행)
  config/settings.py       # 환경 설정 (pydantic-settings)
  exchange/
    base.py                # 거래소 추상 인터페이스
    upbit.py               # 업비트 REST 클라이언트
    candle_cache.py        # 캔들 캐시 (TTL)
  strategy/
    base.py                # BaseStrategy + Signal
    score_based.py         # 멀티팩터 스코어 전략 (기본)
    rsi.py / macd.py / bollinger.py  # 개별 전략
    ensemble.py            # 앙상블 (다수결)
    volume_filter.py       # 거래량 필터
  market/
    regime.py              # 시장 국면 감지 (ADX + BB)
    screener.py            # 거래량 상위 코인 자동 스크리닝
  execution/
    paper_broker.py        # Paper Trading
    live_broker.py         # 업비트 실거래
  risk/
    risk_guard.py          # 손절/익절/리스크 체크
    position_sizer.py      # 포지션 사이징 (fixed/percent/kelly)
  evaluation/
    performance.py         # 성과 평가 (Sharpe, MDD)
    arena.py               # 전략 경쟁
    optimizer.py           # 파라미터 최적화
    controller.py          # 자동 전략 전환
  storage/
    repository.py          # SQLite 거래/포지션 저장소
    strategy_tracker.py    # 전략별 성과 추적
  bot/
    telegram_bot.py        # 텔레그램 알림
    command_handler.py     # 텔레그램 명령어 처리
    ai_assistant.py        # Gemini AI 어시스턴트
  backtest/
    engine.py              # 백테스트 엔진
    walk_forward.py        # Walk-Forward 검증
  web/
    app.py                 # FastAPI 웹 대시보드
    templates/dashboard.html  # 글래스모피즘 UI
  health.py                # 헬스 모니터
```

## 테스트

```bash
pytest                # 전체 테스트 (현재 216개)
ruff check src/       # 린트
ruff format src/      # 포맷
```

## Docker

```bash
docker compose up -d
```

보안 강화: non-root 유저, `cap_drop: ALL`, `read_only`, `no-new-privileges`.

## 라이선스

MIT
