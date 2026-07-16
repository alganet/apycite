# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The commands, end to end, over a real tree on disk.

Exit codes are the interface CI reads. Every test here asserts one, because a
report that says FAIL and exits 0 is the whole failure mode in miniature.
"""

import os
from pathlib import Path

import pytest
import yaml

from apycite.cli.__main__ import main

CITE = '// cite(RFC 9112 § 3.2): "A client MUST send a Host header field."'
CITE2 = '// cite(RFC 9110 § 7.2): "A user agent MUST generate a Host header field."'

CONFIG = """
[apycite]
roots  = ["src"]
output = "specs.yaml"

[[labels]]
match = "src/rules/*.rs"
label = "{stem}"

[[labels]]
match = "**/*"
label = "{path}"

[ratchet]
scope    = "src/rules/*.rs"
baseline = "baseline.txt"
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "apycite.toml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "src" / "rules").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _rule(project: Path, name: str, body: str = "") -> Path:
    path = project / "src" / "rules" / f"{name}.rs"
    path.write_text(body, encoding="utf-8")
    return path


# ── extract ─────────────────────────────────────────────────────────────

def test_extract_writes_a_file_apysource_can_read(project):
    _rule(project, "host", f"fn f() {{\n    {CITE}\n}}")

    assert main(["extract"]) == 0

    doc = yaml.safe_load((project / "specs.yaml").read_text())
    assert doc["sources"][0]["label"] == "RFC 9112"
    fragment = doc["sources"][0]["fragments"][0]
    assert fragment["label"] == "host"
    assert fragment["section"] == "§ 3.2"
    assert fragment["cited_by"] == [{"file": "src/rules/host.rs", "line": 2}]


def test_extracting_nothing_is_not_a_pass(project):
    """A validator that validated nothing has not passed."""
    _rule(project, "host", "fn f() {}")

    assert main(["extract"]) == 1
    assert not (project / "specs.yaml").exists()


def test_landing_the_mechanism_empty_has_to_ask(project):
    """Migration stage one is legitimate. It is not the default."""
    _rule(project, "host", "fn f() {}")

    assert main(["extract", "--allow-empty"]) == 0


def test_a_near_miss_stops_extract(project):
    _rule(project, "host", '// cite(RFC 9112 § 3.2) "no colon"')

    assert main(["extract"]) == 1
    assert not (project / "specs.yaml").exists()


def test_an_unknown_source_stops_extract(project):
    _rule(project, "host", '// cite(Nonesuch): "a quote"')

    assert main(["extract"]) == 1


# ── --frozen ────────────────────────────────────────────────────────────

def test_frozen_passes_when_the_file_is_current(project):
    _rule(project, "host", CITE)
    assert main(["extract"]) == 0
    assert main(["extract", "--frozen"]) == 0


def test_frozen_fails_when_a_cite_changed(project, capsys):
    """The point of committing the generated file: extraction becomes reviewable,
    and 'the scanner quietly stopped finding cites' becomes a red diff."""
    _rule(project, "host", CITE)
    assert main(["extract"]) == 0

    _rule(project, "host", CITE2)
    assert main(["extract", "--frozen"]) == 1
    assert "out of date" in capsys.readouterr().err


def test_frozen_fails_when_the_file_is_missing(project):
    _rule(project, "host", CITE)
    assert main(["extract", "--frozen"]) == 1


# ── ratchet ─────────────────────────────────────────────────────────────

def test_ratchet_needs_a_baseline_before_it_can_enforce_one(project, capsys):
    _rule(project, "a", CITE)
    _rule(project, "b")

    assert main(["ratchet"]) == 1
    assert "--init" in capsys.readouterr().err


def test_init_lists_only_the_uncited(project):
    _rule(project, "a", CITE)
    _rule(project, "b")
    _rule(project, "c")

    assert main(["ratchet", "--init"]) == 0
    listed = [line for line in (project / "baseline.txt").read_text().splitlines()
              if not line.startswith("#")]
    assert listed == ["src/rules/b.rs", "src/rules/c.rs"]

    assert main(["ratchet"]) == 0


def test_init_refuses_to_overwrite(project):
    _rule(project, "a", CITE)
    assert main(["ratchet", "--init"]) == 0
    assert main(["ratchet", "--init"]) == 1


def test_a_new_rule_with_no_cite_fails(project, capsys):
    """The thing the baseline exists to catch."""
    _rule(project, "a", CITE)
    _rule(project, "b")
    assert main(["ratchet", "--init"]) == 0

    _rule(project, "brand_new")       # rule #186, no citation
    assert main(["ratchet"]) == 1
    assert "brand_new" in capsys.readouterr().err


def test_write_will_not_add_a_file_to_the_baseline(project, capsys):
    """The teeth. Adding requires a human edit, visible in review — otherwise
    `--write` is the tool helping you not notice."""
    _rule(project, "a", CITE)
    _rule(project, "b")
    assert main(["ratchet", "--init"]) == 0

    _rule(project, "brand_new")
    assert main(["ratchet", "--write"]) == 1
    assert "will not add them" in capsys.readouterr().err

    listed = (project / "baseline.txt").read_text()
    assert "brand_new" not in listed, "--write grew the baseline"


def test_migrating_a_rule_shrinks_the_baseline(project):
    _rule(project, "a", CITE)
    _rule(project, "b")
    assert main(["ratchet", "--init"]) == 0

    _rule(project, "b", CITE2)        # migrate it
    assert main(["ratchet"]) == 1     # the baseline is now stale, and says so
    assert main(["ratchet", "--write"]) == 0

    listed = [line for line in (project / "baseline.txt").read_text().splitlines()
              if not line.startswith("#")]
    assert listed == []
    assert main(["ratchet"]) == 0     # and with an empty baseline, the rule is
                                      # permanent with no new code


def test_a_stale_baseline_fails_rather_than_passing_quietly(project, capsys):
    """A baseline that no longer describes the tree has stopped being able to
    catch a regression, and would say nothing about having stopped."""
    _rule(project, "a", CITE)
    _rule(project, "b")
    assert main(["ratchet", "--init"]) == 0

    _rule(project, "b", CITE2)
    assert main(["ratchet"]) == 1
    assert "still in baseline.txt" in capsys.readouterr().err


def test_a_baseline_naming_a_deleted_file_fails(project, capsys):
    _rule(project, "a", CITE)
    _rule(project, "b")
    assert main(["ratchet", "--init"]) == 0

    os.remove(project / "src" / "rules" / "b.rs")
    assert main(["ratchet"]) == 1
    assert "no longer exists" in capsys.readouterr().err


def test_a_rule_that_loses_its_last_cite_fails(project, capsys):
    """A regression, not a new file — and the baseline only ever shrinks, so it
    cannot quietly reabsorb it."""
    _rule(project, "a", CITE)
    _rule(project, "b")
    assert main(["ratchet", "--init"]) == 0

    _rule(project, "a")               # the cite was deleted
    assert main(["ratchet"]) == 1
    assert "a.rs is in scope and has no cite" in capsys.readouterr().err


# ── styles ──────────────────────────────────────────────────────────────

def test_styles_says_which_rule_matched(project, capsys):
    assert main(["styles", "--path", "src/rules/a.rs"]) == 0
    out = capsys.readouterr().out
    assert "c" in out and "suffix '.rs'" in out


def test_styles_on_an_unknown_extension_fails_and_says_how_to_fix_it(project, capsys):
    """The refusal has to be actionable, or it is just a wall."""
    assert main(["styles", "--path", "a.xyzzy"]) == 1
    out = capsys.readouterr().out
    assert "[styles]" in out and '".xyzzy"' in out


def test_styles_prints_the_table(project, capsys):
    assert main(["styles"]) == 0
    out = capsys.readouterr().out
    assert ".rs" in out and ".lua" in out and ".tex" in out


# ── the command line itself ─────────────────────────────────────────────

def test_an_unknown_command_is_refused(project):
    assert main(["frobnicate"]) == 2


def test_help_exits_clean(project):
    assert main([]) == 0
    assert main(["--help"]) == 0


def test_a_flag_without_its_value_is_refused(project):
    """A flag that silently does nothing is worse than one that fails."""
    with pytest.raises(SystemExit) as exc:
        main(["verify", "--format"])
    assert exc.value.code == 2


def test_a_missing_config_is_refused(project):
    assert main(["-c", "nope.toml", "extract"]) == 2
