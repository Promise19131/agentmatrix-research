from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.backtest import BacktestRequest
from research_core.backtest_adapter.gm_adapter import GMBacktestAdapter


def build_example_plan(module_path: str | None = None) -> dict:
    target_module = Path(module_path) if module_path else REPO_ROOT / "research_core" / "strategy_engine" / "samples" / "gm_small_cap_monthly.py"
    request = BacktestRequest(
        run_id=f"run_{uuid.uuid4().hex[:12]}",
        strategy_id="gm-small-cap-monthly",
        strategy_version="v1",
        strategy_params={"holdings": 10, "rebalance": "monthly"},
        module_path=str(target_module.resolve()),
        start_time="2025-01-01 08:00:00",
        end_time="2026-03-18 16:00:00",
        benchmark="SHSE.000300",
        initial_cash=1000000,
        execution_engine="gm",
    )
    adapter = GMBacktestAdapter()
    result = adapter.run(request)
    return result.diagnostics


if __name__ == "__main__":
    payload = build_example_plan()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
