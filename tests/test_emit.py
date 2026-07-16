# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Cites -> an apysource sources file.

**P1**: whatever comes out of here, apysource loads. Asserted through apysource's
*real* loader, so it is simultaneously the version-skew tripwire and the guard on
the identity collision below.

**P5**: every targetter apysource has, reachable from a comment. That is the test
of whether "source-agnostic" is a claim or a decoration.
"""

import pytest
import yaml
from apysource.namespaces import OA, SV
from apysource.yaml_input import TARGETTING_KEYS, graph_from_data
from rdflib import RDF

from apycite.config import LabelRule, SpecPattern
from apycite.emit import EmitError, build, render
from apycite.grammar import Cite
from apycite.scan import Found, Site
from apycite.sources import Registry, SourceError

import re

RFC = SpecPattern(re.compile(r"^RFC (?P<n>\d+)$"),
                  {"url": "https://www.rfc-editor.org/rfc/rfc{n}.txt",
                   "type": "text/plain"})

RULES = [LabelRule("src/rules/*.rs", "{stem}"), LabelRule("**/*", "{path}")]


def _registry(entries=None):
    reg = Registry(patterns=[RFC])
    for entry in entries or []:
        reg.entries[entry["label"]] = entry
    return reg


def _found(*specs):
    return [Found(Cite(src, quote, targeting or {}), Site(file, line))
            for src, quote, targeting, file, line in specs]


# ── P1: what comes out, apysource loads ─────────────────────────────────

def test_the_output_loads_back_through_apysource():
    doc = build(_found(("RFC 9110", "the quote", {"section": "§ 7.2"},
                        "src/rules/host.rs", 29)), _registry(), RULES)

    graph = graph_from_data(doc)      # the real loader. If it raises, we shipped junk.
    assert list(graph.subjects(RDF.type, SV.Fragment))
    assert render(doc)


def test_render_refuses_to_write_a_file_apysource_would_reject():
    """The guard runs in production, not only in a test."""
    with pytest.raises(EmitError, match="apysource will not load"):
        render({"sources": [{"label": "x"}]})       # no url


# ── The collision that would have broken the first rule migrated ────────

def test_two_cites_in_one_file_to_one_source_do_not_collide():
    """The bug the spike could not have found, because its two cites were in
    different files.

    Both fragments would have been labelled `host` under `RFC 9110`, minting one
    URN between them. RDF being a set of triples, the two fragments become *one*,
    carrying both snippets — and apysource reads one of them arbitrarily. The
    worst outcome the family can produce: a citation checked twice, another not
    checked at all, and nothing saying so. apysource's `_Minter` refuses it; the
    point is never to hand it that file.
    """
    doc = build(_found(
        ("RFC 9110", "the first sentence", {"section": "§ 7.2"}, "src/rules/host.rs", 29),
        ("RFC 9110", "the second sentence", {"section": "§ 7.2"}, "src/rules/host.rs", 40),
    ), _registry(), RULES)

    labels = [f["label"] for f in doc["sources"][0]["fragments"]]
    assert labels == ["host", "host (2)"]
    graph_from_data(doc)      # and apysource accepts it


def test_the_numbering_does_not_move_when_the_code_does():
    """Labels are ordered by what the citation *says*, not where it is written.

    A label keyed on the line number would churn the generated YAML on every
    edit above a cite — a diff that says a citation changed when none did.
    """
    first = build(_found(
        ("RFC 9110", "aaa", {}, "src/rules/host.rs", 29),
        ("RFC 9110", "bbb", {}, "src/rules/host.rs", 40),
    ), _registry(), RULES)

    # The same two cites, one shifted a hundred lines down, and swapped in file order.
    second = build(_found(
        ("RFC 9110", "bbb", {}, "src/rules/host.rs", 140),
        ("RFC 9110", "aaa", {}, "src/rules/host.rs", 129),
    ), _registry(), RULES)

    def labelled(doc):
        return {f["label"]: f["snippet"] for f in doc["sources"][0]["fragments"]}

    assert labelled(first) == labelled(second)


def test_the_same_quote_in_two_files_is_one_fragment_with_two_sites():
    doc = build(_found(
        ("RFC 9110", "the quote", {"section": "§ 7.2"}, "src/rules/a.rs", 3),
        ("RFC 9110", "the quote", {"section": "§ 7.2"}, "src/rules/b.rs", 9),
    ), _registry(), RULES)

    fragments = doc["sources"][0]["fragments"]
    assert len(fragments) == 1
    assert fragments[0]["cited_by"] == [
        {"file": "src/rules/a.rs", "line": 3},
        {"file": "src/rules/b.rs", "line": 9},
    ]


# ── P5: every apysource targetter, from a comment ───────────────────────

@pytest.mark.parametrize(("targeting", "predicate"), [
    ({"section": "§ 7.2"}, SV.SectionSelector),
    ({"selector": "div.note"}, OA.CssSelector),
])
def test_a_targetter_survives_into_the_graph_as_a_selector(targeting, predicate):
    doc = build(_found(("RFC 9110", "q", targeting, "a.rs", 1)), _registry(), RULES)
    graph = graph_from_data(doc)

    assert list(graph.subjects(RDF.type, predicate)), f"{targeting} did not target"


@pytest.mark.parametrize(("targeting", "predicate"), [
    ({"lines": "120-130"}, SV.sourceLines),
    ({"location": "chapter-1"}, SV.sourceLocation),
])
def test_a_targetter_survives_into_the_graph_as_a_property(targeting, predicate):
    doc = build(_found(("RFC 9110", "q", targeting, "a.rs", 1)), _registry(), RULES)
    graph = graph_from_data(doc)

    assert list(graph.subject_objects(predicate)), f"{targeting} did not target"


def test_every_targetting_key_apysource_knows_can_be_emitted():
    """The agnostic claim, as a property rather than a promise.

    If apysource grows a seventh targetter and apycite cannot emit it, this fails
    — which is the point. The grammar reads its key list from apysource, so the
    only way to break this is to stop passing the keys through.
    """
    targeting = {key: "1" if key.startswith("page") else "x"
                 for key in TARGETTING_KEYS}
    doc = build(_found(("RFC 9110", "q", targeting, "a.rs", 1)), _registry(), RULES)

    fragment = doc["sources"][0]["fragments"][0]
    for key in TARGETTING_KEYS:
        assert key in fragment, f"apycite dropped {key} on the way out"
    graph_from_data(doc)


# ── The registry ────────────────────────────────────────────────────────

def test_a_registry_entry_wins_over_a_pattern():
    """So a project can pin one RFC to datatracker, or to the HTML rendition."""
    reg = _registry([{"label": "RFC 9110",
                      "url": "https://datatracker.ietf.org/doc/html/rfc9110",
                      "type": "text/html"}])
    doc = build(_found(("RFC 9110", "q", {}, "a.rs", 1)), reg, RULES)

    assert doc["sources"][0]["url"] == "https://datatracker.ietf.org/doc/html/rfc9110"


def test_hand_written_fragments_survive():
    """The things the grammar deliberately cannot say cost the author nothing:
    the escape hatch is the sources file they already have."""
    reg = _registry([{
        "label": "Fetch", "url": "https://fetch.spec.whatwg.org/", "type": "text/html",
        "fragments": [{"label": "by hand", "selector": "#origin-header"}],
    }])
    doc = build(_found(("Fetch", "a generated quote", {}, "a.rs", 1)), reg, RULES)

    labels = [f["label"] for f in doc["sources"][0]["fragments"]]
    assert labels == ["by hand", "a.rs"]
    graph_from_data(doc)


def test_an_uncited_registry_entry_is_not_emitted():
    """A source nobody cites is not evidence of anything, and fetching it in CI
    would be a request nobody asked for."""
    reg = _registry([{"label": "Unused", "url": "https://example.org/", "type": "text/html"}])
    doc = build(_found(("RFC 9110", "q", {}, "a.rs", 1)), reg, RULES)

    assert [s["label"] for s in doc["sources"]] == ["RFC 9110"]


def test_an_unknown_source_names_the_file_and_line():
    with pytest.raises(EmitError) as exc:
        build(_found(("Nonesuch", "q", {}, "src/rules/a.rs", 7)), _registry(), RULES)

    assert "src/rules/a.rs:7" in str(exc.value)
    assert "unknown source" in str(exc.value)


def test_a_pattern_mints_a_source_apysource_accepts():
    doc = build(_found(("RFC 9112", "q", {}, "a.rs", 1)), _registry(), RULES)
    source = doc["sources"][0]

    assert source["url"] == "https://www.rfc-editor.org/rfc/rfc9112.txt"
    assert source["type"] == "text/plain"
    graph_from_data(doc)


def test_the_registry_refuses_an_unresolvable_name():
    with pytest.raises(SourceError, match="unknown source"):
        _registry().resolve("Some Book Nobody Registered")


# ── Determinism ─────────────────────────────────────────────────────────

def test_the_same_cites_render_the_same_bytes():
    """`extract --frozen` compares bytes. A run that reorders its own output
    would report a diff on every commit and teach everyone to ignore it."""
    found = _found(
        ("RFC 9112", "b", {}, "src/rules/z.rs", 1),
        ("RFC 9110", "a", {"section": "§ 7.2"}, "src/rules/a.rs", 2),
        ("RFC 9110", "c", {}, "src/rules/m.rs", 3),
    )
    first = render(build(found, _registry(), RULES))
    second = render(build(list(reversed(found)), _registry(), RULES))

    # Bytes, not parsed YAML: `--frozen` diffs the file, and "same data, different
    # order" is still a diff someone has to read and dismiss.
    assert first == second
    assert yaml.safe_load(first)["sources"]
