# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Comment styles, and turning a line of source into the text inside its comment.

The design is `reuse`'s (fsfe/reuse-tool, ``src/reuse/comment.py``): a class per
comment style, class variables for the markers, and two maps from filename and
extension. One thing is deliberately *not* reuse's, and it is the reason this
module exists rather than importing theirs — see ``get_comment_style``.

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

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Register on definition, so a style in a config file's dotted path works.

        reuse scans its own module globals for classes named ``*CommentStyle``.
        Registering here instead means a third-party style — one someone points
        ``[styles]`` at — is in the map the moment it is imported, with no
        import-order question to get wrong.
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


class PythonCommentStyle(CommentStyle):
    SHORTHAND = "python"
    SINGLE_LINE = "#"


class HashCommentStyle(CommentStyle):
    """The same marker, a different name — shell, YAML, TOML, Makefiles."""

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

    A miss returns ``None`` — and here is the one place this parts company with
    reuse, which returns ``None`` so the caller may **skip the file**. Skipping
    is exactly how a cite in an unrecognised language is dropped in silence while
    the run stays green. ``None`` here means *unknown*, and unknown is loud: see
    ``scan.py``, which will not call a tree clean that it could not read.
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


def _find_single(line: str, start: int, style: type[CommentStyle]) -> tuple[int, int]:
    """Where the next single-line marker is, and how long it is. ``(-1, 0)`` if none."""
    if style.SINGLE_LINE_REGEXP is not None:
        match = style.SINGLE_LINE_REGEXP.search(line, start)
        return (match.start(), len(match.group())) if match else (-1, 0)
    if style.SINGLE_LINE:
        pos = line.find(style.SINGLE_LINE, start)
        return (pos, len(style.SINGLE_LINE)) if pos != -1 else (-1, 0)
    return (-1, 0)


def lex_line(
    line: str, style: type[CommentStyle], in_block: bool,
) -> tuple[list[Payload], bool]:
    """Strip comment syntax from one line. Returns its payloads and the block state.

    A block comment is terminated at the **first** ``*/``, because that is where
    the compiler terminates it. Taking the last one would let a quote containing
    ``*/`` parse as though the language agreed — and it does not, so the file
    would mean one thing and we would have read another.
    """
    start, middle, end = style.MULTI_LINE
    payloads: list[Payload] = []
    i = 0

    while i <= len(line):
        if in_block:
            stop = line.find(end, i) if end else -1
            if stop == -1:
                payloads.append(_strip_middle(line[i:], i, middle))
                break
            payloads.append(_strip_middle(line[i:stop], i, middle))
            i, in_block = stop + len(end), False
            continue

        single_pos, single_len = _find_single(line, i, style)
        block_pos = line.find(start, i) if start else -1

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

    raise ValueError(f"unknown placement {placement!r}")


PLACEMENTS = ("single", "block", "block_middle")


def placements_for(style: type[CommentStyle]) -> tuple[str, ...]:
    """The ways this style can carry a one-line cite."""
    out = []
    if style.can_single():
        out.append("single")
    if style.can_block():
        out.extend(("block", "block_middle"))
    return tuple(out)
