# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The real thing, against real documents. `pytest -m live`.

Every unit test in this package can pass while the tool does not work. That is
not a hypothetical: in apysource, *every* tranche of work shipped something that
lied about the source, and not one of those was caught by a green suite. They
were caught by running the real thing against a real document and reading what it
said. The rule that came out of it is written down, and this file is it:

> **Run the real thing against a real document, and read what it says. Then ask
> what the tests mock, because that is where the bug is.**

And a second rule, particular to this package: **a suite that only ever runs RFCs
has never seen apycite work as a general tool.** So the tree below cites five
sources, in four languages, across every path apysource has: the generic fetcher
on plain text (an RFC), the generic fetcher on HTML (a living standard, and a
treaty that is not a specification at all), and two repos that claim their URLs
and fetch something else entirely (MDN's authored markdown; a novel from Project
Gutenberg).

Writing this file has now found bugs twice — three misquotations the first time,
and E10 the second, where apysource insisted that Moby-Dick does not contain
"Call me Ishmael." It does. That is what this file is for.
"""

import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.live

SOURCES = """
sources:
  - label: RFC 9112
    url: https://www.rfc-editor.org/rfc/rfc9112.txt
    type: text/plain

  - label: Fetch
    url: https://fetch.spec.whatwg.org/
    type: text/html

  - label: MDN Origin
    url: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Origin

  - label: UN Charter
    url: https://www.un.org/en/about-us/un-charter/full-text
    type: text/html

  - label: Moby-Dick
    url: https://www.gutenberg.org/ebooks/2701
    publisher: Harper & Brothers
    date: "1851"
"""

CONFIG = """
[apycite]
roots   = ["src"]
sources = "sources.yaml"
output  = "specs.yaml"

[[labels]]
match = "**/*"
label = "{path}"
"""

# Four languages, five sources, one grammar.
#
# Most of these quotes were wrong the first time this file was written, and every
# one of them was caught by running it. The section on the Fetch spec was
# invented; the MDN sentence was misremembered (the source says "The **HTTP**
# Origin request header"); and "Call me Ishmael." on its own was refused as too
# short to be evidence — sixteen characters, which is a phrase, not a citation.
# That is the tool doing its job on its own author, and the scar tissue stays.
TREE = {
    # Plain text, RFC section tree. The generic fetcher.
    "src/host.rs":
        '// cite(RFC 9112 § 3.2): "A client MUST send a Host header field '
        '(Section 7.2 of [HTTP]) in all HTTP/1.1 request messages."',

    # A living HTML standard. `§ 3.2` — not the heading text, which is what the
    # first draft of this guessed at, and which does not exist.
    "src/origin.py":
        '# cite(Fetch § 3.2): "The `Origin` request header indicates where a '
        'fetch originates from."',

    # MDN, in JavaScript. MdnRepo claims this URL and fetches the *authored
    # markdown* from mdn/content instead of the rendered page — so a moved page
    # 404s loudly rather than quietly following a 301 somewhere else.
    #
    # Written across three lines, and broken immediately after an embedded
    # closing quotation mark — the placement that used to truncate a quote into a
    # prefix of the real sentence, which is still *in* the source and so verified
    # green while the rest went unchecked. A real document is the only place that
    # claim can actually be tested.
    "src/mdn.js":
        '// cite(MDN Origin, section: Origin header): "The HTTP Origin request header\n'
        '// indicates the origin (scheme, hostname, and port)\n'
        '// that caused the request."',

    # Not a specification at all, and that is the point: a tool that only ever
    # cites RFCs is a lint-http script wearing a general-purpose hat.
    "src/charter.lua":
        '-- cite(UN Charter, section: Article 51): "Nothing in the present '
        'Charter shall impair the inherent right of individual or collective '
        'self-defence"',

    # A novel, through GutenbergRepo, with no targetter at all — the quote is
    # matched against the whole book. Writing this is what found E10: apysource
    # said Moby-Dick does not contain "Call me Ishmael.", having fetched all 143
    # chapters and read 247 characters of the title page.
    "src/whale.lua":
        '-- cite(Moby-Dick): "Call me Ishmael. Some years ago—never mind how '
        'long precisely—having little or no money in my purse"',
}


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("live")
    (root / "apycite.toml").write_text(CONFIG, encoding="utf-8")
    (root / "sources.yaml").write_text(SOURCES, encoding="utf-8")
    for name, body in TREE.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body + "\n", encoding="utf-8")
    return root


def _run(args, cwd):
    return subprocess.run([sys.executable, "-m", "apycite.cli", *args],
                          cwd=cwd, capture_output=True, text=True, timeout=300)


def test_extract_reads_five_sources_across_four_languages(project):
    result = _run(["extract"], project)
    assert result.returncode == 0, result.stderr

    doc = (project / "specs.yaml").read_text()
    for label in ("RFC 9112", "Fetch", "MDN Origin", "UN Charter", "Moby-Dick"):
        assert label in doc, f"{label} did not survive extraction"


def test_every_quote_is_really_in_the_source(project):
    """The claim, checked against the live documents.

    If this fails, do not reach for the mock. Read what it says — one of these
    four sentences is not in the document that is supposed to contain it, and
    that is the finding, not the bug.
    """
    _run(["extract"], project)
    result = _run(["verify"], project)

    print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_drifted_quote_fails_and_names_the_line(project, tmp_path):
    """The half that matters. A tool that cannot fail has not passed.

    One word of one quote is changed — the drift this whole family exists to
    catch — and the report must name the file and line that has to change.
    """
    mutated = tmp_path / "mutated"
    shutil.copytree(project, mutated, ignore=shutil.ignore_patterns("specs.yaml"))

    path = mutated / "src" / "host.rs"
    path.write_text(path.read_text().replace("request messages", "response messages"),
                    encoding="utf-8")

    assert _run(["extract"], mutated).returncode == 0
    result = _run(["verify"], mutated)

    print(result.stdout)
    assert result.returncode == 1, "a quote the source does not contain verified green"
    assert "cited by src/host.rs:1" in result.stdout, \
        "the failure did not name the code that relies on the quote"


def test_the_repo_backed_sources_really_go_through_their_repos(project):
    """Two repos claim their URLs here, and `--strict-repos` fails if one could
    not serve what it claimed.

    MdnRepo fetches `mdn/content` markdown rather than the rendered page, so a
    moved page 404s instead of quietly following a 301 to a page that says
    something else. GutenbergRepo assembles a book out of its chapters — and
    Moby-Dick is cited here with no targetter at all, which is the case that was
    broken (E10): the quote is matched against the whole book, which is what a
    fragment with no targetter means everywhere else in apysource.
    """
    _run(["extract"], project)
    result = _run(["verify", "--strict-repos"], project)

    print(result.stdout)
    assert result.returncode == 0, result.stdout
