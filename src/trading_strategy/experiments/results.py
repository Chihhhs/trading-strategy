from dataclasses import asdict, dataclass, field

from .spec import EvaluationGate


@dataclass(frozen=True)
class ExperimentResult:
    experiment_name: str
    manifest_fingerprint: str
    dataset_id: str
    strategy_name: str
    window: int
    universe: tuple[str, ...]
    trades: int
    net_pnl_pct: float
    max_drawdown_pct: float
    turnover: float
    coin_contributions: dict[str, float]
    config_diff: dict = field(default_factory=dict)
    version: int = 1

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class PromotionDecision:
    status: str
    passed_comparisons: int
    eligible_comparisons: int
    reasons: tuple[str, ...]
    baseline_fingerprint: str = ""
    candidate_fingerprint: str = ""
    config_diff: dict = field(default_factory=dict)
    version: int = 1

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_mapping(cls, payload):
        allowed = {"status", "passed_comparisons", "eligible_comparisons", "reasons", "baseline_fingerprint", "candidate_fingerprint", "config_diff", "version"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unknown promotion decision fields: {', '.join(unknown)}")
        return cls(
            status=str(payload["status"]),
            passed_comparisons=int(payload.get("passed_comparisons", 0)),
            eligible_comparisons=int(payload.get("eligible_comparisons", 0)),
            reasons=tuple(payload.get("reasons", ())),
            baseline_fingerprint=str(payload.get("baseline_fingerprint", "")),
            candidate_fingerprint=str(payload.get("candidate_fingerprint", "")),
            config_diff=dict(payload.get("config_diff", {})),
            version=int(payload.get("version", 1)),
        )


def _flatten(prefix, value, output):
    if isinstance(value, dict):
        for key in sorted(value):
            next_prefix = f"{prefix}.{key}" if prefix else key
            _flatten(next_prefix, value[key], output)
        return
    output[prefix] = value


def build_config_diff(baseline_spec, candidate_spec):
    ignored = {"name", "evaluation", "target_environment"}
    baseline = {key: value for key, value in baseline_spec.to_dict().items() if key not in ignored}
    candidate = {key: value for key, value in candidate_spec.to_dict().items() if key not in ignored}
    baseline_flat = {}
    candidate_flat = {}
    _flatten("", baseline, baseline_flat)
    _flatten("", candidate, candidate_flat)
    return {
        key: {"baseline": baseline_flat.get(key), "candidate": candidate_flat.get(key)}
        for key in sorted(set(baseline_flat) | set(candidate_flat))
        if baseline_flat.get(key) != candidate_flat.get(key)
    }


def evaluate_candidate(baseline_results, candidate_results, gate: EvaluationGate):
    baseline_by_key = {(row.window, row.universe): row for row in baseline_results}
    eligible = []
    for candidate in candidate_results:
        baseline = baseline_by_key.get((candidate.window, candidate.universe))
        if baseline is None:
            continue
        if baseline.trades < gate.min_trades or candidate.trades < gate.min_trades:
            continue
        eligible.append(
            candidate.net_pnl_pct >= baseline.net_pnl_pct
            and candidate.max_drawdown_pct <= baseline.max_drawdown_pct
        )
    passed = sum(1 for value in eligible if value)
    required = (len(eligible) // 2 + 1) if gate.require_majority else len(eligible)
    approved = len(eligible) >= gate.min_eligible_comparisons and passed >= required
    reasons = (
        ()
        if approved
        else ("insufficient eligible comparisons",)
        if len(eligible) < gate.min_eligible_comparisons
        else ("candidate failed promotion gate",)
    )
    return PromotionDecision(
        status="approved_for_paper" if approved else "rejected",
        passed_comparisons=passed,
        eligible_comparisons=len(eligible),
        reasons=reasons,
        baseline_fingerprint=(baseline_results[0].manifest_fingerprint if baseline_results else ""),
        candidate_fingerprint=(candidate_results[0].manifest_fingerprint if candidate_results else ""),
    )
