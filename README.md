# Birdsong CLI

`birdsong` is a Python CLI for:

- ranking bird species from downloaded eBird histogram TSV exports
- validating bird names against the latest eBird taxonomy
- downloading matching xeno-canto recordings
- building M3U playlists from existing local audio

## Environment setup

This project uses Poetry for packaging and environment management.

In this repository the checkout path lives under iCloud and contains spaces, so the most reliable setup is Poetry's default cache-managed virtualenv rather than an in-project `.venv`.

```bash
poetry install
poetry run birdsong --help
poetry run pytest
```

If you want the shell activated directly:

```bash
poetry shell
birdsong --help
```

## Commands

```bash
birdsong list from-histogram --histogram path/to/export.txt --date 2026-04-13
birdsong playlist build --bird-file birds.txt --sound-dir data/sounds --output birds.m3u
birdsong audio download-xc --bird-file birds.txt --output-dir downloads
birdsong workflow histogram-to-playlist --histogram export.txt --date 2026-04-13 --sound-dir data/sounds --output birds.m3u
```

Taxonomic filtering is available on the histogram-driven commands:

```bash
birdsong list from-histogram \
  --histogram path/to/export.txt \
  --date 2026-05-16 \
  --include-family "Wood-Warblers" \
  --exclude-order "Anseriformes"

birdsong workflow histogram-to-playlist \
  --histogram export.txt \
  --date 2026-05-16 \
  --sound-dir data/sounds \
  --output playlists/warblers.m3u \
  --include-family Parulidae \
  --exclude-family Icteridae
```

Named groups are also supported. A bundled default group catalog includes `songbirds`, plus smaller component groups such as `warblers`, `vireos`, `wrens`, `thrushes`, `sparrows`, and `finches`.

```bash
birdsong workflow histogram-to-playlist \
  --histogram export.txt \
  --date 2026-05-16 \
  --sound-dir data/sounds \
  --output playlists/songbirds.m3u \
  --include-group songbirds \
  --limit 100
```

Custom group files use TOML and can extend or override the bundled defaults:

```toml
version = 1

[groups.forest-birds]
description = "A small custom example."
groups = ["songbirds"]
families = ["Picidae"]
orders = []
```

Pass them with `--group-file path/to/groups.toml`. Filtering always happens before `--limit`, so `--limit` applies to the filtered species list rather than the full histogram ranking.

## Notes

- Histogram-based abundance requires the official TSV downloaded from eBird's "Download Histogram Data" link.
- xeno-canto downloads require an API key from your xeno-canto account. Provide it with `XC_API_KEY` or `--xc-api-key`.
- `workflow histogram-to-playlist` can enforce a floor with `--min-files-per-species`, downloading top-up xeno-canto files only when the current count across your sound dirs is below that threshold.
- Add `--verbose` to `audio download-xc` or `workflow histogram-to-playlist` for per-species and per-file download progress.
- `--include-group` and `--exclude-group` expand named groups from the bundled group catalog and any `--group-file` TOML files you provide.
- `--include-family` and `--exclude-family` accept an eBird family common name, scientific name, or family code. `--include-order` and `--exclude-order` accept eBird order names.
- Taxonomy snapshots are cached under the standard local cache directory, or `BIRDSONG_CACHE_DIR` if set.
