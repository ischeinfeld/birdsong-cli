from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from birdsong.taxonomy import Taxonomy, TaxonomyEntry


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


@pytest.fixture
def taxonomy() -> Taxonomy:
    entries = [
        make_entry(
            "Emu",
            "Dromaius novaehollandiae",
            "emu1",
            "Casuariiformes",
            "Cassowaries and Emu",
            "Casuariidae",
            "cas1",
        ),
        make_entry(
            "Black-bellied Whistling-Duck",
            "Dendrocygna autumnalis",
            "bbwduc",
            "Anseriformes",
            "Ducks, Geese, and Waterfowl",
            "Anatidae",
            "anat1",
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
            "American Barn Owl",
            "Tyto furcata",
            "brnowl",
            "Strigiformes",
            "Barn-Owls",
            "Tytonidae",
            "tyt1",
        ),
        make_entry(
            "Northern Yellow Warbler",
            "Setophaga petechia",
            "yelwar1",
            "Passeriformes",
            "Wood-Warblers",
            "Parulidae",
            "par1",
        ),
        make_entry(
            "Western Flycatcher",
            "Empidonax difficilis",
            "wesfly",
            "Passeriformes",
            "Tyrant Flycatchers",
            "Tyrannidae",
            "tyr1",
        ),
        make_entry(
            "Redpoll",
            "Acanthis flammea",
            "redpol1",
            "Passeriformes",
            "Finches and Euphonias",
            "Fringillidae",
            "fri1",
        ),
        make_entry(
            "American Robin",
            "Turdus migratorius",
            "amerob",
            "Passeriformes",
            "Thrushes",
            "Turdidae",
            "tur1",
        ),
    ]
    return Taxonomy(entries, "2025.0")


@pytest.fixture
def histogram_taxonomy() -> Taxonomy:
    entries = [
        make_entry(
            "Emu",
            "Dromaius novaehollandiae",
            "emu1",
            "Casuariiformes",
            "Cassowaries and Emu",
            "Casuariidae",
            "cas1",
        ),
        make_entry(
            "Black-bellied Whistling-Duck",
            "Dendrocygna autumnalis",
            "bbwduc",
            "Anseriformes",
            "Ducks, Geese, and Waterfowl",
            "Anatidae",
            "anat1",
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
    ]
    return Taxonomy(entries, "2025.0")


@pytest.fixture
def sample_histogram_path() -> Path:
    return PROJECT_ROOT / "data" / "histograms" / "ebird_US-NY__1900_2026_1_12_barchart.txt"
