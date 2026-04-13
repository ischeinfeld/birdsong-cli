from __future__ import annotations

import tomllib
from dataclasses import dataclass
from difflib import get_close_matches
from importlib.resources import files
from pathlib import Path

from .errors import BirdsongError
from .names import normalize_name


@dataclass(frozen=True, slots=True)
class BirdGroup:
    name: str
    description: str
    groups: tuple[str, ...]
    families: tuple[str, ...]
    orders: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExpandedGroupFilters:
    include_families: tuple[str, ...]
    exclude_families: tuple[str, ...]
    include_orders: tuple[str, ...]
    exclude_orders: tuple[str, ...]


class GroupCatalog:
    def __init__(self, groups_by_name: dict[str, BirdGroup]):
        self.groups_by_name = groups_by_name

    def expand_filters(
        self,
        *,
        include_groups: list[str],
        exclude_groups: list[str],
    ) -> ExpandedGroupFilters:
        include_families: list[str] = []
        exclude_families: list[str] = []
        include_orders: list[str] = []
        exclude_orders: list[str] = []

        for group_name in include_groups:
            families, orders = self.expand_group(group_name)
            _extend_unique(include_families, families)
            _extend_unique(include_orders, orders)

        for group_name in exclude_groups:
            families, orders = self.expand_group(group_name)
            _extend_unique(exclude_families, families)
            _extend_unique(exclude_orders, orders)

        return ExpandedGroupFilters(
            include_families=tuple(include_families),
            exclude_families=tuple(exclude_families),
            include_orders=tuple(include_orders),
            exclude_orders=tuple(exclude_orders),
        )

    def expand_group(self, name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        group = self.resolve(name)
        families: list[str] = []
        orders: list[str] = []
        self._expand_group(group, families=families, orders=orders, stack=())
        return tuple(families), tuple(orders)

    def resolve(self, name: str) -> BirdGroup:
        normalized = normalize_name(name)
        group = self.groups_by_name.get(normalized)
        if group is None:
            suggestions = get_close_matches(
                normalized,
                list(self.groups_by_name.keys()),
                n=5,
                cutoff=0.55,
            )
            hint = ""
            if suggestions:
                rendered = [self.groups_by_name[suggestion].name for suggestion in suggestions]
                hint = " Did you mean: " + ", ".join(dict.fromkeys(rendered)) + "?"
            raise BirdsongError(f"Unknown bird group '{name}'.{hint}")
        return group

    def _expand_group(
        self,
        group: BirdGroup,
        *,
        families: list[str],
        orders: list[str],
        stack: tuple[str, ...],
    ) -> None:
        normalized_name = normalize_name(group.name)
        if normalized_name in stack:
            cycle = " -> ".join([*stack, normalized_name, normalized_name])
            raise BirdsongError(f"Bird group definition cycle detected: {cycle}")

        next_stack = (*stack, normalized_name)
        for subgroup_name in group.groups:
            subgroup = self.resolve(subgroup_name)
            self._expand_group(subgroup, families=families, orders=orders, stack=next_stack)
        _extend_unique(families, group.families)
        _extend_unique(orders, group.orders)


def load_group_catalog(group_files: list[Path] | None = None) -> GroupCatalog:
    merged: dict[str, BirdGroup] = {}
    _merge_group_file(DEFAULT_GROUPS_PATH, merged)
    for group_file in group_files or []:
        _merge_group_file(group_file, merged)
    return GroupCatalog(merged)


def _merge_group_file(path: Path, groups_by_name: dict[str, BirdGroup]) -> None:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BirdsongError(f"Bird group file does not exist: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise BirdsongError(f"Bird group file is not valid TOML: {path}: {exc}") from exc

    version = payload.get("version", 1)
    if version != 1:
        raise BirdsongError(f"Unsupported bird group file version in {path}: {version}")

    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, dict):
        raise BirdsongError(f"Bird group file must define a [groups] table: {path}")

    for raw_name, raw_definition in raw_groups.items():
        if not isinstance(raw_definition, dict):
            raise BirdsongError(f"Bird group '{raw_name}' must be a table in {path}")
        group = BirdGroup(
            name=str(raw_name),
            description=_string_value(raw_definition.get("description", ""), path, raw_name, "description"),
            groups=tuple(_string_list(raw_definition.get("groups", []), path, raw_name, "groups")),
            families=tuple(_string_list(raw_definition.get("families", []), path, raw_name, "families")),
            orders=tuple(_string_list(raw_definition.get("orders", []), path, raw_name, "orders")),
        )
        groups_by_name[normalize_name(group.name)] = group


def _string_value(value: object, path: Path, group_name: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise BirdsongError(
            f"Bird group '{group_name}' field '{field_name}' must be a string in {path}"
        )
    return value


def _string_list(value: object, path: Path, group_name: str, field_name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BirdsongError(
            f"Bird group '{group_name}' field '{field_name}' must be a list of strings in {path}"
        )
    return list(value)


def _extend_unique(target: list[str], values: tuple[str, ...] | list[str]) -> None:
    seen = {normalize_name(value) for value in target}
    for value in values:
        normalized = normalize_name(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        target.append(value)


DEFAULT_GROUPS_PATH = Path(str(files("birdsong").joinpath("data/groups.toml")))
