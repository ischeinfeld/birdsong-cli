from __future__ import annotations

from pathlib import Path

import pytest

from birdsong.errors import BirdsongError
from birdsong.taxonomy import TaxonomyStore


def test_taxonomy_store_downloads_and_caches_latest_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    csv_text = "\n".join(
        [
            "SCIENTIFIC_NAME,COMMON_NAME,SPECIES_CODE,CATEGORY,TAXON_ORDER,COM_NAME_CODES,SCI_NAME_CODES,BANDING_CODES,ORDER,FAMILY_COM_NAME,FAMILY_SCI_NAME,REPORT_AS,EXTINCT,EXTINCT_YEAR,FAMILY_CODE",
            "Tyto furcata,American Barn Owl,brnowl,species,1.0,,,,Strigiformes,Owls,Tytonidae,,,,owl1",
            "Setophaga petechia,Northern Yellow Warbler,yelwar1,species,2.0,,,,Passeriformes,Wood-Warblers,Parulidae,,,,warb1",
            "Setophaga petechia x coronata,Yellow Warbler x Yellow-rumped Warbler,x01234,hybrid,3.0,,,,Passeriformes,Wood-Warblers,Parulidae,,,,warb1",
        ]
    )
    store = TaxonomyStore(cache_dir=tmp_path)
    monkeypatch.setattr(store, "_get_latest_version", lambda: "2025.0")
    monkeypatch.setattr(store, "_download_taxonomy_csv", lambda: csv_text)

    taxonomy = store.get_taxonomy()

    assert taxonomy.authority_version == "2025.0"
    assert set(taxonomy.by_common_name) == {
        "American Barn Owl",
        "Northern Yellow Warbler",
    }
    assert (tmp_path / "taxonomy-2025.0.csv").exists()

    monkeypatch.setattr(store, "_get_latest_version", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    fallback_taxonomy = store.get_taxonomy()
    assert fallback_taxonomy.by_common_name["American Barn Owl"].species_code == "brnowl"


def test_taxonomy_normalizes_current_names_and_suggests_replacements(taxonomy):
    assert taxonomy.resolve("american barn owl").common_name == "American Barn Owl"
    assert taxonomy.resolve("Northern   Yellow   Warbler").species_code == "yelwar1"
    assert taxonomy.resolve("western-flycatcher").common_name == "Western Flycatcher"
    assert taxonomy.resolve("Redpoll").common_name == "Redpoll"

    with pytest.raises(BirdsongError) as excinfo:
        taxonomy.resolve("Barn Owl")

    assert "American Barn Owl" in str(excinfo.value)


def test_taxonomy_builds_family_and_order_filters_from_aliases(taxonomy):
    filters = taxonomy.build_filters(
        include_families=["Parulidae"],
        exclude_families=["Thrushes"],
        include_orders=["Passeriformes"],
        exclude_orders=["Strigiformes"],
    )

    assert filters.matches(taxonomy.resolve("Northern Yellow Warbler"))
    assert not filters.matches(taxonomy.resolve("American Robin"))
    assert not filters.matches(taxonomy.resolve("American Barn Owl"))
    assert not filters.matches(taxonomy.resolve("Snow Goose"))


def test_taxonomy_filter_errors_include_suggestions(taxonomy):
    with pytest.raises(BirdsongError) as excinfo:
        taxonomy.build_filters(
            include_families=["Wood Warblerz"],
            exclude_families=[],
            include_orders=[],
            exclude_orders=[],
        )

    assert "Wood-Warblers" in str(excinfo.value)
