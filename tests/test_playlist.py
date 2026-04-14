from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import pytest
from mutagen.id3 import ID3

from birdsong.cli import main
from birdsong.errors import BirdsongError
from birdsong.playlist import build_playlist, export_playlist_audio


FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8000)


def write_silent_mp3(path: Path) -> None:
    source_wav = path.with_suffix(".wav")
    write_silent_wav(source_wav)
    completed = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-y",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source_wav),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    source_wav.unlink()
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "ffmpeg failed to create mp3 fixture")


def test_build_playlist_orders_by_input_species_then_filename(tmp_path: Path, taxonomy):
    sound_dir = tmp_path / "sounds"
    sound_dir.mkdir()
    (sound_dir / "Northern Yellow Warbler 02 Song.mp3").write_bytes(b"a")
    (sound_dir / "Northern Yellow Warbler 01 Song.mp3").write_bytes(b"a")
    (sound_dir / "American Barn Owl 01 Calls.mp3").write_bytes(b"a")
    (sound_dir / "Redpoll-live-cut.wav").write_bytes(b"a")

    requested = [
        taxonomy.resolve("Redpoll"),
        taxonomy.resolve("Northern Yellow Warbler"),
        taxonomy.resolve("American Barn Owl"),
    ]
    output_path = tmp_path / "playlist.m3u"

    result = build_playlist(requested, [sound_dir], output_path, taxonomy)

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1:] == [
        "sounds/Redpoll-live-cut.wav",
        "sounds/Northern Yellow Warbler 01 Song.mp3",
        "sounds/Northern Yellow Warbler 02 Song.mp3",
        "sounds/American Barn Owl 01 Calls.mp3",
    ]
    assert result.entry_count == 4
    assert result.missing_species == []


def test_build_playlist_supports_absolute_paths_and_strict_missing(tmp_path: Path, taxonomy):
    sound_dir = tmp_path / "sounds"
    sound_dir.mkdir()
    owl_file = sound_dir / "American Barn Owl 01 Calls.mp3"
    owl_file.write_bytes(b"a")

    requested = [taxonomy.resolve("American Barn Owl")]
    output_path = tmp_path / "absolute.m3u"
    result = build_playlist(
        requested,
        [sound_dir],
        output_path,
        taxonomy,
        absolute_paths=True,
    )

    assert output_path.read_text(encoding="utf-8").splitlines()[1] == str(owl_file.resolve())
    assert result.entry_count == 1

    with pytest.raises(BirdsongError):
        build_playlist(
            [taxonomy.resolve("American Barn Owl"), taxonomy.resolve("Western Flycatcher")],
            [sound_dir],
            tmp_path / "strict.m3u",
            taxonomy,
            strict=True,
        )


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg required for export tests")
def test_export_playlist_audio_preserves_order_converts_to_mp3_and_tags_tracks(tmp_path: Path, taxonomy):
    sound_dir = tmp_path / "sounds"
    sound_dir.mkdir()
    wav_source = sound_dir / "Redpoll-live-cut.wav"
    mp3_source = sound_dir / "American Barn Owl 01 Calls.mp3"
    mp3_source_2 = sound_dir / "American Barn Owl 02 Song.mp3"
    write_silent_wav(wav_source)
    write_silent_mp3(mp3_source)
    write_silent_mp3(mp3_source_2)

    requested = [
        taxonomy.resolve("Redpoll"),
        taxonomy.resolve("American Barn Owl"),
    ]
    result = build_playlist(requested, [sound_dir], tmp_path / "ordered.m3u", taxonomy)
    export_dir = tmp_path / "exported"

    export_result = export_playlist_audio(result, export_dir)

    exported_names = [track.output_path.name for track in export_result.exported_tracks]
    assert exported_names == [
        "001_Redpoll_01_live_cut.mp3",
        "002_American_Barn_Owl_01_Calls.mp3",
        "002_American_Barn_Owl_02_Song.mp3",
    ]

    first_tags = ID3(export_result.exported_tracks[0].output_path)
    second_tags = ID3(export_result.exported_tracks[1].output_path)
    third_tags = ID3(export_result.exported_tracks[2].output_path)
    assert first_tags.getall("TRCK")[0].text == ["1/3"]
    assert second_tags.getall("TRCK")[0].text == ["2/3"]
    assert third_tags.getall("TRCK")[0].text == ["3/3"]
    assert export_result.exported_tracks[0].output_path.suffix == ".mp3"
    assert export_result.exported_tracks[1].output_path.suffix == ".mp3"
    assert export_result.exported_tracks[2].output_path.suffix == ".mp3"
    assert export_result.exported_tracks[0].bird_number == 1
    assert export_result.exported_tracks[0].bird_file_number == 1
    assert export_result.exported_tracks[1].bird_number == 2
    assert export_result.exported_tracks[1].bird_file_number == 1
    assert export_result.exported_tracks[2].bird_number == 2
    assert export_result.exported_tracks[2].bird_file_number == 2


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg required for export tests")
def test_playlist_build_can_export_without_writing_playlist(
    tmp_path: Path,
    taxonomy,
    monkeypatch: pytest.MonkeyPatch,
):
    sound_dir = tmp_path / "sounds"
    sound_dir.mkdir()
    source_mp3 = sound_dir / "American Barn Owl 01 Calls.mp3"
    write_silent_mp3(source_mp3)
    export_dir = tmp_path / "export"

    monkeypatch.setattr("birdsong.cli.get_taxonomy", lambda: taxonomy)

    exit_code = main(
        [
            "playlist",
            "build",
            "--bird",
            "American Barn Owl",
            "--sound-dir",
            str(sound_dir),
            "--export-dir",
            str(export_dir),
        ]
    )

    assert exit_code == 0
    exported = sorted(export_dir.glob("*.mp3"))
    assert [path.name for path in exported] == ["001_American_Barn_Owl_01_Calls.mp3"]
    assert not (tmp_path / "playlist.m3u").exists()
