from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from birdsong.errors import BirdsongError
from birdsong.playlist import index_audio_files
from birdsong.xc import (
    DownloadedRecording,
    SpeciesDownloadResult,
    XenoCantoClient,
    XenoCantoRecording,
    download_species_recordings,
)


class FakeXCClient:
    def __init__(self, recordings: list[XenoCantoRecording]):
        self.recordings = recordings
        self.downloaded_ids: list[str] = []

    def search_species(self, species_name: str) -> list[XenoCantoRecording]:
        return list(self.recordings)

    def download_recording(self, recording: XenoCantoRecording, destination: Path) -> None:
        destination.write_text(recording.xc_id, encoding="utf-8")
        self.downloaded_ids.append(recording.xc_id)


def test_xc_client_requires_api_key():
    with pytest.raises(BirdsongError):
        XenoCantoClient("")


def test_download_species_recordings_ranks_filters_and_skips_existing(tmp_path: Path, taxonomy):
    recordings = [
        XenoCantoRecording("201", "American Robin", "https://example/201.mp3", "201.mp3", "A", "song", "2024-05-01", "https://lic", "yes", "no"),
        XenoCantoRecording("202", "American Robin", "https://example/202.mp3", "202.mp3", "A", "song", "2025-05-01", "https://lic", "yes", "yes"),
        XenoCantoRecording("203", "American Robin", "https://example/203.mp3", "203.mp3", "A", "song", "2026-01-01", "https://lic", "no", "no"),
        XenoCantoRecording("204", "American Robin", "https://example/204.mp3", "204.mp3", "B", "call", "2023-01-01", "https://lic", "yes", "no"),
        XenoCantoRecording("205", "American Robin", "https://example/205.mp3", "205.mp3", "D", "song", "2026-01-01", "https://lic", "yes", "no"),
    ]
    client = FakeXCClient(recordings)
    robin = taxonomy.resolve("American Robin")

    first = download_species_recordings(client, robin, tmp_path, limit_per_species=2, quality_at_least="C")
    second = download_species_recordings(client, robin, tmp_path, limit_per_species=2, quality_at_least="C")

    assert [item.xc_id for item in first.downloaded] == ["201", "202"]
    assert [item.xc_id for item in second.downloaded] == ["203", "204"]
    assert [item.filename for item in first.downloaded] == [
        "American Robin 01 song 2024 05 01 qA XC201.mp3",
        "American Robin 02 song 2025 05 01 qA XC202.mp3",
    ]
    assert [item.filename for item in second.downloaded] == [
        "American Robin 03 song 2026 01 01 qA XC203.mp3",
        "American Robin 04 call 2023 01 01 qB XC204.mp3",
    ]
    assert second.skipped_existing_ids >= 2

    matched = index_audio_files([tmp_path], [robin], taxonomy)
    assert len(matched["American Robin"]) == 4


def test_download_species_recordings_skips_http_errors_and_continues(tmp_path: Path, taxonomy):
    recordings = [
        XenoCantoRecording("301", "American Robin", "https://example/301.mp3", "301.mp3", "A", "song", "2026-05-03", "https://lic", "yes", "no"),
        XenoCantoRecording("302", "American Robin", "https://example/302.mp3", "302.mp3", "A", "song", "2026-05-02", "https://lic", "yes", "no"),
        XenoCantoRecording("303", "American Robin", "https://example/303.mp3", "303.mp3", "B", "call", "2026-05-01", "https://lic", "yes", "no"),
    ]
    robin = taxonomy.resolve("American Robin")
    progress_messages: list[str] = []

    class FlakyXCClient(FakeXCClient):
        def download_recording(self, recording: XenoCantoRecording, destination: Path) -> None:
            if recording.xc_id == "301":
                raise urllib.error.HTTPError(
                    recording.file_url,
                    404,
                    "Not Found",
                    hdrs=None,
                    fp=None,
                )
            super().download_recording(recording, destination)

    client = FlakyXCClient(recordings)

    result = download_species_recordings(
        client,
        robin,
        tmp_path,
        limit_per_species=2,
        quality_at_least="C",
        progress=progress_messages.append,
    )

    assert [item.xc_id for item in result.downloaded] == ["302", "303"]
    assert result.failed_downloads == 1
    assert any("skipping XC301: download failed (HTTP 404 Not Found)" in message for message in progress_messages)

    matched = index_audio_files([tmp_path], [robin], taxonomy)
    assert len(matched["American Robin"]) == 2


def test_interrupted_download_discards_partial_file(tmp_path: Path):
    client = XenoCantoClient("dummy-key")
    destination = tmp_path / "Great Egret 01 alarm-call 2025 03 18 qA XC123.mp3"
    recording = XenoCantoRecording(
        "123",
        "Great Egret",
        "https://example.invalid/123.mp3",
        "123.mp3",
        "A",
        "alarm call",
        "2025-03-18",
        "https://lic",
        "yes",
        "no",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int):
            raise KeyboardInterrupt()

    def fake_urlopen(request, timeout=60):
        return FakeResponse()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    try:
        with pytest.raises(KeyboardInterrupt):
            client.download_recording(recording, destination)
    finally:
        monkeypatch.undo()

    assert not destination.exists()
    assert not (tmp_path / (destination.name + ".part")).exists()
