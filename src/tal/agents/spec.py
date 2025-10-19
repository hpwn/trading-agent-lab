from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Dict, List, Optional


class BuilderInfo(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    prompt_hash: Optional[str] = None
    run_id: Optional[str] = None


class LineageInfo(BaseModel):
    parent_id: Optional[str] = None
    version: Optional[int] = None
    mutation: Optional[str] = None
    notes: Optional[str] = None


class AgentMetadata(BaseModel):
    builder: Optional[BuilderInfo] = None
    lineage: Optional[LineageInfo] = None


class Components(BaseModel):
    strategy: str = Field(
        ...,
        description=(
            "Dotted path or short name, e.g. "
            "tal.strategies.rsi_mean_rev.RSIMeanReversion or rsi_mean_rev"
        ),
    )
    risk: Optional[str] = None
    tuner: Optional[str] = None


class DataCfg(BaseModel):
    timeframe: str = "1d"
    lookback_bars: int = 1000


class RiskCfg(BaseModel):
    max_drawdown_pct: float = 20.0
    max_position_pct: float = 50.0


class EvalCfg(BaseModel):
    kpis: List[str] = ["pnl", "profit_factor", "sharpe", "max_dd", "win_rate"]


class MarketHours(BaseModel):
    timezone: str = "America/New_York"
    open: str = "09:30"
    close: str = "16:00"


class OrchestratorCfg(BaseModel):
    cycle_minutes: int = 5
    market_hours: MarketHours = MarketHours()


class StorageCfg(BaseModel):
    db_url: str = "sqlite:///./lab.db"
    artifacts_dir: str = "./artifacts"


class LiveCfg(BaseModel):
    model_config = ConfigDict(extra="allow")

    adapter: str = "sim"
    broker: Optional[str] = None
    cash: float = 10_000
    commission: float = 0.0
    slippage_bps: float = 1.0
    ledger_dir: str = "./artifacts/live"
    bars: int = 200
    max_position_pct: float = 50.0
    max_order_usd: Optional[float] = None
    max_daily_loss_pct: Optional[float] = None
    paper: bool = True
    base_url: Optional[str] = None
    symbol: Optional[str] = None
    size_pct: Optional[float] = None
    allow_after_hours: bool = False

    @model_validator(mode="before")
    @classmethod
    def _alias_adapter(cls, values: Dict) -> Dict:
        if isinstance(values, dict) and "adapter" not in values and "broker" in values:
            values = {**values, "adapter": values["broker"]}
        return values


class AgentSpec(BaseModel):
    id: str
    version: int = 0
    capital: float = 100.0
    universe: List[str] = ["SPY"]
    components: Components
    data: DataCfg = DataCfg()
    strategy: Dict = {
        "params": {
            "rsi_len": 14,
            "oversold": 30,
            "overbought": 70,
            "size_pct": 10,
        }
    }
    risk: RiskCfg = RiskCfg()
    evaluation: EvalCfg = EvalCfg()
    orchestrator: OrchestratorCfg = OrchestratorCfg()
    storage: StorageCfg = StorageCfg()
    live: LiveCfg = LiveCfg()
    metadata: Optional[AgentMetadata] = None
