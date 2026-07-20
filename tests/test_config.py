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
    """The defaults scan a tree. Nothing has to be configured.

    Note what is *not* asserted here any more: where an RFC lives. That was config
    once, and it had no business being — see `test_specs_says_where_it_went`.
    """
    config = load(None, tmp_path)

    assert config.roots == ["."]
    assert config.exclude


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


def test_specs_says_where_it_went(tmp_path):
    """`[[specs]]` mapped a name to a URL — which meant apycite shipped a
    hardcoded rfc-editor link while claiming to have no idea where rfc-editor
    lives. It is apysource's now.

    The generic "unknown key 'specs'" would be true and useless: it would not say
    the feature still exists one project over, and a project whose W3C names had
    silently stopped resolving would learn about it at the cite, blaming a name
    that was never the problem.
    """
    path = _write(tmp_path, r"""
[[specs]]
match = '^RFC (?P<n>\d+)$'
source = { url = "https://datatracker.ietf.org/doc/html/rfc{n}", type = "text/html" }
""")
    with pytest.raises(ConfigError, match="moved to apysource") as exc:
        load(path, tmp_path)

    assert "patterns:" in str(exc.value), "it has to say what to write instead"


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


# ── output_format ────────────────────────────────────────────────────────

def test_output_format_defaults_to_yaml(tmp_path):
    assert load(_write(tmp_path, '[apycite]\nroots = ["."]\n'),
                tmp_path).output_format == "yaml"


def test_output_format_turtle(tmp_path):
    assert load(_write(tmp_path, '[apycite]\noutput_format = "turtle"\n'),
                tmp_path).output_format == "turtle"


def test_an_output_format_nobody_knows_is_refused(tmp_path):
    """Only the formats that can be committed.

    `extract --frozen` compares bytes, and every RDF serialization except turtle
    labels its blank nodes afresh each run — a committed file would report a diff
    on every commit, which teaches everyone to ignore the check.
    """
    path = _write(tmp_path, '[apycite]\noutput_format = "json-ld"\n')
    with pytest.raises(ConfigError, match="unknown output_format"):
        load(path, tmp_path)
