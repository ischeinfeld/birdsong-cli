from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import BirdsongError
from .groups import load_group_catalog
from .histogram import HistogramDataset, RankedSpecies, format_ranked_species, parse_histogram_file
from .playlist import (
    AudioExportResult,
    PlaylistBuildResult,
    export_playlist_audio,
    index_audio_files,
    prepare_playlist,
    write_playlist,
)
from .taxonomy import Taxonomy, TaxonomyEntry, TaxonomyStore
from .util import read_bird_names, write_output
from .xc import SpeciesDownloadResult, XenoCantoClient, download_species_recordings


TOP_LEVEL_EPILOG = """Examples:
  birdsong list from-histogram --histogram export.txt --date 2026-05-16 --limit 50
  birdsong playlist build --bird-file birds.txt --sound-dir data/sounds --output playlists/birds.m3u
  birdsong playlist build --bird-file birds.txt --sound-dir data/cornell --export-dir exports/birds
  birdsong audio download-xc --bird "American Robin" --output-dir data/downloads/robin
  birdsong workflow histogram-to-playlist --histogram export.txt --date 2026-05-16 --sound-dir data/sounds --output playlists/birds.m3u --export-dir exports/birds
"""

LIST_GROUP_EPILOG = """Example:
  birdsong list from-histogram --histogram export.txt --date 2026-05-16 --include-group songbirds --limit 100
"""

LIST_HISTOGRAM_EPILOG = """Examples:
  birdsong list from-histogram --histogram export.txt --date 2026-05-16 --limit 50
  birdsong list from-histogram --histogram export.txt --date 2026-05-16 --include-family Parulidae --exclude-family Icteridae --format tsv
"""

PLAYLIST_GROUP_EPILOG = """Example:
  birdsong playlist build --bird-file birds.txt --sound-dir data/sounds --output playlists/birds.m3u
"""

PLAYLIST_BUILD_EPILOG = """Examples:
  birdsong playlist build --bird "American Robin" --bird "Wood Thrush" --sound-dir data/sounds --output playlists/thrushes.m3u
  birdsong playlist build --bird-file birds.txt --sound-dir data/cornell --sound-dir data/downloads --export-dir exports/birds
  birdsong playlist build --bird-file birds.txt --sound-dir data/cornell --sound-dir data/downloads --output playlists/birds.m3u --export-dir exports/birds --absolute-paths
"""

AUDIO_GROUP_EPILOG = """Example:
  birdsong audio download-xc --bird-file birds.txt --output-dir data/downloads
"""

AUDIO_DOWNLOAD_EPILOG = """Examples:
  birdsong audio download-xc --bird "American Robin" --output-dir data/downloads/robin
  XC_API_KEY=your-key birdsong audio download-xc --bird-file birds.txt --output-dir data/downloads --limit-per-species 5 --quality-at-least B --verbose
"""

WORKFLOW_GROUP_EPILOG = """Example:
  birdsong workflow histogram-to-playlist --histogram export.txt --date 2026-05-16 --sound-dir data/sounds --output playlists/birds.m3u
"""

WORKFLOW_HISTOGRAM_EPILOG = """Examples:
  birdsong workflow histogram-to-playlist --histogram export.txt --date 2026-05-16 --sound-dir data/sounds --output playlists/birds.m3u
  XC_API_KEY=your-key birdsong workflow histogram-to-playlist --histogram export.txt --date 2026-05-16 --sound-dir data/cornell --download-dir data/downloads --min-files-per-species 10 --include-group songbirds --output playlists/songbirds.m3u --export-dir exports/songbirds
"""


class BirdsongHelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    def _get_help_string(self, action: argparse.Action) -> str:
        help_text = action.help or ""
        default = action.default
        if "%(default)" in help_text:
            return help_text
        if default is argparse.SUPPRESS or default is None or default is False:
            return help_text
        if isinstance(default, list) and not default:
            return help_text
        if action.option_strings or action.nargs in (argparse.OPTIONAL, argparse.ZERO_OR_MORE):
            return f"{help_text} (default: %(default)s)"
        return help_text


@dataclass(frozen=True, slots=True)
class WorkflowDownloadStats:
    downloaded_species: int = 0
    downloaded_files: int = 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except BirdsongError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="birdsong",
        description=(
            "Rank birds from eBird histogram exports, download xeno-canto recordings, "
            "build M3U playlists from local bird audio, and export ordered MP3 sets."
        ),
        epilog=TOP_LEVEL_EPILOG,
        formatter_class=BirdsongHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command_group", required=True)

    add_list_parsers(subparsers)
    add_playlist_parsers(subparsers)
    add_audio_parsers(subparsers)
    add_workflow_parsers(subparsers)

    return parser


def add_list_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    list_parser = subparsers.add_parser(
        "list",
        help="List bird names from abundance data.",
        description="Commands for building ranked bird lists from abundance inputs.",
        epilog=LIST_GROUP_EPILOG,
        formatter_class=BirdsongHelpFormatter,
    )
    list_subparsers = list_parser.add_subparsers(dest="list_command", required=True)

    histogram_parser = list_subparsers.add_parser(
        "from-histogram",
        help="Rank species from a downloaded eBird histogram TSV.",
        description=(
            "Parse an eBird histogram TSV export, choose the date's intra-month bin, "
            "apply taxonomic filters, and emit the ranked species list."
        ),
        epilog=LIST_HISTOGRAM_EPILOG,
        formatter_class=BirdsongHelpFormatter,
    )
    histogram_parser.add_argument(
        "--histogram",
        required=True,
        type=Path,
        metavar="PATH",
        help="Path to an eBird TSV exported from the 'Download Histogram Data' link.",
    )
    histogram_parser.add_argument(
        "--date",
        required=True,
        type=parse_iso_date,
        metavar="YYYY-MM-DD",
        help="Calendar date used to choose the histogram bin within the month.",
    )
    histogram_parser.add_argument(
        "--min-frequency",
        type=float,
        default=0.0,
        metavar="FLOAT",
        help="Keep only species whose selected bin frequency is at least this value.",
    )
    histogram_parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Keep only the top N ranked species after group, family, and order filters are applied.",
    )
    histogram_parser.add_argument(
        "--output",
        type=Path,
        metavar="PATH",
        help="Write the ranked list to this file instead of standard output.",
    )
    histogram_parser.add_argument(
        "--format",
        choices=["names", "tsv"],
        default="names",
        help="Output one common name per line, or a TSV with taxonomy metadata and frequency.",
    )
    add_taxonomic_filters(histogram_parser)
    histogram_parser.set_defaults(func=cmd_list_from_histogram)


def add_playlist_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    playlist_parser = subparsers.add_parser(
        "playlist",
        help="Build playlists and export ordered MP3s from local audio.",
        description=(
            "Commands for matching local audio files to validated bird names, writing M3U playlists, "
            "and exporting ordered MP3 copies."
        ),
        epilog=PLAYLIST_GROUP_EPILOG,
        formatter_class=BirdsongHelpFormatter,
    )
    playlist_subparsers = playlist_parser.add_subparsers(dest="playlist_command", required=True)

    playlist_build_parser = playlist_subparsers.add_parser(
        "build",
        help="Build an M3U playlist.",
        description=(
            "Validate requested bird names against the current eBird taxonomy, scan one or more "
            "audio directories, and write a playlist ordered by species then filename."
        ),
        epilog=PLAYLIST_BUILD_EPILOG,
        formatter_class=BirdsongHelpFormatter,
    )
    add_bird_inputs(playlist_build_parser)
    playlist_build_parser.add_argument(
        "--sound-dir",
        action="append",
        required=True,
        type=Path,
        metavar="DIR",
        help="Repeatable. Recursively scan this directory for audio files to match.",
    )
    playlist_build_parser.add_argument(
        "--output",
        type=Path,
        metavar="PLAYLIST.m3u",
        help="Path to the M3U playlist file to write. Required unless --export-dir is used.",
    )
    playlist_build_parser.add_argument(
        "--export-dir",
        type=Path,
        metavar="DIR",
        help="Export the ordered playlist files as MP3s into this directory with track-number prefixes and MP3 track tags.",
    )
    playlist_build_parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any requested species have no matching local audio.",
    )
    playlist_build_parser.add_argument(
        "--absolute-paths",
        action="store_true",
        help="Write absolute file paths instead of paths relative to the playlist location.",
    )
    playlist_build_parser.set_defaults(func=cmd_playlist_build)


def add_audio_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    audio_parser = subparsers.add_parser(
        "audio",
        help="Download bird audio.",
        description="Commands for fetching standardized bird audio files from xeno-canto.",
        epilog=AUDIO_GROUP_EPILOG,
        formatter_class=BirdsongHelpFormatter,
    )
    audio_subparsers = audio_parser.add_subparsers(dest="audio_command", required=True)

    download_parser = audio_subparsers.add_parser(
        "download-xc",
        help="Download matching recordings from xeno-canto.",
        description=(
            "Validate requested bird names, query the xeno-canto API, rank results by quality and "
            "recording metadata, and download standardized files while skipping XC ids already present."
        ),
        epilog=AUDIO_DOWNLOAD_EPILOG,
        formatter_class=BirdsongHelpFormatter,
    )
    add_bird_inputs(download_parser)
    download_parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        metavar="DIR",
        help="Directory where downloaded files and the XC manifest should be written.",
    )
    download_parser.add_argument(
        "--limit-per-species",
        type=int,
        default=3,
        metavar="N",
        help="Maximum number of recordings to download for each requested species.",
    )
    download_parser.add_argument(
        "--quality-at-least",
        choices=["A", "B", "C", "D", "E"],
        default="C",
        help="Keep only XC recordings at or above this quality threshold before ranking.",
    )
    download_parser.add_argument(
        "--xc-api-key",
        metavar="KEY",
        help="xeno-canto API key. If omitted, XC_API_KEY is used.",
    )
    download_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-species search progress and per-recording download progress.",
    )
    download_parser.set_defaults(func=cmd_audio_download_xc)


def add_workflow_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    workflow_parser = subparsers.add_parser(
        "workflow",
        help="Run multi-step workflows.",
        description=(
            "Commands that chain ranking, optional XC download top-up, playlist generation, "
            "and optional ordered MP3 export."
        ),
        epilog=WORKFLOW_GROUP_EPILOG,
        formatter_class=BirdsongHelpFormatter,
    )
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", required=True)

    histogram_workflow_parser = workflow_subparsers.add_parser(
        "histogram-to-playlist",
        help="Rank species from a histogram, optionally download missing XC audio, then build a playlist.",
        description=(
            "Rank species from an eBird histogram export, optionally top up missing or undersupplied "
            "species from xeno-canto, and then build the final playlist from all available audio."
        ),
        epilog=WORKFLOW_HISTOGRAM_EPILOG,
        formatter_class=BirdsongHelpFormatter,
    )
    histogram_workflow_parser.add_argument(
        "--histogram",
        required=True,
        type=Path,
        metavar="PATH",
        help="Path to an eBird TSV exported from the 'Download Histogram Data' link.",
    )
    histogram_workflow_parser.add_argument(
        "--date",
        required=True,
        type=parse_iso_date,
        metavar="YYYY-MM-DD",
        help="Calendar date used to choose the histogram bin within the month.",
    )
    histogram_workflow_parser.add_argument(
        "--sound-dir",
        action="append",
        required=True,
        type=Path,
        metavar="DIR",
        help="Repeatable. Recursively scan this local audio directory before optional XC downloads.",
    )
    histogram_workflow_parser.add_argument(
        "--output",
        type=Path,
        metavar="PLAYLIST.m3u",
        help="Path to the M3U playlist file to write. Required unless --export-dir is used.",
    )
    histogram_workflow_parser.add_argument(
        "--export-dir",
        type=Path,
        metavar="DIR",
        help="Export the ordered workflow result as MP3s into this directory with track-number prefixes and MP3 track tags.",
    )
    histogram_workflow_parser.add_argument(
        "--min-frequency",
        type=float,
        default=0.0,
        metavar="FLOAT",
        help="Keep only species whose selected histogram bin frequency is at least this value.",
    )
    histogram_workflow_parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Keep only the top N ranked species after group, family, and order filters are applied.",
    )
    histogram_workflow_parser.add_argument(
        "--download-dir",
        type=Path,
        metavar="DIR",
        help="If set with an XC API key, download new recordings into this directory and include it in the playlist scan.",
    )
    histogram_workflow_parser.add_argument(
        "--xc-api-key",
        metavar="KEY",
        help="xeno-canto API key. If omitted, XC_API_KEY is used.",
    )
    histogram_workflow_parser.add_argument(
        "--quality-at-least",
        choices=["A", "B", "C", "D", "E"],
        default="C",
        help="Keep only XC recordings at or above this quality threshold before ranking.",
    )
    histogram_workflow_parser.add_argument(
        "--min-files-per-species",
        type=positive_int,
        default=1,
        metavar="N",
        help="Target minimum number of matching files per species across local and downloaded audio.",
    )
    histogram_workflow_parser.add_argument(
        "--limit-per-species",
        type=positive_int,
        metavar="N",
        help="If set, cap XC top-up downloads per species for this run even if the file shortfall is larger.",
    )
    histogram_workflow_parser.add_argument(
        "--absolute-paths",
        action="store_true",
        help="Write absolute playlist paths instead of paths relative to the playlist location.",
    )
    histogram_workflow_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-species ranking, skip, and download progress during the workflow.",
    )
    add_taxonomic_filters(histogram_workflow_parser)
    histogram_workflow_parser.set_defaults(func=cmd_workflow_histogram_to_playlist)


def add_bird_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--bird",
        action="append",
        default=[],
        metavar="NAME",
        help="Repeatable. A current eBird species common name.",
    )
    parser.add_argument(
        "--bird-file",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="Repeatable. File containing one bird name per line; blank lines and # comments are ignored.",
    )


def add_taxonomic_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--group-file",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="Repeatable. Additional TOML bird-group definition file. Bundled default groups are always loaded first.",
    )
    parser.add_argument(
        "--include-group",
        action="append",
        default=[],
        metavar="GROUP",
        help="Repeatable. Keep only species in these named groups.",
    )
    parser.add_argument(
        "--exclude-group",
        action="append",
        default=[],
        metavar="GROUP",
        help="Repeatable. Exclude species in these named groups.",
    )
    parser.add_argument(
        "--include-family",
        action="append",
        default=[],
        metavar="FAMILY",
        help="Repeatable. Keep only species in these eBird families. Accepts common name, scientific name, or family code.",
    )
    parser.add_argument(
        "--exclude-family",
        action="append",
        default=[],
        metavar="FAMILY",
        help="Repeatable. Exclude species in these eBird families. Accepts common name, scientific name, or family code.",
    )
    parser.add_argument(
        "--include-order",
        action="append",
        default=[],
        metavar="ORDER",
        help="Repeatable. Keep only species in these eBird orders.",
    )
    parser.add_argument(
        "--exclude-order",
        action="append",
        default=[],
        metavar="ORDER",
        help="Repeatable. Exclude species in these eBird orders.",
    )


def cmd_list_from_histogram(args: argparse.Namespace) -> int:
    taxonomy = get_taxonomy()
    ranked = load_ranked_species_from_histogram(args, taxonomy)
    write_output(format_ranked_species(ranked, args.format), args.output)
    return 0


def cmd_playlist_build(args: argparse.Namespace) -> int:
    require_playlist_or_export(args.output, args.export_dir)
    taxonomy = get_taxonomy()
    requested_entries = resolve_entries_from_args(args, taxonomy)
    result = prepare_playlist(
        requested_entries=requested_entries,
        sound_dirs=args.sound_dir,
        taxonomy=taxonomy,
        strict=args.strict,
    )
    if args.output is not None:
        result = write_playlist_result(
            result,
            output_path=args.output,
            absolute_paths=args.absolute_paths,
        )
    export_result = export_audio_if_requested(
        result,
        export_dir=args.export_dir,
    )
    print_playlist_summary(
        result,
        requested_count=len(requested_entries),
        export_result=export_result,
    )
    return 0


def cmd_audio_download_xc(args: argparse.Namespace) -> int:
    taxonomy = get_taxonomy()
    requested_entries = resolve_entries_from_args(args, taxonomy)
    client = XenoCantoClient(resolve_xc_api_key(args.xc_api_key))

    total_downloaded = 0
    total_species = len(requested_entries)
    for index, entry in enumerate(requested_entries, start=1):
        result = run_species_download(
            client=client,
            entry=entry,
            output_dir=args.output_dir,
            limit_per_species=args.limit_per_species,
            quality_at_least=args.quality_at_least,
            verbose=args.verbose,
            start_message=(
                f"[{index}/{total_species}] {entry.common_name}: searching and ranking recordings"
            ),
            always_report_summary=True,
        )
        total_downloaded += len(result.downloaded)
    print(f"Downloaded {total_downloaded} files total.", file=sys.stderr)
    return 0


def cmd_workflow_histogram_to_playlist(args: argparse.Namespace) -> int:
    require_playlist_or_export(args.output, args.export_dir)
    taxonomy = get_taxonomy()
    ranked = load_ranked_species_from_histogram(args, taxonomy)
    requested_entries = [taxonomy.by_common_name[row.common_name] for row in ranked]

    sound_dirs = unique_paths(list(args.sound_dir))
    matched_before, locally_matched_species = scan_workflow_local_audio(
        sound_dirs=sound_dirs,
        requested_entries=requested_entries,
        taxonomy=taxonomy,
        download_dir=args.download_dir,
    )

    download_stats, final_sound_dirs = run_workflow_downloads(
        args=args,
        requested_entries=requested_entries,
        matched_before=matched_before,
        sound_dirs=sound_dirs,
    )

    playlist_result = prepare_playlist(
        requested_entries=requested_entries,
        sound_dirs=final_sound_dirs,
        taxonomy=taxonomy,
        strict=False,
    )
    if args.output is not None:
        playlist_result = write_playlist_result(
            playlist_result,
            output_path=args.output,
            absolute_paths=args.absolute_paths,
        )
    export_result = export_audio_if_requested(
        playlist_result,
        export_dir=args.export_dir,
    )
    print_workflow_summary(
        requested_entries=requested_entries,
        locally_matched_species=locally_matched_species,
        download_stats=download_stats,
        playlist_result=playlist_result,
        min_files_per_species=args.min_files_per_species,
        export_result=export_result,
    )
    return 0


def get_taxonomy() -> Taxonomy:
    return TaxonomyStore().get_taxonomy()


def resolve_entries_from_args(
    args: argparse.Namespace,
    taxonomy: Taxonomy,
) -> list[TaxonomyEntry]:
    names = read_bird_names(args.bird, args.bird_file)
    if not names:
        raise BirdsongError("Provide at least one bird via --bird or --bird-file.")
    return [taxonomy.resolve(name) for name in names]


def load_ranked_species_from_histogram(
    args: argparse.Namespace,
    taxonomy: Taxonomy,
) -> list[RankedSpecies]:
    dataset = parse_histogram_file(args.histogram, taxonomy)
    return rank_histogram_species(dataset, taxonomy, args)


def rank_histogram_species(
    dataset: HistogramDataset,
    taxonomy: Taxonomy,
    args: argparse.Namespace,
) -> list[RankedSpecies]:
    group_catalog = load_group_catalog(args.group_file)
    group_filters = group_catalog.expand_filters(
        include_groups=args.include_group,
        exclude_groups=args.exclude_group,
    )
    ranked = dataset.rank_for_date(
        target_date=args.date,
        min_frequency=args.min_frequency,
        limit=None,
    )
    filters = taxonomy.build_filters(
        include_families=[*group_filters.include_families, *args.include_family],
        exclude_families=[*group_filters.exclude_families, *args.exclude_family],
        include_orders=[*group_filters.include_orders, *args.include_order],
        exclude_orders=[*group_filters.exclude_orders, *args.exclude_order],
    )
    filtered = [
        row for row in ranked if filters.matches(taxonomy.by_common_name[row.common_name])
    ]
    if args.limit is not None:
        return filtered[: args.limit]
    return filtered


def resolve_xc_api_key(explicit_value: str | None) -> str:
    return explicit_value or os.environ.get("XC_API_KEY", "")


def build_progress_callback(
    species_name: str,
    *,
    enabled: bool,
) -> Callable[[str], None] | None:
    if not enabled:
        return None
    return lambda message: print(f"  {species_name}: {message}", file=sys.stderr)


def summarize_download_result(result: SpeciesDownloadResult) -> str:
    skipped_text = (
        f"{result.skipped_existing_ids} existing XC ids skipped, "
        f"{result.failed_downloads} failed download candidates"
    )
    if result.downloaded:
        return f"downloaded {len(result.downloaded)} files ({skipped_text})"
    return f"no new files downloaded ({skipped_text})"


def report_download_result(
    species_name: str,
    result: SpeciesDownloadResult,
    *,
    verbose: bool,
    always: bool = False,
    indent: str = "",
) -> None:
    if not (always or verbose or result.failed_downloads):
        return
    print(f"{indent}{species_name}: {summarize_download_result(result)}", file=sys.stderr)


def run_species_download(
    *,
    client: XenoCantoClient,
    entry: TaxonomyEntry,
    output_dir: Path,
    limit_per_species: int,
    quality_at_least: str,
    verbose: bool,
    start_message: str,
    always_report_summary: bool,
    summary_indent: str = "",
) -> SpeciesDownloadResult:
    if verbose:
        print(start_message, file=sys.stderr)
    result = download_species_recordings(
        client,
        entry,
        output_dir,
        limit_per_species=limit_per_species,
        quality_at_least=quality_at_least,
        progress=build_progress_callback(entry.common_name, enabled=verbose),
    )
    report_download_result(
        entry.common_name,
        result,
        verbose=verbose,
        always=always_report_summary,
        indent=summary_indent if verbose else "",
    )
    return result


def scan_workflow_local_audio(
    *,
    sound_dirs: list[Path],
    requested_entries: list[TaxonomyEntry],
    taxonomy: Taxonomy,
    download_dir: Path | None,
) -> tuple[dict[str, list[Path]], set[str]]:
    counting_dirs = list(sound_dirs)
    if download_dir is not None and download_dir.exists() and download_dir not in counting_dirs:
        counting_dirs.append(download_dir)
    matched_before = index_audio_files(counting_dirs, requested_entries, taxonomy)
    locally_matched_species = {name for name, files in matched_before.items() if files}
    return matched_before, locally_matched_species


def run_workflow_downloads(
    *,
    args: argparse.Namespace,
    requested_entries: list[TaxonomyEntry],
    matched_before: dict[str, list[Path]],
    sound_dirs: list[Path],
) -> tuple[WorkflowDownloadStats, list[Path]]:
    if args.download_dir is None:
        return WorkflowDownloadStats(), sound_dirs

    api_key = resolve_xc_api_key(args.xc_api_key)
    if not api_key:
        print(
            "Download directory was provided but no xeno-canto API key is set; skipping downloads.",
            file=sys.stderr,
        )
        return WorkflowDownloadStats(), sound_dirs

    client = XenoCantoClient(api_key)
    stats = WorkflowDownloadStats()
    total_species = len(requested_entries)
    for index, entry in enumerate(requested_entries, start=1):
        existing_count = len(matched_before.get(entry.common_name, []))
        needed_count = resolve_workflow_download_need(
            existing_count=existing_count,
            min_files_per_species=args.min_files_per_species,
            limit_per_species=args.limit_per_species,
        )
        if needed_count == 0:
            if args.verbose:
                print(
                    f"[{index}/{total_species}] {entry.common_name}: have {existing_count}, need {args.min_files_per_species}, skipping",
                    file=sys.stderr,
                )
            continue

        result = run_species_download(
            client=client,
            entry=entry,
            output_dir=args.download_dir,
            limit_per_species=needed_count,
            quality_at_least=args.quality_at_least,
            verbose=args.verbose,
            start_message=(
                f"[{index}/{total_species}] {entry.common_name}: have {existing_count}, "
                f"need {args.min_files_per_species}, downloading {needed_count}"
            ),
            always_report_summary=False,
            summary_indent="  ",
        )
        if result.downloaded:
            stats = WorkflowDownloadStats(
                downloaded_species=stats.downloaded_species + 1,
                downloaded_files=stats.downloaded_files + len(result.downloaded),
            )

    final_sound_dirs = list(sound_dirs)
    if args.download_dir not in final_sound_dirs:
        final_sound_dirs.append(args.download_dir)
    return stats, final_sound_dirs


def resolve_workflow_download_need(
    *,
    existing_count: int,
    min_files_per_species: int,
    limit_per_species: int | None,
) -> int:
    needed_count = max(0, min_files_per_species - existing_count)
    if limit_per_species is not None:
        return min(needed_count, limit_per_species)
    return needed_count


def print_playlist_summary(
    result: PlaylistBuildResult,
    *,
    requested_count: int,
    export_result: AudioExportResult | None = None,
) -> None:
    matched_species = sum(1 for files in result.matched_files_by_species.values() if files)
    if result.output_path is not None:
        print(
            (
                f"Wrote {result.entry_count} playlist entries to {result.output_path} "
                f"from {matched_species}/{requested_count} requested species."
            ),
            file=sys.stderr,
        )
    else:
        print(
            (
                f"Prepared {result.entry_count} ordered playlist entries "
                f"from {matched_species}/{requested_count} requested species."
            ),
            file=sys.stderr,
        )
    if export_result is not None:
        print(
            f"Exported {export_result.track_count} MP3 files to {export_result.output_dir}.",
            file=sys.stderr,
        )
    if result.missing_species:
        print("Missing audio for: " + ", ".join(result.missing_species), file=sys.stderr)


def print_workflow_summary(
    *,
    requested_entries: list[TaxonomyEntry],
    locally_matched_species: set[str],
    download_stats: WorkflowDownloadStats,
    playlist_result: PlaylistBuildResult,
    min_files_per_species: int,
    export_result: AudioExportResult | None = None,
) -> None:
    below_target_species = sum(
        1
        for files in playlist_result.matched_files_by_species.values()
        if len(files) < min_files_per_species
    )
    print(
        (
            f"Ranked species: {len(requested_entries)} | "
            f"locally matched species: {len(locally_matched_species)} | "
            f"downloaded species: {download_stats.downloaded_species} | "
            f"downloaded files: {download_stats.downloaded_files} | "
            f"species below min target: {below_target_species} | "
            f"still missing species: {len(playlist_result.missing_species)} | "
            f"playlist entries: {playlist_result.entry_count}"
            + (
                f" | exported mp3 files: {export_result.track_count}"
                if export_result is not None
                else ""
            )
        ),
        file=sys.stderr,
    )
    if export_result is not None:
        print(f"Exported MP3 files to {export_result.output_dir}.", file=sys.stderr)
    if playlist_result.missing_species:
        print("Missing audio for: " + ", ".join(playlist_result.missing_species), file=sys.stderr)


def require_playlist_or_export(output_path: Path | None, export_dir: Path | None) -> None:
    if output_path is None and export_dir is None:
        raise BirdsongError("Provide at least one output target via --output or --export-dir.")


def write_playlist_result(
    result: PlaylistBuildResult,
    *,
    output_path: Path,
    absolute_paths: bool,
) -> PlaylistBuildResult:
    return write_playlist(result, output_path, absolute_paths=absolute_paths)


def export_audio_if_requested(
    result: PlaylistBuildResult,
    *,
    export_dir: Path | None,
) -> AudioExportResult | None:
    if export_dir is None:
        return None
    return export_playlist_audio(result, export_dir)


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'; expected YYYY-MM-DD.") from exc


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Expected a positive integer.")
    return parsed


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
