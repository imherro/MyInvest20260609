from __future__ import annotations

from invest_system.web.data_gap_display import describe_data_gap, unique_data_gap_descriptions


def test_fred_data_gap_is_explained_without_secret_values() -> None:
    item = describe_data_gap("fred:missing_FRED_API_KEY")

    assert item["title"] == "FRED 宏观密钥未被当前进程读取"
    assert "FRED_API_KEY" in item["next_step"]
    assert "secret" not in str(item).lower()


def test_duplicate_live_adapter_gaps_are_collapsed_for_human_pages() -> None:
    items = unique_data_gap_descriptions(
        [
            "live_data_adapter_not_connected",
            "live_data_adapter_not_connected",
            "valuation_metrics_limited:no valuation percentile data was available",
        ]
    )

    assert [item["title"] for item in items] == ["实时数据源未连接", "长期估值分位数据不足"]
