from __future__ import annotations

from typing import Any


def build_daily_workflow_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from invest_system.workflow.daily import build_daily_workflow_state as _build_daily_workflow_state

    return _build_daily_workflow_state(*args, **kwargs)


def run_daily_auto_research(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from invest_system.workflow.auto_research import run_daily_auto_research as _run_daily_auto_research

    return _run_daily_auto_research(*args, **kwargs)


def describe_theme_research_impact(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from invest_system.research.theme_impact import describe_theme_research_impact as _describe_theme_research_impact

    return _describe_theme_research_impact(*args, **kwargs)


__all__ = ["build_daily_workflow_state", "describe_theme_research_impact", "run_daily_auto_research"]
