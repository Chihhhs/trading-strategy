# Non-Crypto Hyperliquid News Strategy

## Status

- Mode: `new_alpha_research`
- Scope: HIP-3 builder-deployed perpetuals on Hyperliquid
- Initial markets: one verified HIP-3 DEX, with a small stock and oil watchlist
- Execution: research and paper observation only
- Live config: unchanged

This is a separate research line from the active crypto Trend strategy. It must
not expand `LIVE_UNIVERSE`, alter the crypto Trend signal, or reuse crypto
promotion evidence as evidence for stocks or commodities.

## Why this needs a separate adapter

Hyperliquid HIP-3 markets are not represented like the default perp DEX. The
API uses a DEX-qualified market identity such as `xyz:XYZ100`; `allMids` and
other info calls accept a DEX; candle requests use the qualified coin name; and
orders require the correct builder-deployed asset identity. A market can also
have deployer-defined oracle, leverage, funding, margin, fee, open-interest,
halt, and settlement behavior.

The current runtime assumes the default DEX and derives symbols as
`NAMEUSDT`. That path is not sufficient for HIP-3. The new line therefore needs
an explicit `InstrumentRef` containing at least:

- `dex`
- `coin`
- `qualified_coin`
- `asset_id`
- `market_class`
- `quote_token`
- `oracle_source`
- `margin_table`
- `leverage_limit`
- `market_status`
- `data_source`

The catalog must be refreshed from Hyperliquid metadata and fail closed when a
market is missing, halted, ambiguous, or no longer tradable.

## Market profiles

Stocks and oil must not share identical timing assumptions.

### Equity profile

- Track the underlying exchange session separately from the 24/7 HIP-3 book.
- Flag overnight, weekend, earnings, guidance, SEC filing, and gap-risk states.
- Do not assume that continuous HIP-3 trading means continuous underlying
  liquidity or reliable price discovery.
- Start with a small, liquid set only after metadata, oracle, spread, depth,
  and fee checks pass.

### Oil profile

- Track EIA, OPEC, geopolitical, supply disruption, inventory, and export
  headlines separately.
- Treat the first price spike as a shock observation, not an automatic entry.
- Measure the reaction at fixed horizons such as T+5m, T+15m, T+1h, and T+4h.
- Require wider volatility-aware risk limits and reject thin weekend or
  off-session conditions until replay evidence supports them.

## News source policy

`@aleabitoreddit` is a candidate stock and semiconductor source, not a truth
source and not a direct order trigger. Its posts should be stored with the
original URL, timestamp, account identity, mentioned tickers, event type, and
whether the post is original analysis, a link, a rumor, or a correction.

Use source tiers:

1. Primary: company filings, SEC/EDGAR, EIA, OPEC, government releases,
   exchange notices, and official company statements.
2. Fast corroboration: Reuters, First Squawk, Barchart, and equivalent
   timestamped market-news feeds.
3. Specialist commentators: `@aleabitoreddit` and other named accounts,
   weighted by measured historical precision per event type and ticker.
4. Community context: Reddit and other social discussion, used for breadth and
   disagreement, never as sole confirmation.

No source receives a permanent credibility score. Scores must be recalibrated
by event class, instrument, market session, and publication-to-price latency.

## Candidate event state

Each event should produce a reproducible state rather than an LLM sentiment
number alone:

- `event_id`, `source_id`, `source_url`, `published_at`, `observed_at`
- `instrument_refs`, `sector`, and `market_scope`
- `event_type`
- `direction`: `bullish`, `bearish`, or `neutral`
- `surprise`, `novelty`, `confidence`, and `source_count`
- `breadth`, `contradiction`, and `rumor_status`
- `expected_half_life`
- `point_in_time_eligible`

The event layer may label a candidate, block a trade, or reduce risk. It must
not create a position without price and execution confirmation.

## Entry hypothesis

The first hypothesis is event-confirmed continuation:

`qualified news event` + `price confirmation` + `liquidity confirmation`

For a long candidate, require a bullish event, a verified instrument mapping,
an aligned local trend, a close above the event range or breakout level, and
acceptable spread and top-of-book depth. Use the inverse for shorts.

Do not chase the initial spike. The first replay should compare a fixed delay
and fixed confirmation window against a no-news Trend or breakout baseline.

## Exit hypothesis

Use a layered exit policy:

1. Exchange-side hard stop based on initial ATR or event-range risk.
2. Thesis invalidation when a verified correction reverses the event, or price
   closes back through the event range and trend structure.
3. News decay exit when the expected half-life expires without follow-through.
4. Volatility and liquidity guard that reduces new risk or blocks re-entry; it
   must not widen an existing protective stop.
5. Trailing protection only after favorable progress. Fixed profit targets are
   not the first default for an event-driven trend candidate.

Equity and oil profiles must have separate decay windows and separate stop
parameters. A result that only works in one market class is not a generic
non-crypto strategy result.

## Research contract

- Use a point-in-time event archive. A current `last30days` summary alone is
  not sufficient for timestamp-accurate replay.
- Keep the HIP-3 market catalog, oracle metadata, fees, margin, and status
  fingerprint with every run.
- Compare gross and net PnL, spread/slippage, funding, turnover, drawdown,
  event count, latency, hold time, exit reasons, MFE/MAE, and concentration.
- Split by equity, oil, market session, event class, source tier, and news
  latency.
- Require out-of-sample cost-adjusted evidence and non-concentration before
  bounded paper observation.
- Paper observation must use a separate state directory and
  `execution_authorized=false` until a later explicit review.

## First implementation slice

1. Add a read-only HIP-3 market catalog and instrument identity tests.
2. Add a research-only event schema and point-in-time validation.
3. Add one small stock/oil fixture and a deterministic event replay report.
4. Compare news-confirmed entries and decay exits against a frozen baseline.
5. Add paper observation only after the research gate passes.

No live order path, live universe change, or automatic social-media execution
belongs in this first slice.
