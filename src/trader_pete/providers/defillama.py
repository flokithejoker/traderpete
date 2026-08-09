from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from trader_pete.models import (
    ActivityMetricType,
    ProtocolActivityMetric,
    ProtocolMetric,
    ProviderBatch,
    utc_now,
)


@dataclass(slots=True)
class DefiLlamaClient:
    base_url: str = "https://api.llama.fi"
    timeout_seconds: float = 30
    protocol_limit: int = 1_500
    activity_limit: int = 750
    minimum_tvl_usd: float = 1_000_000
    _last_request_record: dict[str, object] = field(default_factory=dict, init=False, repr=False)

    def collect(
        self,
    ) -> tuple[
        list[ProtocolMetric],
        list[ProtocolActivityMetric],
        list[ProviderBatch],
        datetime,
    ]:
        observed_at = utc_now()
        protocol_payload = self._get("/protocols", {})
        protocol_request = dict(self._last_request_record)
        activity_requests = [
            ("/overview/fees", ActivityMetricType.FEES, "dailyFees"),
            ("/overview/fees", ActivityMetricType.REVENUE, "dailyRevenue"),
            ("/overview/dexs", ActivityMetricType.DEX_VOLUME, "dailyVolume"),
        ]
        activity_payloads: list[
            tuple[str, ActivityMetricType, str, dict[str, Any], dict[str, object] | None]
        ] = []
        for endpoint, metric_type, data_type in activity_requests:
            try:
                payload = self._get(
                    endpoint,
                    {
                        "excludeTotalDataChart": "true",
                        "excludeTotalDataChartBreakdown": "true",
                        "dataType": data_type,
                    },
                )
            except RuntimeError as error:
                payload = {"protocols": [], "collection_error": str(error)}
                request_record = None
            else:
                request_record = dict(self._last_request_record)
            activity_payloads.append((endpoint, metric_type, data_type, payload, request_record))

        protocols = self._select_protocols(protocol_payload, observed_at)
        activity = [
            metric
            for _, metric_type, _, payload, _ in activity_payloads
            for metric in self._select_activity(payload, metric_type, observed_at)
        ]
        batches = [
            self._batch(
                provider="defillama",
                endpoint="/protocols",
                observed_at=observed_at,
                payload=protocol_payload,
                request_manifest=[protocol_request],
            ),
            *[
                self._batch(
                    provider="defillama",
                    endpoint=f"{endpoint}?dataType={data_type}",
                    observed_at=observed_at,
                    payload=payload,
                    request_manifest=[request_record] if request_record else [],
                )
                for endpoint, _, data_type, payload, request_record in activity_payloads
            ],
        ]
        return protocols, activity, batches, observed_at

    def _batch(
        self,
        *,
        provider: str,
        endpoint: str,
        observed_at: datetime,
        payload: Any,
        request_manifest: list[dict[str, object]] | None = None,
    ) -> ProviderBatch:
        # An explicit empty manifest represents a failed/unreceived response.
        # Falling back here would misattribute the preceding successful request.
        manifest = (
            request_manifest
            if request_manifest is not None
            else ([dict(self._last_request_record)] if self._last_request_record else [])
        )
        fingerprint = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        latest = manifest[-1] if manifest else {}
        return ProviderBatch(
            provider=provider,
            endpoint=endpoint,
            observed_at=observed_at,
            payload=payload,
            request_params_hash=fingerprint,
            response_received_at=latest.get("received_at"),
            http_status=latest.get("status"),
            content_type=latest.get("content_type"),
            request_manifest=manifest,
        )

    def _get(self, endpoint: str, params: dict[str, object]) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                    response = client.get(
                        endpoint, params=params, headers={"accept": "application/json"}
                    )
                    response.raise_for_status()
                    self._last_request_record = {
                        "url": f"{self.base_url}{endpoint}",
                        "params": params,
                        "received_at": utc_now().isoformat(),
                        "status": response.status_code,
                        "content_type": response.headers.get("content-type"),
                    }
                    return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPStatusError):
                    status = error.response.status_code
                    if status not in {408, 429} and status < 500:
                        break
                if attempt < 2:
                    time.sleep(2**attempt)
        raise RuntimeError(f"DefiLlama request failed for {endpoint}: {last_error}") from last_error

    def _select_protocols(
        self, payload: list[dict[str, Any]], observed_at: datetime
    ) -> list[ProtocolMetric]:
        ranked = sorted(payload, key=lambda item: float(item.get("tvl") or 0), reverse=True)
        selected = [item for item in ranked if float(item.get("tvl") or 0) >= self.minimum_tvl_usd][
            : self.protocol_limit
        ]
        return [self._parse_protocol(item, observed_at) for item in selected]

    def _select_activity(
        self,
        payload: dict[str, Any],
        metric_type: ActivityMetricType,
        observed_at: datetime,
    ) -> list[ProtocolActivityMetric]:
        rows = payload.get("protocols") or []
        minimum_7d = 1_000_000 if metric_type is ActivityMetricType.DEX_VOLUME else 10_000
        meaningful = [item for item in rows if float(item.get("total7d") or 0) >= minimum_7d]
        by_size = sorted(meaningful, key=lambda item: float(item.get("total7d") or 0), reverse=True)
        by_growth = sorted(
            meaningful,
            key=lambda item: float(item.get("change_7dover7d") or -10_000),
            reverse=True,
        )
        selected: dict[str, dict[str, Any]] = {}
        half = max(1, self.activity_limit // 2)
        for item in [*by_size[:half], *by_growth[:half]]:
            protocol_id = str(item.get("slug") or item.get("module") or item.get("name") or "")
            if protocol_id:
                selected.setdefault(protocol_id, item)
        return [
            self._parse_activity(item, metric_type, observed_at)
            for item in list(selected.values())[: self.activity_limit]
        ]

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

    @staticmethod
    def _parse_activity(
        item: dict[str, Any], metric_type: ActivityMetricType, observed_at: datetime
    ) -> ProtocolActivityMetric:
        return ProtocolActivityMetric(
            protocol_id=str(item.get("slug") or item.get("module") or item.get("name")),
            name=str(item.get("displayName") or item.get("name") or item.get("module")),
            category=item.get("category"),
            metric_type=metric_type,
            observed_at=observed_at,
            total_24h_usd=item.get("total24h"),
            total_7d_usd=item.get("total7d"),
            total_30d_usd=item.get("total30d"),
            growth_1d_pct=item.get("change_1d"),
            growth_7d_pct=_first_not_none(item.get("change_7dover7d"), item.get("change_7d")),
            growth_30d_pct=_first_not_none(item.get("change_30dover30d"), item.get("change_1m")),
        )


def _first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)
