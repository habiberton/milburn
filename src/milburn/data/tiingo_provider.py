from milburn.config import Settings
from milburn.data.models import CandleMetadata, CandleRequest
from milburn.data.providers import CandleResponse

from tiingo import TiingoClient

TIINGO_CANDLE_COLUMNS = ["adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume"]
NORMALIZED_CANDLE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class TiingoProvider:
    def __init__(self, settings: Settings):
        token = settings.get_tiingo_api_key()
        if token is None:
            raise ValueError("Tiingo API key is required but not provided in settings")
        config = {
            "session": True,
            "api_key": token,
        }
        self._client = TiingoClient(config)
    
    def fetch_candles(self, request: CandleRequest) -> CandleResponse:
        requested_columns = self._requested_columns(request)
        columns_arg = ",".join(requested_columns) if requested_columns is not None else None
        frame = self._client.get_dataframe(
            tickers=request.symbol,
            startDate=request.start,
            endDate=request.end,
            columns=columns_arg,
            frequency=request.frequency,
        )
        frame = self._normalize_frame(frame, request)
        metadata: CandleMetadata = CandleMetadata(
            provider="tiingo",
            symbol=request.symbol,
            frequency=request.frequency,
            start=request.start,
            end=request.end,
            rows=len(frame),
            source="api",
            cache_key=None,
            request_count=0,
            raw_metadata={
                "requested_columns": requested_columns,
                "normalized_columns": list(frame.columns),
                "server_side_columns": True,
            },
        )
        return CandleResponse(frame=frame, metadata=metadata)

    def _requested_columns(self, request: CandleRequest) -> list[str]:
        if request.columns is not None:
            return request.columns
        return TIINGO_CANDLE_COLUMNS

    def _normalize_frame(self, frame, request: CandleRequest):
        frame = frame.copy()
        frame.index.name = "timestamp"
        frame = frame.reset_index()
        frame = frame[["timestamp", *TIINGO_CANDLE_COLUMNS]]
        frame = frame.rename(
            columns={
                "adjOpen": "open",
                "adjHigh": "high",
                "adjLow": "low",
                "adjClose": "close",
                "adjVolume": "volume",
            }
        )

        missing_columns = [
            column for column in NORMALIZED_CANDLE_COLUMNS if column not in frame.columns
        ]
        if missing_columns:
            raise ValueError(
                "Tiingo response is missing required normalized columns: "
                + ", ".join(missing_columns)
            )

        return frame[NORMALIZED_CANDLE_COLUMNS]
