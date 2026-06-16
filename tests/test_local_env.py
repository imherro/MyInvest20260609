from __future__ import annotations

import os

from invest_system.local_env import load_local_env


def test_load_local_env_sets_missing_values_without_overwrite(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# local credentials",
                "FRED_API_KEY=fred-placeholder",
                "TUSHARE_TOKEN='tushare-placeholder'",
                "EXISTING_VALUE=from_file",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setenv("EXISTING_VALUE", "from_environment")

    loaded = load_local_env(env_path)

    assert loaded == ["FRED_API_KEY", "TUSHARE_TOKEN"]
    assert os.environ["FRED_API_KEY"] == "fred-placeholder"
    assert os.environ["TUSHARE_TOKEN"] == "tushare-placeholder"
    assert os.environ["EXISTING_VALUE"] == "from_environment"
