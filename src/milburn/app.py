from datetime import date

from milburn.config import Settings
from milburn.data.models import CandleRequest
from milburn.data.tiingo_provider import TiingoProvider


settings = Settings()
provider = TiingoProvider(settings=settings)

request = CandleRequest(
    symbol="AAPL",
    frequency="daily",
    start=date(2024, 1, 1),
    end=date(2024, 1, 31),
)

response = provider.fetch_candles(request)
print(response.metadata)
print(response.frame.head())
print(response.frame.tail())