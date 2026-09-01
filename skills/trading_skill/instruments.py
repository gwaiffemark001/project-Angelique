"""Broker-metadata-driven instrument classification and price-unit semantics.

Design rule enforced by this module
-----------------------------------
MT5 symbol metadata is the *execution source of truth*. A conventional FX "pip"
is a **display/analysis** unit that is only meaningful for FX instruments.
Metals, crypto, indices, energies and equity CFDs must NOT inherit an FX pip
model; they are expressed in the symbol's own price / tick / point terms.

Classification order of preference:

1. ``trade_calc_mode``    (MT5 profit/margin calculation mode)
2. ``currency_base`` / ``currency_profit`` / ``currency_margin``
3. ``path``               (broker Market Watch tree, e.g. ``Forex\\Majors\\EURUSD``)
4. ``description``
5. symbol *name* -- last resort only, because broker suffixes (``.VX``, ``m``,
   ``.a``, ``_i``, ``#``) and prefixes make names unreliable.

References (MT5 Python API):
  symbol_info():   digits, point, trade_tick_size, trade_tick_value,
                   trade_tick_value_profit, trade_tick_value_loss,
                   trade_contract_size, trade_calc_mode, trade_mode,
                   trade_exemode, filling_mode, trade_stops_level,
                   trade_freeze_level, volume_min/max/step/limit,
                   currency_base/profit/margin, spread, spread_float, swap_*
  symbol_info_tick(): bid, ask, last, time, time_msc
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

# --------------------------------------------------------------------------
# MT5 ENUM_SYMBOL_CALC_MODE
# --------------------------------------------------------------------------
CALC_MODE_FOREX = 0
CALC_MODE_FUTURES = 1
CALC_MODE_CFD = 2
CALC_MODE_CFDINDEX = 3
CALC_MODE_CFDLEVERAGE = 4
CALC_MODE_FOREX_NO_LEVERAGE = 5
CALC_MODE_EXCH_STOCKS = 32
CALC_MODE_EXCH_FUTURES = 33
CALC_MODE_EXCH_FUTURES_FORTS = 34
CALC_MODE_EXCH_BONDS = 35
CALC_MODE_EXCH_STOCKS_MOEX = 36
CALC_MODE_EXCH_BONDS_MOEX = 37
CALC_MODE_SERV_COLLATERAL = 64

CALC_MODE_NAMES = {
    CALC_MODE_FOREX: "FOREX",
    CALC_MODE_FUTURES: "FUTURES",
    CALC_MODE_CFD: "CFD",
    CALC_MODE_CFDINDEX: "CFD_INDEX",
    CALC_MODE_CFDLEVERAGE: "CFD_LEVERAGE",
    CALC_MODE_FOREX_NO_LEVERAGE: "FOREX_NO_LEVERAGE",
    CALC_MODE_EXCH_STOCKS: "EXCH_STOCKS",
    CALC_MODE_EXCH_FUTURES: "EXCH_FUTURES",
    CALC_MODE_EXCH_FUTURES_FORTS: "EXCH_FUTURES_FORTS",
    CALC_MODE_EXCH_BONDS: "EXCH_BONDS",
    CALC_MODE_EXCH_STOCKS_MOEX: "EXCH_STOCKS_MOEX",
    CALC_MODE_EXCH_BONDS_MOEX: "EXCH_BONDS_MOEX",
    CALC_MODE_SERV_COLLATERAL: "SERV_COLLATERAL",
}
FOREX_CALC_MODES = {CALC_MODE_FOREX, CALC_MODE_FOREX_NO_LEVERAGE}

# ENUM_SYMBOL_TRADE_MODE
TRADE_MODE_DISABLED = 0
TRADE_MODE_LONGONLY = 1
TRADE_MODE_SHORTONLY = 2
TRADE_MODE_CLOSEONLY = 3
TRADE_MODE_FULL = 4
TRADE_MODE_NAMES = {
    TRADE_MODE_DISABLED: "DISABLED",
    TRADE_MODE_LONGONLY: "LONG_ONLY",
    TRADE_MODE_SHORTONLY: "SHORT_ONLY",
    TRADE_MODE_CLOSEONLY: "CLOSE_ONLY",
    TRADE_MODE_FULL: "FULL",
}

# ENUM_SYMBOL_TRADE_EXECUTION
EXEMODE_NAMES = {0: "REQUEST", 1: "INSTANT", 2: "MARKET", 3: "EXCHANGE"}

# SYMBOL_FILLING_* bit flags
FILLING_FOK = 1
FILLING_IOC = 2
FILLING_BOC = 4

# --------------------------------------------------------------------------
# Currency / asset reference data
# --------------------------------------------------------------------------
MAJOR_CURRENCIES = frozenset({"USD", "EUR", "JPY", "GBP", "CHF", "AUD", "NZD", "CAD"})
#: Currencies that are quoted often enough to be treated as "standard" FX but
#: which are not part of the eight majors. Anything outside this union is exotic.
MINOR_CURRENCIES = frozenset({
    "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "TRY", "ZAR", "MXN", "SGD",
    "HKD", "CNH", "CNY", "THB", "ILS", "RUB", "INR", "BRL", "KRW", "TWD",
})
FX_CURRENCIES = MAJOR_CURRENCIES | MINOR_CURRENCIES

METAL_CODES = frozenset({"XAU", "XAG", "XPT", "XPD"})
CRYPTO_CODES = frozenset({
    "BTC", "XBT", "ETH", "LTC", "XRP", "BCH", "ADA", "DOT", "SOL", "DOGE",
    "LINK", "BNB", "AVAX", "MATIC", "TRX", "XLM", "UNI", "ATOM", "ETC", "SHIB",
})
ENERGY_CODES = frozenset({"WTI", "BRENT", "UKOIL", "USOIL", "XBR", "XTI", "XNG", "NGAS"})

#: Instrument classes exposed to the rest of the engine.
FX_MAJOR = "FX_MAJOR"
FX_CROSS = "FX_CROSS"
FX_EXOTIC = "FX_EXOTIC"
METAL = "METAL"
CRYPTO = "CRYPTO"
INDEX = "INDEX"
ENERGY = "ENERGY"
EQUITY = "EQUITY"
OTHER = "OTHER"

FX_CLASSES = frozenset({FX_MAJOR, FX_CROSS, FX_EXOTIC})

#: Price unit used for *display*. Execution always uses raw price + tick size.
UNIT_PIPS = "pips"
UNIT_POINTS = "points"
UNIT_PRICE = "price"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return out


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _s(value: Any) -> str:
    return str(value or "").strip()


def canonical_name(symbol: Any) -> str:
    """Uppercase alphanumeric form of a symbol name (suffix characters kept)."""
    return re.sub(r"[^A-Z0-9]", "", _s(symbol).upper())


_SUFFIX_RE = re.compile(
    r"^(?P<core>[A-Z0-9]{3,12}?)"
    r"(?P<suffix>(?:\.[A-Z0-9]{1,4})|(?:_[A-Z0-9]{1,4})|(?:[.\-#])?(?:MICRO|MINI|CASH|SPOT|ECN|RAW|PRO|STD|[MICZRPSAX]))?$",
    re.IGNORECASE,
)


def strip_broker_affixes(symbol: Any) -> str:
    """Best-effort removal of broker prefixes/suffixes from a symbol name.

    Handles ``EURUSD.VX``, ``EURUSDm``, ``XAUUSD.a``, ``BTCUSD_i``, ``#EURUSD``,
    ``EURUSD-5``, ``EURUSD.pro`` and similar broker decorations.

    This is only ever used as a *fallback*; broker metadata takes priority.
    """
    raw = _s(symbol).upper()
    if not raw:
        return ""
    raw = raw.lstrip("#$@").strip()
    # Strip everything after a separator when what remains looks like a code.
    for separator in (".", "_", "-", "/"):
        if separator in raw:
            head = raw.split(separator, 1)[0]
            if len(head) >= 3:
                raw = head
                break
    raw = re.sub(r"[^A-Z0-9]", "", raw)
    # Trailing single-letter broker tags on a 7-char string (EURUSDm -> EURUSD).
    if len(raw) == 7 and raw[:6].isalpha() and raw[6].isalpha():
        raw = raw[:6]
    for tail in ("MICRO", "MINI", "CASH", "SPOT", "ECN", "RAW", "PRO", "STD"):
        if raw.endswith(tail) and len(raw) - len(tail) >= 6:
            raw = raw[: -len(tail)]
            break
    return raw


def split_pair(symbol: Any) -> tuple[str | None, str | None]:
    """Split a 6-letter FX-style code into (base, quote) using name only."""
    core = strip_broker_affixes(symbol)
    if len(core) < 6:
        return None, None
    known = FX_CURRENCIES | METAL_CODES | CRYPTO_CODES
    for start in range(0, len(core) - 5):
        base, quote = core[start:start + 3], core[start + 3:start + 6]
        if base in known and quote in known:
            return base, quote
    if len(core) == 6 and core.isalpha():
        return core[:3], core[3:]
    return None, None


# --------------------------------------------------------------------------
# Instrument profile
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class InstrumentProfile:
    """Everything the engine needs to reason about one broker symbol.

    ``metadata_complete`` is the execution gate: if it is False the engine must
    emit ``BROKER_METADATA_INCOMPLETE`` rather than guessing.
    """

    symbol: str
    instrument_class: str
    base: str | None
    quote: str | None
    currency_base: str | None
    currency_profit: str | None
    currency_margin: str | None
    digits: int
    point: float
    tick_size: float
    tick_value: float
    tick_value_profit: float
    tick_value_loss: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    volume_limit: float
    stops_level_points: int
    freeze_level_points: int
    trade_calc_mode: int | None
    trade_mode: int | None
    trade_exemode: int | None
    filling_mode: int | None
    spread_float: bool
    swap_long: float
    swap_short: float
    swap_mode: int | None
    #: One conventional FX pip in *price* units. ``None`` for non-FX.
    pip_size: float | None
    #: Preferred display unit: ``pips`` (FX), ``points`` (metals/index/energy),
    #: or ``price`` (crypto and anything with an unusable point).
    display_unit: str
    #: How the classification was reached, for auditability.
    classification_basis: str
    metadata_complete: bool
    missing_metadata: tuple[str, ...]
    trades_24_7: bool
    raw: dict[str, Any]

    # -- convenience ------------------------------------------------------
    @property
    def is_fx(self) -> bool:
        return self.instrument_class in FX_CLASSES

    @property
    def is_metal(self) -> bool:
        return self.instrument_class == METAL

    @property
    def is_crypto(self) -> bool:
        return self.instrument_class == CRYPTO

    @property
    def trade_allowed(self) -> bool:
        return self.trade_mode in (None, TRADE_MODE_FULL)

    @property
    def trade_mode_name(self) -> str:
        return TRADE_MODE_NAMES.get(_i(self.trade_mode, -1), "UNKNOWN")

    @property
    def trade_exemode_name(self) -> str:
        return EXEMODE_NAMES.get(_i(self.trade_exemode, -1), "UNKNOWN")

    @property
    def stops_level_price(self) -> float:
        return self.stops_level_points * self.point if self.point > 0 else 0.0

    @property
    def freeze_level_price(self) -> float:
        return self.freeze_level_points * self.point if self.point > 0 else 0.0

    def relevant_assets(self) -> tuple[str, ...]:
        """Currencies / assets whose news is relevant to this instrument."""
        values: list[str] = []
        for candidate in (self.currency_base, self.currency_profit, self.base, self.quote):
            code = _s(candidate).upper()
            if code and code not in values:
                values.append(code)
        return tuple(values)

    def filling_modes(self) -> tuple[str, ...]:
        flags = _i(self.filling_mode, 0)
        out = []
        if flags & FILLING_FOK:
            out.append("FOK")
        if flags & FILLING_IOC:
            out.append("IOC")
        if flags & FILLING_BOC:
            out.append("BOC")
        return tuple(out)

    # -- unit conversion --------------------------------------------------
    def to_points(self, price_distance: float) -> float | None:
        """Convert a *price* distance to MT5 points."""
        distance = _f(price_distance)
        return distance / self.point if self.point > 0 else None

    def to_pips(self, price_distance: float) -> float | None:
        """Convert a *price* distance to conventional FX pips.

        Returns ``None`` for every non-FX instrument -- deliberately, so that
        callers cannot silently compare a gold spread against an FX pip limit.
        """
        if not self.pip_size or self.pip_size <= 0:
            return None
        return _f(price_distance) / self.pip_size

    def to_ticks(self, price_distance: float) -> float | None:
        return _f(price_distance) / self.tick_size if self.tick_size > 0 else None

    def normalize_price(self, price: float) -> float:
        """Round a price to the broker's valid price increment."""
        value = _f(price)
        if self.tick_size > 0:
            value = round(value / self.tick_size) * self.tick_size
        if self.digits > 0:
            value = round(value, self.digits)
        return value

    #: Tolerance absorbing IEEE-754 noise when snapping to the volume grid.
    #: Without it, an "ideal" volume of 0.19999999999999538 -- which is really
    #: 0.2 with float error -- would be floored to 0.19 and under-size the
    #: trade. The risk ceiling itself is never trusted to this rounding: the
    #: caller re-asks the broker for the loss at the normalised volume.
    VOLUME_GRID_EPSILON = 1e-9

    def normalize_volume(self, volume: float) -> float:
        """Floor a volume onto the broker's volume grid (never rounds up).

        "Never rounds up" holds up to ``VOLUME_GRID_EPSILON``; the authoritative
        protection is the broker re-verification in
        ``broker_calc.solve_volume_for_risk``.
        """
        value = _f(volume)
        if self.volume_step > 0:
            steps = int(value / self.volume_step + self.VOLUME_GRID_EPSILON)
            value = steps * self.volume_step
        if self.volume_max > 0:
            value = min(value, self.volume_max)
        decimals = max(0, len(f"{self.volume_step:.10f}".rstrip("0").split(".")[-1])) if self.volume_step else 2
        return round(value, min(8, max(2, decimals)))

    def describe_distance(self, price_distance: float) -> dict[str, Any]:
        """Full multi-unit description of a price distance (single source of truth)."""
        distance = _f(price_distance)
        return {
            "price": distance,
            "points": self.to_points(distance),
            "ticks": self.to_ticks(distance),
            "pips": self.to_pips(distance),
            "unit": self.display_unit,
            "instrument_class": self.instrument_class,
        }

    def format_distance(self, price_distance: float) -> str:
        """Short human-readable distance in the instrument's own natural unit.

        FX renders as pips, metals/indices/energy as points, and anything
        without a meaningful broker unit falls back to raw price. An FX pip
        label is never applied to a non-FX instrument.
        """
        described = self.describe_distance(price_distance)
        if described["unit"] == "pips" and described["pips"] is not None:
            return f"{described['pips']:.1f} pips"
        if described["unit"] == "points" and described["points"] is not None:
            return f"{described['points']:.0f} points"
        return f"{described['price']:.{max(self.digits, 2)}f}"

    def as_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values.pop("raw", None)
        values["missing_metadata"] = list(self.missing_metadata)
        values["filling_modes"] = list(self.filling_modes())
        values["trade_calc_mode_name"] = CALC_MODE_NAMES.get(_i(self.trade_calc_mode, -1), "UNKNOWN")
        values["trade_mode_name"] = TRADE_MODE_NAMES.get(_i(self.trade_mode, -1), "UNKNOWN")
        values["trade_exemode_name"] = EXEMODE_NAMES.get(_i(self.trade_exemode, -1), "UNKNOWN")
        values["relevant_assets"] = list(self.relevant_assets())
        values["stops_level_price"] = self.stops_level_price
        values["freeze_level_price"] = self.freeze_level_price
        return values


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------
def _classify_fx(base: str, quote: str) -> str:
    pair = {base, quote}
    if not pair <= FX_CURRENCIES:
        return FX_EXOTIC
    if not pair <= MAJOR_CURRENCIES:
        return FX_EXOTIC
    return FX_MAJOR if "USD" in pair else FX_CROSS


def classify(symbol: str, specs: dict[str, Any] | None = None) -> tuple[str, str | None, str | None, str]:
    """Return ``(instrument_class, base, quote, basis)``.

    ``basis`` records *which* signal decided the class so the audit report can
    show whether the broker or a name heuristic was responsible.
    """
    specs = specs or {}
    calc_mode = specs.get("trade_calc_mode", specs.get("calc_mode"))
    calc_mode = _i(calc_mode, -1) if calc_mode is not None else -1
    currency_base = _s(specs.get("currency_base")).upper() or None
    currency_profit = _s(specs.get("currency_profit")).upper() or None
    path = _s(specs.get("path")).upper()
    description = _s(specs.get("description")).upper()

    name_base, name_quote = split_pair(symbol)
    base = currency_base or name_base
    quote = currency_profit or name_quote

    # 1. Metals / crypto / energy are decided by the *asset code*, whatever the
    #    calc mode says, because brokers model them as CFD or FOREX freely.
    if base in METAL_CODES:
        return METAL, base, quote, "currency_base" if currency_base else "symbol_name"
    if base in CRYPTO_CODES or (quote in CRYPTO_CODES and base not in FX_CURRENCIES):
        return CRYPTO, base, quote, "currency_base" if currency_base else "symbol_name"
    if base in ENERGY_CODES or any(token in path for token in ("ENERG", "OIL")) or any(
        token in description for token in ("CRUDE", "BRENT", "NATURAL GAS", "WTI")
    ):
        if base in ENERGY_CODES or "OIL" in path or "ENERG" in path:
            return ENERGY, base, quote, "currency_base" if base in ENERGY_CODES else "path"

    # 2. Genuine FX calculation modes with two ISO currency codes.
    if calc_mode in FOREX_CALC_MODES and base and quote:
        if base in FX_CURRENCIES and quote in FX_CURRENCIES:
            return _classify_fx(base, quote), base, quote, "trade_calc_mode+currencies"

    # 3. Index / equity CFDs.
    if calc_mode == CALC_MODE_CFDINDEX:
        return INDEX, base, quote, "trade_calc_mode"
    if calc_mode in {CALC_MODE_EXCH_STOCKS, CALC_MODE_EXCH_STOCKS_MOEX}:
        return EQUITY, base, quote, "trade_calc_mode"
    if any(token in path for token in ("INDIC", "INDEX", "INDICES", "CASH INDEX")):
        return INDEX, base, quote, "path"
    if any(token in path for token in ("SHARE", "STOCK", "EQUIT")):
        return EQUITY, base, quote, "path"
    if any(token in path for token in ("CRYPTO", "COIN", "DIGITAL")):
        return CRYPTO, base, quote, "path"
    if any(token in path for token in ("METAL", "BULLION")):
        return METAL, base, quote, "path"

    # 4. Name-derived FX as the last resort.
    if base and quote and base in FX_CURRENCIES and quote in FX_CURRENCIES:
        return _classify_fx(base, quote), base, quote, "symbol_name"

    return OTHER, base, quote, "unclassified"


REQUIRED_EXECUTION_FIELDS = (
    "digits",
    "point",
    "tick_size",
    "contract_size",
    "volume_min",
    "volume_max",
    "volume_step",
)


def build_profile(symbol: str, specs: dict[str, Any] | None = None) -> InstrumentProfile:
    """Build an :class:`InstrumentProfile` from raw MT5 symbol metadata.

    ``specs`` accepts either MT5 field names (``trade_tick_size``) or the
    engine's short names (``tick_size``); both are read.
    """
    specs = dict(specs or {})

    def pick(*keys: str, default: Any = 0) -> Any:
        for key in keys:
            if key in specs and specs[key] is not None:
                return specs[key]
        return default

    instrument_class, base, quote, basis = classify(symbol, specs)

    digits = _i(pick("digits"), 0)
    point = _f(pick("point"), 0.0)
    tick_size = _f(pick("trade_tick_size", "tick_size"), 0.0)
    tick_value = _f(pick("trade_tick_value", "tick_value"), 0.0)
    tick_value_profit = _f(pick("trade_tick_value_profit", "tick_value_profit"), tick_value)
    tick_value_loss = _f(pick("trade_tick_value_loss", "tick_value_loss"), tick_value)
    contract_size = _f(pick("trade_contract_size", "contract_size"), 0.0)

    # Derive point from digits only when the broker genuinely omitted it.
    if point <= 0 and digits > 0:
        point = 10.0 ** (-digits)
    if tick_size <= 0 and point > 0:
        tick_size = point
    if digits <= 0 and point > 0:
        digits = max(0, round(-1 * (len(f"{point:.10f}".rstrip('0').split('.')[-1]) * -1)))

    missing = tuple(
        name
        for name, value in (
            ("digits", digits),
            ("point", point),
            ("tick_size", tick_size),
            ("contract_size", contract_size),
            ("volume_min", _f(pick("volume_min"))),
            ("volume_max", _f(pick("volume_max"))),
            ("volume_step", _f(pick("volume_step"))),
        )
        if _f(value) <= 0
    )

    pip_size = _pip_size(instrument_class, point, digits, base, quote)
    display_unit = (
        UNIT_PIPS if pip_size and pip_size > 0
        else UNIT_POINTS if point > 0
        else UNIT_PRICE
    )

    return InstrumentProfile(
        symbol=_s(symbol),
        instrument_class=instrument_class,
        base=base,
        quote=quote,
        currency_base=_s(specs.get("currency_base")).upper() or None,
        currency_profit=_s(specs.get("currency_profit")).upper() or None,
        currency_margin=_s(specs.get("currency_margin")).upper() or None,
        digits=digits,
        point=point,
        tick_size=tick_size,
        tick_value=tick_value,
        tick_value_profit=tick_value_profit or tick_value,
        tick_value_loss=tick_value_loss or tick_value,
        contract_size=contract_size,
        volume_min=_f(pick("volume_min")),
        volume_max=_f(pick("volume_max")),
        volume_step=_f(pick("volume_step")),
        volume_limit=_f(pick("volume_limit")),
        stops_level_points=_i(pick("trade_stops_level", "stops_level"), 0),
        freeze_level_points=_i(pick("trade_freeze_level", "freeze_level"), 0),
        trade_calc_mode=_i(specs["trade_calc_mode"], -1) if specs.get("trade_calc_mode") is not None else None,
        trade_mode=_i(specs["trade_mode"], -1) if specs.get("trade_mode") is not None else None,
        trade_exemode=_i(specs["trade_exemode"], -1) if specs.get("trade_exemode") is not None else None,
        filling_mode=_i(specs["filling_mode"], 0) if specs.get("filling_mode") is not None else None,
        spread_float=bool(specs.get("spread_float", True)),
        swap_long=_f(specs.get("swap_long")),
        swap_short=_f(specs.get("swap_short")),
        swap_mode=_i(specs["swap_mode"], -1) if specs.get("swap_mode") is not None else None,
        pip_size=pip_size,
        display_unit=display_unit,
        classification_basis=basis,
        metadata_complete=not missing,
        missing_metadata=missing,
        trades_24_7=instrument_class == CRYPTO,
        raw=specs,
    )


def _pip_size(instrument_class: str, point: float, digits: int, base: str | None, quote: str | None) -> float | None:
    """A conventional FX pip in price units, or ``None`` for non-FX.

    FX convention: 5-digit and 3-digit brokers quote fractional pips, so one pip
    equals ten points. 4-digit / 2-digit quotes make one pip equal one point.
    """
    if instrument_class not in FX_CLASSES:
        return None
    if point > 0:
        return point * 10 if digits in {3, 5} else point
    if _s(quote).upper() == "JPY":
        return 0.01
    return 0.0001


# --------------------------------------------------------------------------
# Legacy-compatible helpers (single implementation, no duplicate formulas)
# --------------------------------------------------------------------------
def is_metal_symbol(symbol: str, specs: dict[str, Any] | None = None) -> bool:
    return build_profile(symbol, specs).instrument_class == METAL


def is_crypto_symbol(symbol: str, specs: dict[str, Any] | None = None) -> bool:
    return build_profile(symbol, specs).instrument_class == CRYPTO
