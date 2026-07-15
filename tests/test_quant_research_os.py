import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class QuantResearchOsTest(unittest.TestCase):
    def _experiment(self, target="research"):
        from trading_strategy.experiments import ExperimentSpec

        return ExperimentSpec.from_mapping(
            {
                "version": 1,
                "name": "quant-os-test",
                "dataset": {"id": "fixture", "path": "fixture.json"},
                "coins": ["BTC"],
                "strategy": {"name": "trend", "parameters": {"min_score": 4}},
                "evaluation": {"windows": [120], "universes": [["BTC"]], "min_trades": 1, "min_eligible_comparisons": 1},
                "target_environment": target,
            }
        )

    def test_incomplete_coverage_rejects_candidate(self):
        from trading_strategy.experiments import EvaluationGate, ExperimentResult, evaluate_candidate

        row = ExperimentResult("base", "a", "fixture", "trend", 120, ("BTC",), 3, 1.0, 2.0, 1.0, {}, missing_data_coins=("BTC",))
        candidate = ExperimentResult("candidate", "b", "fixture", "trend", 120, ("BTC",), 3, 2.0, 1.0, 1.0, {}, missing_data_coins=("BTC",))
        decision = evaluate_candidate([row], [candidate], EvaluationGate(min_trades=1, min_eligible_comparisons=1))
        self.assertEqual(decision.status, "rejected")
        self.assertIn("incomplete required data coverage", decision.reasons)

    def test_run_summary_metrics_are_versioned_and_deterministic(self):
        from trading_strategy.live.engine.summary import build_history_metrics, build_run_summary, strategy_fingerprint

        summary = build_run_summary()
        metrics = build_history_metrics([{"entry": 100.0, "exit": 110.0, "size": 2.0, "exit_reason": "SL", "mfe_r": 1.0, "mae_r": -0.5}])
        self.assertEqual(summary["schema_version"], 3)
        self.assertEqual(metrics["run_turnover_notional"], 420.0)
        self.assertEqual(metrics["run_exit_reason_counts"], {"SL": 1})
        self.assertEqual(strategy_fingerprint({"name": "trend", "timeframe": "1d"}), strategy_fingerprint({"timeframe": "1d", "name": "trend"}))

    def test_paper_candidate_persists_separate_session(self):
        from datetime import datetime, timedelta, timezone

        from trading_strategy.experiments import PaperExperimentAdapter, PromotionDecision, update_paper_session_progress

        spec = self._experiment(target="paper")
        decision = PromotionDecision("approved_for_paper", 1, 1, (), candidate_fingerprint=spec.fingerprint)
        with tempfile.TemporaryDirectory() as directory:
            session = PaperExperimentAdapter().start(spec, decision, session_root=directory)
            payload = json.loads((Path(session.state_dir) / "session.json").read_text(encoding="utf-8"))
            completed = update_paper_session_progress(
                session,
                {"history": [{"pnl": 1.0}] * 10},
                now=datetime.now(timezone.utc) + timedelta(days=61),
            )
        self.assertEqual(payload["session"]["manifest_fingerprint"], spec.fingerprint)
        self.assertEqual(payload["observation_boundary"]["minimum_days"], 60)
        self.assertEqual(payload["observation_boundary"]["minimum_closed_trades"], 10)
        self.assertEqual(completed["status"], "completed")

    def test_l2_capture_is_limited_to_one_five_minute_bucket(self):
        from trading_strategy.live import l2_observations

        book = {
            "bids": [{"price": 100.0, "size": 2.0}],
            "asks": [{"price": 101.0, "size": 3.0}],
            "best_bid": {"price": 100.0, "size": 2.0},
            "best_ask": {"price": 101.0, "size": 3.0},
        }
        l2_observations._LAST_CAPTURE_BUCKET.clear()
        with tempfile.TemporaryDirectory() as directory, patch.object(l2_observations.config, "PROJECT_ROOT", directory):
            first = l2_observations.record_l2_observation("BTC", book_summary=book)
            second = l2_observations.record_l2_observation("BTC", book_summary=book)
            records = list((Path(directory) / "data" / "l2_observations").glob("*.jsonl"))
        self.assertEqual(first["capture_status"], "ok")
        self.assertIsNone(second)
        self.assertEqual(len(records), 1)

    def test_hyperliquid_fixture_reports_missing_coins(self):
        from trading_strategy.backtest.exit_replay import normalize_hourly_data
        from trading_strategy.backtest.hyperliquid_history import collect_fixture

        def fetch(payload):
            coin = payload["req"]["coin"]
            return [{"t": 1, "o": "1", "h": "2", "l": "1", "c": "2", "v": "3"}] if coin == "BTC" else None

        fixture = collect_fixture(("BTC", "MISSING"), days=1, now_ms=1000, fetch=fetch)
        self.assertEqual(fixture["missing_coins"], ["MISSING"])
        self.assertEqual(fixture["data"]["BTC"][0]["close"], 2.0)
        self.assertEqual(normalize_hourly_data(fixture)["BTC"][0]["close"], 2.0)

    def test_l2_jsonl_replay_adapter_uses_observation_shape(self):
        from trading_strategy.backtest.microstructure import load_l2_observation_jsonl

        record = {
            "capture_status": "ok",
            "coin": "BTC",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "signal_direction": "long",
            "bids": [{"price": 100.0, "size": 2.0}],
            "asks": [{"price": 101.0, "size": 3.0}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "l2.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            snapshots = load_l2_observation_jsonl(path)
        self.assertAlmostEqual(snapshots["BTC"][0]["spread_bps"], 99.50248756218905)

    def test_live_review_bundle_cannot_authorize_config_change(self):
        from trading_strategy.experiments import build_live_review_bundle

        spec = self._experiment()
        with tempfile.TemporaryDirectory() as directory:
            paper = Path(directory) / "session.json"
            paper.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
            bundle = build_live_review_bundle(
                manifest=spec,
                backtest_decision={"status": "approved_for_paper"},
                paper_session_path=paper,
                runtime_config_diff={"coin_universe": {"baseline": ["BTC"], "runtime": ["ETH"]}},
                protection_dry_run={"verified": True},
                l2_evidence={"replayable": True},
                output_path=Path(directory) / "bundle.json",
            )
        self.assertEqual(bundle["status"], "rejected")
        self.assertTrue(bundle["manual_only"])
        self.assertIn("runtime_config_drift", bundle["blockers"])


if __name__ == "__main__":
    unittest.main()
