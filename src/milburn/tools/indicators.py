import pandas as pd
import numpy as np
import talib

from pandas import DataFrame
from milburn.tools.results import ToolResult, ToolEvent
from typing import Any


# Trend
# events: sma, price_vs_ma, slope
def calculate_sma(frame, window, price_col="close") -> ToolResult: ...
# events: golden_cross, death_cross
def calculate_sma_cross(frame, fast=50, slow=200) -> ToolResult: ...
# events: ema, price_vs_ema, slope
def calculate_ema(frame, window) -> ToolResult: ...

# Volatility
# events: atr, atr_pct
def calculate_atr(frame, period=14) -> ToolResult: ...
# events:  upper, middle, lower, bandwidth, percent_b
def calculate_bollinger_bands(frame, window=20, stddev=2.0) -> ToolResult: ...

# Momentum
# events: rsi
def calculate_rsi(frame: DataFrame, period=14) -> ToolResult:
    name: str = 'rsi'
    params = { "period": period }
    lookback = len(frame)

    frame = compute_rsi(frame, period)
    events = compute_rsi_events(frame)
    latest = float(frame["rsi"].iloc[-1])

    return ToolResult(
        name=name,
        params=params,
        lookback=lookback,
        latest=latest,
        events=events 
    )

def compute_rsi(frame: DataFrame, period=14) -> DataFrame:
    close = frame["close"].values.astype(np.float64)
    frame["rsi"] = talib.RSI(close, period)
    return frame

def compute_rsi_events(frame: DataFrame) -> list[ToolEvent]:
    events: list[ToolEvent] = []
    rsi = frame["rsi"]
    above = rsi > 70
    below = rsi < 30
    up_cross = above & ~above.shift(1, fill_value=False)
    down_cross = below & ~below.shift(1, fill_value=False)

    crossings = [
        (up_cross, "rsi_overbought", 70),
        (down_cross, "rsi_oversold", 30),
    ]
    for mask, e_type, threshold in crossings:
        for pos in np.flatnonzero(mask.to_numpy()):
            events.append(ToolEvent(
                timestamp=str(frame["timestamp"].iloc[pos].date()),
                type=e_type,
                value=float(rsi.iloc[pos]),
                details={
                    "threshold": threshold,
                    "rsi_prev": float(rsi.iloc[pos-1]),
                    "close": float(frame["close"].iloc[pos])
                },
            ))
    return events

# events: macd, signal, histogram
def calculate_macd(frame, fast=12, slow=26, signal=9) -> ToolResult: ...

# Volume
# events: latest_volume, avg_volume, relative_volume
def calculate_volume_stats(frame, window=20) -> ToolResult: ...

# Levels/Structure
# events: recent swing_high, swing_low, current structure
def detect_swing_points(frame, window=5) -> ToolResult: ...
# events: nearest_support, nearest_resistance, distance to each
def detect_support_resistance(frame, tolerance_pct=0.005, min_touches=2) -> ToolResult: ...