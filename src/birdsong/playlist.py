from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TRCK

from .errors import BirdsongError
from .names import normalize_name, sanitize_filename_component
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

DEFAULT_EXPORT_BITRATE = "192k"
LEADING_NAME_RE = re.compile(r"^(?P<name>.+?)\s+\d{2}\b")


@dataclass(frozen=True, slots=True)
class PlaylistBuildResult:
    output_path: Path | None
    requested_species: list[str]
    matched_files_by_species: dict[str, list[Path]]
    missing_species: list[str]
    ordered_files: list[Path]
    entry_count: int


@dataclass(frozen=True, slots=True)
class AudioExportTrack:
    track_number: int
    bird_number: int
    bird_file_number: int
    species_name: str
    source_path: Path
    output_path: Path


@dataclass(frozen=True, slots=True)
class AudioExportResult:
    output_dir: Path
    exported_tracks: list[AudioExportTrack]

    @property
    def track_count(self) -> int:
        return len(self.exported_tracks)


def prepare_playlist(
    requested_entries: list[TaxonomyEntry],
    sound_dirs: list[Path],
    taxonomy: Taxonomy,
    *,
    strict: bool = False,
) -> PlaylistBuildResult:
    matched_files_by_species = index_audio_files(sound_dirs, requested_entries, taxonomy)
    missing_species = [
        entry.common_name
        for entry in requested_entries
        if not matched_files_by_species.get(entry.common_name)
    ]
    if strict and missing_species:
        raise BirdsongError("Missing audio for: " + ", ".join(missing_species))

    ordered_files = order_playlist_files(requested_entries, matched_files_by_species)
    return PlaylistBuildResult(
        output_path=None,
        requested_species=[entry.common_name for entry in requested_entries],
        matched_files_by_species=matched_files_by_species,
        missing_species=missing_species,
        ordered_files=ordered_files,
        entry_count=len(ordered_files),
    )


def write_playlist(
    playlist_result: PlaylistBuildResult,
    output_path: Path,
    *,
    absolute_paths: bool = False,
) -> PlaylistBuildResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#EXTM3U"]
    for file_path in playlist_result.ordered_files:
        if absolute_paths:
            playlist_path = str(file_path.resolve())
        else:
            playlist_path = os.path.relpath(file_path, start=output_path.parent)
        lines.append(playlist_path)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return replace(playlist_result, output_path=output_path)


def build_playlist(
    requested_entries: list[TaxonomyEntry],
    sound_dirs: list[Path],
    output_path: Path,
    taxonomy: Taxonomy,
    *,
    strict: bool = False,
    absolute_paths: bool = False,
) -> PlaylistBuildResult:
    result = prepare_playlist(
        requested_entries=requested_entries,
        sound_dirs=sound_dirs,
        taxonomy=taxonomy,
        strict=strict,
    )
    return write_playlist(result, output_path, absolute_paths=absolute_paths)


def export_playlist_audio(
    playlist_result: PlaylistBuildResult,
    output_dir: Path,
    *,
    bitrate: str = DEFAULT_EXPORT_BITRATE,
) -> AudioExportResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_path = shutil.which("ffmpeg")
    export_jobs = build_export_jobs(playlist_result)
    track_count = len(export_jobs)
    if track_count == 0:
        return AudioExportResult(output_dir=output_dir, exported_tracks=[])

    exported_tracks: list[AudioExportTrack] = []
    for job in export_jobs:
        destination = output_dir / build_export_filename(
            source_path=job.source_path,
            species_name=job.species_name,
            bird_number=job.bird_number,
            bird_file_number=job.bird_file_number,
            bird_prefix_width=job.bird_prefix_width,
            file_prefix_width=job.file_prefix_width,
        )
        export_audio_file(
            source_path=job.source_path,
            destination=destination,
            ffmpeg_path=ffmpeg_path,
            bitrate=bitrate,
            track_number=job.track_number,
            total_tracks=track_count,
        )
        exported_tracks.append(
            AudioExportTrack(
                track_number=job.track_number,
                bird_number=job.bird_number,
                bird_file_number=job.bird_file_number,
                species_name=job.species_name,
                source_path=job.source_path,
                output_path=destination,
            )
        )

    return AudioExportResult(output_dir=output_dir, exported_tracks=exported_tracks)


def build_export_filename(
    *,
    source_path: Path,
    species_name: str,
    bird_number: int,
    bird_file_number: int,
    bird_prefix_width: int,
    file_prefix_width: int,
) -> str:
    species_part = sanitize_filename_component(species_name).replace(" ", "_")
    detail_part = extract_export_detail(source_path.stem, species_name)
    return (
        f"{bird_number:0{bird_prefix_width}d}_"
        f"{species_part}_"
        f"{bird_file_number:0{file_prefix_width}d}"
        + (f"_{detail_part}" if detail_part else "")
        + ".mp3"
    )


def export_audio_file(
    *,
    source_path: Path,
    destination: Path,
    ffmpeg_path: str | None,
    bitrate: str,
    track_number: int,
    total_tracks: int,
) -> None:
    temp_path = destination.with_name(f"{destination.stem}.part{destination.suffix}")
    if temp_path.exists():
        temp_path.unlink()
    try:
        if source_path.suffix.casefold() == ".mp3":
            shutil.copy2(source_path, temp_path)
        else:
            if ffmpeg_path is None:
                raise BirdsongError("ffmpeg is required to export non-MP3 audio but was not found on PATH.")
            convert_audio_to_mp3(
                source_path=source_path,
                destination=temp_path,
                ffmpeg_path=ffmpeg_path,
                bitrate=bitrate,
            )
        write_track_tag(
            temp_path,
            track_number=track_number,
            total_tracks=total_tracks,
            title=destination.stem,
        )
        temp_path.replace(destination)
    except BaseException:
        if temp_path.exists():
            temp_path.unlink()
        raise


def convert_audio_to_mp3(
    *,
    source_path: Path,
    destination: Path,
    ffmpeg_path: str,
    bitrate: str,
) -> None:
    completed = subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source_path),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(destination),
        ],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "ffmpeg conversion failed"
        raise BirdsongError(f"Unable to export {source_path.name} as mp3: {stderr}")


def write_track_tag(
    path: Path,
    *,
    track_number: int,
    total_tracks: int,
    title: str,
) -> None:
    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("TRCK")
        tags.delall("TIT2")
        tags.add(TRCK(encoding=3, text=[f"{track_number}/{total_tracks}"]))
        tags.add(TIT2(encoding=3, text=[title]))
        tags.save(path)
    except Exception as exc:
        raise BirdsongError(f"Unable to write MP3 tags for {path.name}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class ExportJob:
    track_number: int
    bird_number: int
    bird_file_number: int
    bird_prefix_width: int
    file_prefix_width: int
    species_name: str
    source_path: Path


def build_export_jobs(playlist_result: PlaylistBuildResult) -> list[ExportJob]:
    if not playlist_result.requested_species:
        return []

    bird_prefix_width = max(3, len(str(len(playlist_result.requested_species))))
    max_files_for_any_bird = max(
        (
            len(playlist_result.matched_files_by_species.get(species_name, []))
            for species_name in playlist_result.requested_species
        ),
        default=0,
    )
    file_prefix_width = max(2, len(str(max_files_for_any_bird)))

    jobs: list[ExportJob] = []
    track_number = 1
    for bird_number, species_name in enumerate(playlist_result.requested_species, start=1):
        for bird_file_number, source_path in enumerate(
            playlist_result.matched_files_by_species.get(species_name, []),
            start=1,
        ):
            jobs.append(
                ExportJob(
                    track_number=track_number,
                    bird_number=bird_number,
                    bird_file_number=bird_file_number,
                    bird_prefix_width=bird_prefix_width,
                    file_prefix_width=file_prefix_width,
                    species_name=species_name,
                    source_path=source_path,
                )
            )
            track_number += 1
    return jobs


def extract_export_detail(source_stem: str, species_name: str) -> str:
    stem = sanitize_filename_component(source_stem)
    species_stem = sanitize_filename_component(species_name)
    match = re.match(
        rf"^{re.escape(species_stem)}(?:\s+\d{{1,3}})?(?:\s+|$)",
        stem,
        flags=re.IGNORECASE,
    )
    if match is not None:
        stem = stem[match.end() :].strip()
    detail = sanitize_filename_component(stem).replace(" ", "_")
    return detail if detail else "recording"


def order_playlist_files(
    requested_entries: list[TaxonomyEntry],
    matched_files_by_species: dict[str, list[Path]],
) -> list[Path]:
    ordered_files: list[Path] = []
    for entry in requested_entries:
        ordered_files.extend(matched_files_by_species.get(entry.common_name, []))
    return ordered_files


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
