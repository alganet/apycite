# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""``apycite.toml``, read strictly.

Plain ``tomllib``, and no dependency injection. apycite's configuration is
*data* — a map of extensions to comment styles, a list of patterns, a list of
label rules. apysource needs apywire because it wires a fetcher into a registry
into four commands; there is nothing here to wire. A DI container to carry a
dict of file extensions would be ceremony, and it would drag a compile step and
a generated module along behind it.

Unknown keys are refused, in the shape apysource refuses them: a key we do not
recognise is a key we ignore, and a setting the author believed was in force and
was not is the same class of lie as a citation nobody checked.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apycite.comments import NAME_STYLE_MAP, CommentStyle

#: Shipped patterns, applied *after* whatever the project configures — so a
#: project can pin RFC 9110 to datatracker, or to the HTML rendition, simply by
#: naming it first. It is config, not a branch in the code: the prototype
#: hardcoded rfc-editor, and a second spec family (I-Ds, W3C RECs, ECMA) would
#: then have meant a release rather than three lines of TOML.
DEFAULT_SPECS: list[dict[str, Any]] = [
    {
        "match": r"^RFC (?P<n>\d+)$",
        "source": {
            "url": "https://www.rfc-editor.org/rfc/rfc{n}.txt",
            "type": "text/plain",
        },
    },
]

DEFAULT_EXCLUDE = [
    "**/.git/**", "**/target/**", "**/node_modules/**", "**/__pycache__/**",
    "**/.venv/**", "**/dist/**", "**/build/**",
]

_TOP_KEYS = {"apycite", "styles", "specs", "labels", "ratchet"}
_APYCITE_KEYS = {"roots", "exclude", "sources", "output",
                 "marker_outside_comments"}
_SPEC_KEYS = {"match", "source"}
_LABEL_KEYS = {"match", "label"}
_RATCHET_KEYS = {"scope", "baseline"}


class ConfigError(Exception):
    """The config is wrong, and the run stops rather than guessing at it."""


def _reject_unknown(table: dict[str, Any], allowed: set[str], what: str) -> None:
    unknown = sorted(k for k in table if k not in allowed)
    if unknown:
        raise ConfigError(
            f"{what}: unknown key{'s' if len(unknown) > 1 else ''} "
            f"{', '.join(repr(k) for k in unknown)}. Known: "
            f"{', '.join(sorted(allowed))}. A key apycite does not recognise "
            f"is a key it ignores, and a setting you believed was in force "
            f"and was not is worse than one you never wrote.",
        )


@dataclass(frozen=True)
class SpecPattern:
    """A name shaped like ``RFC 9110`` -> a source entry apysource can read."""

    pattern: re.Pattern[str]
    source: dict[str, str]

    def resolve(self, name: str) -> dict[str, str] | None:
        match = self.pattern.match(name)
        if match is None:
            return None
        fields = match.groupdict()
        return {k: v.format(**fields) for k, v in self.source.items()}


@dataclass(frozen=True)
class LabelRule:
    """A path -> the fragment label a cite in it gets."""

    match: str
    template: str


@dataclass
class Config:
    root: Path
    roots: list[str] = field(default_factory=lambda: ["."])
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    sources: str | None = None
    output: str = "specs.yaml"
    marker_outside_comments: str = "error"
    styles: dict[str, type[CommentStyle]] = field(default_factory=dict)
    specs: list[SpecPattern] = field(default_factory=list)
    labels: list[LabelRule] = field(default_factory=list)
    ratchet_scope: str | None = None
    ratchet_baseline: str | None = None


def _load_style(value: str, key: str) -> type[CommentStyle]:
    """A shorthand, or a dotted path to a class of your own."""
    if value in NAME_STYLE_MAP:
        return NAME_STYLE_MAP[value]

    if "." not in value:
        raise ConfigError(
            f"[styles] {key!r}: unknown comment style {value!r}. Known: "
            f"{', '.join(sorted(NAME_STYLE_MAP))}. Or give a dotted path to a "
            f"CommentStyle subclass of your own.",
        )

    import importlib
    module_name, _, class_name = value.rpartition(".")
    try:
        obj = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError) as exc:
        raise ConfigError(f"[styles] {key!r}: cannot import {value!r}: {exc}") from None

    if not (isinstance(obj, type) and issubclass(obj, CommentStyle)):
        raise ConfigError(f"[styles] {key!r}: {value!r} is not a CommentStyle")
    return obj


def _spec_patterns(raw: list[dict[str, Any]]) -> list[SpecPattern]:
    out = []
    for i, entry in enumerate(raw, 1):
        what = f"[[specs]] #{i}"
        _reject_unknown(entry, _SPEC_KEYS, what)
        if "match" not in entry or "source" not in entry:
            raise ConfigError(f"{what}: needs both 'match' and 'source'")

        source = entry["source"]
        if not isinstance(source, dict) or "url" not in source:
            raise ConfigError(f"{what}: 'source' must be a table with a 'url'")

        try:
            pattern = re.compile(entry["match"])
        except re.error as exc:
            raise ConfigError(f"{what}: bad regex {entry['match']!r}: {exc}") from None

        # A template with a field the pattern never captures is a 404 waiting to
        # happen, and it is knowable *now*. `str.format` would raise at the first
        # citation that used it, weeks later, from a stack trace.
        names = set(pattern.groupindex)
        for key, template in source.items():
            for field_name in re.findall(r"\{(\w+)\}", str(template)):
                if field_name not in names:
                    raise ConfigError(
                        f"{what}: source.{key} uses {{{field_name}}}, which "
                        f"'{entry['match']}' does not capture. Captured: "
                        f"{', '.join(sorted(names)) or '(none)'}",
                    )
        out.append(SpecPattern(pattern, {k: str(v) for k, v in source.items()}))
    return out


def load(path: Path | None, root: Path) -> Config:
    """Read ``apycite.toml``. Absent is fine — the defaults are a working tool."""
    config = Config(root=root)

    if path is None or not path.exists():
        config.specs = _spec_patterns(DEFAULT_SPECS)
        return config

    with open(path, "rb") as handle:
        data = tomllib.load(handle)

    _reject_unknown(data, _TOP_KEYS, str(path))

    main = data.get("apycite", {})
    _reject_unknown(main, _APYCITE_KEYS, "[apycite]")
    config.roots = main.get("roots", config.roots)
    config.exclude = main.get("exclude", config.exclude)
    config.sources = main.get("sources")
    config.output = main.get("output", config.output)
    config.marker_outside_comments = main.get("marker_outside_comments", "error")

    if config.marker_outside_comments not in ("error", "warn"):
        raise ConfigError(
            "[apycite] marker_outside_comments must be \"error\" or \"warn\", "
            f"got {config.marker_outside_comments!r}",
        )

    config.styles = {k.lower(): _load_style(v, k)
                     for k, v in data.get("styles", {}).items()}

    # The project's patterns first, the shipped ones after: naming `RFC 9110`
    # yourself must be able to win.
    config.specs = (_spec_patterns(data.get("specs", []))
                    + _spec_patterns(DEFAULT_SPECS))

    for i, rule in enumerate(data.get("labels", []), 1):
        _reject_unknown(rule, _LABEL_KEYS, f"[[labels]] #{i}")
        if "match" not in rule or "label" not in rule:
            raise ConfigError(f"[[labels]] #{i}: needs both 'match' and 'label'")
        config.labels.append(LabelRule(rule["match"], rule["label"]))

    ratchet = data.get("ratchet", {})
    _reject_unknown(ratchet, _RATCHET_KEYS, "[ratchet]")
    config.ratchet_scope = ratchet.get("scope")
    config.ratchet_baseline = ratchet.get("baseline")

    return config


def find(start: Path) -> Path | None:
    """``apycite.toml``, walking up from the scan root."""
    for directory in (start, *start.parents):
        candidate = directory / "apycite.toml"
        if candidate.exists():
            return candidate
    return None
