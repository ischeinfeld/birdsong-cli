from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import BirdsongError
from .names import sanitize_filename_component
from .taxonomy import TaxonomyEntry
from .util import read_json, write_json

API_URL = "https://xeno-canto.org/api/3/recordings"
MANIFEST_NAME = "xeno-canto-manifest.json"
QUALITY_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
XC_ID_RE = re.compile(r"\bXC(?P<xc_id>\d+)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class XenoCantoRecording:
    xc_id: str
    english_name: str
    file_url: str
    file_name: str
    quality: str | None
    recording_type: str
    recording_date: str
    license_url: str
    animal_seen: str
    playback_used: str

    @classmethod
    def from_api(cls, payload: dict[str, object]) -> "XenoCantoRecording":
        return cls(
            xc_id=str(payload["id"]),
            english_name=str(payload.get("en", "")),
            file_url=_https_url(str(payload.get("file", ""))),
            file_name=str(payload.get("file-name", "")),
            quality=str(payload.get("q", "") or "").upper() or None,
            recording_type=str(payload.get("type", "") or "").strip(),
            recording_date=str(payload.get("date", "") or "").strip(),
            license_url=_https_url(str(payload.get("lic", ""))),
            animal_seen=str(payload.get("animal-seen", "") or "").strip().lower(),
            playback_used=str(payload.get("playback-used", "") or "").strip().lower(),
        )


@dataclass(frozen=True, slots=True)
class DownloadedRecording:
    species_name: str
    species_code: str
    xc_id: str
    filename: str
    quality: str | None
    recording_type: str
    recording_date: str
    license_url: str


@dataclass(frozen=True, slots=True)
class SpeciesDownloadResult:
    species_name: str
    downloaded: list[DownloadedRecording]
    skipped_existing_ids: int
    failed_downloads: int = 0


class XenoCantoClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise BirdsongError(
                "A xeno-canto API key is required. Set XC_API_KEY or pass --xc-api-key."
            )
        self.api_key = api_key

    def search_species(self, species_name: str) -> list[XenoCantoRecording]:
        query = f'en:"={species_name}" grp:birds'
        page = 1
        recordings: list[XenoCantoRecording] = []
        while True:
            payload = self._request_page(query=query, page=page, per_page=500)
            page_recordings = [
                XenoCantoRecording.from_api(recording)
                for recording in payload.get("recordings", [])
            ]
            recordings.extend(page_recordings)
            if page >= int(payload.get("numPages", 1)):
                break
            page += 1
        return recordings

    def download_recording(self, recording: XenoCantoRecording, destination: Path) -> None:
        request = urllib.request.Request(
            recording.file_url,
            headers={"User-Agent": "birdsong-cli/0.1.0"},
        )
        part_path = destination.with_name(destination.name + ".part")
        if part_path.exists():
            part_path.unlink()
        try:
            with urllib.request.urlopen(request, timeout=60) as response, part_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            part_path.replace(destination)
        except BaseException:
            if part_path.exists():
                part_path.unlink()
            raise

    def _request_page(self, *, query: str, page: int, per_page: int) -> dict[str, object]:
        params = urllib.parse.urlencode(
            {
                "query": query,
                "key": self.api_key,
                "page": page,
                "per_page": per_page,
            }
        )
        request = urllib.request.Request(
            f"{API_URL}?{params}",
            headers={"User-Agent": "birdsong-cli/0.1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))


def download_species_recordings(
    client: XenoCantoClient,
    entry: TaxonomyEntry,
    output_dir: Path,
    *,
    limit_per_species: int = 3,
    quality_at_least: str = "C",
    progress: Callable[[str], None] | None = None,
) -> SpeciesDownloadResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / MANIFEST_NAME
    manifest = _load_manifest(manifest_path)
    existing_ids = _existing_xc_ids(output_dir, manifest)
    accepted_quality = _normalize_quality(quality_at_least)
    ranked_candidates = sort_recordings(
        filter_recordings(
            client.search_species(entry.common_name),
            minimum_quality=accepted_quality,
        )
    )

    downloaded: list[DownloadedRecording] = []
    skipped_existing = 0
    failed_downloads = 0
    sequence_number = _next_sequence_number(entry.common_name, output_dir, manifest)

    for recording in ranked_candidates:
        if recording.xc_id in existing_ids:
            skipped_existing += 1
            continue
        filename = build_download_filename(
            common_name=entry.common_name,
            sequence_number=sequence_number,
            recording=recording,
        )
        destination = output_dir / filename
        if progress is not None:
            progress(
                "downloading "
                f"{len(downloaded) + 1}/{limit_per_species}: "
                f"XC{recording.xc_id} "
                f"{(recording.recording_type or 'recording').strip() or 'recording'} "
                f"{recording.recording_date or 'unknown-date'} "
                f"q{recording.quality or 'U'}"
            )
        try:
            client.download_recording(recording, destination)
        except urllib.error.URLError as exc:
            failed_downloads += 1
            if progress is not None:
                progress(
                    f"skipping XC{recording.xc_id}: download failed "
                    f"({_format_download_error(exc)})"
                )
            continue
        manifest["downloads"].append(
            {
                "species_name": entry.common_name,
                "species_code": entry.species_code,
                "xc_id": recording.xc_id,
                "filename": filename,
                "quality": recording.quality,
                "recording_type": recording.recording_type,
                "recording_date": recording.recording_date,
                "license_url": recording.license_url,
            }
        )
        downloaded.append(
            DownloadedRecording(
                species_name=entry.common_name,
                species_code=entry.species_code,
                xc_id=recording.xc_id,
                filename=filename,
                quality=recording.quality,
                recording_type=recording.recording_type,
                recording_date=recording.recording_date,
                license_url=recording.license_url,
            )
        )
        existing_ids.add(recording.xc_id)
        sequence_number += 1
        if len(downloaded) >= limit_per_species:
            break

    write_json(manifest_path, manifest)
    return SpeciesDownloadResult(
        species_name=entry.common_name,
        downloaded=downloaded,
        skipped_existing_ids=skipped_existing,
        failed_downloads=failed_downloads,
    )


def filter_recordings(
    recordings: list[XenoCantoRecording],
    *,
    minimum_quality: str,
) -> list[XenoCantoRecording]:
    threshold = QUALITY_ORDER[minimum_quality]
    filtered = []
    for recording in recordings:
        quality_rank = QUALITY_ORDER.get(recording.quality or "", 99)
        if quality_rank <= threshold:
            filtered.append(recording)
    return filtered


def sort_recordings(recordings: list[XenoCantoRecording]) -> list[XenoCantoRecording]:
    return sorted(recordings, key=_recording_sort_key)


def build_download_filename(
    *,
    common_name: str,
    sequence_number: int,
    recording: XenoCantoRecording,
) -> str:
    suffix = Path(recording.file_name).suffix or ".mp3"
    quality = recording.quality or "U"
    recording_type = sanitize_filename_component(recording.recording_type or "recording").replace(" ", "-")
    recording_date = sanitize_filename_component(recording.recording_date or "unknown-date")
    common_name = sanitize_filename_component(common_name)
    return (
        f"{common_name} {sequence_number:02d} "
        f"{recording_type} {recording_date} "
        f"q{quality} XC{recording.xc_id}{suffix}"
    )


def _recording_sort_key(recording: XenoCantoRecording) -> tuple[object, ...]:
    return (
        QUALITY_ORDER.get(recording.quality or "", 99),
        0 if recording.animal_seen == "yes" else 1,
        0 if recording.playback_used == "no" else 1,
        _sort_date_value(recording.recording_date),
        int(recording.xc_id),
    )


def _sort_date_value(raw_date: str) -> tuple[int, int, int]:
    try:
        year, month, day = (int(part) for part in raw_date.split("-"))
        return (-year, -month, -day)
    except Exception:
        return (0, 0, 0)


def _normalize_quality(value: str) -> str:
    quality = value.upper().strip()
    if quality not in QUALITY_ORDER:
        raise BirdsongError(f"Unsupported quality threshold '{value}'. Use one of A, B, C, D, or E.")
    return quality


def _load_manifest(path: Path) -> dict[str, object]:
    manifest = read_json(path, {"downloads": []})
    if not isinstance(manifest, dict) or "downloads" not in manifest:
        return {"downloads": []}
    if not isinstance(manifest["downloads"], list):
        manifest["downloads"] = []
    return manifest


def _existing_xc_ids(output_dir: Path, manifest: dict[str, object]) -> set[str]:
    ids = {
        str(item["xc_id"])
        for item in manifest.get("downloads", [])
        if isinstance(item, dict) and item.get("xc_id")
    }
    for file_path in output_dir.iterdir():
        if not file_path.is_file():
            continue
        match = XC_ID_RE.search(file_path.name)
        if match:
            ids.add(match.group("xc_id"))
    return ids


def _next_sequence_number(
    common_name: str,
    output_dir: Path,
    manifest: dict[str, object],
) -> int:
    sanitized_name = sanitize_filename_component(common_name)
    prefix_re = re.compile(rf"^{re.escape(sanitized_name)} (?P<number>\d{{2,}})\b")
    numbers: list[int] = []
    for item in manifest.get("downloads", []):
        if (
            isinstance(item, dict)
            and item.get("species_name") == common_name
            and isinstance(item.get("filename"), str)
        ):
            match = prefix_re.match(item["filename"])
            if match:
                numbers.append(int(match.group("number")))
    for file_path in output_dir.iterdir():
        if not file_path.is_file():
            continue
        match = prefix_re.match(file_path.name)
        if match:
            numbers.append(int(match.group("number")))
    if numbers:
        return max(numbers) + 1
    return 1


def _https_url(value: str) -> str:
    if value.startswith("//"):
        return f"https:{value}"
    return value


def _format_download_error(exc: urllib.error.URLError) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    reason = getattr(exc, "reason", None)
    if reason:
        return str(reason)
    return str(exc)
