"""Locked cross-venue replay of the selected state-only momentum candidate."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

try:
    from backtest.run_low_capital_lab import _json_request
    from backtest.run_low_capital_regime_momentum_lab import simulate
except ModuleNotFoundError:
    from run_low_capital_lab import _json_request
    from run_low_capital_regime_momentum_lab import simulate


HOUR_MS = 3_600_000
REPLAY_BARS = 180 * 24


def fetch_funding(coin, start_ms, end_ms):
    rows = []
    cursor = start_ms
    while cursor <= end_ms:
        page = _json_request(
            "https://api.hyperliquid.xyz/info",
            {"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": end_ms},
        )
        if not page:
            break
        rows.extend(
            [int(row["time"]), float(row["fundingRate"])]
            for row in page
            if int(row["time"]) <= end_ms
        )
        cursor = int(page[-1]["time"]) + 1
        if len(page) < 500:
            break
        time.sleep(0.2)
    return sorted({timestamp: rate for timestamp, rate in rows}.items())


def fetch_fixture(path, coin="ETH"):
    now = int(time.time() * 1000)
    end_ms = now // HOUR_MS * HOUR_MS - 1
    start_ms = end_ms - (5000 - 1) * HOUR_MS
    candles = _json_request(
        "https://api.hyperliquid.xyz/info",
        {"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": start_ms, "endTime": end_ms}},
    )
    meta = _json_request("https://api.hyperliquid.xyz/info", {"type": "meta"})
    asset = next(row for row in meta["universe"] if row["name"] == coin and not row.get("isDelisted", False))
    payload = {
        "schema_version": 1,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "Hyperliquid public candleSnapshot and fundingHistory",
        "coin": coin,
        "interval": "1h",
        "sz_decimals": int(asset["szDecimals"]),
        "candles": [[int(row["t"]), float(row["c"])] for row in candles if int(row["T"]) <= end_ms],
        "funding": fetch_funding(coin, start_ms, end_ms),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def aligned(payload):
    timestamps = [int(row[0]) for row in payload["candles"]]
    prices = [float(row[1]) for row in payload["candles"]]
    events = [(int(row[0]), float(row[1])) for row in payload["funding"]]
    cursor = 0
    rates = [0.0]
    for index in range(1, len(timestamps)):
        total = 0.0
        while cursor < len(events) and events[cursor][0] <= timestamps[index]:
            if events[cursor][0] > timestamps[index - 1]:
                total += events[cursor][1]
            cursor += 1
        rates.append(total)
    return timestamps, prices, rates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-artifact", default="data/research_artifacts/low_capital_state_only_momentum.json")
    parser.add_argument("--fixture", default="data/clean_room/hyperliquid_eth_1h_state_only_replay.json")
    parser.add_argument("--output", default="data/research_artifacts/state_only_momentum_hyperliquid_replay.json")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload = fetch_fixture(fixture_path) if args.fetch else json.loads(fixture_path.read_text(encoding="utf-8"))
    candidate_report = json.loads(Path(args.candidate_artifact).read_text(encoding="utf-8"))
    if candidate_report["route"]["decision"] != "validation_pass":
        raise ValueError("candidate has not passed its locked validation")
    candidate = candidate_report["route"]["best"]["candidate"]
    if candidate["coin"] != payload["coin"]:
        raise ValueError("candidate and replay coin differ")
    timestamps, prices, rates = aligned(payload)
    if len(timestamps) < REPLAY_BARS:
        raise ValueError("insufficient Hyperliquid candles for locked replay")
    start = len(timestamps) - REPLAY_BARS
    common = {
        "candidate": candidate,
        "timestamps": timestamps,
        "closes": {payload["coin"]: prices},
        "funding": {payload["coin"]: rates},
        "decimals": {payload["coin"]: payload["sz_decimals"]},
        "start": start,
        "end": len(timestamps),
    }
    normal = simulate(
        common["candidate"], common["timestamps"], common["closes"], common["funding"], common["decimals"], start=start, end=len(timestamps)
    )
    stressed = simulate(
        common["candidate"], common["timestamps"], common["closes"], common["funding"], common["decimals"], start=start, end=len(timestamps), cost_bps=10.0
    )
    failures = []
    if normal["net_return_pct"] <= 0:
        failures.append("normal_net_return_not_positive")
    if stressed["net_return_pct"] <= 0:
        failures.append("stressed_net_return_not_positive")
    if stressed["max_drawdown_pct"] > 20.0:
        failures.append("stressed_drawdown_above_20_pct")
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_authorized": False,
        "decision": "cross_venue_pass" if not failures else "rejected_cross_venue",
        "review": failures,
        "candidate": candidate,
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "data": {"bars": REPLAY_BARS, "start": timestamps[start], "end": timestamps[-1], "source": payload["source"]},
        "normal": normal,
        "stressed": stressed,
        "capital_replay": {
            str(capital): simulate(
                candidate,
                timestamps,
                {payload["coin"]: prices},
                {payload["coin"]: rates},
                {payload["coin"]: payload["sz_decimals"]},
                start=start,
                end=len(timestamps),
                capital=float(capital),
            )
            for capital in (20, 25, 30, 50, 100)
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("decision", "review", "data", "normal", "stressed")}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
