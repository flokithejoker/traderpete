from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from trader_pete.config import Settings
from trader_pete.models import CategoryMarket, MarketAsset, ProviderBatch, utc_now


class ProviderConfigurationError(RuntimeError):
    pass


@dataclass(slots=True)
class CoinGeckoClient:
    api_key: str
    base_url: str
    header_name: str
    timeout_seconds: float = 30

    @classmethod
    def from_settings(cls, settings: Settings) -> CoinGeckoClient:
        if settings.coingecko_pro_api_key:
            return cls(
                api_key=settings.coingecko_pro_api_key,
                base_url="https://pro-api.coingecko.com/api/v3",
                header_name="x-cg-pro-api-key",
            )
        if settings.coingecko_demo_api_key:
            return cls(
                api_key=settings.coingecko_demo_api_key,
                base_url="https://api.coingecko.com/api/v3",
                header_name="x-cg-demo-api-key",
            )
        raise ProviderConfigurationError(
            "Live collection requires COINGECKO_DEMO_API_KEY or COINGECKO_PRO_API_KEY."
        )

    def _get(self, endpoint: str, params: dict[str, object]) -> Any:
        last_error: Exception | None = None
        headers = {self.header_name: self.api_key, "accept": "application/json"}
        for attempt in range(3):
            try:
                with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                    response = client.get(endpoint, params=params, headers=headers)
                    response.raise_for_status()
                    return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code < 500:
                    break
                if attempt < 2:
                    time.sleep(2**attempt)
        raise RuntimeError(f"CoinGecko request failed for {endpoint}: {last_error}") from last_error

    def collect(
        self,
    ) -> tuple[list[MarketAsset], list[CategoryMarket], list[ProviderBatch], datetime]:
        observed_at = utc_now()
        markets_payload = self._get(
            "/coins/markets",
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 250,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h,7d,30d",
            },
        )
        categories_payload = self._get("/coins/categories", {"order": "market_cap_desc"})

        assets = [self._parse_asset(item, observed_at) for item in markets_payload]
        categories = [self._parse_category(item, observed_at) for item in categories_payload]
        payloads = [
            ProviderBatch(
                provider="coingecko",
                endpoint="/coins/markets",
                observed_at=observed_at,
                payload=markets_payload,
            ),
            ProviderBatch(
                provider="coingecko",
                endpoint="/coins/categories",
                observed_at=observed_at,
                payload=categories_payload,
            ),
        ]
        return assets, categories, payloads, observed_at

    @staticmethod
    def _parse_asset(item: dict[str, Any], observed_at: datetime) -> MarketAsset:
        return MarketAsset(
            asset_id=item["id"],
            symbol=item["symbol"].upper(),
            name=item["name"],
            observed_at=observed_at,
            price_usd=item.get("current_price"),
            market_cap_usd=item.get("market_cap"),
            volume_24h_usd=item.get("total_volume"),
            change_24h_pct=item.get("price_change_percentage_24h_in_currency")
            or item.get("price_change_percentage_24h"),
            change_7d_pct=item.get("price_change_percentage_7d_in_currency"),
            change_30d_pct=item.get("price_change_percentage_30d_in_currency"),
        )

    @staticmethod
    def _parse_category(item: dict[str, Any], observed_at: datetime) -> CategoryMarket:
        return CategoryMarket(
            category_id=item["id"],
            name=item["name"],
            observed_at=observed_at,
            market_cap_usd=item.get("market_cap"),
            volume_24h_usd=item.get("volume_24h"),
            change_24h_pct=item.get("market_cap_change_24h"),
        )
