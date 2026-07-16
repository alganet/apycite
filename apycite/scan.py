# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Walking a source tree, and refusing to call it clean when it was not read.

The one thing to understand about this module is what it does with a file whose
language it does not know.

`reuse` returns ``None`` for an unrecognised extension, and its callers skip the
file. For a licence header that is a nuisance. Here it would be a **silent
dropped citation**: a cite in a `.zig` file goes unread, the report says nothing,
CI stays green, and the tool has validated nothing and called it a pass. That is
the precise failure this project exists to prevent, and it would arrive wearing
the tool's own colours.

So the walk rests on a theorem — every cite contains the literal ``cite(``
(``grammar.MARKER``, asserted over every style and placement in the tests) — and
on one rule that follows from it:

    **Every file walked lands in exactly one bucket: parsed with a known comment
    style, proven free of cite-shaped text, unreadable and reported, or excluded
    by a glob someone wrote down. There is no fifth bucket, and "we did not
    recognise the extension" is not one of them.**

``sum(buckets) == files walked`` is a test.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from apycite.comments import CommentStyle, Payload, get_comment_style, lex_line
from apycite.grammar import MARKER, Cite, CiteError, parse


@dataclass(frozen=True)
class Site:
    """Where a cite was found. Becomes apysource's ``cited_by``."""

    file: str
    line: int


@dataclass(frozen=True)
class Found:
    """A cite, and the one place this scan saw it."""

    cite: Cite
    site: Site


@dataclass
class Report:
    """What the walk saw — every file of it, accounted for.

    The buckets are printed on every run. The difference between this and a
    silent skip is the entire feature: "I did not look here, and here is the
    list" is a report; leaving it out is a lie of omission.
    """

    cites: list[Found] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parsed: list[Path] = field(default_factory=list)
    no_style: list[Path] = field(default_factory=list)
    binary: list[Path] = field(default_factory=list)
    excluded: list[Path] = field(default_factory=list)

    @property
    def walked(self) -> int:
        return (len(self.parsed) + len(self.no_style)
                + len(self.binary) + len(self.excluded))

    def lines(self) -> list[str]:
        out = [f"  scanned     {len(self.parsed):>4} files"]
        if self.no_style:
            out.append(f"  no style    {len(self.no_style):>4} files  — probed, cite-free")
        if self.binary:
            out.append(f"  binary      {len(self.binary):>4} files  — not text, not read")
        if self.excluded:
            out.append(f"  excluded    {len(self.excluded):>4} paths  — by config")
        out.append(f"  cites       {len(self.cites):>4}")
        return out


def _decode(path: Path) -> str | None:
    """The file as text, or ``None`` if it is conclusively not text.

    A NUL byte means binary, and a binary file is skipped *and counted*. Anything
    else that will not decode is an error, not a skip: we could not read it, so
    we will not promise it holds no cites.
    """
    raw = path.read_bytes()
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8")


def _payload_cites(
    rel: str, lineno: int, raw: str, payloads: list[Payload],
    report: Report, marker_outside: str,
) -> None:
    """Parse one line's payloads, and account for every ``cite(`` on it."""
    #: Payloads that became something: a citation, or an error about one. A
    #: payload that parsed as an *ordinary comment* is not on this list, and that
    #: distinction is the whole rule below.
    accounted: list[Payload] = []

    for payload in payloads:
        try:
            cite = parse(payload.text)
        except CiteError as exc:
            report.errors.append(f"{rel}:{lineno}: {exc}")
            accounted.append(payload)
            continue
        if cite is not None:
            report.cites.append(Found(cite, Site(rel, lineno)))
            accounted.append(payload)

    # ── The reconciliation rule ──
    #
    # Every `cite(` on this line must have *become* something. Not "must be
    # inside a comment" — that was the first version of this rule, and it had
    # the exact hole it was written to close:
    #
    #     let s = "/*";               <- the lexer believes a block opened
    #     ...
    #     // cite(RFC 9110 § 7.2): "…"   <- now *block content*, payload is the
    #                                       whole line, `//` and all
    #
    # The payload does not begin with `cite`, so it parses as an ordinary
    # comment and returns None. The marker *was* inside a payload — so the old
    # rule was satisfied — and the citation vanished without a word. Which is
    # the one thing this tool must never do.
    #
    # Asking whether the marker was *accounted for* closes that, and subsumes
    # the string-literal case, and catches a third shape nobody had thought of:
    # `// TODO: cite(RFC 9110) here` — prose that is not a near-miss by the
    # grammar's reckoning (it does not start with `cite`) but is cite-shaped all
    # the same, and would have gone unread.
    for match in MARKER.finditer(raw):
        if any(p.contains(match.start()) for p in accounted):
            continue
        message = (
            f"{rel}:{lineno}: cite-shaped text that apycite did not read as a "
            f"citation. It is in a string literal, in ordinary prose, or the "
            f"comment structure above it is not what apycite thinks it is — "
            f"either way, this quote is not being checked. If it is deliberate, "
            f'set marker_outside_comments = "warn".'
        )
        # Refusing by default is affordable, and it is the safe way round: a
        # project with a real `cite()` function flips one config key and gets a
        # list instead of a failure. A project that has quietly lost a citation
        # gets no second chance to notice.
        if marker_outside == "warn":
            report.warnings.append(message)
        else:
            report.errors.append(message)


def scan_file(
    path: Path, rel: str, report: Report,
    overrides: dict[str, type[CommentStyle]] | None = None,
    marker_outside: str = "error",
) -> None:
    """Read one file into the report. Never raises for the file's own content."""
    try:
        text = _decode(path)
    except UnicodeDecodeError as exc:
        report.errors.append(
            f"{rel}: cannot be read as UTF-8 ({exc.reason}). apycite will not "
            f"promise a file holds no cites when it could not read it. Exclude "
            f"it explicitly if that is what you mean.",
        )
        return

    if text is None:
        report.binary.append(path)
        return

    match = get_comment_style(path, overrides)

    if match.style is None:
        # The theorem earns its keep here, and nowhere else. We have no comment
        # style, so we cannot parse — but we can still ask the one question that
        # needs no language at all, and the answer is checkable.
        for lineno, raw in enumerate(text.splitlines(), 1):
            if MARKER.search(raw):
                report.errors.append(
                    f"{rel}:{lineno}: cite-shaped text, but apycite has no "
                    f"comment style for this file ({match.why}). Register one "
                    f'under [styles] (e.g. "{path.suffix}" = "c"), or exclude '
                    f"the path. apycite will not call a tree clean that it "
                    f"could not read.",
                )
        report.no_style.append(path)
        return

    report.parsed.append(path)
    in_block = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        payloads, in_block = lex_line(raw, match.style, in_block)
        _payload_cites(rel, lineno, raw, payloads, report, marker_outside)


def _excluded(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in patterns)


def scan(
    root: Path, roots: list[str], exclude: list[str],
    overrides: dict[str, type[CommentStyle]] | None = None,
    marker_outside: str = "error",
) -> Report:
    """Walk the configured roots. Every file lands in exactly one bucket."""
    report = Report()

    for scan_root in roots:
        # Not resolved. Resolving would follow a symlinked source directory out
        # of the project and leave every path it found unrelatable to the root —
        # and the path relative to the root is what goes into `cited_by`. An
        # absolute path out of somebody's home directory is not a citation.
        base = root / scan_root
        for path in sorted(base.rglob("*")):
            if path.is_dir() or path.is_symlink():
                continue
            rel = str(path.relative_to(root))
            if _excluded(rel, exclude):
                report.excluded.append(path)
                continue
            scan_file(path, rel, report, overrides, marker_outside)

    return report
