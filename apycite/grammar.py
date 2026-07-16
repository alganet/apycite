# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

'''The cite grammar. It runs on payloads — comment syntax is already gone.

    cite(<source>[ § <section>][, <key>: <value>]…): "<quote>"

``<source>`` names a source. It does **not** name a URL, and this module has no
idea what an RFC is: resolution is ``sources.py``'s job, and it resolves through
an ordinary apysource sources file. A grammar that knew about rfc-editor.org
would be a lint-http script wearing a general-purpose hat.

``<key>: <value>`` takes **any apysource fragment key**, and the list is read
from apysource at import — not copied here. A key apysource ships tomorrow works
in a cite tomorrow, with no release of this package. That is the whole reason a
cite can reach a CSS selector, a page range, a line range or a repo location
without a grammar for each.

``§ <section>`` is sugar for ``, section: "§ …"``. One sugar. It exists because a
codebase citing an RFC writes hundreds of them, and it is the shape the original
prototype proved. Not two sugars; the general form is right there.

The quote is required. A snippet-less fragment is perfectly valid apysource — a
selector that merely resolves — and it is deliberately not expressible here. The
claim worth putting next to a line of code is *"the source says this"*, and a
citation that quotes nothing makes no claim anybody can check.
'''

from __future__ import annotations

import re
from dataclasses import dataclass, field

from apysource.yaml_input import TARGETTING_KEYS

#: Every string that parses as a cite, in every comment style, contains this.
#:
#: That is a theorem about the grammar below, and it is what licenses the only
#: safe skip in the whole tool: a file with no ``cite(`` in it provably has no
#: cites, whatever language it is written in. ``tests/test_grammar.py`` asserts
#: it over every style and placement, so loosening the grammar without moving
#: this fails the suite rather than quietly dropping citations.
#:
#: Deliberately *looser* than the grammar (``cite (`` matches, and the grammar
#: rejects it). A probe tighter than the thing it is probing for would have
#: holes; a looser one only raises false alarms, and false alarms are loud.
MARKER = re.compile(r"(?<![A-Za-z0-9_])cite\s*\(")

#: What a cite may target, and it is apysource's list, not ours.
KEYS = frozenset(TARGETTING_KEYS)

#: A comma ends a value only when something *shaped like* a key — a bare word and
#: a colon — follows it. Anything else is part of the value, which is what lets
#: ``selector: h1, h2`` (real CSS) parse in a grammar that has no escapes at all.
#:
#: Shaped like a key, deliberately, and not *a known key*. Splitting only on the
#: six keys apysource knows meant a typo — ``, sekshun: 7.2`` — matched nothing,
#: and was swallowed whole into the **source name**: the citation then named a
#: source called ``RFC 9110, sekshun: 7.2``, and failed as an unknown source
#: rather than a misspelt key. A key we do not recognise must be refused by name,
#: which means the split has to find it first.
_SPLIT = re.compile(r",\s*(?=[A-Za-z_][A-Za-z0-9_]*\s*:)")

_SECTION_SUGAR = "§"


class CiteError(Exception):
    """A line that meant to be a cite and is not.

    Never a warning, never a skip. A typo that silently drops a quote is a
    citation nobody checks, reported as a pass — so the typo stops the run.
    """


@dataclass(frozen=True)
class Cite:
    """One citation: what it names, how it targets, and what it claims."""

    source: str
    quote: str
    targeting: dict[str, str] = field(default_factory=dict)

    def key(self) -> tuple:
        """Identity for de-duplication: the same claim, however many places make it."""
        return (self.source, self.quote, tuple(sorted(self.targeting.items())))


def is_near_miss(payload: str) -> bool:
    """Does this payload announce itself as a cite?

    Anything that does so and then fails to parse is an error, not a comment.
    """
    return re.match(r"cite\b|cite\s*\(", payload.strip()) is not None


def parse(payload: str) -> Cite | None:
    """Parse one comment's contents. ``None`` if it is an ordinary comment.

    Raises ``CiteError`` if it looks like a cite and is not one.
    """
    text = payload.strip()
    if not is_near_miss(text):
        return None

    if not text.startswith("cite("):
        raise CiteError(
            f"expected 'cite(' — got {text[:40]!r}. The grammar is "
            f'cite(<source>): "<quote>"',
        )

    first_quote = text.find('"')
    if first_quote == -1:
        raise CiteError(
            "a cite must carry a quote — the sentence the source says. "
            'The grammar is cite(<source>): "<quote>"',
        )

    # The args end at the LAST ')' before the quote opens, so a value may itself
    # contain parens: `selector: div:nth-child(2)` is a real CSS selector.
    close = text.rfind(")", 0, first_quote)
    if close == -1:
        raise CiteError(
            "a cite's targetting arguments may not contain a double quote "
            "(no ')' before the quote opens). Use single quotes inside a CSS "
            "selector, or define the fragment in your sources file by hand.",
        )

    between = text[close + 1:first_quote]
    if between.strip() != ":":
        raise CiteError(
            f"expected ': ' between the arguments and the quote, got "
            f"{between!r}",
        )

    last_quote = text.rfind('"')
    if last_quote == first_quote:
        raise CiteError("the quote is never closed")

    # Everything after the closing quote must be nothing. A block comment's `*/`
    # is already gone — the lexer took it — so anything left here is real text
    # that the author meant something by, and we cannot know what.
    trailing = text[last_quote + 1:].strip()
    if trailing:
        raise CiteError(
            f"a cite is the only content of its comment; found {trailing!r} "
            f"after the quote",
        )

    quote = text[first_quote + 1:last_quote]
    if not quote.strip():
        raise CiteError("the quote is empty — a citation that quotes nothing "
                        "makes no claim anybody can check")

    source, targeting = _parse_args(text[len("cite("):close])
    return Cite(source=source, quote=quote, targeting=targeting)


def _parse_args(args: str) -> tuple[str, dict[str, str]]:
    """``RFC 9110 § 7.2, selector: h1, h2`` -> ``("RFC 9110", {...})``."""
    parts = _SPLIT.split(args)
    source_part, rest = parts[0], parts[1:]

    targeting: dict[str, str] = {}

    if _SECTION_SUGAR in source_part:
        source_part, section = source_part.split(_SECTION_SUGAR, 1)
        section = section.strip()
        if not section:
            raise CiteError("'§' with no section after it")
        # Stored with the § the author wrote, because that is what apysource's
        # section selectors match against in an RFC.
        targeting["section"] = f"{_SECTION_SUGAR} {section}"

    source = source_part.strip()
    if not source:
        raise CiteError("a cite must name a source")

    for part in rest:
        key, _, value = part.partition(":")
        key, value = key.strip(), value.strip()
        if key not in KEYS:
            raise CiteError(
                f"unknown targetting key {key!r}. apysource knows: "
                f"{', '.join(sorted(KEYS))}",
            )
        if not value:
            raise CiteError(f"{key!r} was given no value")
        if key in targeting:
            raise CiteError(
                f"{key!r} given twice"
                + (" (the '§' sugar is already a section)"
                   if key == "section" else ""),
            )
        targeting[key] = value

    return source, targeting


def render(cite: Cite) -> str:
    """A cite as its comment body. The inverse of ``parse``, and tested as one."""
    args = cite.source
    targeting = dict(cite.targeting)

    section = targeting.pop("section", "")
    if section.startswith(_SECTION_SUGAR):
        args += f" {_SECTION_SUGAR} {section[len(_SECTION_SUGAR):].strip()}"
    elif section:
        targeting["section"] = section

    for key in sorted(targeting):
        args += f", {key}: {targeting[key]}"

    return f'cite({args}): "{cite.quote}"'
