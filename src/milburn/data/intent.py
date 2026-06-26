import re

TA_CATEGORIES_TO_KEYWORDS: dict[str, list[str]] = {
    "trend": [
        "trend", "trending", "direction", "directional", "uptrend", "downtrend",
        "sideways", "ranging", "slope", "sma", "ema", "wma", "dma", "20ma",
        "50ma", "200ma", "macd", "adx", "dmi", "aroon", "ichimoku", "cloud",
        "kumo", "supertrend", "trendline", "channel",
    ],
    "momentum": [
        "momentum", "rsi", "stochastic", "stoch", "stochrsi", "cci", "roc",
        "tsi", "oscillator", "overbought", "oversold", "exhaustion",
        "accelerating", "decelerating", "velocity", "weakening", "strengthening",
        "fading",
    ],
    "volume": [
        "volume", "obv", "vpvr", "vwap", "avwap", "cmf", "chaikin",
        "accumulation", "distribution", "mfi", "participation",
    ],
    "volatility": [
        "volatility", "volatile", "bollinger", "bbands", "squeeze", "expansion",
        "contraction", "atr", "keltner", "donchian", "sigma", "deviation",
        "choppy", "choppiness", "calm", "risk", "riskiness", "vix",
    ],
    "levels": [
        "support", "resistance", "level", "levels", "pivot", "pivots",
        "fibonacci", "fib", "retracement", "extension", "supply", "demand",
        "vah", "val", "poc", "breakout", "breakdown", "retest", "bounce",
        "rejection", "zone", "zones", "confluence", "base", "floor", "ceiling",
        "ath",
    ],
    "patterns": [
        "pattern", "formation", "setup", "triangle", "wedge", "flag", "pennant",
        "rectangle", "candlestick", "candle", "doji", "hammer", "engulfing",
        "harami", "gap",
    ],
    "divergence": ["divergence", "diverge", "diverging", "divergent"],
}

def identify_intent(prompt: str) -> list[str]:
    _KEYWORD_TO_CATEGORY: dict[str, str] = {}
    
    tokens = re.findall(r"[a-z0-9]+", prompt.lower())
    for category, keywords in TA_CATEGORIES_TO_KEYWORDS.items():
        for keyword in keywords:
            _KEYWORD_TO_CATEGORY[keyword] = category

    matched = set()
    for t in tokens: 
        if t in _KEYWORD_TO_CATEGORY:
            print(f"token: {t} -> keyword->cat {_KEYWORD_TO_CATEGORY[t]}")
            matched.add(_KEYWORD_TO_CATEGORY[t])
    _CATEGORIES = list(TA_CATEGORIES_TO_KEYWORDS.keys())
    output = []
    for c in _CATEGORIES:
        if c in matched:
            print(f"FOund: {c}")
            output.append(c)

    return output