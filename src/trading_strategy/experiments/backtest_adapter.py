from dataclasses import asdict, fields
from hashlib import sha256
import json
from pathlib import Path

from trading_strategy.backtest import PortfolioBacktester, load_derivatives_data, load_historical_data
from trading_strategy.backtest.cross_sectional import CrossSectionalStrengthBacktester
from trading_strategy.backtest.independent_lab import load_fixture, load_funding_fixture
from trading_strategy.backtest.overlapping_momentum import OverlappingMomentumBacktester
from trading_strategy.backtest.exit_replay import normalize_hourly_data
from trading_strategy.backtest.fixture_metadata import require_complete_fixture
from trading_strategy.backtest.types import BacktestConfig
from trading_strategy.strategies import get_strategy_definition

from .results import ExperimentResult


class BacktestExperimentAdapter:
    @staticmethod
    def _file_fingerprint(path):
        if not path or not Path(path).is_file():
            return ""
        digest = sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def build_config(self, spec, *, max_days=None, coins=None):
        strategy_values = asdict(spec.strategy.parameters)
        allowed = {field.name for field in fields(BacktestConfig)}
        strategy_values = {key: value for key, value in strategy_values.items() if key in allowed}
        definition = get_strategy_definition(spec.strategy.name)
        return BacktestConfig(
            coins=tuple(coins or spec.coins),
            strategy=spec.strategy.name,
            strategy_parameters=asdict(spec.strategy.parameters),
            max_days=max_days if max_days is not None else max(spec.evaluation.windows),
            initial_capital=spec.portfolio.initial_capital,
            leverage=spec.portfolio.leverage,
            risk_pct=spec.portfolio.risk_pct,
            max_positions=spec.portfolio.max_positions,
            min_bars=definition.min_bars,
            fee_bps=spec.costs.fee_bps,
            slippage_bps=spec.costs.slippage_bps,
            **strategy_values,
        )

    def run(self, spec):
        definition = get_strategy_definition(spec.strategy.name)
        if "overlapping_portfolio" in definition.capabilities:
            return self._run_overlapping_momentum(spec)
        data_map = load_historical_data(spec.dataset.path)
        if "cross_sectional" in definition.capabilities:
            return self._run_cross_sectional(spec, data_map)
        derivatives = load_derivatives_data(spec.dataset.derivatives_path)
        exit_replay_data = self._load_exit_replay_data(
            spec.execution.exit_replay_path,
            spec.execution.replay_metadata_path,
            required_coins=spec.coins if spec.execution.drawdown_source == "mark_to_market" else (),
        )
        windows = spec.evaluation.windows
        universes = spec.evaluation.universes or (spec.coins,)
        rows = []
        dataset_fingerprint = self._file_fingerprint(spec.dataset.path)
        for window in windows:
            for universe in universes:
                coins = tuple(coin for coin in universe if coin in spec.coins)
                if not coins:
                    continue
                config = self.build_config(spec, max_days=window, coins=coins)
                result = PortfolioBacktester(
                    config=config,
                    derivatives_data_map=derivatives,
                    exit_replay_data_map=exit_replay_data,
                    exit_replay_mode=spec.execution.exit_replay_mode,
                ).run(data_map)
                max_drawdown = result.portfolio.get("max_drawdown") or 0.0
                if spec.execution.drawdown_source == "mark_to_market":
                    max_drawdown = result.portfolio.get("mark_to_market_max_drawdown")
                    if max_drawdown is None:
                        raise ValueError("mark-to-market drawdown was not produced by the configured replay")
                initial = float(config.initial_capital or 1.0)
                turnover_notional = sum(
                    abs(float(trade.get("entry") or 0.0) * float(trade.get("size") or 0.0))
                    + abs(float(trade.get("exit_price") or trade.get("exit") or 0.0) * float(trade.get("size") or 0.0))
                    for trade in result.trades
                )
                rows.append(
                    ExperimentResult(
                        experiment_name=spec.name,
                        manifest_fingerprint=spec.fingerprint,
                        dataset_id=spec.dataset.id,
                        strategy_name=spec.strategy.name,
                        window=window,
                        universe=coins,
                        trades=int(result.portfolio.get("trades") or 0),
                        net_pnl_pct=float(result.portfolio.get("total_pnl_pct") or 0.0),
                        max_drawdown_pct=float(max_drawdown),
                        turnover=round(turnover_notional / initial, 6),
                        coin_contributions={row.coin: row.total_pnl for row in result.coin_results},
                        gross_pnl_pct=float(result.portfolio.get("gross_pnl_pct") or 0.0),
                        total_cost_pct=float(result.portfolio.get("total_cost_pct") or 0.0),
                        fee_bps=float(config.fee_bps),
                        slippage_bps=float(config.slippage_bps),
                        average_hold_bars=float(result.portfolio.get("avg_hold_bars") or 0.0),
                        exit_reason_counts=dict(result.portfolio.get("exit_reason_counts") or {}),
                        direction_summary=dict(result.portfolio.get("direction_summary") or {}),
                        missing_data_coins=tuple(result.portfolio.get("missing_data_coins") or ()),
                        dataset_fingerprint=dataset_fingerprint,
                        data_source=spec.dataset.id,
                        version=2,
                    )
                )
        return rows

    def _run_overlapping_momentum(self, spec):
        fixture = load_fixture(spec.dataset.path)
        data_map = {coin.upper(): bars for coin, bars in fixture["data"].items()}
        funding_data = (
            {coin.upper(): rows for coin, rows in load_funding_fixture(spec.dataset.derivatives_path).items()}
            if spec.dataset.derivatives_path
            else None
        )
        dataset_fingerprint = self._file_fingerprint(spec.dataset.path)
        rows = []
        universes = spec.evaluation.universes or (spec.coins,)
        for window in spec.evaluation.windows:
            for universe in universes:
                coins = tuple(coin for coin in universe if coin in spec.coins and coin in data_map)
                metrics = OverlappingMomentumBacktester(
                    fee_bps=spec.costs.fee_bps,
                    slippage_bps=spec.costs.slippage_bps,
                    parameters=spec.strategy.parameters,
                    funding_data={coin: funding_data.get(coin, []) for coin in coins} if funding_data else None,
                ).run({coin: data_map[coin] for coin in coins}, max_bars=window)
                rows.append(
                    ExperimentResult(
                        experiment_name=spec.name,
                        manifest_fingerprint=spec.fingerprint,
                        dataset_id=spec.dataset.id,
                        strategy_name=spec.strategy.name,
                        window=window,
                        universe=coins,
                        trades=metrics.changed_legs,
                        net_pnl_pct=metrics.net_pnl_pct,
                        max_drawdown_pct=metrics.max_drawdown_pct,
                        turnover=metrics.turnover,
                        coin_contributions=metrics.coin_contributions,
                        gross_pnl_pct=metrics.gross_pnl_pct,
                        total_cost_pct=metrics.gross_pnl_pct - metrics.net_pnl_pct,
                        fee_bps=spec.costs.fee_bps,
                        slippage_bps=spec.costs.slippage_bps,
                        dataset_fingerprint=dataset_fingerprint,
                        data_source=spec.dataset.id,
                        version=2,
                    )
                )
        return rows

    def _run_cross_sectional(self, spec, data_map):
        rows = []
        universes = spec.evaluation.universes or (spec.coins,)
        dataset_fingerprint = self._file_fingerprint(spec.dataset.path)
        for window in spec.evaluation.windows:
            for universe in universes:
                coins = tuple(coin for coin in universe if coin in spec.coins)
                result = CrossSectionalStrengthBacktester(
                    initial_capital=spec.portfolio.initial_capital,
                    fee_bps=spec.costs.fee_bps,
                    slippage_bps=spec.costs.slippage_bps,
                    parameters=spec.strategy.parameters,
                ).run(data_map, coins=coins, max_days=window)
                rows.append(
                    ExperimentResult(
                        experiment_name=spec.name,
                        manifest_fingerprint=spec.fingerprint,
                        dataset_id=spec.dataset.id,
                        strategy_name=spec.strategy.name,
                        window=window,
                        universe=coins,
                        trades=result.trades,
                        net_pnl_pct=result.net_pnl_pct,
                        max_drawdown_pct=result.max_drawdown_pct,
                        turnover=result.turnover,
                        coin_contributions=result.coin_contributions,
                        gross_pnl_pct=result.gross_pnl_pct,
                        total_cost_pct=result.gross_pnl_pct - result.net_pnl_pct,
                        fee_bps=spec.costs.fee_bps,
                        slippage_bps=spec.costs.slippage_bps,
                        dataset_fingerprint=dataset_fingerprint,
                        data_source=spec.dataset.id,
                        version=2,
                    )
                )
        return rows

    @staticmethod
    def _load_exit_replay_data(path, metadata_path="", *, required_coins=()):
        if not path:
            return {}
        with open(path, "r", encoding="utf-8") as handle:
            raw_data = json.load(handle)
        if metadata_path:
            with open(metadata_path, "r", encoding="utf-8") as handle:
                metadata = require_complete_fixture(json.load(handle))
            canonical = json.dumps(raw_data, sort_keys=True, separators=(",", ":"))
            checksum = sha256(canonical.encode("utf-8")).hexdigest()
            if metadata.get("checksum_sha256") != checksum:
                raise ValueError("replay fixture checksum does not match its metadata")
            missing = sorted(set(required_coins) - set(metadata.get("coverage_bars") or {}))
            if missing:
                raise ValueError(f"replay fixture is missing required coins: {', '.join(missing)}")
        elif required_coins:
            raise ValueError("mark-to-market replay requires fixture metadata")
        return normalize_hourly_data(raw_data)
