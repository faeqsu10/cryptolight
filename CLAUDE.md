# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cryptolight — 업비트 기반 코인 자동매매봇 (signalight에서 진화한 암호화폐 트레이딩 시스템)

## Commands

- **실행**: `source .venv/bin/activate && python -m cryptolight.main`
- **의존성 설치**: `pip install -e ".[dev]"`
- **테스트**: `pytest`
- **린트**: `ruff check src/`
- **포맷**: `ruff format src/`

## Architecture

```
src/cryptolight/
├── config/          # 환경변수 기반 설정 (pydantic-settings)
├── exchange/        # 거래소 API 클라이언트 (업비트, 추후 바이낸스)
│   ├── base.py      # 추상 인터페이스 (ExchangeClient)
│   └── upbit.py     # 업비트 구현 (REST + JWT 인증)
├── market/          # 시세 데이터 수집/가공 (캔들, 호가, WebSocket)
├── strategy/        # 매매 전략 (RSI, 돌파, 추세추종)
├── execution/       # 주문 실행 (OrderManager, PaperBroker)
├── risk/            # 리스크 관리 (손절, 익절, 킬스위치)
├── portfolio/       # 포지션/잔고 관리
├── bot/             # 텔레그램 알림
├── utils/           # 로깅, 공통 유틸
└── main.py          # 진입점
```

**핵심 데이터 흐름**:
```
Exchange API → Market Data → Strategy(판단) → Risk Guard(검증) → Execution(주문) → Portfolio(상태)
                                                                        ↓
                                                                  Telegram 알림
```

## Environment Variables (.env)

```bash
# 필수 — 거래소
UPBIT_ACCESS_KEY=               # 업비트 API Access Key
UPBIT_SECRET_KEY=               # 업비트 API Secret Key

# 필수 — 알림
TELEGRAM_BOT_TOKEN=             # 텔레그램 봇 토큰
TELEGRAM_CHAT_ID=               # 텔레그램 채팅 ID

# 거래 설정 (기본값 있음)
TRADE_MODE=paper                # paper | live
MAX_ORDER_AMOUNT_KRW=50000      # 1회 최대 주문금액
DAILY_LOSS_LIMIT_KRW=100000     # 일일 손실 한도
TARGET_SYMBOLS=KRW-BTC,KRW-ETH  # 대상 종목

# 로깅
LOG_LEVEL=INFO
```

## Tech Stack

- **Python 3.11+**
- **httpx** — HTTP 클라이언트 (sync/async)
- **pyjwt** — 업비트 JWT 인증
- **pydantic-settings** — 환경변수 설정 관리
- **pandas** — 데이터 처리
- **python-telegram-bot** — 텔레그램 알림
- **SQLite** — 거래 로그 저장 (추후 PostgreSQL)
- **pytest** — 테스트
- **ruff** — 린트/포맷

---

## Core Principles

### 1. Simplicity First
- 가장 간단한 방법으로 구현. 최소한의 코드만 변경
- 근본 원인을 찾아 수정. 임시 해결책 금지
- 필요한 부분만 수정. 불필요한 리팩토링 하지 않기

### 2. Configuration External
- **모든 설정값은 코드 외부에서 관리** (환경변수, .env)
- ✅ `settings.max_order_amount_krw` (pydantic-settings)
- ❌ `MAX_AMOUNT = 50000` (하드코딩)

### 3. Safety First (자동매매 특수 원칙)
- **모든 주문은 리스크 가드를 통과해야 함**
- dry-run/paper trading이 기본 모드
- 실거래 전환 시 소액부터 시작
- 거래소 API 장애 시 즉시 거래 중지
- 킬스위치는 항상 작동 가능해야 함

### 4. Strategy ≠ Execution
- 전략은 판단만 한다 (buy/sell/hold 시그널)
- 실제 주문은 execution 계층이 담당
- 리스크 가드가 중간에서 검증

---

## Workflow Orchestration

### Plan First
- 3+ 단계 또는 설계 결정이 필요한 작업은 반드시 계획 먼저
- 잘못된 방향이면 즉시 멈추고 재계획
- `tasks/todo.md`에 체크 가능한 항목으로 계획 작성

### Subagent Strategy
- 서브에이전트를 적극 활용하여 메인 컨텍스트 깨끗하게 유지
- 리서치, 탐색, 병렬 분석은 서브에이전트에 위임
- 복잡한 문제는 서브에이전트로 더 많은 계산 투입

### Self-Improvement Loop
- 사용자 교정 후: `tasks/lessons.md`에 패턴 기록
- 같은 실수 반복 방지 규칙 작성
- 세션 시작 시 lessons.md 검토

### Verification Before Done
- 작업 완료 전 반드시 동작 증명 (테스트, 로그, 실행)
- "staff engineer가 승인할 수준인가?" 자문
- 테스트 실행, 로그 확인, 정확성 입증

### Auto Commit & Push
- 의미 있는 단위의 작업이 완료되면 사용자가 요청하지 않아도 알아서 커밋하고 푸시
- `.env`, 시크릿 파일은 절대 커밋하지 않음
- 커밋 메시지는 아래 Git Commit Convention을 따름

### Autonomous Bug Fixing
- 버그 리포트 받으면 바로 수정. 질문하지 않기
- 로그, 에러, 실패 테스트를 찾아서 해결
- 사용자의 컨텍스트 전환 불필요

---

## Task Management

1. **Plan First**: `tasks/todo.md`에 체크 가능 항목으로 계획
2. **Verify Plan**: 구현 전 계획 확인
3. **Track Progress**: 진행하면서 항목 완료 표시
4. **Explain Changes**: 각 단계에서 고수준 요약
5. **Document Results**: `tasks/todo.md`에 리뷰 섹션 추가
6. **Capture Lessons**: 교정 후 `tasks/lessons.md` 업데이트

---

## Git Commit Convention

### 형식
```
<타입>(<범위>): <한국어 설명 35자 이내>

<본문 - 선택적, 한국어>

<꼬리말 - 선택적>
```

### 규칙
- **타입, scope**: 영어 소문자
- **설명 (제목), 본문**: 한국어
- **마침표, 이모지**: 금지

### 타입 목록

| 타입 | 용도 |
|------|------|
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `docs` | 문서만 변경 |
| `style` | 코드 포맷/스타일만 변경 |
| `refactor` | 리팩토링 (기능/버그 변경 없음) |
| `test` | 테스트 추가/수정 |
| `chore` | 빌드, 설정, 패키지 변경 |

### Scope 목록

`exchange` · `market` · `strategy` · `execution` · `risk` · `portfolio` · `bot` · `config` · `backtest`

### 예시

```
feat(exchange): 업비트 캔들 조회 구현
fix(risk): 일일 손실 한도 계산 오류 수정
refactor(strategy): RSI 전략 시그널 인터페이스 통일
```

---

## Specialized Agents

프로젝트 전문 에이전트 정의는 `agents/` 디렉토리에 있다. 서브에이전트 생성 시 참고.

| 에이전트 | 파일 | 역할 |
|---------|------|------|
| **quant-analyst** | `agents/quant-analyst.md` | 전략 개발, 백테스트, 시장 데이터 분석 |
| **risk-manager** | `agents/risk-manager.md` | 리스크 관리, 포지션 사이징, 킬스위치 |
| **exchange-engineer** | `agents/exchange-engineer.md` | 거래소 API, WebSocket, 주문 실행 |
| **strategy-developer** | `agents/strategy-developer.md` | 매매 전략 설계/구현, 시그널 생성 |
| **backtest-engineer** | `agents/backtest-engineer.md` | 백테스트 시스템, 성과 검증 |

스킬 참고 자료는 `agents/skills/`에 있다:
- `backtesting-frameworks.md` — 벡터화 백테스터, 성과 지표 계산 패턴
- `risk-metrics.md` — VaR, CVaR, R-multiple, 포지션 사이징 패턴
- `exchange-api-patterns.md` — 업비트 인증, WebSocket, Paper trading 패턴

---

## Exchange API Patterns

### 거래소 클라이언트 구조
```python
# 추상 인터페이스를 통한 거래소 교체 가능 설계
class ExchangeClient(ABC):
    def get_balances(self) -> list[Balance]: ...
    def get_candles(self, symbol, interval, count) -> list[Candle]: ...
    def buy_market(self, symbol, amount_krw) -> OrderResult: ...
    def sell_market(self, symbol, quantity) -> OrderResult: ...
```

### API 호출 안전 규칙
- 업비트 API rate limit 준수 (초당 10회 / 분당 600회)
- 인증 필요 API는 JWT 토큰 매 요청마다 생성
- 네트워크 에러 시 지수 백오프 재시도 (최대 3회)
- 주문 API 실패 시 재시도하지 않음 (중복 주문 방지)

### 주문 안전장치 체크리스트
- [ ] 1회 최대 주문금액 제한
- [ ] 일일 손실 한도
- [ ] 동시 보유 종목 수 제한
- [ ] 손절/익절 규칙
- [ ] 중복 주문 방지
- [ ] 거래소 최소 주문 금액/수량 단위 검증
- [ ] API 장애 시 거래 중지
- [ ] 킬스위치

---

## Logging

### 필수 로그 항목
- 주문 요청/응답
- 체결 결과
- 잔고 변화
- 전략 판단 근거
- 예외/에러
- 거래소 응답 지연

### 포맷
```python
# 표준 로그 포맷
"%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

# logging 모듈의 % 포맷에서는 쉼표 구분자(%,) 사용 불가
# ✅ f-string으로 포맷 후 %s로 전달: logger.info("가격: %s", f"{price:,.0f}")
# ❌ logger.info("가격: %,.0f", price)
```

---

## Key Lessons Learned

### 절대 하지 말 것
- 주문 API 실패 후 자동 재시도 (중복 주문 위험)
- 리스크 가드 없이 직접 주문
- API 키를 코드에 하드코딩
- logging의 % 포맷에서 `%,` 구분자 사용 (지원 안 됨)
- `hatchling.backends` → 올바른 경로는 `hatchling.build`

### 반드시 할 것
- 환경변수에 기본값 제공 (pydantic-settings의 default)
- 모든 주문 전 리스크 가드 통과 확인
- paper trading으로 먼저 검증
- 거래소 API 응답 로깅
- .env 파일은 .gitignore에 포함
