# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""``apycite.toml``, read strictly.

Plain ``tomllib``, and no dependency injection. apycite's configuration is
*data* — a map of extensions to comment styles, a list of label rules, a
baseline. apysource needs apywire because it wires a fetcher into a registry
into four commands; there is nothing here to wire. A DI container to carry a
dict of file extensions would be ceremony, and it would drag a compile step and
a generated module along behind it.

Note what is *not* here: where to find a document. That is apysource's sources
file, not apycite's config, and it was here once — see ``[[specs]]`` below.

Unknown keys are refused, in the shape apysource refuses them: a key we do not
recognise is a key we ignore, and a setting the author believed was in force and
was not is the same class of lie as a citation nobody checked.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apycite.comments import NAME_STYLE_MAP, CommentStyle

DEFAULT_EXCLUDE = [
    "**/.git/**", "**/target/**", "**/node_modules/**", "**/__pycache__/**",
    "**/.venv/**", "**/dist/**", "**/build/**",
]

#: What `output_format` may say.
#:
#: `yaml` is apycite's own; the rest are apysource's serializations, and they are
#: named here rather than taken from `apysource.emit.FORMATS` wholesale because
#: only some of them can be committed. `--frozen` compares bytes, and a format
#: that labels its blank nodes afresh each run would report a diff every commit
#: and teach everyone to ignore it.
OUTPUT_FORMATS = ("yaml", "turtle", "ttl")

_TOP_KEYS = {"apycite", "styles", "labels", "ratchet"}
_APYCITE_KEYS = {"roots", "exclude", "sources", "output", "output_format",
                 "marker_outside_comments"}
_LABEL_KEYS = {"match", "label"}
_RATCHET_KEYS = {"scope", "baseline", "exclude"}

#: What ``[[specs]]`` used to do, and where it went.
#:
#: It mapped a name like ``RFC 9110`` to an rfc-editor URL — which meant apycite
#: shipped a hardcoded rfc-editor link while its own README said it "has no idea
#: what an RFC is, or where rfc-editor lives". Turning a name into a URL is the
#: job of the tool that then fetches the URL, and it now is one: apysource ships
#: a repository that claims rfc-editor and declares the `RFC NNNN` name family
#: alongside it, and a `patterns:` block in the sources file adds a family of
#: your own.
_SPECS_MOVED = (
    "[[specs]] moved to apysource. Turning a name like 'RFC 9110' into a URL is "
    "the job of the tool that fetches the URL — apycite has no idea what an RFC "
    "is, and it has no business minting rfc-editor links. Write the pattern in "
    "your sources file instead:\n"
    "\n"
    "    patterns:\n"
    "      - match: '^W3C (?P<slug>[a-z0-9-]+)$'\n"
    "        source: {url: 'https://www.w3.org/TR/{slug}/', type: text/html}\n"
    "\n"
    "'RFC NNNN' needs no pattern at all — apysource ships a repository that "
    "claims rfc-editor and declares the family beside it. What apycite writes "
    "out is the expanded URL, whichever one apysource resolves the name to."
)


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
    #: How the citations file is written. ``yaml`` is the file a person reads and
    #: reviews; ``turtle`` is the same citations as RDF, for a project that wants
    #: to publish the map from its code to the sentences it implements.
    #:
    #: Only turtle among the RDF serializations is byte-stable, and `extract
    #: --frozen` compares bytes — the others label their blank nodes afresh each
    #: run, so a committed file would show a diff on every commit.
    output_format: str = "yaml"
    marker_outside_comments: str = "error"
    styles: dict[str, type[CommentStyle]] = field(default_factory=dict)
    labels: list[LabelRule] = field(default_factory=list)
    ratchet_scope: str | None = None
    ratchet_baseline: str | None = None
    #: Files inside the scope that carry no normative content, and so can never be
    #: cited: a `mod.rs`, an `__init__.py`, an `index.ts`. Without this they would
    #: sit in the baseline forever and it could never empty.
    ratchet_exclude: list[str] = field(default_factory=list)


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


def load(path: Path | None, root: Path) -> Config:
    """Read ``apycite.toml``. Absent is fine — the defaults are a working tool."""
    config = Config(root=root)

    if path is None or not path.exists():
        return config

    with open(path, "rb") as handle:
        data = tomllib.load(handle)

    # Named before the generic refusal, which would say "unknown key 'specs'" —
    # true, and useless. It would not say that the feature still exists one
    # project over, and a project whose W3C names had silently stopped resolving
    # would find that out at the cite, blaming the wrong thing.
    if "specs" in data:
        raise ConfigError(_SPECS_MOVED)

    _reject_unknown(data, _TOP_KEYS, str(path))

    main = data.get("apycite", {})
    _reject_unknown(main, _APYCITE_KEYS, "[apycite]")
    config.roots = main.get("roots", config.roots)
    config.exclude = main.get("exclude", config.exclude)
    config.sources = main.get("sources")
    config.output = main.get("output", config.output)
    config.output_format = main.get("output_format", config.output_format)
    if config.output_format not in OUTPUT_FORMATS:
        known = ", ".join(sorted(OUTPUT_FORMATS))
        raise ConfigError(
            f"unknown output_format {config.output_format!r}. Known: {known}. "
            f"Only 'yaml' and 'turtle' can be committed and compared by "
            f"`extract --frozen`; the rest relabel their blank nodes each run.",
        )
    config.marker_outside_comments = main.get("marker_outside_comments", "error")

    if config.marker_outside_comments not in ("error", "warn"):
        raise ConfigError(
            "[apycite] marker_outside_comments must be \"error\" or \"warn\", "
            f"got {config.marker_outside_comments!r}",
        )

    config.styles = {k.lower(): _load_style(v, k)
                     for k, v in data.get("styles", {}).items()}

    for i, rule in enumerate(data.get("labels", []), 1):
        _reject_unknown(rule, _LABEL_KEYS, f"[[labels]] #{i}")
        if "match" not in rule or "label" not in rule:
            raise ConfigError(f"[[labels]] #{i}: needs both 'match' and 'label'")
        config.labels.append(LabelRule(rule["match"], rule["label"]))

    ratchet = data.get("ratchet", {})
    _reject_unknown(ratchet, _RATCHET_KEYS, "[ratchet]")
    config.ratchet_scope = ratchet.get("scope")
    config.ratchet_baseline = ratchet.get("baseline")
    config.ratchet_exclude = list(ratchet.get("exclude", []))

    return config


def find(start: Path) -> Path | None:
    """``apycite.toml``, walking up from the scan root."""
    for directory in (start, *start.parents):
        candidate = directory / "apycite.toml"
        if candidate.exists():
            return candidate
    return None
