---
name: exchange-api-patterns
description: 거래소 API 연동 패턴. 업비트 인증, rate limit 관리, WebSocket 수신, 주문 안전장치 구현 패턴 제공.
---

# 거래소 API 패턴

## 업비트 JWT 인증

```python
import hashlib, uuid, jwt
from urllib.parse import urlencode

def upbit_auth_header(access_key: str, secret_key: str, params: dict = None) -> dict:
    payload = {"access_key": access_key, "nonce": str(uuid.uuid4())}
    if params:
        query = urlencode(params).encode()
        m = hashlib.sha512()
        m.update(query)
        payload["query_hash"] = m.hexdigest()
        payload["query_hash_alg"] = "SHA512"
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}
```

## Rate Limit 관리

```python
import asyncio, time

class RateLimiter:
    def __init__(self, max_per_second=10, max_per_minute=600):
        self._second_tokens = max_per_second
        self._minute_tokens = max_per_minute
        self._lock = asyncio.Lock()
        self._last_refill = time.monotonic()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._second_tokens = min(10, self._second_tokens + elapsed * 10)
            self._last_refill = now
            if self._second_tokens < 1:
                await asyncio.sleep(0.1)
            self._second_tokens -= 1
```

## WebSocket 수신 (업비트)

```python
import json, websockets

async def upbit_websocket(symbols: list[str], callback):
    uri = "wss://api.upbit.com/websocket/v1"
    subscribe = [
        {"ticket": "cryptolight"},
        {"type": "ticker", "codes": symbols},
    ]
    while True:
        try:
            async with websockets.connect(uri, ping_interval=30) as ws:
                await ws.send(json.dumps(subscribe))
                async for msg in ws:
                    data = json.loads(msg)
                    await callback(data)
        except websockets.ConnectionClosed:
            await asyncio.sleep(3)  # 재연결 대기
```

## Paper Trading 브로커

```python
@dataclass
class PaperBroker:
    balance_krw: float
    positions: dict = field(default_factory=dict)
    commission_rate: float = 0.0005

    def buy_market(self, symbol: str, amount_krw: float, current_price: float) -> OrderResult:
        commission = amount_krw * self.commission_rate
        net_amount = amount_krw - commission
        quantity = net_amount / current_price
        self.balance_krw -= amount_krw
        self.positions[symbol] = self.positions.get(symbol, 0) + quantity
        return OrderResult(...)

    def sell_market(self, symbol: str, quantity: float, current_price: float) -> OrderResult:
        proceeds = quantity * current_price
        commission = proceeds * self.commission_rate
        self.balance_krw += proceeds - commission
        self.positions[symbol] -= quantity
        return OrderResult(...)
```

## 주문 안전 체크리스트

```python
def pre_order_check(signal, portfolio, market, settings) -> tuple[bool, str]:
    # 1. 모드 확인
    if settings.trade_mode != "live":
        return False, "paper 모드"

    # 2. 최대 주문금액
    if signal.amount > settings.max_order_amount_krw:
        return False, "최대 주문금액 초과"

    # 3. 일일 손실 한도
    if portfolio.daily_loss >= settings.daily_loss_limit_krw:
        return False, "일일 손실 한도 도달"

    # 4. 중복 주문
    if signal.symbol in portfolio.pending_orders:
        return False, "중복 주문"

    # 5. 최소 주문금액 (업비트: 5,000 KRW)
    if signal.amount < 5000:
        return False, "최소 주문금액 미달"

    return True, "통과"
```
