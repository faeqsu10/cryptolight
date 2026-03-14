# Lessons Learned

이 파일은 개발 과정에서 배운 교훈을 기록하여 같은 실수를 반복하지 않기 위한 것이다.

## 스레드 안전성

- **공유 상태에 Lock 필수**: WebSocket 스레드와 스케줄러 스레드가 동시에 `_trailing_highs`, 주문 API를 접근할 수 있다. 공유 mutable 상태에는 반드시 `threading.Lock()`을 추가할 것.
- **LiveBroker 주문 직렬화**: httpx 클라이언트가 동시에 호출되면 JWT 토큰 충돌 가능. `_order_lock`으로 매수/매도를 직렬화.

## WebSocket

- **fallback 패턴**: WebSocket 연결 시 폴링 일시 정지, 끊김 시 자동 재개. 두 경로가 동시에 주문하지 않도록 설계.
- **지수 백오프 재연결**: 1s → 2s → 4s → ... → max. 연결 성공 시 즉시 1s로 초기화.
- **업비트 SIMPLE 포맷**: `{"format": "SIMPLE"}` 추가하면 `cd`(종목코드), `tp`(체결가) 등 축약 키로 응답. 바이트 메시지로 수신됨.

## logging 포맷

- `logger.info("가격: %,.0f", price)` → **지원 안 됨**. `%` 포맷에서 쉼표 구분자 불가.
- 대안: `logger.info("가격: %s", f"{price:,.0f}")` — f-string으로 포맷 후 `%s`로 전달.

## pyproject.toml

- 빌드 백엔드 경로: `hatchling.build` (~~hatchling.backends~~)

## 주문 안전

- **주문 API 실패 후 재시도 금지**: 중복 주문 위험. 실패 시 로그만 남기고 다음 주기에 재시도.
- **리스크 가드 우회 금지**: 모든 주문은 반드시 RiskGuard를 통과해야 함.

## 테스트

- WebSocket 단위 테스트는 실제 연결 없이 `_on_message`, `_on_open`, `_on_close` 직접 호출로 검증 가능.
- `run_forever`는 mock으로 대체하여 스레드 라이프사이클 테스트.
