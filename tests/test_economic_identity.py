from trader_pete.analysis.economic import economic_underlying_key


def test_tokenized_equity_wrappers_share_one_economic_underlying() -> None:
    bstock = economic_underlying_key(
        asset_id="spacex-bstocks-tokenized-stock",
        name="SpaceX bStocks Tokenized Stock",
        symbol="SPCXB",
    )
    xstock = economic_underlying_key(
        asset_id="spacex-xstocks",
        name="SpaceX xStocks",
        symbol="SPCXX",
    )

    assert bstock == xstock == "wrapped:spacex"


def test_ordinary_crypto_assets_keep_exact_provider_identity() -> None:
    assert economic_underlying_key(asset_id="bitcoin", name="Bitcoin", symbol="BTC") == "bitcoin"


def test_company_name_and_ticker_aliases_collapse() -> None:
    ticker = economic_underlying_key(asset_id="aapl-bstocks", name="AAPL bStocks", symbol="AAPLB")
    company = economic_underlying_key(asset_id="apple-xstock", name="Apple xStock", symbol="AAPLX")

    assert ticker == company == "wrapped:aapl"


def test_unmapped_wrapper_symbols_cannot_create_false_breadth() -> None:
    bstock = economic_underlying_key(
        asset_id="foo-corp-bstocks", name="Foo Corp bStocks", symbol="FOOB"
    )
    xstock = economic_underlying_key(
        asset_id="foo-corp-xstock", name="Foo Corp xStock", symbol="FOOX"
    )

    assert bstock == xstock == "wrapped:ambiguous"
