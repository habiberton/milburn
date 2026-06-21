import pandas as pd
from datetime import date
from milburn.model import CandleResponse, CandleMetadata, CandleSummary

def summarize_candles(response: CandleResponse) -> CandleSummary:
    metadata: CandleMetadata = response.metadata
    df: pd.DataFrame = response.frame

    summary: CandleSummary = CandleSummary(
        symbol=metadata.symbol,
        frequency=metadata.frequency,
        start=metadata.start,
        end=metadata.end,
    )

    if (len(df) == 0): return summary

    start: date = (df["timestamp"].iloc[0]).date()
    end: date = (df["timestamp"].iloc[-1]).date()
    fc: float = float(df["close"].iloc[0])
    lc: float = float(df["close"].iloc[-1])
    min_c: float = float(df["close"].min())
    max_c: float = float(df["close"].max())
    vp: bool = bool((df["volume"] > 0).any())

    cols_to_check = [c for c in df.columns if c != "timestamp"]
    missing = {col: int(count) for col, count in df[cols_to_check].isna().sum().items()}

    return summary.model_copy(update={
        "start": start,
        "end": end, 
        "first_close": fc,
        "last_close": lc, 
        "min_close": min_c,
        "max_close": max_c,
        "volume_present": vp,
        "missing": missing
    })