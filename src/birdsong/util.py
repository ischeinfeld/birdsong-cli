from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Iterable


def default_cache_dir() -> Path:
    override = os.environ.get("BIRDSONG_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache).expanduser() / "birdsong"
    return Path.home() / ".cache" / "birdsong"


def read_bird_names(cli_birds: Iterable[str], bird_files: Iterable[Path]) -> list[str]:
    names = [name.strip() for name in cli_birds if name.strip()]
    for bird_file in bird_files:
        for raw_line in bird_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                names.append(line)
    return names


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_output(text: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(text)
        if text and not text.endswith("\n"):
            sys.stdout.write("\n")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))
