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

## 3단계: Paper Trading (Day 3)
- [ ] paper trading 구현
- [ ] 주문 로그 저장
- [ ] 손익 계산

## 4단계: 리스크 관리 (Day 4)
- [ ] 리스크 가드 추가
- [ ] 최대 주문금액 제한
- [ ] 손절/익절 규칙

## 5단계: 실거래 (Day 5)
- [ ] 소액 실거래 테스트
- [ ] 장애 로그 확인
- [ ] 텔레그램 명령어 추가
