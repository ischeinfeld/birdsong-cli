from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from birdsong.cli import main


def test_audio_download_xc_reports_search_failures_without_traceback(
    tmp_path: Path,
    taxonomy,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr("birdsong.cli.get_taxonomy", lambda: taxonomy)

    class FailingXCClient:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def search_species(self, species_name: str):
            raise urllib.error.HTTPError(
                "https://xeno-canto.org/api/3/recordings",
                503,
                "Service Unavailable",
                hdrs=None,
                fp=None,
            )

    monkeypatch.setattr("birdsong.cli.XenoCantoClient", FailingXCClient)

    exit_code = main(
        [
            "audio",
            "download-xc",
            "--bird",
            "American Robin",
            "--output-dir",
            str(tmp_path),
            "--xc-api-key",
            "dummy-key",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error: Unable to query xeno-canto for American Robin: HTTP 503 Service Unavailable" in captured.err
    assert "Traceback" not in captured.err


def test_playlist_build_requires_output_or_export(
    tmp_path: Path,
    taxonomy,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    sound_dir = tmp_path / "sounds"
    sound_dir.mkdir()
    (sound_dir / "American Robin 01 Song.mp3").write_bytes(b"a")

    monkeypatch.setattr("birdsong.cli.get_taxonomy", lambda: taxonomy)

    exit_code = main(
        [
            "playlist",
            "build",
            "--bird",
            "American Robin",
            "--sound-dir",
            str(sound_dir),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Provide at least one output target via --output or --export-dir." in captured.err
