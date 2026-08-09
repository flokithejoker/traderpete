from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from trader_pete.models import ProtocolMetric, ProviderBatch, utc_now


@dataclass(slots=True)
class DefiLlamaClient:
    base_url: str = "https://api.llama.fi"
    timeout_seconds: float = 30
    protocol_limit: int = 250

    def collect(self) -> tuple[list[ProtocolMetric], list[ProviderBatch], datetime]:
        observed_at = utc_now()
        payload = self._get_protocols()

        ranked = sorted(payload, key=lambda item: item.get("tvl") or 0, reverse=True)
        protocols = [
            self._parse_protocol(item, observed_at) for item in ranked[: self.protocol_limit]
        ]
        batch = ProviderBatch(
            provider="defillama",
            endpoint="/protocols",
            observed_at=observed_at,
            payload=payload,
        )
        return protocols, [batch], observed_at

    def _get_protocols(self) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                    response = client.get("/protocols", headers={"accept": "application/json"})
                    response.raise_for_status()
                    return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPStatusError):
                    status = error.response.status_code
                    if status not in {408, 429} and status < 500:
                        break
                if attempt < 2:
                    time.sleep(2**attempt)
        raise RuntimeError(f"DefiLlama request failed for /protocols: {last_error}") from last_error

    @staticmethod
    def _parse_protocol(item: dict[str, Any], observed_at: datetime) -> ProtocolMetric:
        return ProtocolMetric(
            protocol_id=str(item.get("slug") or item.get("id") or item["name"]),
            name=item["name"],
            category=item.get("category"),
            observed_at=observed_at,
            tvl_usd=item.get("tvl"),
            change_1d_pct=item.get("change_1d"),
            change_7d_pct=item.get("change_7d"),
            change_30d_pct=None,
            chains=item.get("chains") or [],
        )
