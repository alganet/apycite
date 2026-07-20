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

**The quote may run onto the following comment lines.** Normative sentences are
long, and a codebase with a line limit should not have to choose between the two.
The rule is the one a single line already obeys — *the quote ends on the line that
ends with a* ``"`` — so this needs no new syntax at all:

    // cite(RFC 9110 § 7.2): "A user agent MUST generate a Host header field in a
    // request unless it sends that information as an ":authority" pseudo-header field."

The lines are joined with a single space. apysource normalises whitespace on both
sides of the comparison, so how a quote is wrapped is not a fact about it. What is
*not* supported is elision: the quote is contiguous source text, and a trailing
``...`` is the only way to say "and it goes on" (apysource then prefix-matches).
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

#: Keys apycite consumes itself rather than passing to apysource. ``label`` names the
#: fragment in the generated store — so a cite can name itself instead of inheriting the
#: path of whichever file happens to sort first. It is deliberately *not* a targeting
#: key: apysource excludes ``label`` from ``TARGETTING_KEYS`` for the same reason it
#: excludes ``snippet`` and ``cited_by`` — those say what to *call* a fragment, or what it
#: *is*, not where in the document to look. So apycite owns it, and drops it before the
#: fragment reaches apysource.
OWN_KEYS = frozenset({"label"})

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
    #: An apycite-owned name for the fragment, or ``None`` to be named by path. Kept out
    #: of ``key()`` on purpose: two places citing the same sentence are still one claim
    #: whether or not one of them chose to name it.
    label: str | None = None

    def key(self) -> tuple:
        """Identity for de-duplication: the same claim, however many places make it."""
        return (self.source, self.quote, tuple(sorted(self.targeting.items())))


#: A payload that *announces itself* as a citation. Looser than `MARKER` on
#: purpose: `cite` followed by a word boundary counts, with no paren, so a
#: half-written citation is an error rather than a comment that reads oddly.
#: `scan.PROBE` has to cover this alternation as well as `MARKER`, which is why
#: it is the bare substring and not `cite(`.
NEAR_MISS = re.compile(r"cite\b|cite\s*\(")


def is_near_miss(payload: str) -> bool:
    """Does this payload announce itself as a cite?

    Anything that does so and then fails to parse is an error, not a comment.
    """
    return NEAR_MISS.match(payload.strip()) is not None


def quote_is_closed(text: str) -> bool:
    '''Has this text's quote actually ended?

    Two conditions, and the second one is not decoration.

    **It ends with a ``"``** — the rule a single line already obeys, where it
    reads as "nothing may follow the closing quote". Across several lines it reads
    as "keep going until a line ends with one", which is the same rule and needs no
    new syntax at all.

    **And it has an even number of them.** Quotation marks inside prose come in
    pairs — RFC 9110 says ``"Host"`` and ``":authority"``, never one half of
    either — so a cite whose quote has really closed has an even count: the two
    delimiters, plus pairs. An odd count means the mark we would have closed on is
    one of the *inner* ones, still open.

    Without the parity test, this is a **false pass**, which is the worst thing
    this tool can produce:

        // cite(RFC 1): "he said "hello"
        // and then left."

    The first line ends with a ``"``, so the quote closes early as
    ``he said "hello`` — and that string *is* in the source, being a prefix of the
    real sentence. So it verifies **green**, the second line is silently dropped,
    and the half of the sentence the author actually cared about is never checked
    by anything. Counting the marks catches it: three is odd, the quote is still
    open, and the reader keeps going and gets the sentence whole.

    The cost is that a quote containing a *lone* ``"`` — prose about the character
    itself — can no longer be cited. It could not honestly be cited before either:
    which mark closes ``"the " character"`` is not something to guess between. It
    is now refused instead of guessed, and the sources file is the escape hatch.
    '''
    return text.endswith('"') and text.count('"') % 2 == 0


def opens_unclosed_quote(payload: str) -> bool:
    """A cite whose quote begins on this line and does not end on it."""
    text = payload.strip()
    return text.startswith("cite(") and '"' in text and not quote_is_closed(text)


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

    source, targeting, label = _parse_args(text[len("cite("):close])
    return Cite(source=source, quote=quote, targeting=targeting, label=label)


def _parse_args(args: str) -> tuple[str, dict[str, str], str | None]:
    """``RFC 9110 § 7.2, selector: h1, h2`` -> ``("RFC 9110", {...}, None)``.

    Returns the source, the apysource targeting keys, and apycite's own ``label`` (or
    ``None``) — kept apart because the label must never reach apysource as a targeting
    instruction.
    """
    parts = _SPLIT.split(args)
    source_part, rest = parts[0], parts[1:]

    targeting: dict[str, str] = {}
    own: dict[str, str] = {}

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
        own_key = key in OWN_KEYS
        if not own_key and key not in KEYS:
            raise CiteError(
                f"unknown targetting key {key!r}. apysource knows: "
                f"{', '.join(sorted(KEYS))}; apycite also takes: "
                f"{', '.join(sorted(OWN_KEYS))}",
            )
        if not value:
            raise CiteError(f"{key!r} was given no value")
        dest = own if own_key else targeting
        if key in dest:
            raise CiteError(
                f"{key!r} given twice"
                + (" (the '§' sugar is already a section)"
                   if key == "section" else ""),
            )
        dest[key] = value

    return source, targeting, own.get("label")


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
    if cite.label is not None:
        args += f", label: {cite.label}"

    return f'cite({args}): "{cite.quote}"'
