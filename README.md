# cryptolight

업비트 기반 코인 자동매매 봇. 전략 분석, 시그널 알림, paper/live trading, 백테스트를 지원한다.

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 환경 설정 (.env)

```env
# 업비트 API (https://upbit.com/mypage/open_api_management)
UPBIT_ACCESS_KEY=your_access_key
UPBIT_SECRET_KEY=your_secret_key

# 텔레그램 봇 (https://t.me/BotFather)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# 거래 설정
TRADE_MODE=paper                # paper | live
MAX_ORDER_AMOUNT_KRW=50000      # 1회 최대 주문 금액
DAILY_LOSS_LIMIT_KRW=100000     # 일일 손실 한도
MAX_POSITIONS=5                 # 동시 보유 종목 수
STOP_LOSS_PCT=-5.0              # 손절 기준 (%)
TAKE_PROFIT_PCT=10.0            # 익절 기준 (%)
TARGET_SYMBOLS=KRW-BTC,KRW-ETH  # 대상 종목

# 전략
STRATEGY_NAME=rsi               # rsi | macd | bollinger | volatility_breakout | ensemble
ENSEMBLE_STRATEGIES=rsi,macd,bollinger  # 앙상블 사용 시 전략 조합

# 스케줄러
SCHEDULE_INTERVAL_MINUTES=5     # 실행 주기 (0이면 1회 실행)
COMMAND_POLL_SECONDS=30         # 텔레그램 명령어 폴링 주기
PAPER_INITIAL_BALANCE=1000000   # Paper 초기 자금 (KRW)
DB_PATH=data/trades.db          # SQLite DB 경로

# 알림
SURGE_ALERT_THRESHOLD=0.05      # 급등/급락 알림 기준 (5%)
LOG_LEVEL=INFO
```

## 실행

### 스케줄러 모드 (기본)

5분마다 자동으로 시세 분석 + 매매 판단을 반복한다.

```bash
python -m cryptolight.main
```

### 1회 실행 모드

```bash
python -m cryptolight.main --once
```

### 전략 변경

```bash
# MACD 전략
STRATEGY_NAME=macd python -m cryptolight.main

# 볼린저밴드
STRATEGY_NAME=bollinger python -m cryptolight.main

# 변동성 돌파
STRATEGY_NAME=volatility_breakout python -m cryptolight.main

# 앙상블 (RSI + MACD + 볼린저 다수결 투표)
STRATEGY_NAME=ensemble python -m cryptolight.main
```

### 백테스트

```bash
# BTC 1년 RSI 백테스트
python -m cryptolight.backtest --symbol KRW-BTC --strategy rsi --days 365

# ETH MACD 백테스트 + 텔레그램 전송
python -m cryptolight.backtest --symbol KRW-ETH --strategy macd --days 180 --telegram

# 초기 자금/주문 금액 지정
python -m cryptolight.backtest --symbol KRW-BTC --strategy ensemble --balance 5000000 --amount 100000
```

## 텔레그램 명령어

| 명령어 | 설명 |
|--------|------|
| `/status` | 현재 상태 조회 |
| `/report` | 일일 요약 리포트 즉시 전송 |
| `/stop` | 긴급 거래 중지 (킬스위치) |
| `/help` | 명령어 목록 |

## 전략

### RSI (기본)
- Wilder smoothing(EMA) 방식 RSI 14
- RSI <= 30: 매수, RSI >= 70: 매도

### MACD
- EMA(12) - EMA(26), Signal EMA(9)
- 골든크로스: 매수, 데드크로스: 매도

### 볼린저밴드
- 20일 이동평균, 표준편차 x 2.5
- 하단 터치: 매수 (mean reversion), 상단 터치: 매도

### 변동성 돌파
- Larry Williams 변동성 돌파 (k=0.5)
- 당일 시가 + 전일 변동폭 * k 돌파 시 매수

### 앙상블
- 여러 전략의 시그널을 다수결 투표로 결합
- 2/3 이상 동의 시 매매, 동률이면 관망

## 리스크 관리

- 1회 최대 주문 금액 제한
- 동시 보유 종목 수 제한
- 일일 손실 한도 (초과 시 매수 차단)
- 자동 손절/익절 트리거
- 중복 시그널 방지
- API 장애 시 지수 백오프 재시도 (최대 3회)

## 프로젝트 구조

```
src/cryptolight/
  main.py              # 진입점 (스케줄러, 전략 실행 흐름)
  config/settings.py   # 환경 설정 (pydantic-settings)
  exchange/
    base.py            # 거래소 추상 인터페이스
    upbit.py           # 업비트 REST 클라이언트
  strategy/
    base.py            # BaseStrategy + Signal
    rsi.py             # RSI 전략
    macd.py            # MACD 전략
    bollinger.py       # 볼린저밴드 전략
    volatility_breakout.py  # 변동성 돌파 전략
    ensemble.py        # 앙상블 전략
  execution/
    base.py            # BaseBroker 인터페이스
    paper_broker.py    # Paper Trading 브로커
    live_broker.py     # 업비트 실거래 브로커
  risk/
    risk_guard.py      # 리스크 관리 모듈
  storage/
    models.py          # TradeRecord, PositionSnapshot
    repository.py      # SQLite 거래/포지션 저장소
  bot/
    telegram_bot.py    # 텔레그램 알림
    command_handler.py # 텔레그램 명령어 처리
  backtest/
    engine.py          # 백테스트 엔진
    data_loader.py     # 과거 캔들 데이터 로더
    __main__.py        # 백테스트 CLI
```
