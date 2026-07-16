# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Cites in, an apysource sources file out — and proven so before it is written.

The last thing this module does on every run, in production and not only in a
test, is load its own output back through ``apysource.yaml_input.graph_from_data``
— the real loader, the one ``apysource check`` uses. If apysource would refuse
the file, apycite refuses to write it.

That guard is the reason apysource is a hard dependency rather than an optional
one. A guard that quietly does not run when the dependency is missing is exactly
the shape of thing this whole family of tools exists to prevent: the feature
appears to work, and what it does when its input is unusual is the bug.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import yaml
from apysource.sources import SourceSet
from apysource.yaml_input import graph_from_data

from apycite.config import LabelRule
from apycite.labels import disambiguate, label_for
from apycite.scan import Found, Site


class EmitError(Exception):
    """The output would not have been a citation file apysource accepts."""


def _dedupe(found: list[Found]) -> list[tuple[Any, list[Site]]]:
    """One claim, however many places make it — each of them recorded.

    Two rules quoting the same sentence of the same section is one fragment with
    two cite sites, not two fragments. Verifying the same quote twice would tell
    the reader nothing and cost a fetch.
    """
    claims: dict[Any, list[Site]] = defaultdict(list)
    order: dict[Any, Any] = {}

    for entry in found:
        key = entry.cite.key()
        if key not in order:
            order[key] = entry.cite
        claims[key].append(entry.site)

    return [(order[key], sorted(claims[key], key=lambda s: (s.file, s.line)))
            for key in order]


def build(
    found: list[Found], sources: SourceSet, rules: list[LabelRule],
) -> dict[str, Any]:
    """The sources document: the file's own entries, plus what the cites say."""
    claims = _dedupe(found)

    # Resolve first, so an unknown source name is reported before any labelling
    # work is done and the error is about the thing the author got wrong.
    #
    # apysource answers `None` rather than raising, and it is right to: it does
    # not know why we were asking. We do — a cite, at a file and a line — and a
    # refusal that does not say where the name was written is one the author has
    # to go and hunt for.
    resolved = []
    minted: dict[str, dict[str, Any]] = {}
    for cite, sites in claims:
        source = sources.resolve(cite.source)
        if source is None:
            where = sites[0]
            raise EmitError(
                f"{where.file}:{where.line}: unknown source {cite.source!r}: it "
                f"is not a label in your sources file, and no pattern mints it. "
                f"Add it to the sources file — or, if it is a whole family, add "
                f"a pattern there.",
            )
        label = source["label"]
        if label not in sources.entries:
            minted[label] = source
        resolved.append((cite, sites, label))

    # ── Labels, unique by construction ──
    #
    # Grouped by (source, base label) and numbered in an order that depends only
    # on what the citation *says*. Two cites in one file against one source get
    # `rule` and `rule (2)`, and which is which does not change when someone adds
    # a line above them.
    groups: dict[tuple[str, str], list[tuple[Any, list[Site]]]] = defaultdict(list)
    for cite, sites, source_label in resolved:
        base = label_for(sites[0].file, rules)
        groups[(source_label, base)].append((cite, sites))

    # Sorted, not discovery-ordered. `extract --frozen` compares the generated
    # file byte for byte, and a run whose output depended on which file the walk
    # reached first would report a diff on commits that changed no citation —
    # which teaches everyone to stop reading the diff.
    fragments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (source_label, base) in sorted(groups):
        members = groups[(source_label, base)]
        members.sort(key=lambda m: (
            m[0].targeting.get("section", ""),
            sorted(m[0].targeting.items()),
            m[0].quote,
        ))
        for index, (cite, sites) in enumerate(members):
            fragment: dict[str, Any] = {"label": disambiguate(base, index)}
            fragment.update(dict(sorted(cite.targeting.items())))
            fragment["snippet"] = cite.quote
            fragment["cited_by"] = [{"file": s.file, "line": s.line} for s in sites]
            fragments[source_label].append(fragment)

    # ── The document ──
    #
    # The sources file's entries keep their hand-written fragments. A selector-only
    # fragment, an image, a chapter tree — the things the grammar deliberately
    # cannot say — survive untouched, so its narrowness costs the author nothing.
    #
    # apysource hands these back with their URLs already filled in, so an entry
    # that named a family — `- label: RFC 9110`, and nothing else — is written out
    # expanded. What apycite generates is *evidence*, and evidence you need a
    # pattern table beside you to read is not evidence: a reviewer opening this
    # file sees the URL that was actually fetched.
    out: list[dict[str, Any]] = []
    for label, entry in sources.entries.items():
        if label not in fragments and not entry.get("fragments"):
            continue  # an entry nobody cites is not evidence of anything
        source = {k: v for k, v in entry.items() if k != "fragments"}
        source["fragments"] = list(entry.get("fragments", [])) + fragments.pop(label, [])
        out.append(source)

    # Whatever is left was minted from a pattern: it is cited, and no entry names it.
    for label in sorted(fragments):
        source = dict(minted[label])
        source.pop("fragments", None)
        source["fragments"] = fragments[label]
        out.append(source)

    return {"sources": out}


def render(document: dict[str, Any]) -> str:
    """The YAML, deterministically — and only after apysource has accepted it."""
    try:
        graph_from_data(document, origin="(apycite output)")
    except ValueError as exc:
        # If this fires, apycite has generated a file `apysource check` would
        # reject. The author cannot fix it — apycite must. Say so plainly rather
        # than writing the file and letting the next command take the blame.
        raise EmitError(
            f"apycite generated a citations file apysource will not load: {exc}\n"
            f"This is a bug in apycite, not in your cites.",
        ) from None

    return str(yaml.safe_dump(document, sort_keys=False, allow_unicode=True,
                              width=10_000))
