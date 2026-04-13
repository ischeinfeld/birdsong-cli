from __future__ import annotations

import pytest

from birdsong.cli import main


def render_help(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit) as excinfo:
        main([*argv, "--help"])
    assert excinfo.value.code == 0
    return capsys.readouterr().out


def test_top_level_help_renders_description_and_examples(capsys: pytest.CaptureFixture[str]):
    help_text = render_help([], capsys)

    assert "Rank birds from eBird histogram exports" in help_text
    assert "Examples:" in help_text
    assert "--export-dir exports/birds" in help_text
    assert "birdsong workflow histogram-to-playlist" in help_text


def test_list_help_shows_defaults_and_filter_limit_semantics(capsys: pytest.CaptureFixture[str]):
    help_text = render_help(["list", "from-histogram"], capsys)

    assert "default: 0.0" in help_text
    assert "default: names" in help_text
    assert "top N ranked species after group" in help_text
    assert "Repeatable. Additional TOML bird-group definition" in help_text


def test_playlist_help_explains_repeatable_inputs(capsys: pytest.CaptureFixture[str]):
    help_text = render_help(["playlist", "build"], capsys)

    assert "Repeatable. A current eBird species common name." in help_text
    assert "Repeatable. File containing one bird name per line" in help_text
    assert "Repeatable. Recursively scan this directory for audio" in help_text
    assert "track-number prefixes" in help_text
    assert "MP3 track" in help_text


def test_audio_and_workflow_help_show_defaults_and_env_var(capsys: pytest.CaptureFixture[str]):
    audio_help = render_help(["audio", "download-xc"], capsys)
    workflow_help = render_help(["workflow", "histogram-to-playlist"], capsys)

    assert "default: 3" in audio_help
    assert "default: C" in audio_help
    assert "XC_API_KEY" in audio_help

    assert "default: 1" in workflow_help
    assert "default: C" in workflow_help
    assert "cap XC top-up downloads per species" in workflow_help
