from __future__ import annotations

import pytest

from invest_system.validators.module_contracts import ThemeValidationError
from scripts.generate_mainline_theme_research import _snapshot_from_evidence


def test_mainline_theme_builder_rejects_stock_code_before_publish() -> None:
    with pytest.raises(ThemeValidationError):
        _snapshot_from_evidence(
            basis_date="2026-06-15",
            next_review_date="2026-06-16",
            data_gaps=[],
            clusters=[
                {
                    "theme_id": "advanced_electronics_manufacturing_chain",
                    "name": "advanced electronics manufacturing chain",
                    "sector": "advanced electronics manufacturing",
                    "theme_state": "strengthening",
                    "signal_type": ["momentum", "structural"],
                    "leading_indicators": ["先进封装", "301566.SZ"],
                    "strength_score": 72,
                    "forming_reason": "fixture theme evidence",
                    "metrics": {
                        "current_pct_avg": 1,
                        "lookback_cumulative_pct_avg": 2,
                        "positive_observation_ratio": 0.6,
                        "evidence_coverage_ratio": 1,
                        "theme_breadth_ratio": 1,
                    },
                    "risks": ["fixture risk"],
                }
            ],
            source_market_snapshot_id=None,
        )
