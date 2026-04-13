from __future__ import annotations

import csv
import io
import json
import urllib.request
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path

from .errors import BirdsongError
from .names import normalize_name
from .util import default_cache_dir, ensure_directory

VERSIONS_URL = "https://api.ebird.org/v2/ref/taxonomy/versions"
TAXONOMY_URL = "https://api.ebird.org/v2/ref/taxonomy/ebird?fmt=csv&locale=en"


def _version_sort_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


@dataclass(frozen=True, slots=True)
class TaxonomyEntry:
    common_name: str
    scientific_name: str
    species_code: str
    authority_version: str
    order_name: str
    family_common_name: str
    family_scientific_name: str
    family_code: str


@dataclass(frozen=True, slots=True)
class TaxonomyFilters:
    include_family_codes: frozenset[str] = field(default_factory=frozenset)
    exclude_family_codes: frozenset[str] = field(default_factory=frozenset)
    include_orders: frozenset[str] = field(default_factory=frozenset)
    exclude_orders: frozenset[str] = field(default_factory=frozenset)

    def matches(self, entry: TaxonomyEntry) -> bool:
        if self.include_family_codes and entry.family_code not in self.include_family_codes:
            return False
        if entry.family_code in self.exclude_family_codes:
            return False
        if self.include_orders and entry.order_name not in self.include_orders:
            return False
        if entry.order_name in self.exclude_orders:
            return False
        return True


class Taxonomy:
    def __init__(self, entries: list[TaxonomyEntry], authority_version: str):
        self.authority_version = authority_version
        self.entries = entries
        self.by_common_name = {entry.common_name: entry for entry in entries}
        self.by_normalized_name = {
            normalize_name(entry.common_name): entry for entry in entries
        }
        self.family_aliases = self._build_family_aliases()
        self.order_aliases = self._build_order_aliases()

    def has_species(self, common_name: str) -> bool:
        return common_name in self.by_common_name

    def resolve(self, name: str) -> TaxonomyEntry:
        entry = self.by_normalized_name.get(normalize_name(name))
        if entry is None:
            suggestions = self.suggest(name)
            hint = ""
            if suggestions:
                hint = " Did you mean: " + ", ".join(suggestions) + "?"
            raise BirdsongError(
                f"'{name}' is not a current eBird species common name.{hint}"
            )
        return entry

    def suggest(self, name: str, limit: int = 5) -> list[str]:
        normalized = normalize_name(name)
        lookup = {normalize_name(entry.common_name): entry.common_name for entry in self.entries}
        suggestions = get_close_matches(
            normalized,
            list(lookup.keys()),
            n=limit,
            cutoff=0.55,
        )
        return [lookup[suggestion] for suggestion in suggestions]

    def build_filters(
        self,
        *,
        include_families: list[str],
        exclude_families: list[str],
        include_orders: list[str],
        exclude_orders: list[str],
    ) -> TaxonomyFilters:
        return TaxonomyFilters(
            include_family_codes=frozenset(
                self._resolve_family_filter(value) for value in include_families
            ),
            exclude_family_codes=frozenset(
                self._resolve_family_filter(value) for value in exclude_families
            ),
            include_orders=frozenset(
                self._resolve_order_filter(value) for value in include_orders
            ),
            exclude_orders=frozenset(
                self._resolve_order_filter(value) for value in exclude_orders
            ),
        )

    def _resolve_family_filter(self, value: str) -> str:
        normalized = normalize_name(value)
        matches = self.family_aliases.get(normalized)
        if matches is None:
            suggestions = get_close_matches(
                normalized,
                list(self.family_aliases.keys()),
                n=5,
                cutoff=0.55,
            )
            hint = ""
            if suggestions:
                rendered = [self.family_aliases[suggestion][1] for suggestion in suggestions]
                hint = " Did you mean: " + ", ".join(dict.fromkeys(rendered)) + "?"
            raise BirdsongError(f"Unknown family filter '{value}'.{hint}")
        family_code, family_label = matches
        return family_code

    def _resolve_order_filter(self, value: str) -> str:
        normalized = normalize_name(value)
        order_name = self.order_aliases.get(normalized)
        if order_name is None:
            suggestions = get_close_matches(
                normalized,
                list(self.order_aliases.keys()),
                n=5,
                cutoff=0.55,
            )
            hint = ""
            if suggestions:
                rendered = [self.order_aliases[suggestion] for suggestion in suggestions]
                hint = " Did you mean: " + ", ".join(dict.fromkeys(rendered)) + "?"
            raise BirdsongError(f"Unknown order filter '{value}'.{hint}")
        return order_name

    def _build_family_aliases(self) -> dict[str, tuple[str, str]]:
        aliases: dict[str, tuple[str, str]] = {}
        for entry in self.entries:
            label = f"{entry.family_common_name} / {entry.family_scientific_name}"
            for alias in {
                entry.family_code,
                entry.family_common_name,
                entry.family_scientific_name,
            }:
                aliases[normalize_name(alias)] = (entry.family_code, label)
        return aliases

    def _build_order_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for entry in self.entries:
            aliases[normalize_name(entry.order_name)] = entry.order_name
        return aliases


class TaxonomyStore:
    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or default_cache_dir()
        ensure_directory(self.cache_dir)

    def get_taxonomy(self) -> Taxonomy:
        remote_version: str | None = None
        remote_error: Exception | None = None

        try:
            remote_version = self._get_latest_version()
        except Exception as exc:  # pragma: no cover - exercised via fallback tests
            remote_error = exc

        if remote_version is not None:
            cache_path = self._cache_path(remote_version)
            if not cache_path.exists():
                try:
                    cache_path.write_text(self._download_taxonomy_csv(), encoding="utf-8")
                except Exception as exc:
                    remote_error = exc
            if cache_path.exists():
                return self._load_taxonomy_from_path(cache_path, remote_version)

        cached = self._latest_cached_path()
        if cached is not None:
            return self._load_taxonomy_from_path(cached, self._version_from_path(cached))

        message = "Unable to load eBird taxonomy and no cached taxonomy snapshot exists."
        if remote_error is not None:
            message += f" Last error: {remote_error}"
        raise BirdsongError(message)

    def _load_taxonomy_from_path(self, path: Path, version: str) -> Taxonomy:
        reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
        entries: list[TaxonomyEntry] = []
        for row in reader:
            if row.get("CATEGORY") != "species":
                continue
            entries.append(
                TaxonomyEntry(
                    common_name=row["COMMON_NAME"],
                    scientific_name=row["SCIENTIFIC_NAME"],
                    species_code=row["SPECIES_CODE"],
                    authority_version=version,
                    order_name=row["ORDER"],
                    family_common_name=row["FAMILY_COM_NAME"],
                    family_scientific_name=row["FAMILY_SCI_NAME"],
                    family_code=row["FAMILY_CODE"],
                )
            )
        return Taxonomy(entries, version)

    def _latest_cached_path(self) -> Path | None:
        cached_paths = sorted(
            self.cache_dir.glob("taxonomy-*.csv"),
            key=lambda path: _version_sort_key(self._version_from_path(path)),
        )
        if not cached_paths:
            return None
        return cached_paths[-1]

    def _cache_path(self, version: str) -> Path:
        return self.cache_dir / f"taxonomy-{version}.csv"

    @staticmethod
    def _version_from_path(path: Path) -> str:
        return path.stem.replace("taxonomy-", "", 1)

    def _get_latest_version(self) -> str:
        payload = self._request_json(VERSIONS_URL)
        latest = next((row for row in payload if row.get("latest")), None)
        if latest is None:
            raise BirdsongError("eBird taxonomy version response did not include a latest version.")
        return str(latest["authorityVer"])

    def _download_taxonomy_csv(self) -> str:
        return self._request_text(TAXONOMY_URL)

    def _request_json(self, url: str) -> object:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "birdsong-cli/0.1.0"}),
            timeout=30,
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    def _request_text(self, url: str) -> str:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "birdsong-cli/0.1.0"}),
            timeout=30,
        ) as response:
            return response.read().decode("utf-8")
