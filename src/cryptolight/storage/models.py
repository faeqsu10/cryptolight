from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TradeRecord:
    symbol: str
    side: str  # buy / sell
    price: float
    quantity: float
    amount_krw: float
    commission: float
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    id: int | None = None


@dataclass
class PositionSnapshot:
    symbol: str
    quantity: float
    avg_price: float
    current_price: float

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_price == 0:
            return 0.0
        return (self.current_price - self.avg_price) / self.avg_price * 100
