# Birdsong CLI

`birdsong` is a Python command-line tool for building bird-sound playlists from:

- downloaded eBird histogram TSV exports
- local directories of bird audio files
- optional xeno-canto downloads used to fill gaps

It validates bird names against the latest live eBird taxonomy, supports taxonomic filtering by families, orders, and named groups, and writes standard `.m3u` playlists.

## Quickstart

This project uses Poetry for packaging and environment management.

```bash
poetry install
poetry run birdsong --help
poetry run pytest
```

If you want an activated shell:

```bash
poetry shell
birdsong --help
```

## What The CLI Does

Current commands:

- `birdsong list from-histogram`
  Rank species from an eBird histogram TSV for a specific date.
- `birdsong playlist build`
  Build an M3U playlist, export ordered MP3s, or do both from an explicit list of bird names and existing local audio.
- `birdsong audio download-xc`
  Download top-ranked xeno-canto recordings for an explicit bird list.
- `birdsong workflow histogram-to-playlist`
  Chain histogram ranking, optional xeno-canto top-up, playlist generation, and/or ordered MP3 export.

## Inputs And Setup

### eBird histogram TSV exports

Abundance input currently comes from the TSV you download from eBird's **Download Histogram Data** link. The CLI does not scrape eBird pages or query eBird directly for histogram data.

The histogram file determines the locality and year-range context. The CLI's `--date` selects the month/day bin within that histogram:

- day `1-7` -> bin 1
- day `8-14` -> bin 2
- day `15-21` -> bin 3
- day `22-end` -> bin 4

### Local sound directories

The playlist and workflow commands recursively scan one or more sound directories and match files to species by filename.

Supported audio extensions:

- `.aac`
- `.aif`
- `.aiff`
- `.flac`
- `.m4a`
- `.mp3`
- `.ogg`
- `.opus`
- `.wav`
- `.wma`

### xeno-canto API key

`audio download-xc` and workflow top-up downloads require a xeno-canto API key.

You can provide it either with:

- `XC_API_KEY` environment variable
- `--xc-api-key`

Example:

```bash
export XC_API_KEY=your-key-here
```

### Taxonomy cache

Taxonomy-dependent commands use the latest live eBird taxonomy version when available, cache it locally, and fall back to the newest cached snapshot if the network is unavailable.

Cache location:

- `BIRDSONG_CACHE_DIR` if set
- otherwise `XDG_CACHE_HOME/birdsong`
- otherwise `~/.cache/birdsong`

Only current eBird `species` entries are accepted as target bird names in v1. Non-species taxa such as hybrids, slash groups, spuhs, forms, and domestics are rejected or skipped.

## Command Reference

### `birdsong list from-histogram`

Use this command when you want a ranked bird list from a downloaded eBird histogram export.

Common behavior:

- parses the TSV and sample-size row
- strips embedded HTML from taxon labels
- skips non-species rows
- validates remaining common names against the current eBird taxonomy
- sorts by descending frequency for the selected date bin
- applies group, family, and order filters
- applies `--limit` after filtering

Important options:

- `--histogram PATH`
  Required. eBird histogram TSV export.
- `--date YYYY-MM-DD`
  Required. Only month and day affect the bin selection.
- `--min-frequency FLOAT`
  Drop species below this frequency threshold.
- `--limit N`
  Keep only the top `N` species after filters.
- `--format names|tsv`
  `names` outputs one common name per line.
  `tsv` outputs `common_name`, `scientific_name`, `species_code`, and `frequency`.
- `--output PATH`
  Write output to a file instead of stdout.

Examples:

```bash
poetry run birdsong list from-histogram \
  --histogram data/histograms/ebird_US-NJ-009__2015_2026_1_12_barchart.txt \
  --date 2026-05-16 \
  --limit 100
```

```bash
poetry run birdsong list from-histogram \
  --histogram "$HIST" \
  --date 2026-05-16 \
  --include-group songbirds \
  --exclude-family Icteridae \
  --format tsv
```

### `birdsong playlist build`

Use this command when you already have a bird list and local audio files and want an `.m3u` playlist, an exported MP3 folder, or both.

Common behavior:

- validates requested bird names against the latest eBird taxonomy
- accepts repeated `--bird` and/or repeated `--bird-file`
- scans one or more `--sound-dir` values recursively
- orders the playlist first by your bird-list order, then by case-insensitive filename order within each species
- uses that same final ordering for MP3 export when `--export-dir` is set
- warns for missing species by default
- exits non-zero with `--strict` if any requested species are missing

Important options:

- `--bird NAME`
  Repeatable. One current eBird species common name.
- `--bird-file PATH`
  Repeatable. One bird name per line. Blank lines and `#` comments are ignored.
- `--sound-dir DIR`
  Required and repeatable. Recursively scanned for audio files.
- `--output PLAYLIST.m3u`
  Optional if `--export-dir` is used. Destination playlist file.
- `--export-dir DIR`
  Optional if `--output` is used. Export the ordered result as MP3 files with bird-order and per-bird file-number filename prefixes plus MP3 track-number tags.
- `--strict`
  Fail instead of warning when species have no matching audio.
- `--absolute-paths`
  Write absolute file paths instead of paths relative to the playlist file's directory.

Examples:

```bash
poetry run birdsong playlist build \
  --bird "American Robin" \
  --bird "Wood Thrush" \
  --sound-dir data/sounds \
  --output playlists/thrushes.m3u
```

```bash
poetry run birdsong playlist build \
  --bird-file birds.txt \
  --sound-dir "data/The Cornell Guide to Bird Sounds--United States and Canada (v2025)" \
  --sound-dir data/downloads/may-16 \
  --output playlists/may-16-birds.m3u \
  --export-dir exports/may-16-birds
```

```bash
poetry run birdsong playlist build \
  --bird-file birds.txt \
  --sound-dir "data/The Cornell Guide to Bird Sounds--United States and Canada (v2025)" \
  --export-dir exports/may-16-birds
```

### `birdsong audio download-xc`

Use this command when you have an explicit bird list and want more recordings from xeno-canto.

Common behavior:

- validates bird names against the current eBird taxonomy first
- queries the official xeno-canto API v3
- filters client-side by minimum quality
- ranks candidates before downloading
- skips XC ids already present in the destination directory
- writes a manifest file named `xeno-canto-manifest.json`
- writes standardized filenames that remain matchable by `playlist build`

Important options:

- `--bird NAME`
- `--bird-file PATH`
- `--output-dir DIR`
  Required. Destination directory for downloads and manifest.
- `--limit-per-species N`
  Maximum downloads per species. Default `3`.
- `--quality-at-least A|B|C|D|E`
  Minimum acceptable XC quality before ranking. Default `C`.
- `--xc-api-key KEY`
  Optional if `XC_API_KEY` is set.
- `--verbose`
  Print per-species search/ranking progress and per-recording download progress.

Examples:

```bash
poetry run birdsong audio download-xc \
  --bird "American Robin" \
  --output-dir data/downloads/robin \
  --xc-api-key "$XC_API_KEY"
```

```bash
poetry run birdsong audio download-xc \
  --bird-file birds.txt \
  --output-dir data/downloads/songbirds \
  --limit-per-species 5 \
  --quality-at-least B \
  --verbose
```

### `birdsong workflow histogram-to-playlist`

Use this command for the main end-to-end flow:

1. read the histogram
2. rank species for the selected date
3. filter by groups/families/orders
4. scan local audio
5. optionally top up missing or undersupplied species from xeno-canto
6. optionally write the final playlist
7. optionally export the final ordered result as MP3s

Important options:

- `--histogram PATH`
  Required histogram TSV.
- `--date YYYY-MM-DD`
  Required date for bin selection.
- `--sound-dir DIR`
  Required and repeatable. Existing local audio directories.
- `--output PLAYLIST.m3u`
  Optional if `--export-dir` is used. Playlist destination.
- `--export-dir DIR`
  Optional if `--output` is used. Export the final ordered result as MP3 files with bird-order and per-bird file-number filename prefixes plus MP3 track-number tags.
- `--min-frequency FLOAT`
  Minimum histogram frequency.
- `--limit N`
  Top `N` species after filtering.
- `--download-dir DIR`
  If set with an XC API key, downloads new XC recordings here and includes this directory in the playlist scan.
- `--min-files-per-species N`
  Target minimum number of matching files per species across local audio and downloads. Default `1`.
- `--limit-per-species N`
  Optional cap on the number of XC top-up downloads attempted per species for this run.
- `--quality-at-least A|B|C|D|E`
  Minimum acceptable XC quality before ranking. Default `C`.
- `--absolute-paths`
  Write absolute paths in the final playlist.
- `--verbose`
  Print ranking, skip, and per-recording download progress.

Examples:

```bash
poetry run birdsong workflow histogram-to-playlist \
  --histogram "$HIST" \
  --date 2026-05-16 \
  --limit 100 \
  --sound-dir "data/The Cornell Guide to Bird Sounds--United States and Canada (v2025)" \
  --output playlists/may-16-cape-may-birds.m3u \
  --export-dir exports/may-16-cape-may-birds
```

```bash
poetry run birdsong workflow histogram-to-playlist \
  --histogram "$HIST" \
  --date 2026-05-16 \
  --limit 100 \
  --include-group songbirds \
  --sound-dir "data/The Cornell Guide to Bird Sounds--United States and Canada (v2025)" \
  --download-dir data/downloads/may-16 \
  --min-files-per-species 10 \
  --xc-api-key "$XC_API_KEY" \
  --verbose \
  --output playlists/may-16-cape-may-songbirds.m3u \
  --export-dir exports/may-16-cape-may-songbirds
```

## Filtering By Groups, Families, And Orders

The histogram-based commands support all of these:

- `--include-group`
- `--exclude-group`
- `--include-family`
- `--exclude-family`
- `--include-order`
- `--exclude-order`

Important behavior:

- filters are applied before `--limit`
- `--limit` always means "top N species after filtering"
- family filters accept family common name, family scientific name, or family code
- order filters accept eBird order names

### Built-in named groups

The bundled group catalog currently includes:

- `songbirds`
- `warblers`
- `vireos`
- `wrens`
- `nuthatches`
- `kinglets`
- `chickadees`
- `gnatcatchers`
- `thrushes`
- `mockingbirds`
- `waxwings`
- `swallows`
- `finches`
- `sparrows`
- `cardinals`
- `tanagers`
- `treecreepers`
- `pipits`
- `larks`

Example:

```bash
poetry run birdsong list from-histogram \
  --histogram "$HIST" \
  --date 2026-05-16 \
  --include-group songbirds \
  --limit 100
```

### Custom group files

You can extend or override the bundled group catalog with repeatable `--group-file` arguments.

Format:

```toml
version = 1

[groups.forest-birds]
description = "Example custom group."
groups = ["songbirds"]
families = ["Picidae"]
orders = []
```

Rules:

- group names are case-insensitive after normalization
- `groups` lets one named group include another
- group definition cycles are rejected
- bundled default groups are loaded first, then your `--group-file` values are merged in order

## xeno-canto Ranking, Filenames, And Duplicate Handling

### Ranking order

XC results are ranked in this order:

1. higher quality `A` -> `E`
2. `animal-seen=yes` before `no` or unknown
3. `playback-used=no` before `yes` or unknown
4. more recent recording date
5. XC numeric id as a final stable tie-breaker

### Standardized filenames

Downloaded files are named so they stay playlist-matchable:

```text
<Common Name> <NN> <description> <recording date> q<quality> XC<id>.<ext>
```

Example:

```text
Great Egret 05 alarm-call 2025 03 18 qA XC123456.mp3
```

XC downloads usually arrive as MP3s, but the code does not assume that. The downloader preserves whatever suffix xeno-canto reports and only falls back to `.mp3` if no suffix is present. The export feature always writes MP3 output, transcoding non-MP3 inputs through `ffmpeg` when needed.

### Duplicate detection and reruns

The downloader skips XC ids already present by checking both:

- `xeno-canto-manifest.json`
- XC ids embedded in filenames already present in the destination directory

This means reruns continue where they left off rather than re-downloading the same XC recordings.

### Failed downloads

- individual recording download failures such as `HTTP 404` are skipped and the downloader continues to the next ranked candidate
- interrupted downloads are written to `.part` files and discarded on failure or Ctrl-C
- XC search/page-fetch failures are reported as clean user-facing errors instead of raw Python tracebacks

## Playlist Matching And Paths

### How local files are matched

`playlist build` and the workflow command match local audio files by filename only in v1.

Primary match rule:

- leading pattern like `<Common Name> 01 ...`

Fallback match rule:

- normalized filename stem starts with the normalized bird common name

Name validation is robust to:

- case differences
- repeated whitespace
- apostrophe variants
- dash variants
- Unicode accents

### Relative vs absolute paths

Default behavior:

- playlist entries are written as paths relative to the playlist file's directory

With `--absolute-paths`:

- playlist entries are written as absolute filesystem paths

If you move a relative-path playlist after generating it, the paths may no longer resolve correctly. In that case either regenerate the playlist in its final location or use `--absolute-paths`.

## MP3 Export

`--export-dir` is available on:

- `birdsong playlist build`
- `birdsong workflow histogram-to-playlist`

Behavior:

- you may use `--export-dir` by itself, `--output` by itself, or both together
- export order is exactly the same as the final playlist order
- exported filenames are prefixed by bird position in the requested list, then file position within that bird
- the filename format is `<bird-number>_<Bird_Name>_<file-number>_<detail>.mp3`
- every exported file is written as `.mp3`
- source MP3 files are copied, then tagged
- non-MP3 sources are transcoded to MP3 through `ffmpeg`
- each exported MP3 gets an MP3 track-number tag like `1/57`, `2/57`, and so on

Example exported filenames:

```text
001_Black_throated_Blue_Warbler_01_Song_US_NY.mp3
001_Black_throated_Blue_Warbler_02_Calls_US_NY.mp3
002_American_Redstart_01_Song_US_NY.mp3
```

The export directory should generally be treated as a dedicated output directory for one export set.

## Troubleshooting

### `Download directory was provided but no xeno-canto API key is set`

Set the API key before running downloads:

```bash
export XC_API_KEY=your-key-here
```

or pass `--xc-api-key`.

### Invalid bird name

Requested bird names must be current eBird species common names. The CLI will suggest close matches when possible.

### Unknown family, order, or group

- family filters must match a current taxonomy family common name, scientific name, or family code
- order filters must match a current taxonomy order name
- group names must exist in the built-in catalog or your `--group-file` TOML

### Missing taxonomy cache or offline taxonomy lookup

The CLI tries the live eBird taxonomy first and falls back to the newest cached snapshot if network access fails. If neither exists yet, rerun with network access so the first snapshot can be cached.

### Some species still have no audio

Possible reasons:

- your sound directories do not contain matching files
- the workflow skipped downloads because no XC API key was available
- XC had no acceptable recordings at or above your quality threshold
- XC candidates failed or were skipped because they were already present

### MP3 export fails

Possible reasons:

- `ffmpeg` is not installed or not on `PATH`
- a source file could not be decoded by `ffmpeg`
- an exported MP3 file could not be tagged after conversion or copy

The export command writes MP3 track-number tags after the audio file is created, so either stage can fail independently.

### xeno-canto returns missing or broken files

The downloader now skips broken per-recording XC downloads and continues, but XC query failures still abort the command with a clean error message because no ranked candidate set can be produced.
