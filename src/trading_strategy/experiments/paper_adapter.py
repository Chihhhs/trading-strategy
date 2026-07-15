from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json

from trading_strategy.strategies import get_strategy_definition


@dataclass(frozen=True)
class PaperSession:
    experiment_name: str
    manifest_fingerprint: str
    strategy_name: str
    timeframe: str
    coins: tuple[str, ...]
    strategy_parameters: dict
    initial_capital: float
    leverage: float
    risk_pct: float
    max_positions: int | None
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    state_dir: str = ""
    observation_days: int = 60
    minimum_closed_trades: int = 10
    version: int = 1

    @property
    def state_id(self):
        return f"experiment-{self.experiment_name}-{self.manifest_fingerprint[:12]}"

    def to_dict(self):
        return asdict(self)


class PaperExperimentAdapter:
    def start(self, spec, approved_result, *, session_root=None):
        if spec.target_environment != "paper":
            raise ValueError("paper adapter requires target_environment=paper")
        if approved_result.status != "approved_for_paper":
            raise ValueError("paper adapter requires an approved_for_paper decision")
        if approved_result.candidate_fingerprint != spec.fingerprint:
            raise ValueError("paper approval fingerprint does not match experiment manifest")
        definition = get_strategy_definition(spec.strategy.name)
        parameters = asdict(spec.strategy.parameters)
        root = Path(session_root) if session_root else None
        state_dir = root / f"experiment-{spec.name}-{spec.fingerprint[:12]}" if root else None
        session = PaperSession(
            experiment_name=spec.name,
            manifest_fingerprint=spec.fingerprint,
            strategy_name=definition.name,
            timeframe=parameters.get("timeframe", definition.default_timeframe),
            coins=spec.coins,
            strategy_parameters=parameters,
            initial_capital=spec.portfolio.initial_capital,
            leverage=spec.portfolio.leverage,
            risk_pct=spec.portfolio.risk_pct,
            max_positions=spec.portfolio.max_positions,
            fee_bps=spec.costs.fee_bps,
            slippage_bps=spec.costs.slippage_bps,
            state_dir=str(state_dir) if state_dir else "",
        )
        if state_dir is None:
            return session
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "status": "observing",
                    "session": session.to_dict(),
                    "approval": approved_result.to_dict(),
                    "observation_boundary": {"minimum_days": 60, "minimum_closed_trades": 10},
                },
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        return session


def update_paper_session_progress(session, state, *, now=None):
    """Update the isolated candidate session artifact; never touches live state."""
    if not session.state_dir:
        return None
    target = Path(session.state_dir) / "session.json"
    if not target.is_file():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    current = now or datetime.now(timezone.utc)
    started = datetime.fromisoformat(payload["started_at"])
    closed_trades = len(state.get("history") or [])
    boundary = payload.get("observation_boundary") or {}
    elapsed_days = max((current - started).total_seconds() / 86400.0, 0.0)
    complete = (
        elapsed_days >= int(boundary.get("minimum_days", session.observation_days))
        and closed_trades >= int(boundary.get("minimum_closed_trades", session.minimum_closed_trades))
    )
    payload["status"] = "completed" if complete else "observing"
    payload["progress"] = {
        "updated_at": current.isoformat(),
        "elapsed_days": round(elapsed_days, 4),
        "closed_trades": closed_trades,
        "remaining_days": max(int(boundary.get("minimum_days", session.observation_days)) - int(elapsed_days), 0),
        "remaining_closed_trades": max(int(boundary.get("minimum_closed_trades", session.minimum_closed_trades)) - closed_trades, 0),
    }
    target.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    return payload
