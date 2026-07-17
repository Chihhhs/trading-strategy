"""Standalone, cost-aware strategy search with a locked final holdout."""

from bisect import bisect_left
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, pstdev
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from trading_strategy.strategies.cross_sectional_momentum import overlapping_momentum_weights


INFO_URL = "https://api.hyperliquid.xyz/info"


@dataclass(frozen=True)
class Candidate:
    name: str
    family: str
    lookback: int
    rebalance_days: int = 7
    top_n: int = 3
    long_lookback: int = 90
    min_breadth: float = 0.0
    weighting: str = "equal"
    volatility_lookback: int = 28
    carry_bps_per_day: float = 0.0
    overlap_cohorts: int = 1
    cohort_spacing: int = 1


@dataclass(frozen=True)
class Metrics:
    net_pnl_pct: float
    gross_pnl_pct: float
    max_drawdown_pct: float
    sharpe: float
    turnover: float
    changed_legs: int
    invested_fraction: float
    max_positive_contribution_share: float
    coin_contributions: dict[str, float]


DEFAULT_CANDIDATES = (
    Candidate("tsm-90", "time_series", 90, top_n=99),
    Candidate("rotation-28", "rotation", 28, top_n=3, min_breadth=0.5),
    Candidate("rotation-14", "rotation", 14, top_n=3, min_breadth=0.5),
    Candidate(
        "rotation-14-diversified",
        "rotation",
        14,
        top_n=5,
        min_breadth=0.5,
        weighting="inverse_vol",
    ),
    Candidate("dual-28-90", "dual", 28, top_n=3, long_lookback=90, min_breadth=0.5),
    Candidate(
        "dual-28-90-inverse-vol",
        "dual",
        28,
        top_n=3,
        long_lookback=90,
        min_breadth=0.5,
        weighting="inverse_vol",
    ),
    Candidate(
        "dual-28-90-diversified",
        "dual",
        28,
        top_n=5,
        long_lookback=90,
        min_breadth=0.5,
        weighting="inverse_vol",
    ),
    Candidate("pullback-14-90", "pullback", 14, top_n=3, long_lookback=90, min_breadth=0.5),
    Candidate(
        "market-neutral-reversal-56",
        "reversal_long_short",
        56,
        top_n=3,
        carry_bps_per_day=1.0,
    ),
)


FOUR_HOUR_CANDIDATES = (
    Candidate("4h-tsm-30d", "time_series", 180, rebalance_days=6, top_n=99),
    Candidate("4h-rotation-7d", "rotation", 42, rebalance_days=42, top_n=3, min_breadth=0.5),
    Candidate("4h-rotation-14d", "rotation", 84, rebalance_days=42, top_n=3, min_breadth=0.5),
    Candidate(
        "4h-rotation-14d-diversified",
        "rotation",
        84,
        rebalance_days=42,
        top_n=5,
        min_breadth=0.5,
        weighting="inverse_vol",
        volatility_lookback=168,
    ),
    Candidate("4h-dual-7d-30d", "dual", 42, rebalance_days=42, top_n=3, long_lookback=180, min_breadth=0.5),
    Candidate(
        "4h-reversal-56d",
        "reversal_long_short",
        336,
        rebalance_days=42,
        top_n=3,
        carry_bps_per_day=1.0,
    ),
    Candidate(
        "4h-overlapping-momentum-14d",
        "overlapping_momentum_long_short",
        84,
        rebalance_days=6,
        top_n=3,
        overlap_cohorts=7,
        cohort_spacing=6,
    ),
    Candidate(
        "4h-overlapping-reversal-56d",
        "overlapping_reversal_long_short",
        336,
        rebalance_days=6,
        top_n=3,
        carry_bps_per_day=1.0,
        overlap_cohorts=7,
        cohort_spacing=6,
    ),
)


def _post(payload):
    request = Request(INFO_URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_current_daily_fixture(
    path,
    *,
    volume_pool=30,
    min_bars=720,
    max_assets=12,
    now_ms=None,
    interval="1d",
    coins=None,
):
    meta, contexts = _post({"type": "metaAndAssetCtxs"})
    available = {
        asset["name"].upper(): (float(context.get("dayNtlVlm") or 0.0), asset["name"])
        for asset, context in zip(meta["universe"], contexts)
        if not asset.get("isDelisted", False)
    }
    if coins:
        missing = [coin for coin in coins if coin.upper() not in available]
        if missing:
            raise ValueError(f"fixed Hyperliquid universe is unavailable: {', '.join(missing)}")
        ranked = [available[coin.upper()] for coin in coins]
        max_assets = len(ranked)
    else:
        ranked = sorted(available.values(), reverse=True)[:volume_pool]
    end_ms = int(now_ms or time.time() * 1000)
    start_ms = end_ms - 5 * 366 * 86_400_000
    data = {}
    volume_snapshot = {}
    for volume, coin in ranked:
        rows = _post(
            {
                "type": "candleSnapshot",
                "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms},
            }
        )
        candles = [
            {
                "time": int(row["t"]),
                "open": float(row["o"]),
                "high": float(row["h"]),
                "low": float(row["l"]),
                "close": float(row["c"]),
                "volume": float(row["v"]),
            }
            for row in rows
        ]
        if len(candles) >= min_bars:
            data[coin] = candles
            volume_snapshot[coin] = volume
        if len(data) >= max_assets:
            break
    if coins and len(data) != len(ranked):
        missing = [coin for _volume, coin in ranked if coin not in data]
        raise ValueError(f"fixed Hyperliquid universe lacks required history: {', '.join(missing)}")
    if len(data) < 5:
        raise ValueError("insufficient current Hyperliquid assets with required history")
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "venue": "hyperliquid",
        "interval": interval,
        "selection": {
            "rule": "fixed manifest universe" if coins else "top current day notional volume with minimum history",
            "volume_pool": volume_pool,
            "min_bars": min_bars,
            "max_assets": max_assets,
            "day_notional_volume": volume_snapshot,
        },
        "data": data,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload


def load_fixture(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_funding_fixture(path):
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    data_directory = Path(manifest["data_directory"])
    if not data_directory.is_absolute() and not data_directory.is_dir():
        data_directory = manifest_path.parent / data_directory.name
    return {
        coin: json.loads((data_directory / f"{coin}.json").read_text(encoding="utf-8"))
        for coin in manifest["completed_coins"]
    }


def fetch_current_perp_meta(path):
    meta, contexts = _post({"type": "metaAndAssetCtxs"})
    assets = {
        asset["name"]: {
            "sz_decimals": int(asset["szDecimals"]),
            "is_delisted": bool(asset.get("isDelisted", False)),
            "mark_price": float(context["markPx"]),
        }
        for asset, context in zip(meta["universe"], contexts)
    }
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "venue": "hyperliquid",
        "assets": assets,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload


def fetch_coinbase_daily_fixture(
    path,
    *,
    products=("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "DOGE-USD", "LINK-USD", "LTC-USD"),
    years=5,
):
    end_seconds = int(time.time())
    start_seconds = end_seconds - years * 366 * 86_400
    data = {}
    for product in products:
        candles = {}
        page_start = start_seconds
        while page_start < end_seconds:
            page_end = min(page_start + 250 * 86_400, end_seconds)
            query = urlencode(
                {
                    "granularity": 86400,
                    "start": datetime.fromtimestamp(page_start, timezone.utc).isoformat(),
                    "end": datetime.fromtimestamp(page_end, timezone.utc).isoformat(),
                }
            )
            request = Request(
                f"https://api.exchange.coinbase.com/products/{product}/candles?{query}",
                headers={"User-Agent": "clean-room-strategy-research"},
            )
            with urlopen(request, timeout=30) as response:
                rows = json.load(response)
            for timestamp, low, high, open_price, close, volume in rows:
                candles[int(timestamp) * 1000] = {
                    "time": int(timestamp) * 1000,
                    "open": float(open_price),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume),
                }
            page_start = page_end
        data[product.split("-")[0]] = [candles[key] for key in sorted(candles)]
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "venue": "coinbase_exchange",
        "interval": "1d",
        "selection": {"rule": "fixed liquid USD spot majors", "products": list(products), "years": years},
        "data": data,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload


def fetch_hyperliquid_funding_fixture(
    candle_fixture_path,
    output_path,
    *,
    pause_seconds=0,
    page_pause_seconds=1.5,
):
    candle_fixture = load_fixture(candle_fixture_path)
    output = Path(output_path)
    data_dir = output.with_suffix("")
    data_dir.mkdir(parents=True, exist_ok=True)
    if output.is_file():
        payload = json.loads(output.read_text(encoding="utf-8-sig"))
        legacy_data = payload.pop("data", {})
        for coin, rows in legacy_data.items():
            coin_path = data_dir / f"{coin}.json"
            if rows and not coin_path.is_file():
                coin_path.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
    else:
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "venue": "hyperliquid",
            "source_fixture": str(candle_fixture_path),
            "completed_coins": [],
        }
    payload.setdefault("completed_coins", [])
    payload["data_directory"] = str(data_dir)
    output.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    coins = sorted(candle_fixture["data"])
    for coin_index, coin in enumerate(coins):
        coin_path = data_dir / f"{coin}.json"
        bars = candle_fixture["data"][coin]
        cached = json.loads(coin_path.read_text(encoding="utf-8")) if coin_path.is_file() else []
        if coin in payload["completed_coins"] and cached and int(cached[-1]["time"]) >= int(bars[-1]["time"]):
            print(f"funding {coin}: cached {len(cached)}", flush=True)
            continue
        if coin in payload["completed_coins"]:
            payload["completed_coins"].remove(coin)
        rows = cached
        cursor = int(rows[-1]["time"]) + 1 if rows else int(bars[0]["time"])
        end_time = int(bars[-1]["time"])
        page_count = 0
        while cursor <= end_time:
            page = _post({"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": end_time})
            if not page:
                break
            rows.extend(
                {
                    "time": int(row["time"]),
                    "funding_rate": float(row["fundingRate"]),
                    "premium": float(row.get("premium") or 0.0),
                }
                for row in page
            )
            next_cursor = int(page[-1]["time"]) + 1
            coin_path.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
            page_count += 1
            print(f"funding {coin}: page {page_count}, rows {len(rows)}", flush=True)
            if next_cursor <= cursor or len(page) < 500:
                break
            cursor = next_cursor
            if page_pause_seconds:
                time.sleep(page_pause_seconds)
        payload["completed_coins"].append(coin)
        output.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        print(f"funding {coin}: fetched {len(rows)} ({coin_index + 1}/{len(coins)})", flush=True)
        if coin_index < len(coins) - 1 and pause_seconds:
            time.sleep(pause_seconds)
    return payload


def _aligned_closes(data):
    points = {coin: {int(bar["time"]): float(bar["close"]) for bar in bars} for coin, bars in data.items()}
    timestamps = sorted(set.intersection(*(set(values) for values in points.values())))
    return timestamps, {coin: [values[timestamp] for timestamp in timestamps] for coin, values in points.items()}


def _aligned_funding(timestamps, coins, funding_data):
    aligned = {coin: [0.0] * len(timestamps) for coin in coins}
    if not funding_data:
        return aligned
    for coin in coins:
        for row in funding_data.get(coin, ()):
            index = bisect_left(timestamps, int(row["time"]))
            if 0 < index < len(timestamps):
                aligned[coin][index] += float(row["funding_rate"])
    return aligned


def _reversal_weights(candidate, closes, index):
    short_returns = {coin: values[index] / values[index - candidate.lookback] - 1.0 for coin, values in closes.items()}
    ordered = [coin for coin, _value in sorted(short_returns.items(), key=lambda item: item[1])]
    longs = ordered[: candidate.top_n]
    shorts = ordered[-candidate.top_n :]
    sleeve = 0.5 / candidate.top_n
    return {coin: sleeve for coin in longs} | {coin: -sleeve for coin in shorts}


def _momentum_weights(candidate, closes, index):
    return {coin: -weight for coin, weight in _reversal_weights(candidate, closes, index).items()}


def _candidate_warmup(candidate):
    base = max(
        candidate.lookback,
        candidate.long_lookback if candidate.family in {"dual", "pullback"} else 0,
    )
    return base + max(candidate.overlap_cohorts - 1, 0) * candidate.cohort_spacing


def _target_weights(candidate, closes, index):
    if candidate.family == "reversal_long_short":
        return _reversal_weights(candidate, closes, index)
    if candidate.family == "momentum_long_short":
        return _momentum_weights(candidate, closes, index)
    if candidate.family == "overlapping_momentum_long_short":
        return overlapping_momentum_weights(
            closes,
            index=index,
            lookback_bars=candidate.lookback,
            top_n=candidate.top_n,
            overlap_cohorts=candidate.overlap_cohorts,
            cohort_spacing_bars=candidate.cohort_spacing,
        )
    if candidate.family == "overlapping_reversal_long_short":
        cohorts = [
            _reversal_weights(candidate, closes, index - offset * candidate.cohort_spacing)
            for offset in range(candidate.overlap_cohorts)
        ]
        coins = set().union(*(set(cohort) for cohort in cohorts))
        return {
            coin: sum(cohort.get(coin, 0.0) for cohort in cohorts) / len(cohorts)
            for coin in coins
            if abs(sum(cohort.get(coin, 0.0) for cohort in cohorts)) > 1e-12
        }
    short_returns = {coin: values[index] / values[index - candidate.lookback] - 1.0 for coin, values in closes.items()}
    breadth = sum(value > 0.0 for value in short_returns.values()) / len(short_returns)
    if breadth < candidate.min_breadth:
        return {}
    if candidate.family == "time_series":
        selected = [coin for coin, value in short_returns.items() if value > 0.0]
    elif candidate.family == "rotation":
        selected = [coin for coin, value in sorted(short_returns.items(), key=lambda item: item[1], reverse=True) if value > 0.0][
            : candidate.top_n
        ]
    else:
        long_returns = {
            coin: values[index] / values[index - candidate.long_lookback] - 1.0 for coin, values in closes.items()
        }
        eligible = [coin for coin, value in long_returns.items() if value > 0.0]
        if candidate.family == "dual":
            selected = [coin for coin in sorted(eligible, key=short_returns.get, reverse=True) if short_returns[coin] > 0.0][
                : candidate.top_n
            ]
        elif candidate.family == "pullback":
            selected = sorted(eligible, key=short_returns.get)[: candidate.top_n]
        else:
            raise ValueError(f"unknown candidate family: {candidate.family}")
    if candidate.top_n < len(selected):
        selected = selected[: candidate.top_n]
    if not selected:
        return {}
    if candidate.weighting == "equal":
        return {coin: 1.0 / len(selected) for coin in selected}
    if candidate.weighting != "inverse_vol":
        raise ValueError(f"unknown weighting: {candidate.weighting}")
    inverse_volatility = {}
    for coin in selected:
        values = closes[coin]
        start = max(index - candidate.volatility_lookback, 1)
        returns = [values[offset] / values[offset - 1] - 1.0 for offset in range(start, index + 1)]
        volatility = pstdev(returns) if len(returns) > 1 else 0.0
        inverse_volatility[coin] = 1.0 / max(volatility, 0.005)
    total = sum(inverse_volatility.values())
    return {coin: value / total for coin, value in inverse_volatility.items()}


def evaluate(
    candidate,
    data,
    *,
    start_index,
    end_index=None,
    one_way_cost_bps=6.5,
    periods_per_year=365.0,
    bars_per_day=1.0,
    aligned_funding=None,
    funding_data=None,
):
    timestamps, closes = _aligned_closes(data)
    funding = aligned_funding or _aligned_funding(timestamps, closes, funding_data)
    end_index = min(end_index or len(next(iter(closes.values()))), len(next(iter(closes.values()))))
    warmup = _candidate_warmup(candidate)
    if start_index <= warmup or end_index - start_index < 2:
        raise ValueError("evaluation segment requires warmup and at least two return bars")
    weights = _target_weights(candidate, closes, start_index - 1)
    gross_equity = 1.0
    turnover = sum(abs(value) for value in weights.values())
    net_equity = max(1.0 - turnover * one_way_cost_bps / 10_000.0, 0.0)
    changed_legs = len(weights)
    invested_days = 0
    daily_net = []
    contributions = {coin: 0.0 for coin in closes}
    cost_rate = one_way_cost_bps / 10_000.0
    for index in range(start_index, end_index):
        returns = {coin: values[index] / values[index - 1] - 1.0 for coin, values in closes.items()}
        gross_return = sum(weights.get(coin, 0.0) * value for coin, value in returns.items())
        funding_return = -sum(weights.get(coin, 0.0) * funding[coin][index] for coin in closes)
        previous_net = net_equity
        gross_equity *= 1.0 + gross_return
        net_equity *= 1.0 + gross_return
        net_equity *= 1.0 + funding_return
        carry_cost = (
            sum(abs(value) for value in weights.values())
            * candidate.carry_bps_per_day
            / bars_per_day
            / 10_000.0
        )
        net_equity *= max(1.0 - carry_cost, 0.0)
        for coin, value in returns.items():
            contributions[coin] += weights.get(coin, 0.0) * (value - funding[coin][index]) * 100.0
        if weights:
            invested_days += 1
        if (index - start_index + 1) % candidate.rebalance_days == 0 and index < end_index - 1:
            target = _target_weights(candidate, closes, index)
            changed = set(weights) | set(target)
            day_turnover = sum(abs(target.get(coin, 0.0) - weights.get(coin, 0.0)) for coin in changed)
            changed_legs += sum(abs(target.get(coin, 0.0) - weights.get(coin, 0.0)) > 1e-12 for coin in changed)
            turnover += day_turnover
            net_equity *= max(1.0 - day_turnover * cost_rate, 0.0)
            weights = target
        daily_net.append(net_equity / previous_net - 1.0)
    max_drawdown = 0.0
    equity = 1.0
    local_peak = 1.0
    for value in daily_net:
        equity *= 1.0 + value
        local_peak = max(local_peak, equity)
        max_drawdown = max(max_drawdown, (local_peak - equity) / local_peak * 100.0)
    volatility = pstdev(daily_net) if len(daily_net) > 1 else 0.0
    sharpe = mean(daily_net) / volatility * math.sqrt(periods_per_year) if volatility else 0.0
    positive_contributions = [value for value in contributions.values() if value > 0.0]
    max_positive_share = (
        max(positive_contributions) / sum(positive_contributions)
        if positive_contributions
        else 0.0
    )
    return Metrics(
        net_pnl_pct=(net_equity - 1.0) * 100.0,
        gross_pnl_pct=(gross_equity - 1.0) * 100.0,
        max_drawdown_pct=max_drawdown,
        sharpe=sharpe,
        turnover=turnover,
        changed_legs=changed_legs,
        invested_fraction=invested_days / len(daily_net),
        max_positive_contribution_share=max_positive_share,
        coin_contributions={coin: value for coin, value in contributions.items() if value},
    )


def search(
    data,
    *,
    holdout_days=120,
    fold_days=120,
    candidates=DEFAULT_CANDIDATES,
    unlock_holdout=False,
    periods_per_year=365.0,
    bars_per_day=1.0,
    funding_data=None,
):
    timestamps, closes = _aligned_closes(data)
    aligned_funding = _aligned_funding(timestamps, closes, funding_data)
    total = len(timestamps)
    development_end = total - holdout_days
    warmup = max(_candidate_warmup(candidate) for candidate in candidates)
    starts = list(range(warmup + 1, development_end - fold_days + 1, fold_days))
    starts = starts[-6:]
    rows = []
    eligible = []
    for candidate in candidates:
        folds = [
            evaluate(
                candidate,
                data,
                start_index=start,
                end_index=start + fold_days,
                periods_per_year=periods_per_year,
                bars_per_day=bars_per_day,
                aligned_funding=aligned_funding,
            )
            for start in starts
        ]
        positive = sum(row.net_pnl_pct > 0.0 for row in folds)
        median_sharpe = sorted(row.sharpe for row in folds)[len(folds) // 2]
        worst_drawdown = max(row.max_drawdown_pct for row in folds)
        positive_rows = [row for row in folds if row.net_pnl_pct > 0.0]
        worst_concentration = max((row.max_positive_contribution_share for row in positive_rows), default=1.0)
        required_positive = math.ceil(len(folds) * 0.75)
        passed = positive >= required_positive and median_sharpe > 0.5 and worst_drawdown <= 25.0 and worst_concentration <= 0.6
        rows.append(
            {
                "candidate": asdict(candidate),
                "folds": [asdict(row) for row in folds],
                "positive_folds": positive,
                "required_positive_folds": required_positive,
                "median_sharpe": median_sharpe,
                "worst_drawdown_pct": worst_drawdown,
                "worst_positive_contribution_share": worst_concentration,
                "passed": passed,
            }
        )
        if passed:
            eligible.append((median_sharpe, candidate))
    provisional_selected = max(eligible, default=(None, None), key=lambda item: item[0])[1]
    robustness = None
    selected = provisional_selected
    if provisional_selected is not None:
        shift_step = 1 if provisional_selected.rebalance_days <= bars_per_day else max(int(bars_per_day), 1)
        shifts = range(0, provisional_selected.rebalance_days, shift_step)

        def audit(candidate, *, one_way_cost_bps):
            scenarios = [
                evaluate(
                    candidate,
                    data,
                    start_index=start + shift,
                    end_index=start + shift + fold_days,
                    one_way_cost_bps=one_way_cost_bps,
                    periods_per_year=periods_per_year,
                    bars_per_day=bars_per_day,
                    aligned_funding=aligned_funding,
                )
                for shift in shifts
                for start in starts
                if start + shift + fold_days <= development_end
            ]
            positive_rows = [row for row in scenarios if row.net_pnl_pct > 0.0]
            return {
                "scenarios": len(scenarios),
                "positive_scenarios": len(positive_rows),
                "required_positive_scenarios": math.ceil(len(scenarios) * 0.75),
                "median_net_pnl_pct": sorted(row.net_pnl_pct for row in scenarios)[len(scenarios) // 2],
                "median_sharpe": sorted(row.sharpe for row in scenarios)[len(scenarios) // 2],
                "worst_drawdown_pct": max(row.max_drawdown_pct for row in scenarios),
                "worst_positive_contribution_share": max(
                    (row.max_positive_contribution_share for row in positive_rows),
                    default=0.0,
                ),
            }

        normal = audit(provisional_selected, one_way_cost_bps=6.5)
        stressed_candidate = replace(
            provisional_selected,
            carry_bps_per_day=provisional_selected.carry_bps_per_day + 1.0,
        )
        stressed = audit(stressed_candidate, one_way_cost_bps=10.0)
        robust = all(
            summary["positive_scenarios"] >= summary["required_positive_scenarios"]
            and summary["worst_drawdown_pct"] <= 25.0
            and summary["worst_positive_contribution_share"] <= 0.6
            for summary in (normal, stressed)
        )
        robustness = {"normal": normal, "stressed": stressed, "passed": robust}
        if not robust:
            selected = None
    holdout = (
        evaluate(
            selected,
            data,
            start_index=development_end,
            end_index=total,
            periods_per_year=periods_per_year,
            bars_per_day=bars_per_day,
            aligned_funding=aligned_funding,
        )
        if selected and unlock_holdout
        else None
    )
    return {
        "bars": total,
        "coins": sorted(closes),
        "holdout_days": holdout_days,
        "development_fold_starts": starts,
        "candidates": rows,
        "provisional_selected": asdict(provisional_selected) if provisional_selected else None,
        "robustness": robustness,
        "selected": asdict(selected) if selected else None,
        "holdout_unlocked": bool(unlock_holdout),
        "holdout": asdict(holdout) if holdout else None,
    }


def write_search_report(fixture_path, output_path, *, unlock_holdout=False, funding_path=None):
    fixture = load_fixture(fixture_path)
    is_four_hour = fixture.get("interval") == "4h"
    funding_data = load_funding_fixture(funding_path) if funding_path else None
    candidates = FOUR_HOUR_CANDIDATES if is_four_hour else DEFAULT_CANDIDATES
    if funding_data:
        candidates = tuple(replace(candidate, carry_bps_per_day=0.0) for candidate in candidates)
    report = search(
        fixture["data"],
        holdout_days=720 if is_four_hour else 120,
        fold_days=720 if is_four_hour else 120,
        candidates=candidates,
        unlock_holdout=unlock_holdout,
        periods_per_year=2190.0 if is_four_hour else 365.0,
        bars_per_day=6.0 if is_four_hour else 1.0,
        funding_data=funding_data,
    )
    report["fixture"] = {key: value for key, value in fixture.items() if key != "data"}
    report["funding_fixture"] = str(funding_path) if funding_path else None
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
