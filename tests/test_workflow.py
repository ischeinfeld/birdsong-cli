from __future__ import annotations

from pathlib import Path

import pytest

from birdsong.cli import main
from birdsong.xc import DownloadedRecording, SpeciesDownloadResult


def test_workflow_histogram_to_playlist_downloads_missing_species(
    tmp_path: Path,
    histogram_taxonomy,
    sample_histogram_path,
    monkeypatch: pytest.MonkeyPatch,
):
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "Snow Goose 01 Calls.mp3").write_bytes(b"a")
    download_dir = tmp_path / "downloads"
    output_path = tmp_path / "workflow.m3u"

    monkeypatch.setattr("birdsong.cli.get_taxonomy", lambda: histogram_taxonomy)

    def fake_download_species_recordings(client, entry, output_dir, **kwargs):
        if entry.common_name == "Black-bellied Whistling-Duck":
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = "Black-bellied Whistling-Duck 01 call 2025 03 18 qA XC999.mp3"
            (output_dir / filename).write_bytes(b"b")
            return SpeciesDownloadResult(
                species_name=entry.common_name,
                downloaded=[
                    DownloadedRecording(
                        species_name=entry.common_name,
                        species_code=entry.species_code,
                        xc_id="999",
                        filename=filename,
                        quality="A",
                        recording_type="call",
                        recording_date="2025-03-18",
                        license_url="https://example",
                    )
                ],
                skipped_existing_ids=0,
            )
        return SpeciesDownloadResult(entry.common_name, [], 0)

    monkeypatch.setattr("birdsong.cli.download_species_recordings", fake_download_species_recordings)

    exit_code = main(
        [
            "workflow",
            "histogram-to-playlist",
            "--histogram",
            str(sample_histogram_path),
            "--date",
            "2026-03-18",
            "--min-frequency",
            "0.0001",
            "--limit",
            "2",
            "--sound-dir",
            str(local_dir),
            "--download-dir",
            str(download_dir),
            "--output",
            str(output_path),
            "--xc-api-key",
            "dummy-key",
        ]
    )

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8").splitlines()[1:] == [
        "local/Snow Goose 01 Calls.mp3",
        "downloads/Black-bellied Whistling-Duck 01 call 2025 03 18 qA XC999.mp3",
    ]


def test_workflow_histogram_to_playlist_without_downloads_uses_existing_audio(
    tmp_path: Path,
    histogram_taxonomy,
    sample_histogram_path,
    monkeypatch: pytest.MonkeyPatch,
):
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "Snow Goose 01 Calls.mp3").write_bytes(b"a")
    output_path = tmp_path / "workflow-no-downloads.m3u"

    monkeypatch.setattr("birdsong.cli.get_taxonomy", lambda: histogram_taxonomy)

    exit_code = main(
        [
            "workflow",
            "histogram-to-playlist",
            "--histogram",
            str(sample_histogram_path),
            "--date",
            "2026-01-01",
            "--min-frequency",
            "0.01",
            "--limit",
            "1",
            "--sound-dir",
            str(local_dir),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8").splitlines()[1:] == [
        "local/Snow Goose 01 Calls.mp3",
    ]


def test_workflow_histogram_to_playlist_tops_up_to_minimum_file_count(
    tmp_path: Path,
    histogram_taxonomy,
    sample_histogram_path,
    monkeypatch: pytest.MonkeyPatch,
):
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "Snow Goose 01 Calls.mp3").write_bytes(b"a")
    download_dir = tmp_path / "downloads"
    output_path = tmp_path / "workflow-top-up.m3u"

    monkeypatch.setattr("birdsong.cli.get_taxonomy", lambda: histogram_taxonomy)

    def fake_download_species_recordings(client, entry, output_dir, **kwargs):
        assert entry.common_name == "Snow Goose"
        assert kwargs["limit_per_species"] == 2
        output_dir.mkdir(parents=True, exist_ok=True)
        filenames = [
            "Snow Goose 01 call 2025 03 18 qA XC999.mp3",
            "Snow Goose 02 call 2025 03 17 qA XC998.mp3",
        ]
        for filename in filenames:
            (output_dir / filename).write_bytes(b"b")
        return SpeciesDownloadResult(
            species_name=entry.common_name,
            downloaded=[
                DownloadedRecording(
                    species_name=entry.common_name,
                    species_code=entry.species_code,
                    xc_id="999",
                    filename=filenames[0],
                    quality="A",
                    recording_type="call",
                    recording_date="2025-03-18",
                    license_url="https://example",
                ),
                DownloadedRecording(
                    species_name=entry.common_name,
                    species_code=entry.species_code,
                    xc_id="998",
                    filename=filenames[1],
                    quality="A",
                    recording_type="call",
                    recording_date="2025-03-17",
                    license_url="https://example",
                ),
            ],
            skipped_existing_ids=0,
        )

    monkeypatch.setattr("birdsong.cli.download_species_recordings", fake_download_species_recordings)

    exit_code = main(
        [
            "workflow",
            "histogram-to-playlist",
            "--histogram",
            str(sample_histogram_path),
            "--date",
            "2026-01-01",
            "--min-frequency",
            "0.01",
            "--limit",
            "1",
            "--sound-dir",
            str(local_dir),
            "--download-dir",
            str(download_dir),
            "--min-files-per-species",
            "3",
            "--output",
            str(output_path),
            "--xc-api-key",
            "dummy-key",
        ]
    )

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8").splitlines()[1:] == [
        "downloads/Snow Goose 01 call 2025 03 18 qA XC999.mp3",
        "local/Snow Goose 01 Calls.mp3",
        "downloads/Snow Goose 02 call 2025 03 17 qA XC998.mp3",
    ]
