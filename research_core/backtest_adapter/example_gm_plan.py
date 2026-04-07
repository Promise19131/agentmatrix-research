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

SAMPLE_MODULES = {
    'gm_small_cap_monthly': REPO_ROOT / 'research_core' / 'strategy_engine' / 'samples' / 'gm_small_cap_monthly.py',
    'gm_style_rotation': REPO_ROOT / 'research_core' / 'strategy_engine' / 'samples' / 'gm_style_rotation.py',
}

SAMPLE_REQUESTS = {
    'gm_small_cap_monthly': {
        'start_time': '2025-01-01 08:00:00',
        'end_time': '2026-03-18 16:00:00',
        'benchmark': 'SHSE.000300',
        'initial_cash': 1000000,
        'strategy_params': {'sample_name': 'gm_small_cap_monthly', 'holdings': 10, 'rebalance': 'monthly'},
    },
    'gm_style_rotation': {
        'start_time': '2025-01-01 08:00:00',
        'end_time': '2025-12-31 16:00:00',
        'benchmark': 'SHSE.000300',
        'initial_cash': 10000000,
        'strategy_params': {'sample_name': 'gm_style_rotation', 'rotation_window': 20, 'holdings': 10},
    },
}


def resolve_module_path(sample_name: str | None = None, module_path: str | None = None) -> Path:
    if module_path:
        return Path(module_path).resolve()
    if sample_name and sample_name in SAMPLE_MODULES:
        return SAMPLE_MODULES[sample_name].resolve()
    return SAMPLE_MODULES['gm_small_cap_monthly'].resolve()


def build_example_plan(sample_name: str | None = None, module_path: str | None = None) -> dict:
    resolved_sample = sample_name or 'gm_small_cap_monthly'
    target_module = resolve_module_path(sample_name=resolved_sample, module_path=module_path)
    request_defaults = SAMPLE_REQUESTS.get(resolved_sample, SAMPLE_REQUESTS['gm_small_cap_monthly'])
    strategy_name = target_module.stem.replace('_', '-')
    request = BacktestRequest(
        run_id=f"run_{uuid.uuid4().hex[:12]}",
        strategy_id=strategy_name,
        strategy_version='v1',
        strategy_params=request_defaults['strategy_params'],
        module_path=str(target_module),
        start_time=request_defaults['start_time'],
        end_time=request_defaults['end_time'],
        benchmark=request_defaults['benchmark'],
        initial_cash=request_defaults['initial_cash'],
        execution_engine='gm',
    )
    adapter = GMBacktestAdapter()
    result = adapter.run(request)
    return result.diagnostics


if __name__ == '__main__':
    sample_name = sys.argv[1] if len(sys.argv) > 1 else None
    payload = build_example_plan(sample_name=sample_name)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
