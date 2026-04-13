from __future__ import annotations

from datetime import date

import pytest

from birdsong.histogram import date_to_bin_index, parse_histogram_file


def test_parse_sample_histogram_extracts_bins_and_skips_non_species(sample_histogram_path, histogram_taxonomy):
    dataset = parse_histogram_file(sample_histogram_path, histogram_taxonomy)

    assert len(dataset.sample_sizes) == 48
    row_names = {row.common_name for row in dataset.rows}
    assert "Snow Goose" in row_names
    assert "Black-bellied Whistling-Duck" in row_names
    assert "Fulvous/Lesser Whistling-Duck" not in row_names


def test_rank_for_specific_date_uses_intra_month_bins(sample_histogram_path, histogram_taxonomy):
    dataset = parse_histogram_file(sample_histogram_path, histogram_taxonomy)

    jan_1_ranked = dataset.rank_for_date(date(2026, 1, 1), min_frequency=0.01)
    jan_10_ranked = dataset.rank_for_date(date(2026, 1, 10), min_frequency=0.01, limit=1)

    assert date_to_bin_index(date(2026, 1, 1)) == 0
    assert date_to_bin_index(date(2026, 1, 10)) == 1
    assert jan_1_ranked[0].common_name == "Snow Goose"
    assert jan_1_ranked[0].frequency == pytest.approx(0.0202561)
    assert jan_10_ranked[0].frequency == pytest.approx(0.0183023)
