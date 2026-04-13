from __future__ import annotations

from pathlib import Path

import pytest

from birdsong.cli import main
from birdsong.taxonomy import Taxonomy, TaxonomyEntry


def write_histogram_fixture(path: Path) -> Path:
    def row(label: str, first_bin: float) -> str:
        values = [f"{first_bin:.3f}"] + ["0"] * 47
        return "\t".join([label, *values])

    lines = [
        "\t".join(["Sample Size:", *(["1"] * 48)]),
        row("Black-bellied Whistling-Duck (<i>Dendrocygna autumnalis</i>)", 0.900),
        row("Snow Goose (<i>Anser caerulescens</i>)", 0.800),
        row("Emu (<i>Dromaius novaehollandiae</i>)", 0.700),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_entry(
    common_name: str,
    scientific_name: str,
    species_code: str,
    order_name: str,
    family_common_name: str,
    family_scientific_name: str,
    family_code: str,
) -> TaxonomyEntry:
    return TaxonomyEntry(
        common_name=common_name,
        scientific_name=scientific_name,
        species_code=species_code,
        authority_version="2025.0",
        order_name=order_name,
        family_common_name=family_common_name,
        family_scientific_name=family_scientific_name,
        family_code=family_code,
    )


def test_list_from_histogram_applies_taxonomic_filter_before_limit(
    tmp_path: Path,
    histogram_taxonomy,
    monkeypatch: pytest.MonkeyPatch,
):
    histogram_path = write_histogram_fixture(tmp_path / "filter-test.txt")
    output_path = tmp_path / "filtered.txt"

    monkeypatch.setattr("birdsong.cli.get_taxonomy", lambda: histogram_taxonomy)

    exit_code = main(
        [
            "list",
            "from-histogram",
            "--histogram",
            str(histogram_path),
            "--date",
            "2026-01-01",
            "--limit",
            "1",
            "--include-order",
            "Casuariiformes",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8") == "Emu\n"


def test_workflow_histogram_to_playlist_excludes_filtered_families(
    tmp_path: Path,
    histogram_taxonomy,
    monkeypatch: pytest.MonkeyPatch,
):
    histogram_path = write_histogram_fixture(tmp_path / "workflow-filter-test.txt")
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "Black-bellied Whistling-Duck 01 Calls.mp3").write_bytes(b"a")
    (local_dir / "Snow Goose 01 Calls.mp3").write_bytes(b"a")
    (local_dir / "Emu 01 Calls.mp3").write_bytes(b"a")
    output_path = tmp_path / "filtered-workflow.m3u"

    monkeypatch.setattr("birdsong.cli.get_taxonomy", lambda: histogram_taxonomy)

    exit_code = main(
        [
            "workflow",
            "histogram-to-playlist",
            "--histogram",
            str(histogram_path),
            "--date",
            "2026-01-01",
            "--sound-dir",
            str(local_dir),
            "--exclude-family",
            "Anatidae",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8").splitlines()[1:] == [
        "local/Emu 01 Calls.mp3",
    ]


def test_list_from_histogram_applies_default_songbirds_group_before_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    entries = [
        make_entry(
            "American Robin",
            "Turdus migratorius",
            "amerob",
            "Passeriformes",
            "Thrushes and Allies",
            "Turdidae",
            "tur1",
        ),
        make_entry(
            "Snow Goose",
            "Anser caerulescens",
            "snogoo",
            "Anseriformes",
            "Ducks, Geese, and Waterfowl",
            "Anatidae",
            "anat1",
        ),
        make_entry(
            "Emu",
            "Dromaius novaehollandiae",
            "emu1",
            "Casuariiformes",
            "Cassowaries and Emu",
            "Casuariidae",
            "cas1",
        ),
    ]
    default_songbird_families = [
        "New World Warblers",
        "Vireos, Shrike-Babblers, and Erpornis",
        "Wrens",
        "Nuthatches",
        "Kinglets",
        "Tits, Chickadees, and Titmice",
        "Gnatcatchers",
        "Mockingbirds and Thrashers",
        "Waxwings",
        "Swallows",
        "Finches, Euphonias, and Allies",
        "New World Sparrows",
        "Cardinals and Allies",
        "Tanagers and Allies",
        "Treecreepers",
        "Wagtails and Pipits",
        "Larks",
    ]
    for index, family_name in enumerate(default_songbird_families, start=1):
        entries.append(
            make_entry(
                f"Placeholder Songbird {index}",
                f"Placeholderus songbirdus {index}",
                f"place{index}",
                "Passeriformes",
                family_name,
                f"FamilySci{index}",
                f"fam{index}",
            )
        )

    taxonomy = Taxonomy(entries, "2025.0")
    histogram_path = tmp_path / "songbird-filter-test.txt"
    histogram_path.write_text(
        "\n".join(
            [
                "\t".join(["Sample Size:", *(["1"] * 48)]),
                "\t".join(["Snow Goose (<i>Anser caerulescens</i>)", "0.900", *(["0"] * 47)]),
                "\t".join(["American Robin (<i>Turdus migratorius</i>)", "0.850", *(["0"] * 47)]),
                "\t".join(["Emu (<i>Dromaius novaehollandiae</i>)", "0.700", *(["0"] * 47)]),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "songbirds.txt"

    monkeypatch.setattr("birdsong.cli.get_taxonomy", lambda: taxonomy)

    exit_code = main(
        [
            "list",
            "from-histogram",
            "--histogram",
            str(histogram_path),
            "--date",
            "2026-01-01",
            "--include-group",
            "songbirds",
            "--limit",
            "1",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8") == "American Robin\n"
