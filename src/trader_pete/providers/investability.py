from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from trader_pete.config import Settings, StrategyPolicy
from trader_pete.models import (
    InvestabilityAssetData,
    InvestabilityDataBundle,
    OhlcCandle,
    ProviderBatch,
    SocialCoverage,
    TokenIdentitySnapshot,
    TokenSecuritySnapshot,
    VenueQuoteSnapshot,
    utc_now,
)
from trader_pete.providers.coingecko import CoinGeckoClient

PLATFORM_TO_DEX_CHAIN = {
    "ethereum": "ethereum",
    "binance-smart-chain": "bsc",
    "base": "base",
    "arbitrum-one": "arbitrum",
    "optimistic-ethereum": "optimism",
    "polygon-pos": "polygon",
    "avalanche": "avalanche",
    "solana": "solana",
    "sui": "sui",
}

PLATFORM_TO_EVM_CHAIN_ID = {
    "ethereum": "1",
    "binance-smart-chain": "56",
    "base": "8453",
    "arbitrum-one": "42161",
    "optimistic-ethereum": "10",
    "polygon-pos": "137",
    "avalanche": "43114",
    "fantom": "250",
    "cronos": "25",
    "linea": "59144",
}

APPROVED_QUOTES = ("USD", "USDT", "USDC", "EUR")


@dataclass(slots=True)
class InvestabilityCollector:
    settings: Settings
    policy: StrategyPolicy
    timeout_seconds: float = 25
    _last_response_meta: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def collect(self, asset_ids: list[str]) -> InvestabilityDataBundle:
        observed_at = utc_now()
        selected_ids = list(dict.fromkeys(asset_ids))[
            : self.policy.maximum_candidates_per_run + self.policy.maximum_open_positions + 1
        ]
        if not selected_ids:
            return InvestabilityDataBundle(observed_at=observed_at)

        coin_gecko = CoinGeckoClient.from_settings(self.settings)
        payloads: list[ProviderBatch] = []
        prepared: list[dict[str, Any]] = []
        for asset_id in selected_ids:
            gaps: list[str] = []
            detail: dict[str, Any] | None = None
            tickers: dict[str, Any] = {"tickers": []}
            ohlc: list[list[float]] = []
            try:
                detail = coin_gecko._get(
                    f"/coins/{asset_id}",
                    {
                        "localization": "false",
                        "tickers": "false",
                        "market_data": "true",
                        "community_data": "false",
                        "developer_data": "false",
                        "sparkline": "false",
                    },
                )
                payloads.append(
                    coin_gecko._batch(
                        provider="coingecko",
                        endpoint=f"/coins/{asset_id}?purpose=identity-and-supply",
                        observed_at=observed_at,
                        payload=detail,
                    )
                )
            except RuntimeError as error:
                gaps.append(f"CoinGecko identity unavailable: {error}")
            try:
                ohlc = coin_gecko._get(
                    f"/coins/{asset_id}/ohlc",
                    {"vs_currency": "usd", "days": "30", "precision": "full"},
                )
                payloads.append(
                    coin_gecko._batch(
                        provider="coingecko",
                        endpoint=f"/coins/{asset_id}/ohlc?days=30",
                        observed_at=observed_at,
                        payload=ohlc,
                    )
                )
            except RuntimeError as error:
                gaps.append(f"CoinGecko OHLC unavailable: {error}")
            try:
                tickers = coin_gecko._get(
                    f"/coins/{asset_id}/tickers",
                    {
                        "exchange_ids": "kraken",
                        "include_exchange_logo": "false",
                        "page": 1,
                        "depth": "false",
                        "order": "volume_desc",
                    },
                )
                payloads.append(
                    coin_gecko._batch(
                        provider="coingecko",
                        endpoint=f"/coins/{asset_id}/tickers?exchange_ids=kraken",
                        observed_at=observed_at,
                        payload=tickers,
                    )
                )
            except RuntimeError as error:
                gaps.append(f"CoinGecko Kraken identity link unavailable: {error}")
            prepared.append(
                {
                    "asset_id": asset_id,
                    "detail": detail,
                    "ohlc": ohlc,
                    "tickers": tickers,
                    "gaps": gaps,
                }
            )

        kraken_pairs: dict[str, Any] = {}
        try:
            response = self._get_json(
                "https://api.kraken.com/0/public/AssetPairs", {"assetVersion": "1"}
            )
            kraken_pairs = response.get("result") or {}
            payloads.append(
                self._batch(
                    provider="kraken",
                    endpoint="/0/public/AssetPairs?assetVersion=1",
                    observed_at=observed_at,
                    payload=response,
                )
            )
        except RuntimeError as error:
            for item in prepared:
                item["gaps"].append(f"Kraken pair directory unavailable: {error}")

        assets: list[InvestabilityAssetData] = []
        for item in prepared:
            asset_id = item["asset_id"]
            detail = item["detail"]
            identity = self._identity(asset_id, detail, observed_at) if detail else None
            candles = self._candles(item["ohlc"])
            security, security_payloads = self._security(identity, observed_at)
            payloads.extend(security_payloads)
            quotes: list[VenueQuoteSnapshot] = []
            kraken_quote, kraken_payload = self._kraken_quote(
                asset_id,
                identity,
                item["tickers"],
                kraken_pairs,
                observed_at,
            )
            if kraken_quote:
                quotes.append(kraken_quote)
            if kraken_payload:
                payloads.append(kraken_payload)
            dex_quote, dex_payload = self._dex_quote(identity, observed_at)
            if dex_quote:
                quotes.append(dex_quote)
            if dex_payload:
                payloads.append(dex_payload)
            if not quotes:
                item["gaps"].append("No contract-matched DEX pool or CoinGecko-linked Kraken pair.")
            assets.append(
                InvestabilityAssetData(
                    asset_id=asset_id,
                    identity=identity,
                    candles=candles,
                    security=security,
                    quotes=quotes,
                    data_gaps=list(dict.fromkeys(item["gaps"])),
                )
            )
        return InvestabilityDataBundle(
            observed_at=observed_at,
            assets=assets,
            payloads=payloads,
        )

    @staticmethod
    def _identity(
        asset_id: str,
        detail: dict[str, Any],
        observed_at: datetime,
    ) -> TokenIdentitySnapshot:
        platforms = {
            str(platform): str(address)
            for platform, address in (detail.get("platforms") or {}).items()
            if platform and address
        }
        platform = detail.get("asset_platform_id")
        if not platform or platform not in platforms:
            platform = next(
                (value for value in PLATFORM_TO_DEX_CHAIN if value in platforms),
                next(iter(platforms), None),
            )
        market = detail.get("market_data") or {}
        return TokenIdentitySnapshot(
            asset_id=asset_id,
            symbol=str(detail.get("symbol") or "").upper(),
            name=str(detail.get("name") or asset_id),
            observed_at=observed_at,
            asset_platform_id=detail.get("asset_platform_id"),
            chain_id=platform,
            contract_address=platforms.get(platform) if platform else None,
            contract_candidates=platforms,
            circulating_supply=_number(market.get("circulating_supply")),
            total_supply=_number(market.get("total_supply")),
            max_supply=_number(market.get("max_supply")),
            market_cap_usd=_currency_value(market.get("market_cap"), "usd"),
            fully_diluted_valuation_usd=_currency_value(
                market.get("fully_diluted_valuation"), "usd"
            ),
        )

    @staticmethod
    def _candles(payload: list[list[float]]) -> list[OhlcCandle]:
        rows: list[OhlcCandle] = []
        for item in payload:
            if len(item) < 5 or any(_number(value) is None for value in item[:5]):
                continue
            try:
                rows.append(
                    OhlcCandle(
                        closed_at=datetime.fromtimestamp(float(item[0]) / 1000, tz=UTC),
                        open=float(item[1]),
                        high=float(item[2]),
                        low=float(item[3]),
                        close=float(item[4]),
                    )
                )
            except (ValueError, TypeError):
                continue
        return rows

    def _security(
        self,
        identity: TokenIdentitySnapshot | None,
        observed_at: datetime,
    ) -> tuple[TokenSecuritySnapshot | None, list[ProviderBatch]]:
        if not identity or not identity.chain_id or not identity.contract_address:
            return None, []
        evm_chain = PLATFORM_TO_EVM_CHAIN_ID.get(identity.chain_id)
        if not evm_chain:
            return (
                TokenSecuritySnapshot(
                    asset_id=identity.asset_id,
                    provider="unavailable",
                    observed_at=observed_at,
                    chain_id=identity.chain_id,
                    contract_address=identity.contract_address,
                    limitations=["No deterministic security adapter for this chain."],
                ),
                [],
            )
        payloads: list[ProviderBatch] = []
        try:
            response = self._get_json(
                f"https://api.gopluslabs.io/api/v1/token_security/{evm_chain}",
                {"contract_addresses": identity.contract_address},
            )
            payloads.append(
                self._batch(
                    provider="goplus",
                    endpoint=f"/api/v1/token_security/{evm_chain}?asset={identity.asset_id}",
                    observed_at=observed_at,
                    payload=response,
                )
            )
        except RuntimeError as error:
            return (
                TokenSecuritySnapshot(
                    asset_id=identity.asset_id,
                    provider="goplus",
                    observed_at=observed_at,
                    chain_id=identity.chain_id,
                    contract_address=identity.contract_address,
                    limitations=[str(error)],
                ),
                payloads,
            )
        result = response.get("result") or {}
        row = result.get(identity.contract_address.lower()) or result.get(identity.contract_address)
        coverage = SocialCoverage.PARTIAL if response.get("code") == 2 else SocialCoverage.MEASURED
        if not isinstance(row, dict):
            return (
                TokenSecuritySnapshot(
                    asset_id=identity.asset_id,
                    provider="goplus",
                    observed_at=observed_at,
                    chain_id=identity.chain_id,
                    contract_address=identity.contract_address,
                    coverage=SocialCoverage.UNAVAILABLE,
                    limitations=["GoPlus returned no record for the resolved contract."],
                ),
                payloads,
            )
        source_verified = None
        contract_name = None
        is_proxy = _flag(row.get("is_proxy"))
        proxy_implementation_address = None
        proxy_implementation_verified = None
        etherscan_verified = False
        limitations: list[str] = [
            "Provider flags are screening evidence, not a contract audit or sell guarantee."
        ]
        if self.settings.etherscan_api_key:
            try:
                etherscan = self._get_json(
                    "https://api.etherscan.io/v2/api",
                    {
                        "chainid": evm_chain,
                        "module": "contract",
                        "action": "getsourcecode",
                        "address": identity.contract_address,
                        "apikey": self.settings.etherscan_api_key,
                    },
                )
                payloads.append(
                    self._batch(
                        provider="etherscan",
                        endpoint=f"/v2/api?module=contract&action=getsourcecode&asset={identity.asset_id}",
                        observed_at=observed_at,
                        payload=etherscan,
                    )
                )
                valid_response = str(etherscan.get("status")) == "1" and isinstance(
                    etherscan.get("result"), list
                )
                source_row = (
                    next(
                        (
                            value
                            for value in (etherscan.get("result") or [])
                            if isinstance(value, dict)
                        ),
                        None,
                    )
                    if valid_response
                    else None
                )
                if source_row:
                    etherscan_verified = True
                    source_verified = bool(str(source_row.get("SourceCode") or "").strip())
                    contract_name = str(source_row.get("ContractName") or "") or None
                    etherscan_proxy = _flag(source_row.get("Proxy"))
                    if etherscan_proxy is not None:
                        is_proxy = etherscan_proxy
                    proxy_implementation_address = (
                        str(source_row.get("Implementation") or "").strip() or None
                    )
                    if is_proxy is True and proxy_implementation_address:
                        implementation = self._get_json(
                            "https://api.etherscan.io/v2/api",
                            {
                                "chainid": evm_chain,
                                "module": "contract",
                                "action": "getsourcecode",
                                "address": proxy_implementation_address,
                                "apikey": self.settings.etherscan_api_key,
                            },
                        )
                        payloads.append(
                            self._batch(
                                provider="etherscan",
                                endpoint=(
                                    "/v2/api?module=contract&action=getsourcecode&purpose="
                                    f"proxy-implementation&asset={identity.asset_id}"
                                ),
                                observed_at=observed_at,
                                payload=implementation,
                            )
                        )
                        implementation_row = (
                            next(
                                (
                                    value
                                    for value in (implementation.get("result") or [])
                                    if isinstance(value, dict)
                                ),
                                None,
                            )
                            if str(implementation.get("status")) == "1"
                            else None
                        )
                        proxy_implementation_verified = bool(
                            implementation_row
                            and str(implementation_row.get("SourceCode") or "").strip()
                        )
                    elif is_proxy is False:
                        proxy_implementation_verified = True
                else:
                    limitations.append(
                        "Etherscan returned no validated source record for the resolved contract."
                    )
            except RuntimeError as error:
                limitations.append(f"Etherscan source verification unavailable: {error}")
        else:
            limitations.append("Etherscan source verification is unmeasured (no free API key).")
        holders = row.get("holders") or []
        top10 = sum((_number(value.get("percent")) or 0) for value in holders[:10]) * 100
        return (
            TokenSecuritySnapshot(
                asset_id=identity.asset_id,
                provider="goplus+etherscan" if etherscan_verified else "goplus",
                observed_at=observed_at,
                chain_id=identity.chain_id,
                contract_address=identity.contract_address,
                coverage=coverage,
                is_open_source=_flag(row.get("is_open_source")),
                is_honeypot=_flag(row.get("is_honeypot")),
                cannot_buy=_flag(row.get("cannot_buy")),
                cannot_sell_all=_flag(row.get("cannot_sell_all")),
                is_blacklisted=_flag(row.get("is_blacklisted")),
                hidden_owner=_flag(row.get("hidden_owner")),
                can_take_back_ownership=_flag(row.get("can_take_back_ownership")),
                owner_change_balance=_flag(row.get("owner_change_balance")),
                buy_tax_pct=_tax_pct(row.get("buy_tax")),
                sell_tax_pct=_tax_pct(row.get("sell_tax")),
                holder_count=_integer(row.get("holder_count")),
                top10_holder_pct=min(100, top10) if holders else None,
                source_verified=source_verified,
                contract_name=contract_name,
                is_proxy=is_proxy,
                proxy_implementation_address=proxy_implementation_address,
                proxy_implementation_verified=proxy_implementation_verified,
                limitations=limitations,
            ),
            payloads,
        )

    def _kraken_quote(
        self,
        asset_id: str,
        identity: TokenIdentitySnapshot | None,
        ticker_payload: dict[str, Any],
        pairs: dict[str, Any],
        observed_at: datetime,
    ) -> tuple[VenueQuoteSnapshot | None, ProviderBatch | None]:
        if not identity:
            return None, None
        ticker = next(
            (
                value
                for quote in APPROVED_QUOTES
                for value in ticker_payload.get("tickers", [])
                if str(value.get("target") or "").upper() == quote
                and not value.get("is_stale")
                and not value.get("is_anomaly")
            ),
            None,
        )
        if not ticker:
            return None, None
        base = _normal_symbol(str(ticker.get("base") or identity.symbol))
        target = _normal_symbol(str(ticker.get("target") or ""))
        match = next(
            (
                (key, value)
                for key, value in pairs.items()
                if _pair_symbols(value) == (base, target)
            ),
            None,
        )
        if not match:
            return None, None
        pair_key, pair = match
        try:
            response = self._get_json(
                "https://api.kraken.com/0/public/Depth",
                {"pair": pair.get("altname") or pair_key, "count": 100},
            )
        except RuntimeError:
            return None, None
        book = next(iter((response.get("result") or {}).values()), {})
        bids = _book_rows(book.get("bids") or [])
        asks = _book_rows(book.get("asks") or [])
        if not bids or not asks:
            return None, None
        quote_observed_at = self._last_response_meta.get("response_received_at") or utc_now()
        best_bid, best_ask = bids[0][0], asks[0][0]
        mid = (best_bid + best_ask) / 2
        notional = min(
            self.policy.paper_initial_cash_usd * self.policy.maximum_position_nav_pct / 100,
            self.policy.paper_initial_cash_usd * self.policy.maximum_deployed_nav_pct / 100,
        )
        buy_vwap = _buy_vwap(asks, notional)
        quantity = notional / mid
        sell_vwap = _sell_vwap(bids, quantity)
        fee_pct = _number((pair.get("fees") or [[0, 0.4]])[0][1]) or 0.4
        fee_bps = fee_pct * 100
        spread_bps = (best_ask - best_bid) / mid * 10_000
        buy_impact = ((buy_vwap / best_ask) - 1) * 10_000 if buy_vwap else None
        sell_impact = ((best_bid / sell_vwap) - 1) * 10_000 if sell_vwap else None
        round_trip = (
            (buy_vwap - sell_vwap) / mid * 10_000 + 2 * fee_bps if buy_vwap and sell_vwap else None
        )
        quote_is_usd = target in {"USD", "USDT", "USDC"}
        limitations = []
        if not quote_is_usd:
            limitations.append(
                "EUR pair is observed but cannot size the USD paper portfolio without FX."
            )
        payload = self._batch(
            provider="kraken",
            endpoint=f"/0/public/Depth?pair={pair.get('altname') or pair_key}",
            observed_at=quote_observed_at,
            payload=response,
        )
        return (
            VenueQuoteSnapshot(
                asset_id=asset_id,
                provider="kraken",
                venue="Kraken",
                venue_type="cex_spot",
                pair=str(pair.get("wsname") or pair.get("altname") or pair_key),
                base_symbol=base,
                quote_symbol=target,
                observed_at=quote_observed_at,
                chain_id=identity.chain_id,
                contract_address=identity.contract_address,
                executable=quote_is_usd,
                pair_online=pair.get("status") == "online",
                best_bid=best_bid,
                best_ask=best_ask,
                mid_price=mid,
                spread_bps=spread_bps,
                buy_vwap_price=buy_vwap,
                sell_vwap_price=sell_vwap,
                buy_impact_bps=max(0, buy_impact) if buy_impact is not None else None,
                sell_impact_bps=max(0, sell_impact) if sell_impact is not None else None,
                buy_depth_1pct_usd=_depth_quote(asks, upper=best_ask * 1.01),
                sell_depth_1pct_usd=_depth_quote(bids, lower=best_bid * 0.99),
                taker_fee_bps=fee_bps,
                estimated_round_trip_cost_bps=round_trip,
                intended_notional_usd=notional,
                limitations=limitations,
            ),
            payload,
        )

    def _dex_quote(
        self,
        identity: TokenIdentitySnapshot | None,
        observed_at: datetime,
    ) -> tuple[VenueQuoteSnapshot | None, ProviderBatch | None]:
        if not identity or not identity.chain_id or not identity.contract_address:
            return None, None
        dex_chain = PLATFORM_TO_DEX_CHAIN.get(identity.chain_id)
        if not dex_chain:
            return None, None
        endpoint = (
            f"https://api.dexscreener.com/token-pairs/v1/{dex_chain}/{identity.contract_address}"
        )
        try:
            response = self._get_json(endpoint, {})
        except RuntimeError:
            return None, None
        payload = self._batch(
            provider="dexscreener",
            endpoint=f"/token-pairs/v1/{dex_chain}/{identity.contract_address}",
            observed_at=observed_at,
            payload=response,
        )
        rows = [
            value
            for value in response
            if str((value.get("baseToken") or {}).get("address") or "").lower()
            == identity.contract_address.lower()
        ]
        if not rows:
            return None, payload
        stable = {"USDC", "USDT", "DAI", "USD"}
        rows.sort(
            key=lambda value: (
                str((value.get("quoteToken") or {}).get("symbol") or "").upper() in stable,
                _number((value.get("liquidity") or {}).get("usd")) or 0,
            ),
            reverse=True,
        )
        row = rows[0]
        quote_symbol = str((row.get("quoteToken") or {}).get("symbol") or "").upper()
        created = _timestamp_ms(row.get("pairCreatedAt"))
        notional = self.policy.paper_initial_cash_usd * self.policy.maximum_position_nav_pct / 100
        return (
            VenueQuoteSnapshot(
                asset_id=identity.asset_id,
                provider="dexscreener",
                venue=str(row.get("dexId") or "DEX"),
                venue_type="dex_analytics",
                pair=f"{identity.symbol}/{quote_symbol}",
                base_symbol=identity.symbol,
                quote_symbol=quote_symbol,
                observed_at=observed_at,
                chain_id=identity.chain_id,
                contract_address=identity.contract_address,
                pair_address=row.get("pairAddress"),
                pair_url=row.get("url"),
                executable=False,
                pair_online=True,
                mid_price=_number(row.get("priceUsd")),
                liquidity_usd=_number((row.get("liquidity") or {}).get("usd")),
                volume_24h_usd=_number((row.get("volume") or {}).get("h24")),
                pair_created_at=created,
                intended_notional_usd=notional,
                limitations=[
                    "DEX Screener has no executable router quote, order-book depth, "
                    "or sell simulation."
                ],
            ),
            payload,
        )

    def _get_json(self, url: str, params: dict[str, object]) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.get(
                        url, params=params, headers={"accept": "application/json"}
                    )
                    response.raise_for_status()
                    sanitized = {
                        key: value for key, value in params.items() if key.lower() != "apikey"
                    }
                    self._last_response_meta = {
                        "request_params_hash": hashlib.sha256(
                            json.dumps(
                                {"url": url, "params": sanitized},
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest(),
                        "response_received_at": datetime.now(UTC),
                        "http_status": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "request_manifest": [
                            {
                                "url": url,
                                "params": sanitized,
                                "received_at": datetime.now(UTC).isoformat(),
                                "status": response.status_code,
                                "content_type": response.headers.get("content-type"),
                            }
                        ],
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
        raise RuntimeError(f"Provider request failed for {url}: {last_error}") from last_error

    def _batch(
        self,
        *,
        provider: str,
        endpoint: str,
        observed_at: datetime,
        payload: Any,
    ) -> ProviderBatch:
        return ProviderBatch(
            provider=provider,
            endpoint=endpoint,
            observed_at=observed_at,
            payload=payload,
            **self._last_response_meta,
        )


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _currency_value(value: Any, currency: str) -> float | None:
    return _number(value.get(currency)) if isinstance(value, dict) else None


def _flag(value: Any) -> bool | None:
    if value in ("1", 1, True):
        return True
    if value in ("0", 0, False):
        return False
    return None


def _tax_pct(value: Any) -> float | None:
    number = _number(value)
    return number * 100 if number is not None else None


def _timestamp_ms(value: Any) -> datetime | None:
    number = _number(value)
    return datetime.fromtimestamp(number / 1000, tz=UTC) if number is not None else None


def _normal_symbol(value: str) -> str:
    symbol = value.upper().replace(".", "")
    return {"XBT": "BTC", "XXBT": "BTC", "XDG": "DOGE"}.get(symbol, symbol)


def _pair_symbols(value: dict[str, Any]) -> tuple[str, str] | None:
    name = value.get("wsname")
    if not name or "/" not in name:
        return None
    base, quote = str(name).split("/", 1)
    return _normal_symbol(base), _normal_symbol(quote)


def _book_rows(rows: list[list[Any]]) -> list[tuple[float, float]]:
    result = []
    for row in rows:
        if len(row) < 2:
            continue
        price, volume = _number(row[0]), _number(row[1])
        if price and volume:
            result.append((price, volume))
    return result


def _buy_vwap(asks: list[tuple[float, float]], notional: float) -> float | None:
    remaining = notional
    quantity = 0.0
    spent = 0.0
    for price, volume in asks:
        take_quote = min(remaining, price * volume)
        quantity += take_quote / price
        spent += take_quote
        remaining -= take_quote
        if remaining <= 1e-9:
            return spent / quantity
    return None


def _sell_vwap(bids: list[tuple[float, float]], quantity: float) -> float | None:
    remaining = quantity
    proceeds = 0.0
    sold = 0.0
    for price, volume in bids:
        take = min(remaining, volume)
        proceeds += take * price
        sold += take
        remaining -= take
        if remaining <= 1e-12:
            return proceeds / sold
    return None


def _depth_quote(
    rows: list[tuple[float, float]], *, upper: float | None = None, lower: float | None = None
) -> float:
    return sum(
        price * volume
        for price, volume in rows
        if (upper is None or price <= upper) and (lower is None or price >= lower)
    )
