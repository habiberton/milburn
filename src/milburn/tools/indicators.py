import pandas as pd
import numpy as np
import talib

from typing import Any
from pandas import DataFrame
from milburn.tools.results import ToolResult, ToolEvent
from milburn.helper import print_json


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
    latest: dict[str, Any] = {}

    frame = compute_rsi(frame, period)
    events = compute_rsi_events(frame)
    latest["rsi"] = round(float(frame["rsi"].iloc[-1]), 3)

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
                    "rsi_prev": round(float(rsi.iloc[pos-1]), 3),
                    "close": round(float(frame["close"].iloc[pos]), 3)
                },
            ))
    return events

# events: macd, signal, histogram
def calculate_macd(frame, fast=12, slow=26, signal=9) -> ToolResult:
    latest: dict[str, Any] = {}
    warnings: list[str] = []
    frame = compute_macd(frame, fast, slow, signal)

    last = frame["macd"].iloc[-1]
    if pd.isna(last):
        warnings.append(f"macd needs ~{slow + signal} bars; only {len(frame)} available — no reading")
    else:
        latest["macd"] = round(float(frame["macd"].iloc[-1]), 3)
        latest["signal"] = round(float(frame["signal"].iloc[-1]), 3)
        latest["histogram"] = round(float(frame["histogram"].iloc[-1]), 3)
    return ToolResult(
        name="macd",
        params={
            "fast":fast,
            "slow":slow,
            "signal":signal
        },
        lookback=len(frame),
        latest=latest,
        events=compute_macd_events(frame),
        warnings=warnings
    )

def compute_macd(frame: DataFrame, fast: int, slow: int, signal: int) -> DataFrame:
    close = frame["close"].values.astype(np.float64)
    (frame["macd"], frame["signal"], frame["histogram"]) = talib.MACD(close, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    return frame

def compute_macd_events(frame: DataFrame) -> list[ToolEvent]:
    events: list[ToolEvent] = []
    macd = frame["macd"]
    signal_line = frame["signal"]
    above = macd > signal_line    
    up_cross = above & ~above.shift(1, fill_value=False)
    down_cross = ~above & above.shift(1, fill_value=False)

    crossings = [
        (up_cross, "cross_above_signal"),
        (down_cross, "cross_below_signal"),
    ]

    for mask, e_type in crossings:
        for pos in np.flatnonzero(mask.to_numpy()):
            events.append(ToolEvent(
                timestamp=str(frame["timestamp"].iloc[pos].date()),
                type=e_type,
                value=round(float(macd.iloc[pos]), 3),
                details={
                    "signal": round(float(signal_line.iloc[pos]), 3),
                    "macd_prev": round(float(macd.iloc[pos - 1]), 3),
                    "close": round(float(frame["close"].iloc[pos]), 3),
                },
            ))
    return events
# Volume
# events: latest_volume, avg_volume, relative_volume
def calculate_volume_stats(frame, window=20) -> ToolResult: ...

# Levels/Structure
# events: recent swing_high, swing_low, current structure
def detect_swing_points(frame, window=5) -> ToolResult: ...
# events: nearest_support, nearest_resistance, distance to each
def detect_support_resistance(frame, tolerance_pct=0.005, min_touches=2) -> ToolResult: ...