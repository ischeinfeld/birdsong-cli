from __future__ import annotations

from pathlib import Path

import pytest

from birdsong.errors import BirdsongError
from birdsong.groups import load_group_catalog


def test_custom_group_file_can_extend_default_groups(tmp_path: Path):
    group_file = tmp_path / "groups.toml"
    group_file.write_text(
        "\n".join(
            [
                "version = 1",
                "",
                "[groups.waterfowl]",
                'description = "Waterfowl and allies."',
                'families = ["Anatidae"]',
                "",
                "[groups.mixed-birds]",
                'description = "Two-family test group."',
                'groups = ["songbirds"]',
                'families = ["Anatidae"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    catalog = load_group_catalog([group_file])

    families, orders = catalog.expand_group("mixed-birds")

    assert "Thrushes and Allies" in families
    assert "Anatidae" in families
    assert orders == ()


def test_unknown_group_reports_close_match():
    catalog = load_group_catalog()

    with pytest.raises(BirdsongError) as excinfo:
        catalog.expand_group("songbirdz")

    assert "songbirds" in str(excinfo.value)
