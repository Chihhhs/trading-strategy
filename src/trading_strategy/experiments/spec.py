from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import math
import re

from trading_strategy.strategies import get_strategy_definition


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_finite_number(value, name):
    if not _is_number(value) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite numbers")


def _require_positive_int(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be positive integers")


def _checked_mapping(payload, *, name, allowed, required=()):
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be an object")
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise ValueError(f"unknown {name} fields: {', '.join(unknown)}")
    missing = sorted(set(required) - set(payload))
    if missing:
        raise ValueError(f"missing {name} fields: {', '.join(missing)}")
    return payload


@dataclass(frozen=True)
class DatasetSpec:
    id: str
    path: str
    derivatives_path: str = ""


@dataclass(frozen=True)
class ExecutionSpec:
    exit_replay_path: str = ""
    replay_metadata_path: str = ""
    exit_replay_mode: str = "strict"
    drawdown_source: str = "closed_balance"


@dataclass(frozen=True)
class PortfolioSpec:
    initial_capital: float = 1000.0
    leverage: float = 3.0
    risk_pct: float = 0.05
    max_positions: int | None = None


@dataclass(frozen=True)
class CostSpec:
    fee_bps: float = 4.5
    slippage_bps: float = 2.0


@dataclass(frozen=True)
class StrategySpec:
    name: str
    parameters: Any
    required_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationGate:
    baseline: str | None = None
    windows: tuple[int, ...] = (120, 180, 240)
    universes: tuple[tuple[str, ...], ...] = ()
    min_trades: int = 5
    min_eligible_comparisons: int = 3
    require_majority: bool = True
    require_complete_data: bool = True


@dataclass(frozen=True)
class ExperimentSpec:
    version: int
    name: str
    dataset: DatasetSpec
    coins: tuple[str, ...]
    strategy: StrategySpec
    portfolio: PortfolioSpec
    costs: CostSpec
    evaluation: EvaluationGate
    execution: ExecutionSpec = ExecutionSpec()
    target_environment: str = "research"

    @classmethod
    def from_mapping(cls, payload):
        payload = _checked_mapping(
            payload,
            name="experiment",
            allowed={"version", "name", "dataset", "coins", "strategy", "portfolio", "costs", "evaluation", "execution", "target_environment"},
            required={"version", "name", "dataset", "coins", "strategy"},
        )
        if payload["version"] != 1:
            raise ValueError("unsupported experiment version")
        if not isinstance(payload["name"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", payload["name"]):
            raise ValueError("experiment name must be a safe identifier")
        dataset = _checked_mapping(payload["dataset"], name="dataset", allowed={"id", "path", "derivatives_path"}, required={"id", "path"})
        strategy = _checked_mapping(payload["strategy"], name="strategy", allowed={"name", "parameters", "required_capabilities"}, required={"name"})
        portfolio = _checked_mapping(payload.get("portfolio", {}), name="portfolio", allowed={"initial_capital", "leverage", "risk_pct", "max_positions"})
        costs = _checked_mapping(payload.get("costs", {}), name="costs", allowed={"fee_bps", "slippage_bps"})
        evaluation = _checked_mapping(payload.get("evaluation", {}), name="evaluation", allowed={"baseline", "windows", "universes", "min_trades", "min_eligible_comparisons", "require_majority", "require_complete_data"})
        execution = _checked_mapping(
            payload.get("execution", {}),
            name="execution",
            allowed={"exit_replay_path", "replay_metadata_path", "exit_replay_mode", "drawdown_source"},
        )
        if not all(isinstance(dataset.get(key, ""), str) for key in ("id", "path", "derivatives_path")):
            raise ValueError("dataset fields must be strings")
        if not dataset["id"] or not dataset["path"]:
            raise ValueError("dataset id and path must not be empty")
        if not isinstance(strategy.get("parameters", {}), dict):
            raise ValueError("strategy parameters must be an object")
        if not isinstance(strategy.get("required_capabilities", []), list) or not all(
            isinstance(value, str) for value in strategy.get("required_capabilities", [])
        ):
            raise ValueError("required_capabilities must be an array of strings")
        definition = get_strategy_definition(strategy["name"])
        parameters = definition.parse_parameters(strategy.get("parameters", {}))
        required_capabilities = tuple(sorted(set(strategy.get("required_capabilities", ()))))
        unsupported = sorted(set(required_capabilities) - set(definition.capabilities))
        if unsupported:
            raise ValueError(f"unsupported {definition.name} capabilities: {', '.join(unsupported)}")
        if not isinstance(payload["coins"], list) or not all(isinstance(coin, str) for coin in payload["coins"]):
            raise ValueError("coins must be an array of strings")
        coins = tuple(coin.strip().upper() for coin in payload["coins"] if coin.strip())
        if not coins:
            raise ValueError("experiment coins must not be empty")
        target = str(payload.get("target_environment", "research"))
        if target not in ("research", "paper"):
            raise ValueError("target_environment must be research or paper")
        for key in ("initial_capital", "leverage", "risk_pct"):
            _require_finite_number(portfolio.get(key, getattr(PortfolioSpec(), key)), f"portfolio.{key}")
        if portfolio.get("max_positions") is not None:
            _require_positive_int(portfolio["max_positions"], "portfolio.max_positions")
        for key in ("fee_bps", "slippage_bps"):
            _require_finite_number(costs.get(key, getattr(CostSpec(), key)), f"costs.{key}")
        portfolio_spec = PortfolioSpec(**portfolio)
        cost_spec = CostSpec(**costs)
        if portfolio_spec.initial_capital <= 0 or portfolio_spec.leverage <= 0:
            raise ValueError("portfolio capital and leverage must be positive")
        if not 0 < portfolio_spec.risk_pct <= 1:
            raise ValueError("portfolio risk_pct must be between 0 and 1")
        if portfolio_spec.max_positions is not None and portfolio_spec.max_positions <= 0:
            raise ValueError("portfolio max_positions must be positive")
        if not math.isfinite(float(cost_spec.fee_bps)) or not math.isfinite(float(cost_spec.slippage_bps)):
            raise ValueError("costs must be finite")
        if cost_spec.fee_bps < 0 or cost_spec.slippage_bps < 0:
            raise ValueError("costs must not be negative")
        if not isinstance(execution.get("exit_replay_path", ""), str):
            raise ValueError("execution.exit_replay_path must be a string")
        if not isinstance(execution.get("replay_metadata_path", ""), str):
            raise ValueError("execution.replay_metadata_path must be a string")
        if execution.get("exit_replay_mode", "strict") not in ("strict", "close_confirmed"):
            raise ValueError("execution.exit_replay_mode must be strict or close_confirmed")
        if execution.get("drawdown_source", "closed_balance") not in ("closed_balance", "mark_to_market"):
            raise ValueError("execution.drawdown_source must be closed_balance or mark_to_market")
        if execution.get("drawdown_source") == "mark_to_market" and not execution.get("exit_replay_path"):
            raise ValueError("execution.mark_to_market requires execution.exit_replay_path")
        if execution.get("drawdown_source") == "mark_to_market" and not execution.get("replay_metadata_path"):
            raise ValueError("execution.mark_to_market requires execution.replay_metadata_path")
        windows = evaluation.get("windows", [120, 180, 240])
        universes = evaluation.get("universes", [])
        if not isinstance(windows, list) or not windows or not all(
            isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in windows
        ):
            raise ValueError("evaluation windows must contain positive integers")
        if not isinstance(universes, list) or not all(
            isinstance(universe, list) and universe and all(isinstance(coin, str) for coin in universe)
            for universe in universes
        ):
            raise ValueError("evaluation universes must be arrays of coin strings")
        if "require_majority" in evaluation and not isinstance(evaluation["require_majority"], bool):
            raise ValueError("evaluation require_majority must be a boolean")
        if "require_complete_data" in evaluation and not isinstance(evaluation["require_complete_data"], bool):
            raise ValueError("evaluation require_complete_data must be a boolean")
        _require_positive_int(evaluation.get("min_trades", 5), "evaluation.min_trades")
        _require_positive_int(
            evaluation.get("min_eligible_comparisons", 3),
            "evaluation.min_eligible_comparisons",
        )
        if evaluation.get("baseline") is not None and not isinstance(evaluation["baseline"], str):
            raise ValueError("evaluation baseline must be a string or null")
        gate = EvaluationGate(
            baseline=evaluation.get("baseline"),
            windows=tuple(windows),
            universes=tuple(tuple(coin.upper() for coin in universe) for universe in universes),
            min_trades=evaluation.get("min_trades", 5),
            min_eligible_comparisons=evaluation.get("min_eligible_comparisons", 3),
            require_majority=evaluation.get("require_majority", True),
            require_complete_data=evaluation.get("require_complete_data", True),
        )
        if gate.min_trades <= 0 or gate.min_eligible_comparisons <= 0 or not gate.windows:
            raise ValueError("evaluation gate requires positive min_trades and windows")
        return cls(
            version=1,
            name=str(payload["name"]),
            dataset=DatasetSpec(**dataset),
            coins=coins,
            strategy=StrategySpec(
                name=definition.name,
                parameters=parameters,
                required_capabilities=required_capabilities,
            ),
            portfolio=portfolio_spec,
            costs=cost_spec,
            evaluation=gate,
            execution=ExecutionSpec(**execution),
            target_environment=target,
        )

    def to_dict(self):
        return asdict(self)

    @property
    def fingerprint(self):
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode("utf-8")).hexdigest()


def load_experiment(path):
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return ExperimentSpec.from_mapping(payload)
