# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The registry — which is an apysource sources file, and nothing new.

It is validated through apysource's *real* loader rather than by looking at the
keys ourselves. If the sources file is malformed, the author should hear it from
the tool that owns the format, now — not from a scan of 184 files that then hands
apysource a document it refuses.
"""

import re
from pathlib import Path

import pytest

from apycite.config import SpecPattern
from apycite.sources import SourceError, load_registry

RFC = SpecPattern(re.compile(r"^RFC (?P<n>\d+)$"),
                  {"url": "https://www.rfc-editor.org/rfc/rfc{n}.txt",
                   "type": "text/plain"})

GOOD = """
sources:
  - label: Fetch
    url: https://fetch.spec.whatwg.org/
    type: text/html
    fragments:
      - label: by hand
        selector: "#origin-header"
  - label: Moby-Dick
    url: https://www.gutenberg.org/ebooks/2701
    publisher: Harper & Brothers
"""


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_no_sources_file_is_fine(tmp_path):
    """A project citing only RFCs never needs one."""
    registry = load_registry(None, [RFC])

    assert registry.resolve("RFC 9110")["url"].endswith("rfc9110.txt")


def test_entries_load_with_their_hand_written_fragments(tmp_path):
    registry = load_registry(_write(tmp_path, GOOD), [RFC])

    assert set(registry.entries) == {"Fetch", "Moby-Dick"}
    assert registry.entries["Fetch"]["fragments"][0]["label"] == "by hand"
    # The whole source vocabulary, not a subset apycite decided to know about.
    assert registry.entries["Moby-Dick"]["publisher"] == "Harper & Brothers"


def test_a_malformed_sources_file_is_refused_by_apysource(tmp_path):
    """Not by us. It is apysource's format, and apysource says what it accepts.

    `snipet:` used to load without a murmur and verify nothing at all — which is
    the bug apysource's unknown-key rejection exists to prevent. apycite gets that
    for free by handing the file to the real loader, and would lose it the moment
    it started parsing the file itself.
    """
    path = _write(tmp_path, """
sources:
  - label: Fetch
    url: https://fetch.spec.whatwg.org/
    fragments:
      - label: f
        snipet: "a typo apysource refuses"
""")
    with pytest.raises(ValueError, match="unknown key"):
        load_registry(path, [RFC])


def test_a_missing_sources_file_is_an_error(tmp_path):
    with pytest.raises(SourceError, match="not found"):
        load_registry(tmp_path / "nope.yaml", [RFC])


def test_the_registry_beats_a_pattern(tmp_path):
    path = _write(tmp_path, """
sources:
  - label: RFC 9110
    url: https://datatracker.ietf.org/doc/html/rfc9110
    type: text/html
""")
    registry = load_registry(path, [RFC])

    assert registry.resolve("RFC 9110")["url"] == \
        "https://datatracker.ietf.org/doc/html/rfc9110"


def test_an_unresolvable_name_is_refused_not_guessed(tmp_path):
    registry = load_registry(_write(tmp_path, GOOD), [RFC])

    with pytest.raises(SourceError, match="unknown source 'Fetsh'"):
        registry.resolve("Fetsh")


def test_a_minted_source_is_remembered(tmp_path):
    """`used()` must find it after the fact, or the emitted file loses its URL."""
    registry = load_registry(None, [RFC])
    registry.resolve("RFC 9112")

    assert registry.used("RFC 9112")["label"] == "RFC 9112"
