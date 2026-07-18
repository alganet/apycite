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
from apysource.sources import sources_from_data
from apysource.yaml_input import TARGETTING_KEYS, graph_from_data
from rdflib import RDF

from apycite.config import LabelRule
from apycite.emit import EmitError, build, render
from apycite.grammar import Cite
from apycite.scan import Found, Site

RULES = [LabelRule("src/rules/*.rs", "{stem}"), LabelRule("**/*", "{path}")]


def _sources(entries=None, patterns=None):
    """A sources file, through apysource's *real* loader.

    Never a hand-rolled fake. What a source entry may say is apysource's to
    define, and a second copy of it here is how apycite ends up emitting a key
    the loader silently stopped accepting. `RFC NNNN` needs no pattern: apysource
    ships it, which is the whole point of this refactor.
    """
    data = {"sources": list(entries or [])}
    if patterns:
        data["patterns"] = patterns
    return sources_from_data(data, "(test)")


def _found(*specs):
    return [Found(Cite(src, quote, targeting or {}), Site(file, line))
            for src, quote, targeting, file, line in specs]


# ── P1: what comes out, apysource loads ─────────────────────────────────

def test_the_output_loads_back_through_apysource():
    doc = build(_found(("RFC 9110", "the quote", {"section": "§ 7.2"},
                        "src/rules/host.rs", 29)), _sources(), RULES)

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
    ), _sources(), RULES)

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
    ), _sources(), RULES)

    # The same two cites, one shifted a hundred lines down, and swapped in file order.
    second = build(_found(
        ("RFC 9110", "bbb", {}, "src/rules/host.rs", 140),
        ("RFC 9110", "aaa", {}, "src/rules/host.rs", 129),
    ), _sources(), RULES)

    def labelled(doc):
        return {f["label"]: f["snippet"] for f in doc["sources"][0]["fragments"]}

    assert labelled(first) == labelled(second)


def test_the_same_quote_in_two_files_is_one_fragment_with_two_sites():
    doc = build(_found(
        ("RFC 9110", "the quote", {"section": "§ 7.2"}, "src/rules/a.rs", 3),
        ("RFC 9110", "the quote", {"section": "§ 7.2"}, "src/rules/b.rs", 9),
    ), _sources(), RULES)

    fragments = doc["sources"][0]["fragments"]
    assert len(fragments) == 1
    assert fragments[0]["cited_by"] == [
        {"file": "src/rules/a.rs", "line": 3},
        {"file": "src/rules/b.rs", "line": 9},
    ]


# ── A per-cite label: a fragment can name itself ────────────────────────

def test_an_explicit_label_overrides_the_path_based_one():
    """A cite may name its fragment instead of inheriting the citing file's path —
    the fix for a helper's path standing in for the sentence it enforces."""
    doc = build([
        Found(
            Cite("RFC 9110", "the entity-tag equivalence sentence",
                 {"section": "§ 8.8.3"}, label="entity-tag equivalence"),
            Site("src/helpers/headers.rs", 1045),
        ),
    ], _sources(), RULES)

    labels = [f["label"] for f in doc["sources"][0]["fragments"]]
    assert labels == ["entity-tag equivalence"]
    graph_from_data(doc)      # apysource accepts the named fragment


def test_a_labelled_cite_is_left_out_of_sibling_numbering():
    """A named fragment does not consume a `(N)` slot, so its unlabelled siblings do
    not skip one — they stay `host`, `host (2)`."""
    doc = build([
        Found(Cite("RFC 9110", "aaa first", {}), Site("src/rules/host.rs", 10)),
        Found(Cite("RFC 9110", "bbb named", {}, label="the-key-sentence"),
              Site("src/rules/host.rs", 20)),
        Found(Cite("RFC 9110", "ccc third", {}), Site("src/rules/host.rs", 30)),
    ], _sources(), RULES)

    labels = sorted(f["label"] for f in doc["sources"][0]["fragments"])
    assert labels == ["host", "host (2)", "the-key-sentence"]
    graph_from_data(doc)


def test_a_shared_sentence_is_named_from_whichever_site_labels_it():
    """The same sentence in two files is one fragment; if either site names it, that
    name wins regardless of which the walk reaches first — here the labelled site is
    second, and its name still takes over the path-derived default."""
    doc = build([
        Found(Cite("RFC 9110", "one shared sentence", {"section": "§ 8.8.3"}),
              Site("src/helpers/headers.rs", 100)),
        Found(Cite("RFC 9110", "one shared sentence", {"section": "§ 8.8.3"},
                   label="etag equivalence"),
              Site("src/rules/etag.rs", 5)),
    ], _sources(), RULES)

    fragments = doc["sources"][0]["fragments"]
    assert len(fragments) == 1
    assert fragments[0]["label"] == "etag equivalence"
    assert len(fragments[0]["cited_by"]) == 2


def test_a_base_label_is_the_alphabetically_first_citing_path():
    """A shared, *unlabelled* fragment is named for whichever citing path sorts first —
    the behaviour a per-cite label exists to override, pinned here so the override has
    something to be measured against."""
    doc = build([
        Found(Cite("RFC 9110", "the shared claim", {"section": "§ 8.8.3"}),
              Site("src/rules/zzz.rs", 5)),
        Found(Cite("RFC 9110", "the shared claim", {"section": "§ 8.8.3"}),
              Site("src/helpers/headers.rs", 100)),
    ], _sources(), RULES)

    fragments = doc["sources"][0]["fragments"]
    assert len(fragments) == 1
    # helpers/headers.rs sorts before rules/zzz.rs, so its {path} label wins.
    assert fragments[0]["label"] == "src/helpers/headers.rs"


# ── P5: every apysource targetter, from a comment ───────────────────────

@pytest.mark.parametrize(("targeting", "predicate"), [
    ({"section": "§ 7.2"}, SV.SectionSelector),
    ({"selector": "div.note"}, OA.CssSelector),
])
def test_a_targetter_survives_into_the_graph_as_a_selector(targeting, predicate):
    doc = build(_found(("RFC 9110", "q", targeting, "a.rs", 1)), _sources(), RULES)
    graph = graph_from_data(doc)

    assert list(graph.subjects(RDF.type, predicate)), f"{targeting} did not target"


@pytest.mark.parametrize(("targeting", "predicate"), [
    ({"lines": "120-130"}, SV.sourceLines),
    ({"location": "chapter-1"}, SV.sourceLocation),
])
def test_a_targetter_survives_into_the_graph_as_a_property(targeting, predicate):
    doc = build(_found(("RFC 9110", "q", targeting, "a.rs", 1)), _sources(), RULES)
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
    doc = build(_found(("RFC 9110", "q", targeting, "a.rs", 1)), _sources(), RULES)

    fragment = doc["sources"][0]["fragments"][0]
    for key in TARGETTING_KEYS:
        assert key in fragment, f"apycite dropped {key} on the way out"
    graph_from_data(doc)


# ── The sources file ────────────────────────────────────────────────────

def test_an_entry_wins_over_a_pattern():
    """So a project can pin one RFC to datatracker, or to the HTML rendition."""
    doc = build(_found(("RFC 9110", "q", {}, "a.rs", 1)), _sources([
        {"label": "RFC 9110", "url": "https://datatracker.ietf.org/doc/html/rfc9110",
         "type": "text/html"},
    ]), RULES)

    assert doc["sources"][0]["url"] == "https://datatracker.ietf.org/doc/html/rfc9110"


def test_hand_written_fragments_survive():
    """The things the grammar deliberately cannot say cost the author nothing:
    the escape hatch is the sources file they already have."""
    doc = build(_found(("Fetch", "a generated quote", {}, "a.rs", 1)), _sources([{
        "label": "Fetch", "url": "https://fetch.spec.whatwg.org/", "type": "text/html",
        "fragments": [{"label": "by hand", "selector": "#origin-header"}],
    }]), RULES)

    labels = [f["label"] for f in doc["sources"][0]["fragments"]]
    assert labels == ["by hand", "a.rs"]
    graph_from_data(doc)


def test_an_uncited_entry_is_not_emitted():
    """A source nobody cites is not evidence of anything, and fetching it in CI
    would be a request nobody asked for."""
    doc = build(_found(("RFC 9110", "q", {}, "a.rs", 1)), _sources([
        {"label": "Unused", "url": "https://example.org/", "type": "text/html"},
    ]), RULES)

    assert [s["label"] for s in doc["sources"]] == ["RFC 9110"]


def test_an_unknown_source_names_the_file_and_line():
    """apysource answers `None`, because it does not know why we asked. We do."""
    with pytest.raises(EmitError) as exc:
        build(_found(("Nonesuch", "q", {}, "src/rules/a.rs", 7)), _sources(), RULES)

    assert "src/rules/a.rs:7" in str(exc.value)
    assert "unknown source" in str(exc.value)


def test_a_pattern_mints_a_source_apysource_accepts():
    """The pattern is apysource's now, and apycite never learns what an RFC is —
    it asks, and writes down the answer."""
    doc = build(_found(("RFC 9112", "q", {}, "a.rs", 1)), _sources(), RULES)
    source = doc["sources"][0]

    assert source["url"] == "https://www.rfc-editor.org/rfc/rfc9112.txt"
    assert source["type"] == "text/plain"
    graph_from_data(doc)


def test_a_named_entry_is_written_out_expanded():
    """The sources file may now say `- label: RFC 9110` and nothing else. What
    apycite *writes* still carries the full url.

    Not a stylistic choice. The generated file carries no `patterns:` block, so an
    entry emitted as a bare name would be a file apysource could not load — and
    `render` would refuse it as a bug in apycite, which it would be. It is also
    the right output: this file is evidence, and evidence you need a pattern table
    beside you to read is not evidence.
    """
    doc = build(_found(("RFC 9110", "a generated quote", {}, "a.rs", 1)), _sources([
        {"label": "RFC 9110",
         "fragments": [{"label": "by hand", "lines": "10-12"}]},
    ]), RULES)
    source = doc["sources"][0]

    assert source["url"] == "https://www.rfc-editor.org/rfc/rfc9110.txt"
    assert source["type"] == "text/plain"
    assert [f["label"] for f in source["fragments"]] == ["by hand", "a.rs"]
    graph_from_data(doc)          # the guard: no patterns block, and it still loads


def test_a_family_the_sources_file_declares_is_reachable_from_a_cite():
    """A `patterns:` block is apysource's key in apysource's file — but a cite
    naming a member of that family resolves through it, expanded, all the same."""
    doc = build(_found(("W3C css-color-4", "q", {}, "a.rs", 1)), _sources(patterns=[
        {"match": r"^W3C (?P<slug>[a-z0-9-]+)$",
         "source": {"url": "https://www.w3.org/TR/{slug}/", "type": "text/html"}},
    ]), RULES)

    assert doc["sources"][0]["url"] == "https://www.w3.org/TR/css-color-4/"
    graph_from_data(doc)


# ── Determinism ─────────────────────────────────────────────────────────

def test_the_same_cites_render_the_same_bytes():
    """`extract --frozen` compares bytes. A run that reorders its own output
    would report a diff on every commit and teach everyone to ignore it."""
    found = _found(
        ("RFC 9112", "b", {}, "src/rules/z.rs", 1),
        ("RFC 9110", "a", {"section": "§ 7.2"}, "src/rules/a.rs", 2),
        ("RFC 9110", "c", {}, "src/rules/m.rs", 3),
    )
    first = render(build(found, _sources(), RULES))
    second = render(build(list(reversed(found)), _sources(), RULES))

    # Bytes, not parsed YAML: `--frozen` diffs the file, and "same data, different
    # order" is still a diff someone has to read and dismiss.
    assert first == second
    assert yaml.safe_load(first)["sources"]
