import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class ExperimentSpecTest(unittest.TestCase):
    def test_live_trend_baseline_matches_50_coin_runtime_contract(self):
        from trading_strategy.experiments import load_experiment

        spec = load_experiment(Path(ROOT) / "experiments" / "live_trend_baseline.json")
        self.assertEqual(spec.strategy.name, "trend")
        self.assertEqual(len(spec.coins), 50)
        self.assertEqual(spec.evaluation.universes, (spec.coins,))
        self.assertEqual(spec.portfolio.leverage, 5.0)
        self.assertEqual(spec.portfolio.risk_pct, 0.08)
        self.assertEqual(spec.portfolio.max_positions, 2)
        self.assertEqual(spec.strategy.parameters.min_score, 3)
        self.assertTrue(spec.strategy.parameters.derivatives_crowding_exit_enabled)
        self.assertEqual(spec.strategy.parameters.derivatives_crowding_action, "reduce")
        self.assertEqual(spec.strategy.parameters.derivatives_crowding_reduce_fraction, 0.75)

    def _payload(self):
        return {
            "version": 1,
            "name": "trend-baseline",
            "dataset": {
                "id": "binance-daily-240d",
                "path": "data/historical_prices/binance_240d.json",
            },
            "coins": ["BTC", "ETH"],
            "strategy": {
                "name": "trend",
                "parameters": {"min_score": 4, "atr_trailing_enabled": False},
            },
            "portfolio": {
                "initial_capital": 1000.0,
                "leverage": 3.0,
                "risk_pct": 0.05,
                "max_positions": 2,
            },
            "costs": {"fee_bps": 4.5, "slippage_bps": 2.0},
            "evaluation": {
                "baseline": None,
                "windows": [120, 180, 240],
                "universes": [["BTC"], ["BTC", "ETH"]],
                "min_trades": 5,
                "min_eligible_comparisons": 3,
                "require_majority": True,
            },
            "target_environment": "research",
        }

    def test_registry_exposes_typed_strategy_definition(self):
        from trading_strategy.strategies import get_strategy_definition

        definition = get_strategy_definition("trend")
        self.assertEqual(definition.name, "trend")
        self.assertEqual(definition.default_timeframe, "1d")
        self.assertGreaterEqual(definition.min_bars, 50)
        self.assertIn("position_adjustment", definition.capabilities)
        parameters = definition.parse_parameters({"min_score": 5})
        self.assertEqual(parameters.min_score, 5)
        self.assertEqual(parameters.timeframe, "1d")

    def test_intraday_definition_limits_strategy_context_for_fast_iteration(self):
        from trading_strategy.strategies import get_strategy_definition

        definition = get_strategy_definition("intraday_momentum")
        self.assertEqual(definition.context_bars, 90)

    def test_trend_pullback_paper_parameters_disable_time_fallback(self):
        from trading_strategy.experiments.paper_adapter import PaperSession
        from trading_strategy.paper import _experiment_params

        session = PaperSession(
            "pullback",
            "fingerprint",
            "trend_pullback_reclaim",
            "4h",
            ("BNB",),
            {"max_hold_days": None},
            25.0,
            1.0,
            0.02,
            1,
        )
        self.assertIsNone(_experiment_params(session)["max_hold_days"])

    def test_intraday_exit_preserves_global_bars_since_entry_with_rolling_context(self):
        from trading_strategy.strategies import StrategyContext, get_strategy

        position = {"entry_klines_len": 90, "bars_since_entry": 24}
        window = [{"close": 100.0, "high": 101.0, "low": 99.0} for _ in range(90)]
        result = get_strategy("intraday_momentum").evaluate_open_position(
            position,
            StrategyContext(
                coin="BTC",
                window=window,
                config={"intraday_max_hold_bars": 24},
                mode="backtest",
            ),
        )

        self.assertEqual(result["exit_reason"], "TIME")
        self.assertEqual(position["bars_since_entry"], 24)

    def test_manifest_round_trip_has_stable_fingerprint(self):
        from trading_strategy.experiments import ExperimentSpec

        first = ExperimentSpec.from_mapping(self._payload())
        reordered = dict(reversed(list(self._payload().items())))
        second = ExperimentSpec.from_mapping(reordered)

        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.to_dict()["strategy"]["parameters"]["min_score"], 4)
        self.assertEqual(first.coins, ("BTC", "ETH"))

    def test_manifest_rejects_unknown_top_level_field(self):
        from trading_strategy.experiments import ExperimentSpec

        payload = self._payload()
        payload["surprise"] = True
        with self.assertRaisesRegex(ValueError, "unknown experiment fields: surprise"):
            ExperimentSpec.from_mapping(payload)

    def test_manifest_rejects_unknown_strategy_parameter(self):
        from trading_strategy.experiments import ExperimentSpec

        payload = self._payload()
        payload["strategy"]["parameters"]["magic_threshold"] = 3
        with self.assertRaisesRegex(ValueError, "unknown trend parameters: magic_threshold"):
            ExperimentSpec.from_mapping(payload)

    def test_manifest_rejects_unsupported_strategy_capability(self):
        from trading_strategy.experiments import ExperimentSpec

        payload = self._payload()
        payload["strategy"]["required_capabilities"] = ["intrabar_exit"]
        with self.assertRaisesRegex(ValueError, "unsupported trend capabilities: intrabar_exit"):
            ExperimentSpec.from_mapping(payload)

    def test_manifest_rejects_invalid_cost_and_risk_values(self):
        from trading_strategy.experiments import ExperimentSpec

        payload = self._payload()
        payload["costs"]["fee_bps"] = -1
        with self.assertRaisesRegex(ValueError, "costs must not be negative"):
            ExperimentSpec.from_mapping(payload)

    def test_manifest_rejects_wrong_container_and_boolean_types(self):
        from trading_strategy.experiments import ExperimentSpec

        payload = self._payload()
        payload["coins"] = "BTC"
        with self.assertRaisesRegex(ValueError, "coins must be an array"):
            ExperimentSpec.from_mapping(payload)

        payload = self._payload()
        payload["evaluation"]["require_majority"] = "false"
        with self.assertRaisesRegex(ValueError, "require_majority must be a boolean"):
            ExperimentSpec.from_mapping(payload)

    def test_manifest_rejects_non_finite_costs_and_non_positive_windows(self):
        from trading_strategy.experiments import ExperimentSpec

        payload = self._payload()
        payload["costs"]["fee_bps"] = float("nan")
        with self.assertRaisesRegex(ValueError, "costs.*must be finite"):
            ExperimentSpec.from_mapping(payload)

        payload = self._payload()
        payload["evaluation"]["windows"] = [-1]
        with self.assertRaisesRegex(ValueError, "windows must contain positive integers"):
            ExperimentSpec.from_mapping(payload)

    def test_load_experiment_reads_json(self):
        from trading_strategy.experiments import load_experiment

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "experiment.json"
            path.write_text(json.dumps(self._payload()), encoding="utf-8")
            spec = load_experiment(path)

        self.assertEqual(spec.name, "trend-baseline")

    def test_backtest_adapter_maps_shared_and_strategy_settings(self):
        from trading_strategy.experiments import BacktestExperimentAdapter, ExperimentSpec

        spec = ExperimentSpec.from_mapping(self._payload())
        adapter = BacktestExperimentAdapter()
        config = adapter.build_config(spec, max_days=180)

        self.assertEqual(config.coins, ("BTC", "ETH"))
        self.assertEqual(config.max_days, 180)
        self.assertEqual(config.fee_bps, 4.5)
        self.assertEqual(config.slippage_bps, 2.0)
        self.assertEqual(config.max_positions, 2)
        from trading_strategy.strategies import get_strategy_definition

        self.assertEqual(config.min_bars, get_strategy_definition("trend").min_bars)
        self.assertEqual(config.atr_trailing_enabled, False)
        self.assertEqual(config.strategy_parameters["min_score"], 4)

    def test_execution_requires_replay_for_mark_to_market_drawdown(self):
        from trading_strategy.experiments import ExperimentSpec

        payload = self._payload()
        payload["execution"] = {"drawdown_source": "mark_to_market"}
        with self.assertRaisesRegex(ValueError, "requires execution.exit_replay_path"):
            ExperimentSpec.from_mapping(payload)

        payload["execution"] = {"exit_replay_path": "hourly.json", "drawdown_source": "mark_to_market"}
        with self.assertRaisesRegex(ValueError, "requires execution.replay_metadata_path"):
            ExperimentSpec.from_mapping(payload)

    def test_backtest_adapter_uses_mtm_drawdown_for_replay_profile(self):
        from trading_strategy.experiments import BacktestExperimentAdapter, ExperimentSpec

        payload = self._payload()
        payload["evaluation"] = {
            "windows": [120],
            "universes": [["BTC"]],
            "min_trades": 1,
            "min_eligible_comparisons": 1,
            "require_majority": False,
        }
        payload["coins"] = ["BTC"]
        with tempfile.TemporaryDirectory() as directory:
            replay_path = Path(directory) / "hourly.json"
            replay_data = {"BTC": [{"open_time": 3600000, "open": 1, "high": 1, "low": 1, "close": 1}]}
            replay_path.write_text(json.dumps(replay_data), encoding="utf-8")
            metadata_path = Path(directory) / "hourly.metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "complete": True,
                        "coverage_bars": {"BTC": 1},
                        "checksum_sha256": __import__("hashlib").sha256(
                            json.dumps(replay_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
                        ).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            payload["execution"] = {
                "exit_replay_path": str(replay_path),
                "replay_metadata_path": str(metadata_path),
                "exit_replay_mode": "strict",
                "drawdown_source": "mark_to_market",
            }
            spec = ExperimentSpec.from_mapping(payload)
            result = MagicMock()
            result.portfolio = {
                "trades": 1,
                "total_pnl_pct": 2.0,
                "max_drawdown": 9.0,
                "mark_to_market_max_drawdown": 3.0,
            }
            result.trades = []
            result.coin_results = []
            runner = MagicMock()
            runner.run.return_value = result
            with patch("trading_strategy.experiments.backtest_adapter.load_historical_data", return_value={"BTC": []}), patch(
                "trading_strategy.experiments.backtest_adapter.load_derivatives_data", return_value={}
            ), patch("trading_strategy.experiments.backtest_adapter.PortfolioBacktester", return_value=runner) as backtester:
                rows = BacktestExperimentAdapter().run(spec)

        self.assertEqual(rows[0].max_drawdown_pct, 3.0)
        self.assertIn("BTC", backtester.call_args.kwargs["exit_replay_data_map"])

    def test_backtest_adapter_rejects_mismatched_replay_metadata(self):
        from trading_strategy.experiments import BacktestExperimentAdapter

        with tempfile.TemporaryDirectory() as directory:
            replay_path = Path(directory) / "hourly.json"
            replay_path.write_text(json.dumps({"BTC": []}), encoding="utf-8")
            metadata_path = Path(directory) / "hourly.metadata.json"
            metadata_path.write_text(
                json.dumps({"complete": True, "coverage_bars": {"BTC": 1}, "checksum_sha256": "wrong"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "checksum"):
                BacktestExperimentAdapter._load_exit_replay_data(
                    str(replay_path),
                    str(metadata_path),
                    required_coins=("BTC",),
                )

    def test_experiment_result_is_serializable_and_includes_turnover(self):
        from trading_strategy.experiments import ExperimentResult

        result = ExperimentResult(
            experiment_name="candidate",
            manifest_fingerprint="abc",
            dataset_id="fixture",
            strategy_name="trend",
            window=120,
            universe=("BTC",),
            trades=5,
            net_pnl_pct=12.0,
            max_drawdown_pct=8.0,
            turnover=3.5,
            coin_contributions={"BTC": 120.0},
        )

        payload = result.to_dict()
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["turnover"], 3.5)
        json.dumps(payload)

    def test_config_diff_reports_changed_strategy_and_cost_values(self):
        from trading_strategy.experiments import ExperimentSpec, build_config_diff

        baseline = ExperimentSpec.from_mapping(self._payload())
        candidate_payload = self._payload()
        candidate_payload["strategy"]["parameters"]["min_score"] = 5
        candidate_payload["costs"]["slippage_bps"] = 3.0
        candidate = ExperimentSpec.from_mapping(candidate_payload)

        diff = build_config_diff(baseline, candidate)
        self.assertEqual(diff["strategy.parameters.min_score"], {"baseline": 4, "candidate": 5})
        self.assertEqual(diff["costs.slippage_bps"], {"baseline": 2.0, "candidate": 3.0})
        self.assertNotIn("name", diff)

    def test_entry_quality_diagnostic_never_authorizes_paper_or_live(self):
        from backtest.run_entry_quality_diagnostic import build_diagnostic
        from trading_strategy.experiments import ExperimentResult, ExperimentSpec

        baseline = ExperimentSpec.from_mapping(self._payload())
        candidate_payload = self._payload()
        candidate_payload["strategy"]["parameters"]["trend_rsi_max_long"] = 50.0
        candidate = ExperimentSpec.from_mapping(candidate_payload)
        baseline_row = ExperimentResult("baseline", "a", "fixture", "trend", 120, ("BTC",), 5, -5.0, 20.0, 1.0, {"BTC": -5.0})
        candidate_row = ExperimentResult("candidate", "b", "fixture", "trend", 120, ("BTC",), 5, -4.0, 19.0, 0.8, {"BTC": -4.0})
        report = build_diagnostic(baseline, candidate, [baseline_row], [candidate_row])
        self.assertEqual(report["status"], "research_follow_up")
        self.assertTrue(report["research_only"])
        self.assertIn("live", report["does_not_authorize"])

    def test_btc_regime_attribution_is_causal_and_marks_small_buckets(self):
        from trading_strategy.backtest.regime_attribution import btc_regime_at, portfolio_attribution, research_verdict

        bars = [{"time": index * 86_400_000, "close": 100.0 + index} for index in range(8)]
        self.assertEqual(btc_regime_at(bars, 7 * 86_400_000, threshold_pct=3.0), "bull")
        self.assertEqual(btc_regime_at(bars, 5 * 86_400_000, threshold_pct=3.0), "neutral")
        report = portfolio_attribution([
            {"coin": "BTC", "direction": "long", "entry_time": 7 * 86_400_000, "exit_time": 8 * 86_400_000, "pnl": 1.0, "gross_pnl": 1.1, "cost": 0.1, "hold_bars": 1, "exit_reason": "EOD"}
        ], bars)
        self.assertEqual(report["buckets"]["bull:long"]["trades"], 1)
        self.assertTrue(report["buckets"]["bull:long"]["insufficient_sample"])
        self.assertEqual(report["buckets"]["bull:long"]["coin_concentration"]["top_1"]["coin"], "BTC")
        self.assertEqual(report["buckets"]["bull:long"]["coin_concentration"]["leave_one_coin_out"][0]["net_pnl_without_coin"], 0.0)
        self.assertEqual(research_verdict(report), "insufficient_sample")

    def test_promotion_requires_majority_of_eligible_comparisons(self):
        from trading_strategy.experiments import EvaluationGate, ExperimentResult, evaluate_candidate

        def row(name, window, pnl, drawdown, trades=6):
            return ExperimentResult(
                experiment_name=name,
                manifest_fingerprint=name,
                dataset_id="fixture",
                strategy_name="trend",
                window=window,
                universe=("BTC",),
                trades=trades,
                net_pnl_pct=pnl,
                max_drawdown_pct=drawdown,
                turnover=2.0,
                coin_contributions={"BTC": pnl},
            )

        baselines = [row("base", 120, 10, 20), row("base", 180, 8, 18), row("base", 240, 12, 22)]
        candidates = [row("candidate", 120, 12, 19), row("candidate", 180, 9, 17), row("candidate", 240, 5, 25)]
        decision = evaluate_candidate(
            baselines,
            candidates,
            EvaluationGate(windows=(120, 180, 240), universes=(("BTC",),), min_trades=5),
        )

        self.assertEqual(decision.status, "approved_for_paper")
        self.assertEqual(decision.passed_comparisons, 2)
        self.assertEqual(decision.eligible_comparisons, 3)

    def test_promotion_rejects_insufficient_samples(self):
        from trading_strategy.experiments import EvaluationGate, ExperimentResult, evaluate_candidate

        result = ExperimentResult(
            experiment_name="candidate",
            manifest_fingerprint="abc",
            dataset_id="fixture",
            strategy_name="trend",
            window=120,
            universe=("BTC",),
            trades=2,
            net_pnl_pct=50.0,
            max_drawdown_pct=1.0,
            turnover=1.0,
            coin_contributions={"BTC": 500.0},
        )
        decision = evaluate_candidate([], [result], EvaluationGate(min_trades=5))

        self.assertEqual(decision.status, "rejected")
        self.assertIn("insufficient eligible comparisons", decision.reasons)

    def test_promotion_requires_minimum_number_of_eligible_comparisons(self):
        from trading_strategy.experiments import EvaluationGate, ExperimentResult, evaluate_candidate

        row = ExperimentResult(
            experiment_name="candidate",
            manifest_fingerprint="abc",
            dataset_id="fixture",
            strategy_name="trend",
            window=240,
            universe=("BTC",),
            trades=5,
            net_pnl_pct=10.0,
            max_drawdown_pct=5.0,
            turnover=1.0,
            coin_contributions={"BTC": 100.0},
        )
        decision = evaluate_candidate(
            [replace(row, experiment_name="baseline")],
            [row],
            EvaluationGate(min_trades=5, min_eligible_comparisons=3),
        )

        self.assertEqual(decision.status, "rejected")
        self.assertEqual(decision.eligible_comparisons, 1)
        self.assertIn("insufficient eligible comparisons", decision.reasons)

    def test_paper_adapter_rejects_unapproved_candidate(self):
        from trading_strategy.experiments import ExperimentSpec, PaperExperimentAdapter, PromotionDecision

        payload = self._payload()
        payload["target_environment"] = "paper"
        spec = ExperimentSpec.from_mapping(payload)
        decision = PromotionDecision("rejected", 0, 0, ("insufficient eligible comparisons",))

        with self.assertRaisesRegex(ValueError, "approved_for_paper"):
            PaperExperimentAdapter().start(spec, decision)

    def test_paper_adapter_uses_same_strategy_parameters(self):
        from trading_strategy.experiments import ExperimentSpec, PaperExperimentAdapter, PromotionDecision

        payload = self._payload()
        payload["target_environment"] = "paper"
        spec = ExperimentSpec.from_mapping(payload)
        decision = PromotionDecision(
            "approved_for_paper",
            2,
            3,
            (),
            candidate_fingerprint=spec.fingerprint,
        )
        session = PaperExperimentAdapter().start(spec, decision)

        self.assertEqual(session.strategy_name, "trend")
        self.assertEqual(session.timeframe, "1d")
        self.assertEqual(session.strategy_parameters["min_score"], 4)
        self.assertEqual(session.fee_bps, 4.5)
        self.assertEqual(session.slippage_bps, 2.0)
        self.assertEqual(session.manifest_fingerprint, spec.fingerprint)
        self.assertEqual(session.version, 1)
        self.assertTrue(session.state_id.startswith("experiment-trend-baseline-"))

    def test_paper_adapter_rejects_approval_for_another_manifest(self):
        from trading_strategy.experiments import ExperimentSpec, PaperExperimentAdapter, PromotionDecision

        payload = self._payload()
        payload["target_environment"] = "paper"
        spec = ExperimentSpec.from_mapping(payload)
        decision = PromotionDecision(
            "approved_for_paper",
            3,
            3,
            (),
            candidate_fingerprint="different-manifest",
        )

        with self.assertRaisesRegex(ValueError, "fingerprint"):
            PaperExperimentAdapter().start(spec, decision)

    def test_experiment_paper_runner_uses_registry_strategy_hooks(self):
        from trading_strategy.experiments import PaperSession
        from trading_strategy.paper import run_experiment_once
        from trading_strategy.strategies import StrategySignal

        session = PaperSession(
            experiment_name="paper-hook-test",
            manifest_fingerprint="abc",
            strategy_name="trend",
            timeframe="1d",
            coins=("BTC",),
            strategy_parameters={"timeframe": "1d", "min_score": 4},
            initial_capital=1000.0,
            leverage=3.0,
            risk_pct=0.05,
            max_positions=1,
        )
        state = {
            "balance": 1000.0,
            "positions": [],
            "history": [],
            "stats": {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0},
            "cooldowns": {},
        }
        strategy = MagicMock()
        strategy.generate_signal.return_value = StrategySignal("long", 120.0, 90.0, 4, "TEST")
        strategy.should_block_for_btc.return_value = False
        strategy.build_exit_policy.return_value = {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True}
        bars = [{"close": 100.0, "high": 101.0, "low": 99.0} for _ in range(70)]
        with (
            patch("trading_strategy.paper.get_strategy", return_value=strategy),
            patch("trading_strategy.paper._load_experiment_state", return_value=state),
            patch("trading_strategy.paper.get_current_prices", return_value={"BTC": 100.0}),
            patch("trading_strategy.paper.get_binance_klines", return_value=bars),
            patch("trading_strategy.paper.save_shared_state"),
        ):
            result = run_experiment_once(session)

        strategy.generate_signal.assert_called_once()
        strategy.initialize_position.assert_called_once()
        self.assertEqual(result["positions"][0]["strategy_name"], "trend")

    def test_experiment_paper_runner_applies_btc_filter_hook(self):
        from trading_strategy.experiments import PaperSession
        from trading_strategy.paper import run_experiment_once
        from trading_strategy.strategies import StrategySignal

        session = PaperSession(
            experiment_name="paper-btc-filter-test",
            manifest_fingerprint="abc",
            strategy_name="trend",
            timeframe="1d",
            coins=("ETH",),
            strategy_parameters={"timeframe": "1d", "min_score": 4},
            initial_capital=1000.0,
            leverage=3.0,
            risk_pct=0.05,
            max_positions=1,
        )
        state = {
            "balance": 1000.0,
            "positions": [],
            "history": [],
            "stats": {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0},
            "cooldowns": {},
        }
        strategy = MagicMock()
        strategy.generate_signal.return_value = StrategySignal("long", 120.0, 90.0, 4, "TEST")
        strategy.should_block_for_btc.return_value = True
        bars = [{"close": 100.0, "high": 101.0, "low": 99.0} for _ in range(70)]
        with (
            patch("trading_strategy.paper.get_strategy", return_value=strategy),
            patch("trading_strategy.paper._load_experiment_state", return_value=state),
            patch("trading_strategy.paper.get_current_prices", return_value={"ETH": 100.0}),
            patch("trading_strategy.paper.get_binance_klines", return_value=bars),
            patch("trading_strategy.paper.save_shared_state"),
        ):
            result = run_experiment_once(session)

        strategy.should_block_for_btc.assert_called_once()
        self.assertEqual(result["positions"], [])

    def test_experiment_paper_positions_apply_stop_and_reduction_hooks(self):
        from trading_strategy.paper import _update_experiment_positions

        position = {
            "coin": "BTC",
            "direction": "long",
            "entry": 100.0,
            "tp": None,
            "sl": 90.0,
            "size": 2.0,
            "entry_time": "2026-07-13T00:00:00",
        }
        state = {
            "balance": 1000.0,
            "positions": [position],
            "history": [],
            "stats": {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0},
        }
        strategy = MagicMock()
        strategy.resolve_stop_target.return_value = {"should_update": True, "sl": 105.0}
        strategy.evaluate_open_position.return_value = {
            "exit_reason": None,
            "position_adjustment": {
                "action": "reduce",
                "fraction": 0.5,
                "reason": "RISK_REDUCE",
                "reduction_key": "crowding:1",
            },
        }
        strategy.build_exit_policy.return_value = {"requires_tp": False, "requires_sl": True}

        _update_experiment_positions(
            state,
            {"BTC": 110.0},
            {"BTC": [{"close": 110.0, "high": 111.0, "low": 109.0}]},
            strategy,
            {"max_hold_days": 30, "fee_bps": 4.5, "slippage_bps": 2.0},
        )

        strategy.resolve_stop_target.assert_called_once()
        self.assertEqual(position["sl"], 105.0)
        self.assertEqual(position["size"], 1.0)
        self.assertEqual(position["derivatives_crowding_reductions"], ["crowding:1"])
        self.assertAlmostEqual(state["balance"], 1009.8635, places=4)
        self.assertEqual(state["history"][0]["exit_reason"], "RISK_REDUCE")


if __name__ == "__main__":
    unittest.main()
