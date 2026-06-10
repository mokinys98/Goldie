import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from .models import AccountData, CandleData, SymbolData, TickData
from .settings import AgentSettings


class ReadOnlyBrokerAdapter(Protocol):
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def account(self) -> AccountData: ...
    def symbol(self) -> SymbolData: ...
    def tick(self) -> TickData: ...
    def completed_m1_candles(self, count: int) -> list[CandleData]: ...


class FakeBrokerAdapter:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self._connected = False
        self._random = random.Random(42)
        self._base = Decimal("2350.00")
        self._candles = self._make_candles()

    def _make_candles(self) -> list[CandleData]:
        current_minute = datetime.now(UTC).replace(second=0, microsecond=0)
        rows: list[CandleData] = []
        price = self._base
        for index in range(12, 0, -1):
            movement = Decimal(str(round(math.sin(index / 2) * 0.4 + 0.22, 2)))
            close = price + movement
            rows.append(
                CandleData(
                    symbol="XAUUSD",
                    opened_at=current_minute - timedelta(minutes=index),
                    open=price,
                    high=max(price, close) + Decimal("0.08"),
                    low=min(price, close) - Decimal("0.08"),
                    close=close,
                    tick_volume=100 + index,
                )
            )
            price = close
        self._base = price
        return rows

    def connect(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def account(self) -> AccountData:
        return AccountData(
            observed_at=datetime.now(UTC),
            broker="Goldie Fake Broker",
            server="local-demo",
            login="100001",
            currency="EUR",
            balance=Decimal("10000"),
            equity=Decimal("10000"),
            margin_free=Decimal("10000"),
            leverage=100,
            is_demo=True,
        )

    def symbol(self) -> SymbolData:
        return SymbolData(
            symbol="XAUUSD",
            digits=2,
            point=Decimal("0.01"),
            tick_size=Decimal("0.01"),
            tick_value=Decimal("1"),
            contract_size=Decimal("100"),
            volume_min=Decimal("0.01"),
            volume_max=Decimal("100"),
            volume_step=Decimal("0.01"),
        )

    def tick(self) -> TickData:
        noise = Decimal(str(round(self._random.uniform(-0.03, 0.03), 2)))
        bid = self._base + noise
        return TickData(
            symbol="XAUUSD",
            observed_at=datetime.now(UTC),
            bid=bid,
            ask=bid + Decimal("0.20"),
        )

    def completed_m1_candles(self, count: int) -> list[CandleData]:
        return self._candles[-count:]


class Mt5ReadOnlyAdapter:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self._mt5 = None
        self._symbol: str | None = None

    def connect(self) -> None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError("Install the agent with the 'mt5' extra on Windows") from exc
        self._mt5 = mt5
        kwargs = {}
        if self.settings.mt5_terminal_path:
            kwargs["path"] = self.settings.mt5_terminal_path
        if self.settings.mt5_login:
            kwargs["login"] = self.settings.mt5_login
        if self.settings.mt5_password:
            kwargs["password"] = self.settings.mt5_password
        if self.settings.mt5_server:
            kwargs["server"] = self.settings.mt5_server
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
        self._symbol = self._find_symbol()

    def close(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()

    def _find_symbol(self) -> str:
        symbols = self._mt5.symbols_get()
        if symbols is None:
            raise RuntimeError(f"Cannot read MT5 symbols: {self._mt5.last_error()}")
        hint = self.settings.mt5_symbol_hint.upper()
        candidates = [item.name for item in symbols if hint in item.name.upper()]
        if not candidates:
            raise RuntimeError(f"No symbol contains hint '{hint}'")
        candidates.sort(key=lambda value: (len(value), value))
        symbol = candidates[0]
        if not self._mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Cannot select symbol '{symbol}'")
        return symbol

    def account(self) -> AccountData:
        info = self._mt5.account_info()
        terminal = self._mt5.terminal_info()
        if info is None or terminal is None:
            raise RuntimeError(f"Cannot read account: {self._mt5.last_error()}")
        demo_mode = getattr(self._mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        return AccountData(
            observed_at=datetime.now(UTC),
            broker=getattr(info, "company", "Unknown"),
            server=getattr(info, "server", "Unknown"),
            login=str(info.login),
            currency=info.currency,
            balance=Decimal(str(info.balance)),
            equity=Decimal(str(info.equity)),
            margin_free=Decimal(str(info.margin_free)),
            leverage=info.leverage,
            is_demo=info.trade_mode == demo_mode,
        )

    def symbol(self) -> SymbolData:
        info = self._mt5.symbol_info(self._symbol)
        if info is None:
            raise RuntimeError(f"Cannot read symbol: {self._mt5.last_error()}")
        return SymbolData(
            symbol=info.name,
            digits=info.digits,
            point=Decimal(str(info.point)),
            tick_size=Decimal(str(info.trade_tick_size)),
            tick_value=Decimal(str(info.trade_tick_value)),
            contract_size=Decimal(str(info.trade_contract_size)),
            volume_min=Decimal(str(info.volume_min)),
            volume_max=Decimal(str(info.volume_max)),
            volume_step=Decimal(str(info.volume_step)),
        )

    def tick(self) -> TickData:
        tick = self._mt5.symbol_info_tick(self._symbol)
        if tick is None:
            raise RuntimeError(f"Cannot read tick: {self._mt5.last_error()}")
        return TickData(
            symbol=self._symbol,
            observed_at=datetime.fromtimestamp(tick.time_msc / 1000, tz=UTC),
            bid=Decimal(str(tick.bid)),
            ask=Decimal(str(tick.ask)),
        )

    def completed_m1_candles(self, count: int) -> list[CandleData]:
        rates = self._mt5.copy_rates_from_pos(self._symbol, self._mt5.TIMEFRAME_M1, 1, count)
        if rates is None:
            raise RuntimeError(f"Cannot read M1 candles: {self._mt5.last_error()}")
        return [
            CandleData(
                symbol=self._symbol,
                opened_at=datetime.fromtimestamp(int(item["time"]), tz=UTC),
                open=Decimal(str(item["open"])),
                high=Decimal(str(item["high"])),
                low=Decimal(str(item["low"])),
                close=Decimal(str(item["close"])),
                tick_volume=int(item["tick_volume"]),
            )
            for item in rates
        ]


def create_adapter(settings: AgentSettings) -> ReadOnlyBrokerAdapter:
    if settings.agent_mode == "fake":
        return FakeBrokerAdapter(settings)
    if settings.agent_mode == "mt5":
        return Mt5ReadOnlyAdapter(settings)
    raise ValueError(f"Unsupported agent mode: {settings.agent_mode}")
