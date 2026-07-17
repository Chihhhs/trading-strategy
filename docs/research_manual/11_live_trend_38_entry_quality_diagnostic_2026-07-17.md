# Fixed 38-Coin Trend Entry-Quality Diagnostic

Status: research-only. This result does not authorize observer, paper execution, or live changes.

## Frozen baseline

- Universe: the fixed 38-coin `LIVE_UNIVERSE` in `apps/live_config.py`.
- Data: 300 daily bars plus 240 days of 1h strict replay, ending at the last complete UTC date, 2026-07-16.
- Historical source: Binance USD-M Futures; metadata records per-coin coverage and the `binance_usdm_then_binance_spot_historical_only` fallback policy.
- Execution: daily Trend decision, strict 1h stop replay, mark-to-market drawdown, 5x leverage, 8% risk, two positions, 4.5 bps fee, and 2 bps slippage.

Baseline net PnL / MTM drawdown: 120d `-39.7% / 53.09%`, 180d `-49.1% / 64.22%`, 240d `-12.6% / 53.45%`.

## Single candidate

The raw attribution report found one cross-fold hypothesis: RSI `<50`. The candidate changes only the shared RSI entry ceiling:

- long ceiling: `75 -> 50`
- short ceiling: `55 -> 50`

All exits, costs, leverage, risk, position cap, BTC behavior, derivatives settings, fixture, and universe remain unchanged.

## Result

The candidate improved net PnL and did not worsen drawdown in all three windows:

| Window | Net PnL | MTM drawdown | Trades |
| --- | ---: | ---: | ---: |
| 120d | `22.1%` | `27.60%` | 4 |
| 180d | `-42.8%` | `57.15%` | 26 |
| 240d | `72.4%` | `27.05%` | 16 |

Decision: `research_follow_up`, not promotion. The 120d sample is only four trades, and the 240d result is concentrated in DOGE, UNI, and SUI. The only permitted next step is one stricter OOS/absolute-performance validation with concentration limits.

Artifacts:

- `experiments/live_trend_baseline_38.json`
- `experiments/live_trend_entry_rsi_ceiling_50_38.json`
- `data/historical_prices/binance_1h_240d_live_38coins.metadata.json`
- `data/research_artifacts/trend_entry_attribution_38coin.json`
- `data/research_artifacts/live_trend_entry_rsi_ceiling_50_38_diagnostic.json`
