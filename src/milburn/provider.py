from typing import Protocol

from milburn.model import CandleResponse, CandleRequest

class CandleProvider(Protocol):
    def fetch_candles(self, request: CandleRequest) -> CandleResponse:
        ...