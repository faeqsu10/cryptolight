# cryptolight 개발 TODO

## 1단계: 거래소 연결 (Day 1) ✅
- [x] 프로젝트 구조 생성
- [x] 설정/로깅 세팅
- [x] 업비트 클라이언트 구현 (잔고/시세/캔들/주문)
- [x] 공개 API 연동 테스트 (현재가, 캔들)
- [x] CLAUDE.md 작성

## 2단계: 알림봇 (Day 2) ✅
- [x] RSI 전략 작성 (strategy/base.py + strategy/rsi.py)
- [x] 텔레그램 알림 연동 (bot/telegram_bot.py)
- [x] BTC/ETH 시그널 전송 (main.py 흐름 연결)

## 3단계: Paper Trading (Day 3) ✅
- [x] paper trading 구현
- [x] 주문 로그 저장
- [x] 손익 계산

## 4단계: 리스크 관리 (Day 4) ✅
- [x] 리스크 가드 추가
- [x] 최대 주문금액 제한
- [x] 손절/익절 규칙

## 5단계: 실거래 (Day 5) ✅
- [x] LiveBroker 실거래 브로커 구현
- [x] 텔레그램 명령어 추가 (/status, /stop, /help)
- [x] 킬스위치 (긴급 정지) 구현
- [x] main.py paper/live 모드 통합

## 6단계: Phase 2 확장 ✅
- [x] APScheduler 스케줄러 (5분 간격 반복 실행, --once 모드)
- [x] SIGTERM/SIGINT graceful shutdown
- [x] 텔레그램 명령어 30초 폴링 (별도 job)
- [x] 중복 시그널 방지
- [x] PaperBroker 포지션/잔고 SQLite 영속화
- [x] RSI Wilder smoothing(EMA) 정확도 개선
- [x] 변동성 돌파 전략 추가 (strategy_name 설정)
- [x] 전략 팩토리 함수
- [x] API 지수 백오프 재시도 (429/5xx 대응)
- [x] BaseBroker 공통 인터페이스
- [x] RiskGuard broker 타입 독립
- [x] 급등/급락 알림, 일일 요약 강화
- [x] Settings 통합 (스케줄러/전략/알림/DB경로)

## 7단계: Phase 3 확장 ✅
- [x] 백테스트 엔진 (수익률, Sharpe, MDD, 승률, CLI)
- [x] 업비트 캔들 페이지네이션 (to 파라미터)
- [x] MACD 전략 (골든/데드크로스)
- [x] 볼린저밴드 전략 (mean reversion)
- [x] 앙상블 전략 (다수결 투표)
- [x] 전략 팩토리 + strategy_name 설정 반영
- [x] 급등/급락 알림 (surge_alert_threshold)
- [x] 일일 요약 스케줄 (매일 09:00 KST)
- [x] /report 텔레그램 명령어
- [x] ensemble_strategies 설정

## 8단계: Phase 4 프로덕션 강화 ✅
- [x] trade_mode Literal["paper","live"] 검증
- [x] LiveBroker 하드캡 (ABSOLUTE_MAX_ORDER_KRW)
- [x] LiveBroker 주문 체결 검증 (get_order 재조회)
- [x] 트레일링 스톱 (고점 대비 N% 하락 매도)
- [x] 백테스트 슬리피지/스프레드 모델링
- [x] 백테스트 Buy&Hold 벤치마크 + Alpha
- [x] SQLite 스레드 안전 (check_same_thread=False, WAL)
- [x] 스케줄러 timezone=Asia/Seoul
- [x] RotatingFileHandler 파일 로깅
- [x] Docker 컨테이너화 (Dockerfile + docker-compose + .dockerignore)
- [x] .gitignore에 data/ 추가
- [x] pytest 단위 테스트 35개 (settings, risk, backtest, strategies, broker)
- [x] ruff 린트 클린

## 9단계: Phase 4b 고급 리스크/성능 ✅
- [x] 포지션 사이징 (fixed / percent / Kelly Criterion)
- [x] 캔들 캐시 (TTL 기반, 중복 API 호출 방지)
- [x] 이상 거래 감지 (종목별 쿨다운, 시간당 주문 횟수 제한)
- [x] main.py에 포지션 사이징/캐시/쿨다운 통합
- [x] pytest 52개 (position_sizer, cooldown, candle_cache 추가)

## 10단계: Phase 4c 보안/안정성 ✅
- [x] 토큰/API키 로그 마스킹 (RedactingFormatter)
- [x] 전략별 거래 추적 (trades 테이블 strategy 컬럼 + 마이그레이션)
- [x] 스레드 안전한 시그널 중복 방지 (threading.Lock)
- [x] pytest 56개 (logger 마스킹 테스트 추가)
