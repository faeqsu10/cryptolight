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

## 11단계: Phase 4d 헬스체크/운영 ✅
- [x] HealthMonitor (가동시간, 에러 추적, 건강 판단)
- [x] /status 명령어 실시간 헬스 정보 응답
- [x] strategy_job 성공/실패 헬스 기록
- [x] pytest 63개

## 12단계: 멀티팩터 스코어 전략 + 자기개선 루프 ✅
- [x] ScoreBasedStrategy (RSI+MACD+BB+Volume 멀티팩터)
- [x] 시장 국면 감지 (MarketRegime: trending/sideways/volatile)
- [x] 거래량 필터 (VolumeFilter)
- [x] 성과 평가 (PerformanceEvaluator)
- [x] StrategyArena 백테스트 경쟁
- [x] AdaptiveController 전략 자동 전환
- [x] Walk-Forward 검증
- [x] 텔레그램 /info, /ask 명령어

## 13단계: 웹 대시보드 ✅
- [x] FastAPI + Jinja2 SSR 글래스모피즘 UI
- [x] API 5개 (/, /api/market, /api/portfolio, /api/trades, /api/status)
- [x] SecurityHeadersMiddleware (CSP, XSS 방지)
- [x] 127.0.0.1 기본 바인딩, API키 미노출

## 14단계: 4단계 고도화 ✅
- [x] 분봉 캔들 지원 (candle_interval 설정, 기본 4시간봉)
- [x] 업비트 거래량 상위 코인 자동 스크리닝
- [x] 신규 종목 추가 전 자동 백테스트 검증 (Sharpe ratio)
- [x] 코인 간 상관관계 필터 (피어슨 상관계수)
- [x] pytest 180개

## 15단계: 아키텍트 리뷰 10개 항목 수정 ✅
- [x] CRITICAL-1: Live 모드 손절/익절 작동 (BaseBroker 확장)
- [x] CRITICAL-2: SQLite 멀티스레드 Lock 추가
- [x] CRITICAL-3: TradeRecord strategy 필드 전 브로커 전달
- [x] HIGH-1: 자기개선 루프 전략 전환 실제 적용
- [x] HIGH-2: PaperBroker 스레드 안전
- [x] HIGH-3: Live 모드 get_balance() 일괄 조회 재활용
- [x] MEDIUM-1: daily_pnl 매수만 있는 날 음수 문제 수정
- [x] MEDIUM-2: Arena Sharpe ratio 비표준 계산 수정
- [x] MEDIUM-3: ticker 중복 호출 제거
- [x] MEDIUM-4: AI 어시스턴트 close() 누락 수정
- [x] 보유 종목 target_symbols 누락 시 가격 조회 버그 수정
- [x] pytest 197개

## 16단계: 초보자 친화 UX 개선 ✅
- [x] 매수/매도 체결 시 상세 텔레그램 알림 (종목, 금액, 수량, 사유)
- [x] 지표 해설 (RSI, MACD, 볼린저밴드 쉬운 설명)
- [x] 일일 리포트 초보자 해설 (용어 설명, 상황 판단)
- [x] 리포트에 거래 상세 내역 포함 (뭘 얼마에 사고팔았는지)
- [x] 리포트에 보유 코인 상세 현황 (수량, 매수가, 현재가, 손익)

## 17단계: 튜닝 가시성 + systemd 서비스화 ✅
- [x] /criteria 명령어 (현재 매수/매도 기준 + 초보자 설명)
- [x] /tuning 명령어 (튜닝 이력, 다음 튜닝 시간, 쿨다운)
- [x] /info 확장 (전략 기준 요약 포함)
- [x] 파라미터 튜닝 스케줄링 (6시간 주기, 전략 전환과 분리)
- [x] 튜닝 이력 SQLite 영속화 (strategy_parameter_state, parameter_adjustments)
- [x] systemd user service 등록 (재부팅 자동 복구)
- [x] 텔레그램 long polling 재시도 백오프
- [x] command handler 스레드 안전
- [x] README/pyproject.toml 수정 (jinja2 의존성, 포트/테스트 수)
- [x] pytest 210개

## 18단계: 전문가 회의 기반 CRITICAL+HIGH 수정 ✅
- [x] ScoreBasedStrategy 가중치 독립 적용 (rsi_dir, macd_hist 누락 수정)
- [x] _last_signals 주문 성공 후로 이동 (시그널 차단 버그)
- [x] Gemini API key URL→header 전환
- [x] 텔레그램 봇 토큰 로그 마스킹 추가
- [x] 웹 대시보드 HTTP Basic Auth + CORS
- [x] SQLite 전체 read 메서드 락 + busy_timeout
- [x] XSS 이스케이프 보강 (dashboard innerHTML)
- [x] Walk-Forward 시계열 순서 보존 (anchored 방식)
- [x] ParameterOptimizer/StrategyArena slippage/spread 전달
- [x] Docker 보안 강화 (non-root, cap_drop, gcc 제거)
- [x] pytest 216개

## 향후 과제
- [ ] Equity curve 시각화
- [ ] WebSocket real-time data
- [ ] 바이낸스 거래소 지원
- [ ] PostgreSQL 마이그레이션
- [ ] /tune-now 수동 튜닝 명령어
- [ ] score threshold / min_confidence 자동 튜닝
- [ ] HOLD 상태인 종목의 이유 표시
- [ ] main.py God Module 분할 (orchestrator/trading_engine/telegram_formatter/tuning_engine)
- [ ] BaseBroker 추상화 완성 (isinstance 제거)
- [ ] 트레일링 스톱 고점 DB 영속화
- [ ] 손절 후 확장 쿨다운
- [ ] 캔들 페이지네이션 (200개 제한 해소)
- [ ] 미실현 손익 기반 일일 손실 한도
