from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

from contracts.attribution import AttributionReport, AttributionSummary
from contracts.backtest import BacktestRequest, BacktestResult, PerformanceMetrics
from research_core.backtest_adapter.base import BacktestAdapter


class GMBacktestAdapter(BacktestAdapter):
    engine_name = "gm"

    def read_source(self, module_path: str) -> str:
        target = Path(module_path)
        if not target.exists():
            raise FileNotFoundError(f"Strategy module not found: {module_path}")
        return target.read_text(encoding="utf-8-sig")

    def parse_tree(self, module_path: str) -> ast.Module:
        return ast.parse(self.read_source(module_path))

    def detect_entrypoint(self, module_path: str) -> tuple[str, list[str]]:
        tree = self.parse_tree(module_path)
        function_names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        if "start_backtest" in function_names:
            return "start_backtest", function_names
        if "run_strategy" in function_names:
            return "run_strategy", function_names
        if "start_strategy" in function_names:
            return "start_strategy", function_names
        if "init" in function_names and "algo" in function_names:
            return "run", function_names
        raise AttributeError("Strategy module must expose start_backtest, run_strategy, start_strategy, or standard gm init/algo hooks")

    def extract_run_defaults(self, module_path: str) -> dict[str, Any]:
        tree = self.parse_tree(module_path)
        for node in tree.body:
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not isinstance(test, ast.Compare):
                continue
            if not isinstance(test.left, ast.Name) or test.left.id != "__name__":
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    call = stmt.value
                    if isinstance(call.func, ast.Name) and call.func.id == "run":
                        defaults = {}
                        for keyword in call.keywords:
                            if keyword.arg is None:
                                continue
                            try:
                                defaults[keyword.arg] = ast.literal_eval(keyword.value)
                            except Exception:
                                defaults[keyword.arg] = ast.unparse(keyword.value)
                        return defaults
        return {}

    def build_gm_kwargs(self, request: BacktestRequest, module_defaults: dict[str, Any]) -> dict[str, Any]:
        return {
            "strategy_id": request.strategy_id or module_defaults.get("strategy_id"),
            "backtest_start_time": request.start_time or module_defaults.get("backtest_start_time"),
            "backtest_end_time": request.end_time or module_defaults.get("backtest_end_time"),
            "backtest_initial_cash": request.initial_cash or module_defaults.get("backtest_initial_cash"),
            "backtest_commission_ratio": module_defaults.get("backtest_commission_ratio"),
            "backtest_slippage_ratio": module_defaults.get("backtest_slippage_ratio"),
            "backtest_match_mode": module_defaults.get("backtest_match_mode"),
            "backtest_adjust": module_defaults.get("backtest_adjust"),
            "mode": module_defaults.get("mode", "MODE_BACKTEST"),
            "token": module_defaults.get("token"),
            "filename": module_defaults.get("filename", Path(request.module_path).name),
        }

    def build_execution_plan(self, request: BacktestRequest) -> dict[str, Any]:
        self.validate(request)
        entrypoint, detected_functions = self.detect_entrypoint(request.module_path)
        module_defaults = self.extract_run_defaults(request.module_path)
        return {
            "engine": self.engine_name,
            "module_path": request.module_path,
            "entrypoint": entrypoint,
            "detected_functions": detected_functions,
            "module_defaults": module_defaults,
            "gm_kwargs": self.build_gm_kwargs(request, module_defaults),
            "strategy_params": request.strategy_params,
        }

    def run(self, request: BacktestRequest) -> BacktestResult:
        plan = self.build_execution_plan(request)
        metrics = PerformanceMetrics(
            total_return=0.0,
            annualized_return=0.0,
            benchmark_return=0.0,
            excess_return=0.0,
            max_drawdown=0.0,
            sharpe=0.0,
            volatility=0.0,
        )
        attribution = AttributionReport(
            summary=AttributionSummary(total_return=0.0),
            notes=["GM adapter scaffold created. Connect real GM backtest result parsing next."],
        )
        return BacktestResult(
            run_id=request.run_id,
            status="planned",
            engine=self.engine_name,
            strategy_id=request.strategy_id,
            strategy_version=request.strategy_version,
            benchmark=request.benchmark,
            metrics=metrics,
            attribution=attribution,
            diagnostics={"execution_plan": plan, "cwd": os.getcwd()},
        )

