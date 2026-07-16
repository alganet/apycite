# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""apycite.toml, and the settings it refuses to accept quietly."""

from pathlib import Path

import pytest

from apycite.config import ConfigError, find, load


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "apycite.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_no_config_is_a_working_tool(tmp_path):
    """The defaults scan a tree and resolve an RFC. Nothing has to be configured."""
    config = load(None, tmp_path)

    assert config.roots == ["."]
    assert config.specs, "the RFC pattern is a shipped default"
    assert config.specs[0].resolve("RFC 9110") == {
        "url": "https://www.rfc-editor.org/rfc/rfc9110.txt",
        "type": "text/plain",
    }


def test_an_unknown_key_is_refused(tmp_path):
    """A setting the author believed was in force and was not is the same class
    of lie as a citation nobody checked."""
    path = _write(tmp_path, '[apycite]\nrootz = ["src"]\n')

    with pytest.raises(ConfigError, match="unknown key 'rootz'"):
        load(path, tmp_path)


def test_an_unknown_table_is_refused(tmp_path):
    path = _write(tmp_path, "[stiles]\n'.zig' = 'c'\n")
    with pytest.raises(ConfigError, match="unknown key 'stiles'"):
        load(path, tmp_path)


def test_a_project_pattern_beats_the_shipped_one(tmp_path):
    """So a project can pin RFCs to datatracker, or to the HTML rendition."""
    path = _write(tmp_path, r"""
[[specs]]
match = '^RFC (?P<n>\d+)$'
source = { url = "https://datatracker.ietf.org/doc/html/rfc{n}", type = "text/html" }
""")
    config = load(path, tmp_path)

    assert config.specs[0].resolve("RFC 9110")["url"] == \
        "https://datatracker.ietf.org/doc/html/rfc9110"
    # And the shipped one is still there, behind it.
    assert len(config.specs) == 2


def test_a_template_field_the_pattern_never_captures_is_refused_now(tmp_path):
    """It is a 404 waiting to happen, and it is knowable at config load.

    `str.format` would have raised at the first citation that used the pattern,
    weeks later, out of a stack trace.
    """
    path = _write(tmp_path, r"""
[[specs]]
match = '^RFC (?P<n>\d+)$'
source = { url = "https://example.org/{number}" }
""")
    with pytest.raises(ConfigError, match=r"\{number\}, which"):
        load(path, tmp_path)


def test_a_bad_regex_is_refused(tmp_path):
    path = _write(tmp_path, "[[specs]]\nmatch = '^RFC ((\\d+)$'\nsource = { url = 'x' }\n")
    with pytest.raises(ConfigError, match="bad regex"):
        load(path, tmp_path)


def test_a_style_shorthand_resolves(tmp_path):
    path = _write(tmp_path, '[styles]\n".zig2" = "c"\n')
    config = load(path, tmp_path)

    assert config.styles[".zig2"].SHORTHAND == "c"


def test_an_unknown_style_names_the_ones_that_exist(tmp_path):
    path = _write(tmp_path, '[styles]\n".zig2" = "klingon"\n')

    with pytest.raises(ConfigError) as exc:
        load(path, tmp_path)
    assert "c" in str(exc.value) and "html" in str(exc.value)


def test_marker_outside_comments_takes_two_values(tmp_path):
    path = _write(tmp_path, '[apycite]\nmarker_outside_comments = "shrug"\n')

    with pytest.raises(ConfigError, match='must be "error" or "warn"'):
        load(path, tmp_path)


def test_the_config_is_found_by_walking_up(tmp_path):
    _write(tmp_path, "[apycite]\n")
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)

    assert find(deep) == tmp_path / "apycite.toml"


def test_no_config_anywhere_is_not_an_error(tmp_path):
    assert find(tmp_path) is None
