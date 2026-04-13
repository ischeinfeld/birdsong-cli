from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from .errors import BirdsongError
from .groups import load_group_catalog
from .histogram import HistogramDataset, RankedSpecies, format_ranked_species, parse_histogram_file
from .playlist import build_playlist, index_audio_files
from .taxonomy import Taxonomy, TaxonomyEntry, TaxonomyStore
from .util import read_bird_names, write_output
from .xc import XenoCantoClient, download_species_recordings


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except BirdsongError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="birdsong")
    subparsers = parser.add_subparsers(dest="command_group", required=True)

    list_parser = subparsers.add_parser("list", help="List bird names from abundance data.")
    list_subparsers = list_parser.add_subparsers(dest="list_command", required=True)
    histogram_parser = list_subparsers.add_parser(
        "from-histogram",
        help="Rank species from a downloaded eBird histogram TSV.",
    )
    histogram_parser.add_argument("--histogram", required=True, type=Path)
    histogram_parser.add_argument("--date", required=True, type=parse_iso_date)
    histogram_parser.add_argument("--min-frequency", type=float, default=0.0)
    histogram_parser.add_argument("--limit", type=int)
    histogram_parser.add_argument("--output", type=Path)
    histogram_parser.add_argument("--format", choices=["names", "tsv"], default="names")
    add_taxonomic_filters(histogram_parser)
    histogram_parser.set_defaults(func=cmd_list_from_histogram)

    playlist_parser = subparsers.add_parser("playlist", help="Build playlists from local audio.")
    playlist_subparsers = playlist_parser.add_subparsers(dest="playlist_command", required=True)
    playlist_build_parser = playlist_subparsers.add_parser("build", help="Build an M3U playlist.")
    add_bird_inputs(playlist_build_parser)
    playlist_build_parser.add_argument("--sound-dir", action="append", required=True, type=Path)
    playlist_build_parser.add_argument("--output", required=True, type=Path)
    playlist_build_parser.add_argument("--strict", action="store_true")
    playlist_build_parser.add_argument("--absolute-paths", action="store_true")
    playlist_build_parser.set_defaults(func=cmd_playlist_build)

    audio_parser = subparsers.add_parser("audio", help="Download bird audio.")
    audio_subparsers = audio_parser.add_subparsers(dest="audio_command", required=True)
    download_parser = audio_subparsers.add_parser(
        "download-xc",
        help="Download matching recordings from xeno-canto.",
    )
    add_bird_inputs(download_parser)
    download_parser.add_argument("--output-dir", required=True, type=Path)
    download_parser.add_argument("--limit-per-species", type=int, default=3)
    download_parser.add_argument(
        "--quality-at-least",
        choices=["A", "B", "C", "D", "E"],
        default="C",
    )
    download_parser.add_argument("--xc-api-key")
    download_parser.add_argument("--verbose", action="store_true")
    download_parser.set_defaults(func=cmd_audio_download_xc)

    workflow_parser = subparsers.add_parser("workflow", help="Run multi-step workflows.")
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", required=True)
    histogram_workflow_parser = workflow_subparsers.add_parser(
        "histogram-to-playlist",
        help="Rank species from a histogram, optionally download missing XC audio, then build a playlist.",
    )
    histogram_workflow_parser.add_argument("--histogram", required=True, type=Path)
    histogram_workflow_parser.add_argument("--date", required=True, type=parse_iso_date)
    histogram_workflow_parser.add_argument("--sound-dir", action="append", required=True, type=Path)
    histogram_workflow_parser.add_argument("--output", required=True, type=Path)
    histogram_workflow_parser.add_argument("--min-frequency", type=float, default=0.0)
    histogram_workflow_parser.add_argument("--limit", type=int)
    histogram_workflow_parser.add_argument("--download-dir", type=Path)
    histogram_workflow_parser.add_argument("--xc-api-key")
    histogram_workflow_parser.add_argument(
        "--quality-at-least",
        choices=["A", "B", "C", "D", "E"],
        default="C",
    )
    histogram_workflow_parser.add_argument("--min-files-per-species", type=positive_int, default=1)
    histogram_workflow_parser.add_argument("--limit-per-species", type=positive_int)
    histogram_workflow_parser.add_argument("--absolute-paths", action="store_true")
    histogram_workflow_parser.add_argument("--verbose", action="store_true")
    add_taxonomic_filters(histogram_workflow_parser)
    histogram_workflow_parser.set_defaults(func=cmd_workflow_histogram_to_playlist)

    return parser


def add_bird_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bird", action="append", default=[])
    parser.add_argument("--bird-file", action="append", default=[], type=Path)


def add_taxonomic_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--group-file",
        action="append",
        default=[],
        type=Path,
        help="Additional TOML bird-group definition file. Bundled default groups are always loaded first.",
    )
    parser.add_argument(
        "--include-group",
        action="append",
        default=[],
        help="Include only species in these named bird groups.",
    )
    parser.add_argument(
        "--exclude-group",
        action="append",
        default=[],
        help="Exclude species in these named bird groups.",
    )
    parser.add_argument(
        "--include-family",
        action="append",
        default=[],
        help="Include only these eBird families. Accepts family common name, scientific name, or family code.",
    )
    parser.add_argument(
        "--exclude-family",
        action="append",
        default=[],
        help="Exclude these eBird families. Accepts family common name, scientific name, or family code.",
    )
    parser.add_argument(
        "--include-order",
        action="append",
        default=[],
        help="Include only these eBird orders.",
    )
    parser.add_argument(
        "--exclude-order",
        action="append",
        default=[],
        help="Exclude these eBird orders.",
    )


def cmd_list_from_histogram(args: argparse.Namespace) -> int:
    taxonomy = get_taxonomy()
    dataset = parse_histogram_file(args.histogram, taxonomy)
    ranked = rank_histogram_species(dataset, taxonomy, args)
    write_output(format_ranked_species(ranked, args.format), args.output)
    return 0


def cmd_playlist_build(args: argparse.Namespace) -> int:
    taxonomy = get_taxonomy()
    requested_entries = resolve_entries_from_args(args, taxonomy)
    result = build_playlist(
        requested_entries=requested_entries,
        sound_dirs=args.sound_dir,
        output_path=args.output,
        taxonomy=taxonomy,
        strict=args.strict,
        absolute_paths=args.absolute_paths,
    )
    matched_species = sum(1 for files in result.matched_files_by_species.values() if files)
    print(
        (
            f"Wrote {result.entry_count} playlist entries to {result.output_path} "
            f"from {matched_species}/{len(requested_entries)} requested species."
        ),
        file=sys.stderr,
    )
    if result.missing_species:
        print(
            "Missing audio for: " + ", ".join(result.missing_species),
            file=sys.stderr,
        )
    return 0


def cmd_audio_download_xc(args: argparse.Namespace) -> int:
    taxonomy = get_taxonomy()
    requested_entries = resolve_entries_from_args(args, taxonomy)
    api_key = args.xc_api_key or os.environ.get("XC_API_KEY", "")
    client = XenoCantoClient(api_key)

    total_downloaded = 0
    total_species = len(requested_entries)
    for index, entry in enumerate(requested_entries, start=1):
        if args.verbose:
            print(
                f"[{index}/{total_species}] {entry.common_name}: searching and ranking recordings",
                file=sys.stderr,
            )
        result = download_species_recordings(
            client,
            entry,
            args.output_dir,
            limit_per_species=args.limit_per_species,
            quality_at_least=args.quality_at_least,
            progress=(
                (lambda message, species=entry.common_name: print(f"  {species}: {message}", file=sys.stderr))
                if args.verbose
                else None
            ),
        )
        total_downloaded += len(result.downloaded)
        print(
            (
                f"{entry.common_name}: downloaded {len(result.downloaded)} files"
                f" ({result.skipped_existing_ids} existing XC ids skipped, "
                f"{result.failed_downloads} failed download candidates)"
            ),
            file=sys.stderr,
        )
    print(f"Downloaded {total_downloaded} files total.", file=sys.stderr)
    return 0


def cmd_workflow_histogram_to_playlist(args: argparse.Namespace) -> int:
    taxonomy = get_taxonomy()
    dataset = parse_histogram_file(args.histogram, taxonomy)
    ranked = rank_histogram_species(dataset, taxonomy, args)
    requested_entries = [taxonomy.by_common_name[row.common_name] for row in ranked]

    sound_dirs = unique_paths(list(args.sound_dir))
    counting_dirs = list(sound_dirs)
    if args.download_dir is not None and args.download_dir.exists() and args.download_dir not in counting_dirs:
        counting_dirs.append(args.download_dir)

    matched_before = index_audio_files(counting_dirs, requested_entries, taxonomy)
    locally_matched_species = {
        name for name, files in matched_before.items() if files
    }

    downloaded_species = 0
    downloaded_files = 0
    xc_api_key = args.xc_api_key or os.environ.get("XC_API_KEY", "")
    if args.download_dir is not None and xc_api_key:
        client = XenoCantoClient(args.xc_api_key or os.environ.get("XC_API_KEY", ""))
        total_species = len(requested_entries)
        for index, entry in enumerate(requested_entries, start=1):
            existing_count = len(matched_before.get(entry.common_name, []))
            needed_count = max(0, args.min_files_per_species - existing_count)
            if needed_count == 0:
                if args.verbose:
                    print(
                        f"[{index}/{total_species}] {entry.common_name}: have {existing_count}, need {args.min_files_per_species}, skipping",
                        file=sys.stderr,
                    )
                continue
            if args.limit_per_species is not None:
                needed_count = min(needed_count, args.limit_per_species)
            if needed_count == 0:
                continue
            if args.verbose:
                print(
                    f"[{index}/{total_species}] {entry.common_name}: have {existing_count}, need {args.min_files_per_species}, downloading {needed_count}",
                    file=sys.stderr,
                )
            result = download_species_recordings(
                client,
                entry,
                args.download_dir,
                limit_per_species=needed_count,
                quality_at_least=args.quality_at_least,
                progress=(
                    (lambda message, species=entry.common_name: print(f"  {species}: {message}", file=sys.stderr))
                    if args.verbose
                    else None
                ),
            )
            if result.downloaded:
                downloaded_species += 1
                downloaded_files += len(result.downloaded)
                if args.verbose:
                    print(
                        f"  {entry.common_name}: downloaded {len(result.downloaded)} files ({result.skipped_existing_ids} existing XC ids skipped, {result.failed_downloads} failed download candidates)",
                        file=sys.stderr,
                    )
            elif args.verbose:
                print(
                    f"  {entry.common_name}: no new files downloaded ({result.skipped_existing_ids} existing XC ids skipped, {result.failed_downloads} failed download candidates)",
                    file=sys.stderr,
                )
            elif result.failed_downloads:
                print(
                    f"{entry.common_name}: skipped {result.failed_downloads} failed download candidates.",
                    file=sys.stderr,
                )
        if args.download_dir not in sound_dirs:
            sound_dirs.append(args.download_dir)
    elif args.download_dir is not None and not xc_api_key:
        print(
            "Download directory was provided but no xeno-canto API key is set; skipping downloads.",
            file=sys.stderr,
        )

    playlist_result = build_playlist(
        requested_entries=requested_entries,
        sound_dirs=sound_dirs,
        output_path=args.output,
        taxonomy=taxonomy,
        absolute_paths=args.absolute_paths,
        strict=False,
    )
    below_target_species = sum(
        1
        for files in playlist_result.matched_files_by_species.values()
        if len(files) < args.min_files_per_species
    )

    print(
        (
            f"Ranked species: {len(requested_entries)} | "
            f"locally matched species: {len(locally_matched_species)} | "
            f"downloaded species: {downloaded_species} | "
            f"downloaded files: {downloaded_files} | "
            f"species below min target: {below_target_species} | "
            f"still missing species: {len(playlist_result.missing_species)} | "
            f"playlist entries: {playlist_result.entry_count}"
        ),
        file=sys.stderr,
    )
    if playlist_result.missing_species:
        print(
            "Missing audio for: " + ", ".join(playlist_result.missing_species),
            file=sys.stderr,
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
    ranked = [
        row for row in ranked if filters.matches(taxonomy.by_common_name[row.common_name])
    ]
    if args.limit is not None:
        ranked = ranked[: args.limit]
    return ranked


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
