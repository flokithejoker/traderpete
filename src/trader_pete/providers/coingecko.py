from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from trader_pete.config import Settings
from trader_pete.models import (
    CategoryMarket,
    MarketAsset,
    ProviderBatch,
    TrendingAsset,
    utc_now,
)


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
                retry_after = 0.0
                if isinstance(error, httpx.HTTPStatusError):
                    status = error.response.status_code
                    if status not in {408, 429} and status < 500:
                        break
                    try:
                        retry_after = float(error.response.headers.get("retry-after", "0"))
                    except ValueError:
                        retry_after = 0.0
                if attempt < 2:
                    time.sleep(min(10, max(retry_after, 2**attempt)))
        raise RuntimeError(f"CoinGecko request failed for {endpoint}: {last_error}") from last_error

    def collect(
        self,
        *,
        requested_asset_ids: list[str] | None = None,
    ) -> tuple[
        list[MarketAsset],
        list[CategoryMarket],
        list[TrendingAsset],
        list[ProviderBatch],
        datetime,
    ]:
        observed_at = utc_now()
        markets_payload: list[dict[str, Any]] = []
        for page in range(1, 5):
            try:
                page_payload = self._get(
                    "/coins/markets",
                    {
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": 250,
                        "page": page,
                        "sparkline": "false",
                        "price_change_percentage": "24h,7d,30d",
                    },
                )
            except RuntimeError:
                if page == 1:
                    raise
                break
            markets_payload.extend(page_payload)
            if len(page_payload) < 250:
                break
        categories_payload = self._get("/coins/categories", {"order": "market_cap_desc"})
        trending_payload = self._get("/search/trending", {})

        assets = [self._parse_asset(item, observed_at) for item in markets_payload]
        trending_assets = [
            self._parse_trending(item["item"], observed_at, rank)
            for rank, item in enumerate(trending_payload.get("coins", []), start=1)
        ]
        known_ids = {asset.asset_id for asset in assets}
        requested_ids = set(requested_asset_ids or [])
        requested_ids.update(item.asset_id for item in trending_assets)
        missing_asset_ids = sorted(requested_ids - known_ids)
        requested_markets_payload: list[dict[str, Any]] = []
        if missing_asset_ids:
            requested_markets_payload = self._get(
                "/coins/markets",
                {
                    "vs_currency": "usd",
                    "ids": ",".join(missing_asset_ids),
                    "order": "market_cap_desc",
                    "per_page": min(250, len(missing_asset_ids)),
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "24h,7d,30d",
                },
            )
            assets.extend(
                self._parse_asset(item, observed_at) for item in requested_markets_payload
            )
        assets = list({asset.asset_id: asset for asset in assets}.values())
        categories = [self._parse_category(item, observed_at) for item in categories_payload]
        payloads = [
            ProviderBatch(
                provider="coingecko",
                endpoint="/coins/markets?universe=top1000-best-effort",
                observed_at=observed_at,
                payload=markets_payload,
            ),
            ProviderBatch(
                provider="coingecko",
                endpoint="/coins/categories",
                observed_at=observed_at,
                payload=categories_payload,
            ),
            ProviderBatch(
                provider="coingecko",
                endpoint="/search/trending",
                observed_at=observed_at,
                payload=trending_payload,
            ),
        ]
        if requested_markets_payload:
            payloads.append(
                ProviderBatch(
                    provider="coingecko",
                    endpoint="/coins/markets?universe=registry-and-trending",
                    observed_at=observed_at,
                    payload=requested_markets_payload,
                )
            )
        return assets, categories, trending_assets, payloads, observed_at

    @staticmethod
    def _parse_asset(item: dict[str, Any], observed_at: datetime) -> MarketAsset:
        return MarketAsset(
            asset_id=item["id"],
            symbol=item["symbol"].upper(),
            name=item["name"],
            observed_at=_timestamp(item.get("last_updated"), observed_at),
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
            observed_at=_timestamp(item.get("updated_at"), observed_at),
            market_cap_usd=item.get("market_cap"),
            volume_24h_usd=item.get("volume_24h"),
            change_24h_pct=item.get("market_cap_change_24h"),
            top_asset_ids=item.get("top_3_coins_id") or [],
        )

    @staticmethod
    def _parse_trending(item: dict[str, Any], observed_at: datetime, rank: int) -> TrendingAsset:
        return TrendingAsset(
            asset_id=item["id"],
            symbol=item["symbol"].upper(),
            name=item["name"],
            observed_at=observed_at,
            search_rank=rank,
            market_cap_rank=item.get("market_cap_rank"),
        )


def _timestamp(value: object, fallback: datetime) -> datetime:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
