# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Comment styles, and turning a line of source into the text inside its comment.

A class per comment style, class variables for the markers, and two maps — one
from filename, one from extension — resolved most-specific first. Adding a
language is a class and a map entry, and the property tests pick it up the moment
it registers.

The lexer here is the first of the two phases the grammar depends on. It strips
comment syntax **and nothing else**, so that ``grammar.py`` never sees a ``*/``.
That is not tidiness; it is what makes the quote rule work at all. The quote runs
to the *last* ``"`` on the line — a rule written for a line that ends at the
quote — and a trailing ``*/`` would eat it. Removing the terminator before the
quote rule runs restores it by construction, and no amount of regex would.

The lexer is naive about string literals: ``let s = "// not a comment";`` looks
like a comment to it. Every consequence of that is *loud* — a false payload
becomes a near-miss error, never a dropped cite — and the reconciliation rule in
``scan.py`` closes the one case where it could have been quiet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple


class MultiLineSegments(NamedTuple):
    """The three markers of a block comment: ``/*``, ``*``, ``*/``."""

    start: str
    middle: str
    end: str


#: Every registered style, by its shorthand — what a config file names it.
NAME_STYLE_MAP: dict[str, type["CommentStyle"]] = {}


class CommentStyle:
    """How one family of languages writes a comment."""

    #: The name a config file uses: ``".zig" = "c"``.
    SHORTHAND: str = ""
    #: The single-line marker, when the language has one.
    SINGLE_LINE: str = ""
    #: For languages where the marker varies: Rust's ``///`` and ``//!`` are
    #: comments too, and stripping a bare ``//`` from ``/// cite(…)`` would
    #: leave ``/ cite(…)`` — which parses as nothing, and drops the citation.
    SINGLE_LINE_REGEXP: re.Pattern[str] | None = None
    MULTI_LINE: MultiLineSegments = MultiLineSegments("", "", "")
    #: Delimiters of a string literal, inside which a comment marker is *text*.
    #: Only the double quote, deliberately: it means "string" in every language
    #: this tool knows, whereas the apostrophe does not — it is a lifetime in
    #: Rust (``&'static str``) and a plain word in prose, and treating those as
    #: strings would desynchronise the scan far more often than it would save it.
    STRING_DELIMITERS: tuple[str, ...] = ('"',)

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Register on definition, so a style named by dotted path in config works.

        A third-party style — one someone points ``[styles]`` at — is in the map
        the moment it is imported, with no import-order question to get wrong and
        no module to scan.
        """
        super().__init_subclass__(**kwargs)  # type: ignore[arg-type]
        name = cls.SHORTHAND or cls.__name__.removesuffix("CommentStyle").lower()
        NAME_STYLE_MAP[name] = cls

    @classmethod
    def can_single(cls) -> bool:
        return bool(cls.SINGLE_LINE or cls.SINGLE_LINE_REGEXP)

    @classmethod
    def can_block(cls) -> bool:
        return bool(cls.MULTI_LINE.start and cls.MULTI_LINE.end)


# ── The styles ──────────────────────────────────────────────────────────

class CCommentStyle(CommentStyle):
    """C and everything shaped like it — including Rust, whose doc comments vary."""

    SHORTHAND = "c"
    SINGLE_LINE = "//"
    SINGLE_LINE_REGEXP = re.compile(r"//+!?")
    MULTI_LINE = MultiLineSegments("/*", "*", "*/")


class HashCommentStyle(CommentStyle):
    """Python, shell, Ruby, YAML, TOML, Makefiles — everything that comments with ``#``."""

    SHORTHAND = "hash"
    SINGLE_LINE = "#"


class HtmlCommentStyle(CommentStyle):
    """HTML, XML, and Markdown. No single-line form at all."""

    SHORTHAND = "html"
    MULTI_LINE = MultiLineSegments("<!--", "", "-->")


class CssCommentStyle(CommentStyle):
    """Block only. CSS has no ``//``, and pretending it does is a false positive."""

    SHORTHAND = "css"
    MULTI_LINE = MultiLineSegments("/*", "*", "*/")


class LispCommentStyle(CommentStyle):
    SHORTHAND = "lisp"
    SINGLE_LINE = ";"
    SINGLE_LINE_REGEXP = re.compile(r";+")


class HaskellCommentStyle(CommentStyle):
    SHORTHAND = "haskell"
    SINGLE_LINE = "--"
    MULTI_LINE = MultiLineSegments("{-", "", "-}")


class SqlCommentStyle(CommentStyle):
    SHORTHAND = "sql"
    SINGLE_LINE = "--"
    MULTI_LINE = MultiLineSegments("/*", "*", "*/")


class LuaCommentStyle(CommentStyle):
    SHORTHAND = "lua"
    SINGLE_LINE = "--"
    MULTI_LINE = MultiLineSegments("--[[", "", "]]")


class TexCommentStyle(CommentStyle):
    SHORTHAND = "tex"
    SINGLE_LINE = "%"
    SINGLE_LINE_REGEXP = re.compile(r"%+")


class PhpCommentStyle(CommentStyle):
    SHORTHAND = "php"
    SINGLE_LINE = "//"
    SINGLE_LINE_REGEXP = re.compile(r"//+|#")
    MULTI_LINE = MultiLineSegments("/*", "*", "*/")


# ── The maps ────────────────────────────────────────────────────────────

EXTENSION_STYLE_MAP: dict[str, type[CommentStyle]] = {
    ext: CCommentStyle for ext in (
        ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".rs", ".go", ".java",
        ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".kt", ".kts", ".swift",
        ".zig", ".scala", ".cs", ".dart", ".proto", ".m", ".mm", ".v",
        ".scss", ".sass", ".less", ".d.ts",
    )
} | {
    ext: HashCommentStyle for ext in (
        ".py", ".pyi", ".sh", ".bash", ".zsh", ".fish", ".rb", ".pl", ".pm",
        ".yaml", ".yml", ".toml", ".cfg", ".conf", ".ini", ".tf", ".r",
        ".jl", ".nix", ".ex", ".exs", ".cmake", ".gradle", ".env",
    )
} | {
    ext: HtmlCommentStyle for ext in (
        ".html", ".htm", ".xhtml", ".xml", ".svg", ".md", ".markdown",
        ".vue", ".xsl", ".rss",
    )
} | {
    ".css": CssCommentStyle,
    ".lisp": LispCommentStyle, ".el": LispCommentStyle, ".clj": LispCommentStyle,
    ".cljs": LispCommentStyle, ".scm": LispCommentStyle, ".rkt": LispCommentStyle,
    ".hs": HaskellCommentStyle, ".lhs": HaskellCommentStyle,
    ".sql": SqlCommentStyle,
    ".lua": LuaCommentStyle,
    ".tex": TexCommentStyle, ".sty": TexCommentStyle, ".cls": TexCommentStyle,
    ".bib": TexCommentStyle, ".erl": TexCommentStyle,
    ".php": PhpCommentStyle, ".php5": PhpCommentStyle, ".phtml": PhpCommentStyle,
}

FILENAME_STYLE_MAP: dict[str, type[CommentStyle]] = {
    name: HashCommentStyle for name in (
        "makefile", "gnumakefile", "dockerfile", "containerfile", "justfile",
        "rakefile", "gemfile", "vagrantfile", "cmakelists.txt", "brewfile",
        ".gitignore", ".gitattributes", ".editorconfig", ".dockerignore",
    )
}

# Names a config file may reasonably reach for. There was a `PythonCommentStyle`
# here, identical to `HashCommentStyle` in every respect and reachable by no
# extension at all — two classes that could never disagree, one of which nothing
# used. An alias says the same thing and cannot drift from itself.
NAME_STYLE_MAP["python"] = HashCommentStyle
NAME_STYLE_MAP["shell"] = HashCommentStyle


@dataclass(frozen=True)
class StyleMatch:
    """A resolved style, and *why* — so a refusal can be acted on.

    ``apycite styles --path x.foo`` prints the rule that fired. Telling someone
    "no comment style for .foo" without telling them how the lookup works leaves
    them guessing at a config key.
    """

    style: type[CommentStyle] | None
    why: str


def get_comment_style(
    path: Path,
    overrides: dict[str, type[CommentStyle]] | None = None,
) -> StyleMatch:
    """Which comment style a file is written in, and how we decided.

    Config overrides come **first**: a project can correct us without waiting
    for a release. Then exact filename, then the combined suffixes (``.blade.php``,
    ``.d.ts``), then the final suffix.

    A miss returns ``None``, and ``None`` means **unknown** — never *skip*.
    Skipping is how a cite in an unrecognised language is dropped in silence while
    the run stays green, so unknown is loud: see ``scan.py``, which will not call a
    tree clean that it could not read.
    """
    overrides = overrides or {}
    name = path.name.lower()
    combined = "".join(path.suffixes).lower()
    final = path.suffix.lower()

    for key, label in ((name, "filename"), (combined, "combined suffix"),
                       (final, "suffix")):
        if key and key in overrides:
            return StyleMatch(overrides[key], f"config override, by {label} {key!r}")

    if name in FILENAME_STYLE_MAP:
        return StyleMatch(FILENAME_STYLE_MAP[name], f"filename {name!r}")
    if combined and combined != final and combined in EXTENSION_STYLE_MAP:
        return StyleMatch(EXTENSION_STYLE_MAP[combined], f"combined suffix {combined!r}")
    if final and final in EXTENSION_STYLE_MAP:
        return StyleMatch(EXTENSION_STYLE_MAP[final], f"suffix {final!r}")

    return StyleMatch(None, f"no rule matched {path.name!r}")


# ── Phase one: the lexer ────────────────────────────────────────────────

@dataclass(frozen=True)
class Payload:
    """The text inside a comment, and where it sits on the raw line.

    ``col`` is what lets ``scan.py`` ask the question that closes the silent-drop
    hole: *was this ``cite(`` actually inside a comment, or in a string literal
    the lexer walked straight past?*
    """

    text: str
    col: int

    def contains(self, pos: int) -> bool:
        return self.col <= pos < self.col + len(self.text)


def _string_spans(line: str, delimiters: tuple[str, ...]) -> list[tuple[int, int]]:
    """The half-open ranges of ``line`` that are inside a string literal.

    A comment marker in one of these is not a marker. HTTP is what taught this:
    a media range is written ``*/*``, so ``"image/*"`` in ordinary Rust source
    contains the three characters that open a block comment, and a lexer reading
    them as one swallows every citation in the rest of the file.

    An unterminated quote runs to the end of the line rather than being ignored.
    That is the conservative direction: a stray marker inside the run goes unread
    and the *reconciliation* rule in ``scan`` reports it, which is a complaint. The
    other way round invents a comment out of code, which is a silent misreading.
    """
    spans: list[tuple[int, int]] = []
    i, n = 0, len(line)
    while i < n:
        if line[i] not in delimiters:
            i += 1
            continue
        quote, j = line[i], i + 1
        while j < n:
            if line[j] == "\\":
                j += 2
                continue
            if line[j] == quote:
                break
            j += 1
        spans.append((i, min(j + 1, n)))
        i = j + 1
    return spans


def _outside(pos: int, spans: list[tuple[int, int]]) -> bool:
    """Whether ``pos`` is code rather than the inside of a string literal."""
    return not any(lo <= pos < hi for lo, hi in spans)


def _find_single(
    line: str, start: int, style: type[CommentStyle], spans: list[tuple[int, int]],
) -> tuple[int, int]:
    """Where the next single-line marker is, and how long it is. ``(-1, 0)`` if none."""
    if style.SINGLE_LINE_REGEXP is not None:
        for match in style.SINGLE_LINE_REGEXP.finditer(line, start):
            if _outside(match.start(), spans):
                return match.start(), len(match.group())
        return -1, 0
    if style.SINGLE_LINE:
        pos = line.find(style.SINGLE_LINE, start)
        while pos != -1 and not _outside(pos, spans):
            pos = line.find(style.SINGLE_LINE, pos + 1)
        return (pos, len(style.SINGLE_LINE)) if pos != -1 else (-1, 0)
    return -1, 0


def _find_block(
    line: str, start: int, opener: str, spans: list[tuple[int, int]],
) -> int:
    """Where the next block-comment opener is, skipping string literals."""
    if not opener:
        return -1
    pos = line.find(opener, start)
    while pos != -1 and not _outside(pos, spans):
        pos = line.find(opener, pos + 1)
    return pos


def lex_line(
    line: str, style: type[CommentStyle], in_block: bool,
) -> tuple[list[Payload], bool]:
    """Strip comment syntax from one line. Returns its payloads and the block state.

    A block comment is terminated at the **first** ``*/``, because that is where
    the compiler terminates it. Taking the last one would let a quote containing
    ``*/`` parse as though the language agreed — and it does not, so the file
    would mean one thing and we would have read another.

    A marker inside a string literal is not a marker. Only *outside* a block: once
    a block is open, the language is no longer reading strings either, so neither
    are we.
    """
    start, middle, end = style.MULTI_LINE
    payloads: list[Payload] = []
    i = 0
    spans = _string_spans(line, style.STRING_DELIMITERS)

    while i <= len(line):
        if in_block:
            stop = line.find(end, i) if end else -1
            if stop == -1:
                payloads.append(_strip_middle(line[i:], i, middle))
                break
            payloads.append(_strip_middle(line[i:stop], i, middle))
            i, in_block = stop + len(end), False
            continue

        single_pos, single_len = _find_single(line, i, style, spans)
        block_pos = _find_block(line, i, start, spans)

        if single_pos == -1 and block_pos == -1:
            break

        # Whichever opens first wins. A `//` after a `/*` on the same line is
        # inside the block, not a comment of its own.
        if block_pos == -1 or (single_pos != -1 and single_pos < block_pos):
            col = single_pos + single_len
            payloads.append(Payload(line[col:], col))
            break

        i, in_block = block_pos + len(start), True

    return payloads, in_block


def _strip_middle(text: str, col: int, middle: str) -> Payload:
    """Drop the ``*`` that continues a block comment onto the next line."""
    if not middle:
        return Payload(text, col)
    lead = len(text) - len(text.lstrip())
    if text[lead:].startswith(middle):
        cut = lead + len(middle)
        return Payload(text[cut:], col + cut)
    return Payload(text, col)


# ── Rendering, for the property tests ───────────────────────────────────

def wrap_point(body: str) -> int:
    """Where to break a rendered cite body across lines. ``-1`` if nowhere.

    **Deliberately adversarial**: it breaks immediately after an embedded closing
    quotation mark whenever the sentence has one. That is the placement that used
    to end the quote early — ``…sends an ":authority"`` / ``pseudo-header field."``
    — and produce a truncated quote that *still verified green*, being a prefix of
    the real sentence.

    Choosing the safe break here would have made the round-trip property agree with
    a bug rather than catch it. ``grammar.quote_is_closed`` counts the marks, and
    this is what proves it: every style, every quote with an embedded pair, broken
    at the worst possible place.
    """
    opening = body.find('"')
    if opening == -1:
        return -1

    hostile = body.find('" ', opening + 1)
    if hostile != -1:
        return hostile + 1

    middle = (opening + len(body)) // 2
    cut = body.find(" ", middle)
    return cut if cut > opening else body.find(" ", opening + 1)


def render(style: type[CommentStyle], body: str, placement: str = "single") -> str:
    """Write ``body`` as a comment, the way the *language* would.

    Written from the language, deliberately independent of the lexer. A renderer
    derived from the parser would agree with it about anything, including a
    shared mistake — which is the failure this project keeps finding, and the
    reason the round-trip property is worth anything at all.
    """
    start, middle, end = style.MULTI_LINE

    if placement == "single":
        if not style.can_single():
            raise ValueError(f"{style.SHORTHAND} has no single-line comment")
        return f"{style.SINGLE_LINE} {body}"

    if placement == "block":
        if not style.can_block():
            raise ValueError(f"{style.SHORTHAND} has no block comment")
        return f"{start} {body} {end}"

    if placement == "block_middle":
        if not style.can_block():
            raise ValueError(f"{style.SHORTHAND} has no block comment")
        cont = f"{middle} " if middle else ""
        return f"{start}\n {cont}{body}\n {end}"

    # The quote broken across two comment lines. Long normative sentences are the
    # reason this exists, and they are exactly the ones a round-trip test must
    # cover — a quote that survives being written on one line proves nothing about
    # a quote that was written on two.
    cut = wrap_point(body)
    if cut == -1:
        raise ValueError("this body cannot be wrapped")
    head, tail = body[:cut], body[cut + 1:]

    if placement == "single_wrapped":
        if not style.can_single():
            raise ValueError(f"{style.SHORTHAND} has no single-line comment")
        return f"{style.SINGLE_LINE} {head}\n{style.SINGLE_LINE} {tail}"

    if placement == "block_wrapped":
        if not style.can_block():
            raise ValueError(f"{style.SHORTHAND} has no block comment")
        cont = f"{middle} " if middle else ""
        return f"{start} {head}\n {cont}{tail} {end}"

    raise ValueError(f"unknown placement {placement!r}")


PLACEMENTS = ("single", "block", "block_middle", "single_wrapped", "block_wrapped")


def placements_for(style: type[CommentStyle]) -> tuple[str, ...]:
    """The ways this style can carry a cite."""
    out: list[str] = []
    if style.can_single():
        out.extend(("single", "single_wrapped"))
    if style.can_block():
        out.extend(("block", "block_middle", "block_wrapped"))
    return tuple(out)
