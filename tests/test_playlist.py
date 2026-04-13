from __future__ import annotations

from pathlib import Path

import pytest

from birdsong.errors import BirdsongError
from birdsong.playlist import build_playlist


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
