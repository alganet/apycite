# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Turning the name in a cite into a source apysource can fetch.

The registry is **not a new concept**. It is an ordinary apysource sources file
— the same one `apysource check` reads — and a cite names an entry in it by its
`label`. That is the whole resolution model, and it is why apycite can cite a
Gutenberg book, an MDN page, a WHATWG living standard or a CSS spec without
knowing what any of those are:

    sources:
      - label: RFC 9110
        url: https://www.rfc-editor.org/rfc/rfc9110.txt
        type: text/plain
      - label: Moby-Dick               # GutenbergRepo claims this URL
        url: https://www.gutenberg.org/ebooks/2701
        publisher: Harper & Brothers
      - label: MDN Origin              # MdnRepo claims this one
        url: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Origin

Repo claiming, format detection, section trees, anchor inference, redirect
surfacing — none of it is here. It is all apysource's, and it is reached by
writing a source entry.

Patterns exist only because writing 350 entries for RFC 1..9999 by hand is
silly. They can express a *uniform family* — a URL and a media type. A book
needs an ISBN, a publisher, an edition; a chapter needs a `part_of`. Those have
biographies, and a biography goes in the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from apysource.yaml_input import SOURCE_KEYS, graph_from_data

from apycite.config import SpecPattern


class SourceError(Exception):
    """A cite named a source that could not be resolved. Never guessed at."""


@dataclass
class Registry:
    """The sources file, as data — plus whatever the patterns mint on demand."""

    #: label -> the source entry, exactly as written. Hand-written fragments and
    #: all: they survive into the output untouched, so the things the grammar
    #: deliberately cannot say (a selector-only fragment, a `part_of` chapter
    #: tree) cost the user nothing. The escape hatch is the file they already have.
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    patterns: list[SpecPattern] = field(default_factory=list)
    _minted: dict[str, dict[str, Any]] = field(default_factory=dict)

    def resolve(self, name: str) -> dict[str, Any]:
        """The source a cite names. Registry first, then patterns, then refuse."""
        if name in self.entries:
            return self.entries[name]
        if name in self._minted:
            return self._minted[name]

        for pattern in self.patterns:
            source = pattern.resolve(name)
            if source is not None:
                entry = {"label": name, **source}
                self._minted[name] = entry
                return entry

        raise SourceError(
            f"unknown source {name!r}: it is not a label in your sources file, "
            f"and no [[specs]] pattern matches it. Add it to the sources file, "
            f"or add a pattern.",
        )

    def used(self, name: str) -> dict[str, Any]:
        """The entry, once resolution has already happened."""
        return self.entries.get(name) or self._minted[name]


def load_registry(path: Path | None, patterns: list[SpecPattern]) -> Registry:
    """Read the sources file, and prove apysource will accept it.

    Validated through apysource's *real* loader, not by looking at the keys
    ourselves. If the registry is malformed, the author should hear it now — from
    the tool that owns the format — rather than after a scan of 184 files.
    """
    registry = Registry(patterns=patterns)
    if path is None:
        return registry

    if not path.exists():
        raise SourceError(f"sources file not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    # Raises on anything apysource would refuse: an unknown key, a colliding
    # identity, a snippet written as a list.
    graph_from_data(data, origin=str(path))

    for entry in data["sources"]:
        label = entry["label"]
        unknown = set(entry) - SOURCE_KEYS
        if unknown:  # pragma: no cover — graph_from_data already refused it
            raise SourceError(f"source {label!r}: unknown keys {sorted(unknown)}")
        registry.entries[label] = entry

    return registry
