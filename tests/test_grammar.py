# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The grammar, as properties.

These are not examples. They are the three claims the whole tool rests on:

* **P2** — a cite written in any style, in any placement, reads back as itself.
* **P2b** — where a language cannot carry a cite unambiguously, we refuse. The
  refusal is a promise, and it is asserted as one.
* **P3** — every cite contains the literal ``cite(``. This is the theorem that
  licenses skipping a file we have no comment style for, and it is the only
  reason such a skip is safe.

The renderer is written from the *language* (``comments.render``) and the parser
from the payload (``grammar.parse``), and they are separate on purpose. A
renderer derived from the parser would agree with it about anything at all,
including a mistake they shared — which is the failure this project keeps
finding, and it would make the round-trip property worth precisely nothing.
"""

import re

import pytest

from apycite import comments
from apycite.comments import NAME_STYLE_MAP, lex_line, placements_for
from apycite.grammar import KEYS, MARKER, Cite, CiteError, parse, render
from apycite.scan import Report, scan_file

STYLES = sorted(NAME_STYLE_MAP.values(), key=lambda s: s.SHORTHAND)

#: One extension per style, so a rendered cite can be written to a file the
#: scanner will resolve back to the very style it was written in.
EXT = {
    "c": ".rs", "hash": ".py", "html": ".md", "css": ".css",
    "lisp": ".el", "haskell": ".hs", "sql": ".sql", "lua": ".lua",
    "tex": ".tex", "php": ".php",
}

#: Quotes chosen to break things. Every one of them is a real hazard:
#: the embedded `"` is in RFC 9110 § 7.2 and already in lint-http's tree; the
#: `*/` and `-->` are the comment terminators; `#` and `//` are other languages'
#: markers; the ellipsis is apysource's deliberate-truncation mark.
QUOTES = [
    "A client MUST send a Host header field in all HTTP/1.1 request messages.",
    'A user agent MUST generate a Host header field unless it sends an ":authority" pseudo-header.',
    "Nothing in the present Charter shall impair the inherent right of self-defence",
    "text with a # hash and a // slash inside",
    "text mentioning § 7.2 by name",
    "Ünicöde, ellipsis…, and a trailing mark",
    "a quote that just ends...",
]

TARGETINGS = [
    {},
    {"section": "§ 7.2"},
    {"section": "Article 51"},
    {"selector": "#resolving-color-values"},
    {"selector": "div:nth-child(2)"},          # nested parens
    {"selector": "h1, h2"},                    # a comma inside a value
    {"lines": "120-130"},
    {"location": "chapter-1"},
    {"page_start": "40", "page_end": "42"},
]

CITES = [Cite(source=src, quote=q, targeting=t)
         for src, q, t in zip(
             ["RFC 9110", "UN Charter", "Moby-Dick", "CSS Color 4", "Fetch",
              "MDN Origin", "PEP 8", "Some Book", "RFC 9112"],
             QUOTES * 2, TARGETINGS)]


def _cases():
    for cite in CITES:
        for style in STYLES:
            for placement in placements_for(style):
                yield cite, style, placement


CASES = list(_cases())
IDS = [f"{s.SHORTHAND}-{p}-{c.source}" for c, s, p in CASES]


# ── P2: render -> scan identity ─────────────────────────────────────────

@pytest.mark.parametrize(("cite", "style", "placement"), CASES, ids=IDS)
def test_a_cite_reads_back_as_itself(cite, style, placement, tmp_path):
    """The round trip, over every style and every placement it supports.

    Driven through the real scanner rather than the lexer alone, because a quote
    that runs onto the next line is reassembled *there* — and a property that
    tested only the parts a single line goes through would say nothing about the
    case this exists for.

    A new comment style is tested the moment it registers, in every placement,
    wrapped and unwrapped. That is what makes an unbounded language table safe to
    grow.
    """
    path = tmp_path / f"x{EXT[style.SHORTHAND]}"
    path.write_text(comments.render(style, render(cite), placement) + "\n",
                    encoding="utf-8")

    report = Report()
    scan_file(path, path.name, report)

    assert not report.errors
    assert [f.cite for f in report.cites] == [cite]


@pytest.mark.parametrize("style", STYLES, ids=[s.SHORTHAND for s in STYLES])
def test_an_ordinary_comment_is_not_a_cite(style):
    """The lexer must not turn prose into a citation."""
    for placement in placements_for(style):
        if placement.endswith("_wrapped"):
            continue  # there is no quote in prose to wrap inside
        line = comments.render(style, "just an ordinary comment", placement)
        in_block = False
        for raw in line.split("\n"):
            payloads, in_block = lex_line(raw, style, in_block)
            assert all(parse(p.text) is None for p in payloads)


def test_code_before_the_comment_is_fine():
    """`x = 1;  // cite(...)` — the marker is found wherever it is on the line."""
    line = '    let host = 1; // cite(RFC 9110 § 7.2): "the quote"'
    payloads, _ = lex_line(line, NAME_STYLE_MAP["c"], False)
    cite = parse(payloads[0].text)
    assert cite == Cite("RFC 9110", "the quote", {"section": "§ 7.2"})


def test_code_after_a_block_comment_is_fine():
    """`/* cite(...) */ if (x) {` parses — the lexer ends the comment where C does."""
    line = '/* cite(RFC 9110 § 7.2): "the quote" */ if (host_count == 0) {'
    payloads, in_block = lex_line(line, NAME_STYLE_MAP["c"], False)
    assert not in_block
    assert parse(payloads[0].text) == Cite("RFC 9110", "the quote", {"section": "§ 7.2"})


def test_the_quote_may_contain_quotes():
    """RFC 9110 § 7.2 really does contain `":authority"`, and lint-http cites it.

    This is why the quote runs to the *last* `"` on the line rather than the
    second one — and why the lexer has to take `*/` off first.
    """
    body = 'cite(RFC 9110 § 7.2): "generate a Host header unless it sends ":authority" instead"'
    line = f"/* {body} */"
    payloads, _ = lex_line(line, NAME_STYLE_MAP["c"], False)
    cite = parse(payloads[0].text)
    assert cite.quote == 'generate a Host header unless it sends ":authority" instead'


# ── P2b: the refusals ───────────────────────────────────────────────────

def test_a_quote_containing_the_terminator_is_refused():
    """`/* cite(X): "a */ b" */` — C ends that comment at the first `*/`.

    The file means one thing and we would have read another. A wrong answer is
    worse than no answer, so this stops the run.
    """
    line = '/* cite(RFC 1): "a */ b" */'
    payloads, _ = lex_line(line, NAME_STYLE_MAP["c"], False)
    with pytest.raises(CiteError):
        parse(payloads[0].text)


def test_a_double_quote_in_the_arguments_is_refused():
    """There is no escaping in this grammar, and there is not going to be."""
    with pytest.raises(CiteError, match="may not contain a double quote"):
        parse('cite(Foo, selector: [x="1"]): "the quote"')


def test_trailing_text_after_the_quote_is_refused():
    with pytest.raises(CiteError, match="only content of its comment"):
        parse('cite(RFC 1): "the quote" and then some')


@pytest.mark.parametrize("payload", [
    'cite(RFC 1) "no colon"',
    'cite(RFC 1): no quote at all',
    'cite(RFC 1): "unterminated',
    'cite(): "nothing named"',
    'cite(RFC 1 §): "empty section"',
    'cite(RFC 1): ""',
    'cite(RFC 1, bogus: x): "unknown key"',
    'cite(RFC 1, section: ): "no value"',
    'cite(RFC 1 § 2, section: 3): "section twice"',
    'cite RFC 1: "no parens"',
])
def test_a_near_miss_is_an_error_not_a_shrug(payload):
    """Every one of these announces itself as a cite and is not one.

    Dropping any of them would leave a quote nobody checks and a run that passes.
    """
    with pytest.raises(CiteError):
        parse(payload)


def test_an_unknown_key_names_the_keys_that_exist():
    """The list comes from apysource, so it cannot go stale here."""
    with pytest.raises(CiteError) as exc:
        parse('cite(RFC 1, sekshun: 2): "q"')
    for key in KEYS:
        assert key in str(exc.value)


def test_a_misspelt_key_is_not_swallowed_into_the_source_name():
    """The bug these properties caught, kept caught.

    The argument splitter used to split only on the six keys apysource knows. A
    typo matched none of them, so `, sekshun: 7.2` was not an argument at all —
    it was swallowed into the **source name**, and the citation went on to name
    a source called `RFC 9110, sekshun: 7.2`. The run failed, so nothing was
    silently dropped; but it failed as an unknown *source*, which sent the
    author looking in the wrong file for a mistake they had made in this one.

    The splitter now finds anything *shaped like* a key, so an unrecognised one
    can be refused by name.
    """
    with pytest.raises(CiteError, match="unknown targetting key 'sekshun'"):
        parse('cite(RFC 9110, sekshun: 7.2): "q"')


def test_a_comma_inside_a_value_is_not_an_argument_boundary():
    """`h1, h2` is one CSS selector, and there is no escape character to help us."""
    cite = parse('cite(Fetch, selector: h1, h2): "q"')
    assert cite.source == "Fetch"
    assert cite.targeting == {"selector": "h1, h2"}


# ── P3: the marker theorem ──────────────────────────────────────────────

@pytest.mark.parametrize(("cite", "style", "placement"), CASES, ids=IDS)
def test_every_cite_contains_the_marker(cite, style, placement):
    """The theorem: a file with no `cite(` in it provably has no cites.

    This is the *only* thing that makes it safe to skip a file whose language we
    do not know. If the grammar is ever loosened without the marker moving with
    it, this fails — rather than a citation quietly going unread.
    """
    for line in comments.render(style, render(cite), placement).split("\n"):
        if "cite" in line:
            assert MARKER.search(line), f"the probe would not have found: {line!r}"


def test_the_probe_is_looser_than_the_grammar():
    """A probe tighter than what it probes for has holes. This one has margin."""
    assert MARKER.search("cite (RFC 1)")     # the grammar rejects the space
    assert MARKER.search("cite(")
    assert not MARKER.search("excite(")      # not a word we mean
    assert not MARKER.search("my_cite(")
    assert not MARKER.search("citation")


def test_the_marker_is_not_a_regex_accident():
    """Guard the one assumption every skip in this tool leans on."""
    assert MARKER.pattern == r"(?<![A-Za-z0-9_])cite\s*\("
    assert re.compile(MARKER.pattern)
