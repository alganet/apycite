# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The walk, and the promise that nothing goes unlooked-at.

The load-bearing test in this file — arguably in the package — is
``test_a_cite_in_an_unknown_language_fails_the_run``. `reuse`'s design, which
everything else here is borrowed from, would skip that file and pass. Getting
that one case right is why this module exists rather than importing theirs.
"""

from pathlib import Path

import pytest

from apycite.comments import NAME_STYLE_MAP
from apycite.scan import Report, scan, scan_file


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


def _scan(tmp_path, files, **kw) -> Report:
    root = _tree(tmp_path, files)
    return scan(root, ["."], kw.pop("exclude", []), **kw)


CITE = '// cite(RFC 9110 § 7.2): "A user agent MUST generate a Host header field."'


# ── The bucket invariant ────────────────────────────────────────────────

def test_every_file_walked_lands_in_exactly_one_bucket(tmp_path):
    """`sum(buckets) == walked`. There is no fifth bucket, and no quiet one."""
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02")
    report = _scan(tmp_path, {
        "a.rs": CITE,
        "b.py": "# nothing here",
        "c.unknownext": "no marker in here at all",
        "vendor/d.rs": CITE,
    }, exclude=["vendor/*"])

    assert report.walked == 5
    assert len(report.parsed) == 2      # a.rs, b.py
    assert len(report.no_style) == 1    # c.unknownext — probed, clean
    assert len(report.binary) == 1      # bin.dat
    assert len(report.excluded) == 1    # vendor/d.rs
    assert not report.errors


def test_a_binary_file_is_skipped_and_counted(tmp_path):
    (tmp_path / "x.bin").write_bytes(b"\x00cite(RFC 1)")
    report = scan(tmp_path, ["."], [])

    assert [p.name for p in report.binary] == ["x.bin"]
    assert not report.errors  # a NUL byte is not a citation


# ── The load-bearing one ────────────────────────────────────────────────

@pytest.mark.parametrize("ext", [".zig2", ".tera", ".weird", ".xyzzy"])
def test_a_cite_in_an_unknown_language_fails_the_run(tmp_path, ext):
    """The requirement the package exists for.

    `reuse` would return None for this extension and its caller would skip the
    file. Skipping it means the quote is never checked, the report says nothing,
    and CI is green — which is the exact lie this tool is built to prevent.
    """
    report = _scan(tmp_path, {f"a{ext}": CITE})

    assert report.errors, "a cite in an unknown language was silently dropped"
    assert "no comment style" in report.errors[0]
    assert ext in report.errors[0]      # the error must name the fix


def test_the_unknown_language_error_says_how_to_fix_it(tmp_path):
    report = _scan(tmp_path, {"a.xyzzy": CITE})
    assert "[styles]" in report.errors[0]


def test_a_style_override_rescues_an_unknown_extension(tmp_path):
    root = _tree(tmp_path, {"a.xyzzy": CITE})
    report = scan(root, ["."], [], overrides={".xyzzy": NAME_STYLE_MAP["c"]})

    assert not report.errors
    assert len(report.cites) == 1
    assert report.cites[0].cite.source == "RFC 9110"


def test_an_unstyled_file_with_no_marker_is_a_safe_skip(tmp_path):
    """The theorem, used. We looked with the one instrument that needs no
    language, and the claim we make — "no cite here" — is true and checkable."""
    report = _scan(tmp_path, {"a.xyzzy": "nothing cite-shaped, honest"})

    assert not report.errors
    assert len(report.no_style) == 1


def test_a_file_that_is_not_utf8_is_an_error_not_a_skip(tmp_path):
    """We could not read it, so we will not promise it holds no cites."""
    (tmp_path / "a.rs").write_bytes(b"// cite(RFC 1): \xff\xfe\"q\"")
    report = scan(tmp_path, ["."], [])

    assert report.errors
    assert "cannot be read as UTF-8" in report.errors[0]


# ── The lexer hole, closed by reconciliation ────────────────────────────

def test_a_string_literal_that_opens_a_block_does_not_swallow_a_cite(tmp_path):
    """The one way this tool could lose a cite quietly, and it does not.

    `let s = "/*";` puts the naive lexer into block mode. Twenty lines later a
    real `// cite(...)` is inside that phantom block, gets treated as block
    content, and — with `*` stripping and no `*/` in sight — could parse as
    nothing at all. Reconciliation catches it: the marker fired, and the cite
    was not accounted for, so the run stops.
    """
    report = _scan(tmp_path, {"a.rs": '\n'.join([
        'let s = "/*";',
        'fn check() {',
        f'    {CITE}',
        '    if host_count == 0 {}',
        '}',
    ])})

    # Either it parsed the cite (fine), or it lost it and said so (also fine).
    # What must not happen is losing it in silence — and it did, until the
    # reconciliation rule started asking whether a marker was *accounted for*
    # rather than merely whether it sat inside some payload. It sat inside one:
    # the whole line, `//` and all, read as the body of a phantom block comment.
    assert report.cites or report.errors, "the cite vanished without a word"


def test_a_cite_in_a_string_literal_is_reported(tmp_path):
    """Not a comment, so not a cite — but loudly not, because we cannot be sure."""
    report = _scan(tmp_path, {
        "a.rs": 'let example = "cite(RFC 1): \\"q\\"";',
    })

    assert report.errors
    assert "did not read as a citation" in report.errors[0]


def test_cite_shaped_prose_in_a_comment_is_reported(tmp_path):
    """The third shape, which the sharpened rule caught for free.

    `// TODO: cite(RFC 9110) here` is not a near-miss by the grammar's reckoning
    — it does not *start* with `cite`, so the parser calls it an ordinary comment
    and moves on. It is cite-shaped all the same, and someone meant something by
    it. Reading it as prose and saying nothing is how a quote goes unchecked.
    """
    report = _scan(tmp_path, {"a.rs": "// TODO: cite(RFC 9110) here, once I read it"})

    assert report.errors
    assert "did not read as a citation" in report.errors[0]


def test_marker_outside_comments_can_be_downgraded(tmp_path):
    """A project with a real `cite()` function flips one key, and gets a list."""
    root = _tree(tmp_path, {"a.rs": 'let x = cite(thing);'})
    report = scan(root, ["."], [], marker_outside="warn")

    assert not report.errors
    assert report.warnings
    assert "did not read as a citation" in report.warnings[0]


def test_a_marker_inside_the_quote_is_accounted_for(tmp_path):
    """A source that itself talks about `cite(` must not trip the reconciliation.

    The marker is inside a payload that *became* a citation, so it is accounted
    for — which is what "accounted for" has to mean, rather than "is a citation".
    """
    report = _scan(tmp_path, {
        "a.rs": '// cite(RFC 1): "the function cite( is unrelated"',
    })

    assert not report.errors
    assert len(report.cites) == 1


# ── Near misses ─────────────────────────────────────────────────────────

def test_a_near_miss_stops_the_run(tmp_path):
    """A typo must break CI, not quietly drop a quote."""
    report = _scan(tmp_path, {"a.rs": '// cite(RFC 9110 § 7.2) "missing colon"'})

    assert report.errors
    assert "a.rs:1" in report.errors[0]


def test_the_error_names_the_file_and_the_line(tmp_path):
    report = _scan(tmp_path, {"deep/nested/rule.rs": '\n\n// cite(): "no source"'})

    assert report.errors[0].startswith("deep/nested/rule.rs:3:")


# ── The cites themselves ────────────────────────────────────────────────

def test_a_cite_records_where_it_was_made(tmp_path):
    report = _scan(tmp_path, {"src/rules/host.rs": f"fn f() {{\n    {CITE}\n}}"})

    found = report.cites[0]
    assert found.site.file == "src/rules/host.rs"
    assert found.site.line == 2


def test_the_same_quote_in_two_places_is_found_twice(tmp_path):
    """De-duplication is `emit`'s job, and it needs both sites to do it."""
    report = _scan(tmp_path, {"a.rs": CITE, "b.rs": CITE})

    assert len(report.cites) == 2
    assert {f.site.file for f in report.cites} == {"a.rs", "b.rs"}


def test_cites_are_found_in_every_language_at_once(tmp_path):
    """The agnostic claim, exercised. If this only ever ran on Rust it would be
    a lint-http script wearing a general-purpose hat."""
    report = _scan(tmp_path, {
        "a.rs": '// cite(RFC 9110 § 7.2): "the rust one"',
        "b.py": '# cite(PEP 8, section: Naming): "the python one"',
        "c.md": '<!-- cite(UN Charter, section: Article 51): "the markdown one" -->',
        "d.lua": '-- cite(Moby-Dick, location: chapter-1): "the lua one"',
        "e.css": '/* cite(CSS Color 4, selector: #resolving): "the css one" */',
        "f.tex": '% cite(Some Book, page_start: 40, page_end: 42): "the tex one"',
        "g.sql": '-- cite(Some Text, lines: 120-130): "the sql one"',
    })

    assert not report.errors
    assert len(report.cites) == 7
    assert {f.cite.quote.split()[1] for f in report.cites} == {
        "rust", "python", "markdown", "lua", "css", "tex", "sql",
    }


def test_scan_file_is_given_the_path_it_reports(tmp_path):
    """The reported path is relative to the project root — it goes into
    `cited_by`, and an absolute path from someone's laptop is not a citation."""
    root = _tree(tmp_path, {"src/a.rs": CITE})
    report = Report()
    scan_file(root / "src/a.rs", "src/a.rs", report)

    assert report.cites[0].site.file == "src/a.rs"
