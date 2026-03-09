# cryptolight

업비트 기반 코인 자동매매 봇. 멀티팩터 스코어 전략, 시장 국면 감지, AI 어시스턴트, 자기개선 루프를 지원한다.

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

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
| `TRADE_MODE` | 거래 모드 (`paper` / `live`) | `paper` |
| `STRATEGY_NAME` | 매매 전략 | `score` |
| `TARGET_SYMBOLS` | 대상 종목 | `KRW-BTC,KRW-ETH` |
| `GOOGLE_API_KEY` | Gemini AI API 키 (/ask용) | (선택) |
| `GEMINI_MODEL` | Gemini 모델명 | `gemini-2.5-flash` |

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

| 국면 | 특징 | MACD 가중치 | BB 가중치 | 매수 임계값 |
|------|------|-----------|----------|-----------|
| 추세장 (trending) | ADX >= 25 | 1.5x | 0.5x | 55점 |
| 횡보장 (sideways) | ADX < 25, 변동 낮음 | 0.5x | 1.5x | 65점 |
| 변동장 (volatile) | BB 폭 >= 6% | 1.0x | 1.0x | 75점 |

**안전 장치**:
- confidence 게이트: 신뢰도 40% 미만 시 주문 자동 차단
- 거래량 부족 시 시그널 무시

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
| `/ask <질문>` | AI에게 질문 (Gemini, 일일 10회 제한) |
| `/status` | 봇 상태 조회 |
| `/report` | 일일 요약 리포트 |
| `/mute` | 자동 알림 끄기 (시그널, 급등/급락) |
| `/unmute` | 자동 알림 켜기 |
| `/stop` | 긴급 거래 중지 (킬스위치) |
| `/help` | 명령어 목록 |

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

매주 일요일 03:00 KST에 자동 실행 (`ENABLE_AUTO_OPTIMIZATION=true` 설정 시):

1. **성과 평가** — Sharpe ratio, 승률, MDD 분석
2. **전략 경쟁** — 다중 전략 백테스트 비교 (Arena)
3. **파라미터 최적화** — Random Search + Walk-Forward 검증
4. **자동 전환** — Sharpe 개선폭 >= 0.5일 때 전략 교체
5. **롤백** — 전환 후 성과 악화 시 이전 전략으로 복원

## 리스크 관리

- 1회 최대 주문 금액 제한 + Live 하드캡
- 동시 보유 종목 수 제한
- 일일 손실 한도 (초과 시 매수 차단)
- 자동 손절/익절/트레일링 스톱
- confidence 게이트 (낮은 신뢰도 시그널 차단)
- 중복 시그널 방지 + 매매 쿨다운
- API 장애 시 지수 백오프 재시도 (주문 API는 재시도 안 함)
- SQLite WAL 모드 + 스레드 안전

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
  health.py                # 헬스 모니터
```

## 테스트

```bash
pytest                # 전체 테스트 (136개)
ruff check src/       # 린트
ruff format src/      # 포맷
```

## 라이선스

MIT
