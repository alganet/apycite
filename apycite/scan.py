# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Walking a source tree, and refusing to call it clean when it was not read.

The one thing to understand about this module is what it does with a file whose
language it does not know.

The obvious thing to do — no comment style, so skip it — is a **silently dropped
citation**: a cite in a `.zig` file goes unread, the report says nothing, CI stays
green, and the tool has validated nothing and called it a pass. That is the
precise failure this project exists to prevent, and it would arrive wearing the
tool's own colours.

So the walk rests on a theorem — every cite contains the literal ``cite(``
(``grammar.MARKER``, asserted over every style and placement in the tests) — and
on one rule that follows from it.

Two things are skipped on that authority, and they are not the same skip. A file
whose *language* is unknown is skipped when it has no ``MARKER``, which is what
the theorem says outright. A file whose language is known skips only its *lexer*,
and needs a wider licence: this module reports near-misses too — text that
announces itself as a citation and then fails to parse — which ``MARKER`` does
not match. ``PROBE`` below is that wider licence, and why it is the bare
substring rather than the marker.

The rule itself:

    **Every file walked lands in exactly one bucket: parsed with a known comment
    style, proven free of cite-shaped text, unreadable and reported, or excluded
    by a glob someone wrote down. There is no fifth bucket, and "we did not
    recognise the extension" is not one of them.**

``sum(buckets) == paths walked`` is a test.

One nuance in ``excluded``: a glob that excludes everything under a directory is
answered by not entering the directory, and the *directory* is what gets counted.
So that bucket holds paths rather than files, and a pruned directory contributes
one entry however many files are inside it. Enumerating them would mean walking
the very tree the glob said to skip, which is the cost the glob exists to avoid —
and we did not look inside, so claiming a count would be inventing one.
"""

from __future__ import annotations

import fnmatch
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from apycite.comments import CommentStyle, Payload, get_comment_style, lex_line
from apycite.grammar import (
    MARKER,
    Cite,
    CiteError,
    is_near_miss,
    opens_unclosed_quote,
    parse,
    quote_is_closed,
)


#: The four characters every citation — and every complaint about one — must
#: contain. A file without them is not read past its decode.
#:
#: It is deliberately looser than ``MARKER``, and the difference is the whole
#: point. ``MARKER`` covers every *valid* cite, which is what licenses skipping
#: a file whose language we do not know. But this module also reports things
#: that are **not** valid cites: ``is_near_miss`` matches ``cite\b`` as well as
#: ``cite\s*\(``, so ``// cite this properly please`` announces itself, fails to
#: parse, and is an error. ``MARKER`` does not see it.
#:
#: Guarding the lexer on ``MARKER`` would therefore turn that reported error into
#: silence — a dropped diagnostic, wearing this tool's own colours. So the guard
#: has to be a superset of ``MARKER`` *and* ``is_near_miss``, and since both begin
#: with these four characters, the bare substring is exactly that union — and is
#: a plain C-level ``str.__contains__`` besides, cheaper than either regex.
#:
#: Being loose costs almost nothing: on a real tree ``cite(`` appears in 2 files
#: per 3000 and ``cite`` in 69, so the safe probe still skips ~97% of the lexing.
PROBE = "cite"


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

    ``excluded`` counts **paths**, not files: a directory pruned by a glob is one
    entry, because the walk never entered it and so cannot say what was inside.
    ``walked`` is the sum of the buckets, and inherits that reading.
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


#: One line, as the lexer left it: its number, its raw text, and its payloads.
Lexed = tuple[int, str, list[Payload]]


def _continue_quote(
    lexed: list[Lexed], start: int, opening: Payload, rel: str,
) -> tuple[str, int, list[Payload]]:
    """Read a quote that runs past the end of its line.

    Returns the joined payload text, the index of the last line consumed, and
    every payload that went into it — which the reconciliation rule needs, or the
    continuation lines would each look like an unread ``cite(``.

    **The guard that matters is the one on line 4 of the loop.** An unterminated
    quote reads forward, and what it reads forward over might be another cite:

        // cite(RFC 9110 § 7.2): "a quote somebody forgot to close
        // cite(RFC 9112 § 3.2): "and the one below it, swallowed whole"

    Without the guard the second line is joined into the first quote, and the
    second citation is *gone* — not wrong, not reported: gone, from a run that
    exits 0. It is the same shape as every other bug this scanner has had, and it
    arrives the moment quotes are allowed to span lines. So a continuation line
    that is itself cite-shaped stops the run, and says which quote ate which.
    """
    text = opening.text.strip()
    used = [opening]

    for i in range(start + 1, len(lexed)):
        lineno, _, payloads = lexed[i]

        if len(payloads) != 1:
            break  # code, a blank line, or something too odd to read forward over

        payload = payloads[0]
        if MARKER.search(payload.text):
            raise CiteError(
                f"the quote opened on line {lexed[start][0]} is never closed, and "
                f"line {lineno} is itself a cite — it would have been swallowed "
                f"into that quote and never checked. Close the quote above.",
            )

        text = f"{text} {payload.text.strip()}"
        used.append(payload)

        if quote_is_closed(text):
            return text, i, used

    # Nothing closed it. Two different mistakes end up here, and they want
    # different words: a quote nobody terminated, and a quote whose quotation
    # marks do not pair up. Only the second needs explaining.
    marks = text.count('"')
    if marks >= 3 and marks % 2:
        raise CiteError(
            "the quote's quotation marks do not pair up, so it never closes. "
            "Marks inside a quoted sentence come in pairs; a lone one cannot be "
            "told from the mark that ends the quote, and this grammar has no "
            "escapes. Cite a sentence without it, or write the fragment into "
            "your sources file by hand.",
        )

    # Hand the *opening* line back to the grammar, which knows exactly what is
    # wrong with it — an unterminated quote, or text after the closing one — and
    # says so far better than this function could.
    raise _reraise(opening.text)


def _reraise(payload: str) -> CiteError:
    """The grammar's own diagnosis of a line that would not close."""
    try:
        parse(payload)
    except CiteError as exc:
        return exc
    return CiteError("the quote is never closed")


def _payload_cites(
    rel: str, lineno: int, raw: str, payloads: list[Payload],
    report: Report, marker_outside: str, accounted: list[Payload],
) -> None:
    """Account for every ``cite(`` on one line.

    ``accounted`` is the payloads that *became* something — a citation, or an
    error about one. A payload that parsed as an ordinary comment is not on it,
    and that distinction is the whole rule below. It is passed in because a quote
    that spans lines accounts for payloads this call never saw.
    """
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

    # Nothing below this line can find anything in a file that does not contain
    # the four characters `cite`, so most of a real tree stops here — and the
    # decode above still happened, so a file we could not read is still an error
    # rather than a quiet pass. See PROBE.
    has_probe = PROBE in text

    match = get_comment_style(path, overrides)

    if match.style is None:
        # The theorem earns its keep here. We have no comment style, so we
        # cannot parse — but we can still ask the one question that needs no
        # language at all, and the answer is checkable.
        lines = enumerate(text.splitlines(), 1) if has_probe else ()
        for lineno, raw in lines:
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

    # Read, and provably clean. Everything below would run and find nothing:
    # no payload can be a near-miss, so `accounted` stays empty, and
    # `_payload_cites` has no marker to reconcile. Same report, none of the work.
    if not has_probe:
        return

    # Lexed in full before anything is parsed, because a quote may run onto the
    # lines below it and the reader has to be able to look ahead.
    lexed: list[Lexed] = []
    in_block = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        payloads, in_block = lex_line(raw, match.style, in_block)
        lexed.append((lineno, raw, payloads))

    #: lineno -> the payloads on it that became a citation, or an error about one.
    #: A quote spanning three lines accounts for payloads on all three.
    accounted: dict[int, list[Payload]] = defaultdict(list)
    #: The last line a multi-line quote consumed, so its lines are not re-read as
    #: comments of their own.
    consumed_through = -1

    for i, (lineno, _, payloads) in enumerate(lexed):
        if i <= consumed_through:
            continue

        for payload in payloads:
            if not is_near_miss(payload.text):
                continue

            try:
                if opens_unclosed_quote(payload.text):
                    joined, last, used = _continue_quote(lexed, i, payload, rel)
                    cite = parse(joined)
                    consumed_through = last
                    for line_used, p in zip(
                            [n for n, _, _ in lexed[i:last + 1]], used):
                        accounted[line_used].append(p)
                else:
                    cite = parse(payload.text)
                    accounted[lineno].append(payload)
            except CiteError as exc:
                report.errors.append(f"{rel}:{lineno}: {exc}")
                accounted[lineno].append(payload)
                continue

            if cite is not None:
                report.cites.append(Found(cite, Site(rel, lineno)))

    for lineno, raw, payloads in lexed:
        _payload_cites(rel, lineno, raw, payloads, report, marker_outside,
                       accounted[lineno])


def _excluded(rel: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        # `**/` means "at any depth, including none". fnmatch has no path
        # semantics to say that: it compiles the prefix to a regex demanding a
        # separator before the name, so `**/.git/**` matched a *nested* .git and
        # never the one at the root — which is the only .git a repository has.
        # Every shipped default (.git, target, node_modules, dist, build) lives
        # at the root, so every one of them was inert where it was needed.
        if pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]):
            return True
    return False


def _prune_prefixes(patterns: list[str]) -> list[str]:
    """The directory prefixes a pattern set says to not descend into at all.

    Only a pattern that excludes *everything* beneath a directory licenses
    skipping that directory, and that is what a trailing ``/*`` or ``/**`` says.
    Both forms behave identically here, because fnmatch has no path semantics:
    it compiles ``*`` to ``.*``, which crosses separators. So ``vendor/*``
    already matches ``vendor/sub/deep.rs``, and prunes just as soundly.

    A pattern of any other shape (``*.min.js``, ``docs/*.md``) prunes nothing
    and its files go on being enumerated and tested one at a time.
    """
    prefixes = []
    for pat in patterns:
        for suffix in ("/**", "/*"):
            if pat.endswith(suffix):
                prefixes.append(pat[: -len(suffix)])
                break
    return prefixes


def _pruned(rel: str, prefixes: list[str]) -> bool:
    """Is this directory one we were told not to enter?

    Two-shot, for the same reason ``_excluded`` is: ``**/`` means "at any depth,
    including none", and fnmatch cannot say that on its own.
    """
    for prefix in prefixes:
        if fnmatch.fnmatch(rel, prefix):
            return True
        if prefix.startswith("**/") and fnmatch.fnmatch(rel, prefix[3:]):
            return True
    return False


def _walk(base: Path, base_rel: str, prefixes: list[str],
          report: Report) -> list[tuple[str, str]]:
    """Every file under ``base``, as ``(rel, abs)`` strings, pruned directories
    never entered.

    ``rglob`` enumerated the whole tree before exclusion was applied one file at
    a time, so a repository's ``.git`` was fully stat'd on every run only to be
    thrown away — which on a repo with a hundred thousand loose objects is the
    entire cost of the scan. Stopping at the directory is the same answer for
    less work.

    A pruned directory is reported **as itself**. That is a real change to what
    ``excluded`` counts (paths, not files), and it is the honest reading: we did
    not look inside, so we cannot enumerate what is there.

    The path relative to the root is threaded down the walk as a plain string
    rather than recovered afterwards with ``Path.relative_to``, which costs
    ~40µs a call — on a 20 000-file tree that one method was more of the scan
    than reading every file in it. A child's relative path is its parent's plus
    a separator and a name; there is nothing to recompute.

    Symlinks are not followed and not returned, matching ``rglob``, which does
    not descend into them either. The path is deliberately never resolved.
    """
    files: list[tuple[str, str]] = []
    stack = [(str(base), base_rel)]
    while stack:
        parent, parent_rel = stack.pop()
        try:
            entries = list(os.scandir(parent))
        except OSError:
            # A directory we cannot list is not a file we failed to read, and
            # `rglob` was equally silent about it. Nothing to report.
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            rel = f"{parent_rel}/{entry.name}" if parent_rel else entry.name
            if entry.is_dir(follow_symlinks=False):
                if _pruned(rel, prefixes):
                    report.excluded.append(Path(entry.path))
                else:
                    stack.append((entry.path, rel))
            else:
                files.append((rel, entry.path))
    return files


def scan(
    root: Path, roots: list[str], exclude: list[str],
    overrides: dict[str, type[CommentStyle]] | None = None,
    marker_outside: str = "error",
) -> Report:
    """Walk the configured roots. Every file lands in exactly one bucket."""
    report = Report()
    prefixes = _prune_prefixes(exclude)

    for scan_root in roots:
        # Not resolved. Resolving would follow a symlinked source directory out
        # of the project and leave every path it found unrelatable to the root —
        # and the path relative to the root is what goes into `cited_by`. An
        # absolute path out of somebody's home directory is not a citation.
        base = root / scan_root
        # The root itself is "", so its children's relative paths are bare
        # names — which is what `_excluded` has always been given.
        base_rel = "" if scan_root in (".", "") else scan_root.replace(os.sep, "/")

        # Sorted on the relative path, which orders identically to sorting the
        # absolute ones: they share a prefix, so the suffix decides. That is the
        # order `sorted(rglob(...))` produced, and `extract --frozen` compares
        # bytes, so it is not ours to change.
        for rel, abs_path in sorted(_walk(base, base_rel, prefixes, report)):
            if _excluded(rel, exclude):
                report.excluded.append(Path(abs_path))
                continue
            scan_file(Path(abs_path), rel, report, overrides, marker_outside)

    # The walk visits directories in stack order, so pruned entries arrive in
    # whatever order the filesystem listed them. Nothing reads this list but its
    # length; sorting costs nothing and keeps two runs comparable.
    report.excluded.sort()

    return report
