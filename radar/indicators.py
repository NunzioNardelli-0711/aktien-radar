"""Technische Kennzahlen."""
import math

import pandas as pd


def sma(series: pd.Series, n: int) -> float | None:
    if len(series) < n:
        return None
    return float(series.iloc[-n:].mean())


def rsi(closes, n: int = 14) -> float | None:
    """RSI nach Wilder."""
    s = pd.Series(list(closes), dtype="float64").dropna()
    if len(s) < n + 1:
        return None
    delta = s.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    val = 100 - 100 / (1 + rs)
    return None if math.isnan(val) else float(val)


def safe(x, digits: int = 4):
    """Zahl runden, NaN/None -> None (für JSON)."""
    try:
        if x is None:
            return None
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, digits)
    except (TypeError, ValueError):
        return None
