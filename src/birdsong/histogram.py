from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from pathlib import Path

from .errors import BirdsongError
from .taxonomy import Taxonomy

HTML_TAG_RE = re.compile(r"<[^>]+>")
SCI_NAME_RE = re.compile(r"^(.*?)\s*\((.*?)\)\s*$")


@dataclass(frozen=True, slots=True)
class HistogramRow:
    common_name: str
    scientific_name: str
    species_code: str
    frequencies: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class RankedSpecies:
    common_name: str
    scientific_name: str
    species_code: str
    frequency: float


class HistogramDataset:
    def __init__(self, rows: list[HistogramRow], sample_sizes: tuple[float, ...]):
        self.rows = rows
        self.sample_sizes = sample_sizes

    def rank_for_date(
        self,
        target_date: date,
        min_frequency: float = 0.0,
        limit: int | None = None,
    ) -> list[RankedSpecies]:
        bin_index = date_to_bin_index(target_date)
        ranked = [
            RankedSpecies(
                common_name=row.common_name,
                scientific_name=row.scientific_name,
                species_code=row.species_code,
                frequency=row.frequencies[bin_index],
            )
            for row in self.rows
            if row.frequencies[bin_index] >= min_frequency
        ]
        ranked.sort(key=lambda row: (-row.frequency, row.common_name.casefold()))
        if limit is not None:
            ranked = ranked[:limit]
        return ranked


def date_to_bin_index(target_date: date) -> int:
    if target_date.day <= 7:
        month_bin = 0
    elif target_date.day <= 14:
        month_bin = 1
    elif target_date.day <= 21:
        month_bin = 2
    else:
        month_bin = 3
    return (target_date.month - 1) * 4 + month_bin


def parse_histogram_file(path: Path, taxonomy: Taxonomy) -> HistogramDataset:
    sample_sizes: tuple[float, ...] | None = None
    rows: list[HistogramRow] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        if parts[0] == "Sample Size:":
            sample_sizes = _parse_frequency_row(parts, path)
            continue
        if len(parts) < 49 or not _looks_like_data_row(parts):
            continue
        common_name, scientific_name = _parse_taxon_label(parts[0])
        if not taxonomy.has_species(common_name):
            continue
        entry = taxonomy.by_common_name[common_name]
        rows.append(
            HistogramRow(
                common_name=entry.common_name,
                scientific_name=scientific_name or entry.scientific_name,
                species_code=entry.species_code,
                frequencies=_parse_frequency_row(parts, path),
            )
        )

    if sample_sizes is None:
        raise BirdsongError(f"{path} does not contain a Sample Size row.")
    return HistogramDataset(rows, sample_sizes)


def format_ranked_species(rows: list[RankedSpecies], output_format: str) -> str:
    if output_format == "names":
        return "".join(f"{row.common_name}\n" for row in rows)
    header = "common_name\tscientific_name\tspecies_code\tfrequency\n"
    body = "".join(
        f"{row.common_name}\t{row.scientific_name}\t{row.species_code}\t{row.frequency:.7g}\n"
        for row in rows
    )
    return header + body


def _parse_taxon_label(label: str) -> tuple[str, str]:
    clean_label = unescape(label).strip()
    match = SCI_NAME_RE.match(clean_label)
    if not match:
        return HTML_TAG_RE.sub("", clean_label).strip(), ""
    common_name = HTML_TAG_RE.sub("", match.group(1)).strip()
    scientific_name = HTML_TAG_RE.sub("", match.group(2)).strip()
    return common_name, scientific_name


def _parse_frequency_row(parts: list[str], path: Path) -> tuple[float, ...]:
    values = [value for value in parts[1:] if value != ""]
    if len(values) != 48:
        raise BirdsongError(
            f"{path} contains a histogram row with {len(values)} frequency bins; expected 48."
        )
    return tuple(float(value) for value in values)


def _looks_like_data_row(parts: list[str]) -> bool:
    try:
        float(parts[1])
    except (TypeError, ValueError):
        return False
    return True
