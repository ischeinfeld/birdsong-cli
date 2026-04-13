from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import BirdsongError
from .names import normalize_name
from .taxonomy import Taxonomy, TaxonomyEntry

SUPPORTED_AUDIO_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}

LEADING_NAME_RE = re.compile(r"^(?P<name>.+?)\s+\d{2}\b")


@dataclass(frozen=True, slots=True)
class PlaylistBuildResult:
    output_path: Path
    matched_files_by_species: dict[str, list[Path]]
    missing_species: list[str]
    entry_count: int


def build_playlist(
    requested_entries: list[TaxonomyEntry],
    sound_dirs: list[Path],
    output_path: Path,
    taxonomy: Taxonomy,
    *,
    strict: bool = False,
    absolute_paths: bool = False,
) -> PlaylistBuildResult:
    matched_files_by_species = index_audio_files(sound_dirs, requested_entries, taxonomy)
    missing_species = [
        entry.common_name
        for entry in requested_entries
        if not matched_files_by_species.get(entry.common_name)
    ]
    if strict and missing_species:
        raise BirdsongError(
            "Missing audio for: " + ", ".join(missing_species)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#EXTM3U"]
    entry_count = 0
    for entry in requested_entries:
        for file_path in matched_files_by_species.get(entry.common_name, []):
            if absolute_paths:
                playlist_path = str(file_path.resolve())
            else:
                playlist_path = os.path.relpath(file_path, start=output_path.parent)
            lines.append(playlist_path)
            entry_count += 1
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return PlaylistBuildResult(
        output_path=output_path,
        matched_files_by_species=matched_files_by_species,
        missing_species=missing_species,
        entry_count=entry_count,
    )


def index_audio_files(
    sound_dirs: list[Path],
    requested_entries: list[TaxonomyEntry],
    taxonomy: Taxonomy,
) -> dict[str, list[Path]]:
    requested_by_normalized = {
        normalize_name(entry.common_name): entry.common_name for entry in requested_entries
    }
    requested_prefixes = sorted(requested_by_normalized, key=len, reverse=True)
    matched: dict[str, list[Path]] = {entry.common_name: [] for entry in requested_entries}

    for sound_dir in sound_dirs:
        if not sound_dir.exists():
            continue
        for file_path in sound_dir.rglob("*"):
            if not file_path.is_file() or file_path.suffix.casefold() not in SUPPORTED_AUDIO_EXTENSIONS:
                continue
            matched_name = match_audio_file(
                file_path,
                requested_by_normalized=requested_by_normalized,
                requested_prefixes=requested_prefixes,
                taxonomy=taxonomy,
            )
            if matched_name is not None:
                matched[matched_name].append(file_path)

    for files in matched.values():
        files.sort(key=lambda path: (path.name.casefold(), str(path)))
    return matched


def match_audio_file(
    file_path: Path,
    *,
    requested_by_normalized: dict[str, str],
    requested_prefixes: list[str],
    taxonomy: Taxonomy,
) -> str | None:
    stem = file_path.stem
    leading_match = LEADING_NAME_RE.match(stem)
    if leading_match is not None:
        normalized = normalize_name(leading_match.group("name"))
        if normalized in requested_by_normalized:
            return requested_by_normalized[normalized]
        canonical = taxonomy.by_normalized_name.get(normalized)
        if canonical is not None:
            resolved = requested_by_normalized.get(normalize_name(canonical.common_name))
            if resolved is not None:
                return resolved

    normalized_stem = normalize_name(stem)
    for prefix in requested_prefixes:
        if normalized_stem == prefix or normalized_stem.startswith(prefix + " "):
            return requested_by_normalized[prefix]
    return None
