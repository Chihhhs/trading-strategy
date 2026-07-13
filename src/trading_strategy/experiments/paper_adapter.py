from dataclasses import asdict, dataclass

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
    version: int = 1

    @property
    def state_id(self):
        return f"experiment-{self.experiment_name}-{self.manifest_fingerprint[:12]}"

    def to_dict(self):
        return asdict(self)


class PaperExperimentAdapter:
    def start(self, spec, approved_result):
        if spec.target_environment != "paper":
            raise ValueError("paper adapter requires target_environment=paper")
        if approved_result.status != "approved_for_paper":
            raise ValueError("paper adapter requires an approved_for_paper decision")
        if approved_result.candidate_fingerprint != spec.fingerprint:
            raise ValueError("paper approval fingerprint does not match experiment manifest")
        definition = get_strategy_definition(spec.strategy.name)
        parameters = asdict(spec.strategy.parameters)
        return PaperSession(
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
        )
