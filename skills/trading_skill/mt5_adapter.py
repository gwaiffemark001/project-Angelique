from __future__ import annotations

from typing import Any, Protocol


class MT5Adapter(Protocol):
    """The only interface the trading workflow uses for MT5/Wine."""

    def account(self, mode: str, symbol: str | None = None) -> dict[str, Any]: ...
    def symbols(self, mode: str, symbol: str | None = None) -> list[str]: ...
    def market(self, symbol: str, timeframes: tuple[str, ...], mode: str, count: int) -> dict[str, Any]: ...
    def execute(self, order: dict[str, Any], mode: str) -> dict[str, Any]: ...
    def positions(self, mode: str) -> dict[str, Any]: ...
    def recent_deals(self, mode: str, minutes: int = 60) -> dict[str, Any]: ...
    def calculate_profit(self, mode: str, symbol: str, direction: str, volume: float, price_open: float, price_close: float) -> dict[str, Any]: ...


class WineMT5Adapter:
    """Adapter boundary for the MT5 Python process running inside Wine."""

    def __init__(self, bridge_client: Any):
        self.bridge = bridge_client

    def account(self, mode: str, symbol: str | None = None) -> dict[str, Any]:
        payload = {"account_mode": mode}
        if symbol:
            payload["symbol"] = symbol
        return self.bridge.request("account", payload)

    def symbols(self, mode: str, symbol: str | None = None) -> list[str]:
        payload = {"account_mode": mode}
        if symbol:
            payload["symbol"] = symbol
        response = self.bridge.request("symbols", payload)
        return list(response.get("symbols", []))

    def market(self, symbol: str, timeframes: tuple[str, ...], mode: str, count: int) -> dict[str, Any]:
        return self.bridge.request("market", {"symbol": symbol, "timeframes": list(timeframes), "account_mode": mode, "count": count})

    def execute(self, order: dict[str, Any], mode: str) -> dict[str, Any]:
        return self.bridge.request("execute", {"order": order, "account_mode": mode})

    def positions(self, mode: str) -> dict[str, Any]:
        return self.bridge.request("positions", {"account_mode": mode})

    def recent_deals(self, mode: str, minutes: int = 60) -> dict[str, Any]:
        return self.bridge.request("recent_deals", {"account_mode": mode, "minutes": int(minutes)})

    def calculate_profit(self, mode: str, symbol: str, direction: str, volume: float, price_open: float, price_close: float) -> dict[str, Any]:
        return self.bridge.request("calculate_profit", {"account_mode": mode, "symbol": symbol, "direction": direction, "volume": float(volume), "price_open": float(price_open), "price_close": float(price_close)})

    # -- broker-authoritative calculations ---------------------------------
    def calculate_margin(self, mode: str, symbol: str, direction: str, volume: float,
                         price: float) -> dict[str, Any]:
        return self.bridge.request("calculate_margin", {
            "account_mode": mode, "symbol": symbol, "direction": direction,
            "volume": float(volume), "price": float(price),
        })

    def symbol_specs(self, mode: str, symbols: list[str] | str) -> dict[str, Any]:
        """READ-ONLY full broker specification. This never sends an order."""
        names = [symbols] if isinstance(symbols, str) else list(symbols)
        return self.bridge.request("symbol_specs", {"account_mode": mode, "symbols": names})

    def order_preflight(self, mode: str, symbol: str, direction: str, volume: float,
                        price: float, stop_loss: float | None = None,
                        take_profit: float | None = None) -> dict[str, Any]:
        """Broker-side OrderCheck. Validates without sending."""
        payload: dict[str, Any] = {
            "account_mode": mode, "symbol": symbol, "direction": direction,
            "volume": float(volume), "price": float(price),
        }
        if stop_loss:
            payload["stop_loss"] = float(stop_loss)
        if take_profit:
            payload["take_profit"] = float(take_profit)
        return self.bridge.request("order_preflight", payload)


class BrokerCalculatorAdapter:
    """Bind an :class:`MT5Adapter` and account mode to the ``BrokerCalculator``
    protocol used by :mod:`broker_calc` and :mod:`execution_preflight`.

    This is the ONLY route by which the engine obtains monetary values for an
    execution decision. If the underlying bridge cannot answer, the calling
    code blocks the trade rather than substituting an estimate.
    """

    def __init__(self, adapter: Any, mode: str = "demo"):
        self.adapter = adapter
        self.mode = mode

    def calculate_profit(self, symbol: str, direction: str, volume: float,
                         price_open: float, price_close: float) -> dict[str, Any]:
        return self.adapter.calculate_profit(self.mode, symbol, direction, volume,
                                             price_open, price_close)

    def calculate_margin(self, symbol: str, direction: str, volume: float,
                         price: float) -> dict[str, Any]:
        calculate = getattr(self.adapter, "calculate_margin", None)
        if calculate is None:
            return {"status": "error",
                    "error": "This MT5 adapter does not implement order_calc_margin."}
        return calculate(self.mode, symbol, direction, volume, price)

    def order_check(self, request: dict[str, Any]) -> dict[str, Any]:
        preflight = getattr(self.adapter, "order_preflight", None)
        if preflight is None:
            return {"retcode": -1, "comment": "This MT5 adapter does not implement OrderCheck."}
        return preflight(
            self.mode, request.get("symbol"), request.get("type"), request.get("volume"),
            request.get("price"), request.get("sl"), request.get("tp"),
        )
