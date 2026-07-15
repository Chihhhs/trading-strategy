"""Manual-only live review bundle creation; this module never changes runtime config."""

from datetime import datetime, timezone
from pathlib import Path
import json


def build_live_review_bundle(*, manifest, backtest_decision, paper_session_path, runtime_config_diff, protection_dry_run, l2_evidence, output_path):
    paper_path = Path(paper_session_path)
    paper = json.loads(paper_path.read_text(encoding="utf-8")) if paper_path.is_file() else {}
    blockers = []
    if backtest_decision.get("status") != "approved_for_paper":
        blockers.append("backtest_not_approved_for_paper")
    if runtime_config_diff:
        blockers.append("runtime_config_drift")
    if not protection_dry_run.get("verified", False):
        blockers.append("protection_dry_run_failed")
    if not l2_evidence.get("replayable", False):
        blockers.append("l2_evidence_not_replayable")
    if paper.get("status") not in ("completed", "observing"):
        blockers.append("paper_session_missing_or_invalid")
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_for_manual_live_review" if not blockers else "rejected",
        "blockers": blockers,
        "manifest": {"name": manifest.name, "fingerprint": manifest.fingerprint},
        "backtest_decision": backtest_decision,
        "paper_session": paper,
        "runtime_config_diff": runtime_config_diff,
        "protection_dry_run": protection_dry_run,
        "l2_evidence": l2_evidence,
        "manual_only": True,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    return payload
