# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The commands. Each returns an exit code; none of them exits.

There is no ``apycite check``. That word belongs to ``apysource check``, and a CI
log must never leave a reader wondering which of two tools passed. For the same
reason the ratchet is not ``--check`` either, though the original design called
it that.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

from apycite import baseline, emit
from apycite.comments import (
    EXTENSION_STYLE_MAP,
    FILENAME_STYLE_MAP,
    NAME_STYLE_MAP,
    get_comment_style,
)
from apysource.sources import load_sources

from apycite.config import Config
from apycite.scan import Report, scan


def _scan(config: Config) -> Report:
    return scan(config.root, config.roots, config.exclude, config.styles,
                config.marker_outside_comments)


def _complain(report: Report) -> int:
    for warning in report.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for error in report.errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if report.errors else 0


def _document(config: Config, report: Report, fmt: str | None = None) -> str:
    path = config.root / config.sources if config.sources else None

    # The existence check stays on this side of the line. It is *our* config that
    # named a file that is not there, and a bare FileNotFoundError from apysource
    # would print as "error: [Errno 2] ...", blaming the tool that was asked.
    if path is not None and not path.exists():
        raise emit.EmitError(f"sources file not found: {path}")

    return emit.render(emit.build(report.cites, load_sources(path), config.labels),
                       fmt or config.output_format)


def extract(config: Config, *, frozen: bool = False,
            allow_empty: bool = False, fmt: str | None = None) -> int:
    """Scan, resolve, and write the citations file."""
    report = _scan(config)

    for line in report.lines():
        print(line, file=sys.stderr)
    if config.exclude:
        print(f"  (excluding {', '.join(config.exclude)})", file=sys.stderr)

    if _complain(report):
        return 1

    # "A validator that validated nothing has not passed." An extraction that
    # found no cites at all has not proven a tree is cited; it has proven nothing.
    # Migration stage one — landing the mechanism empty — is the legitimate case,
    # and it has to ask.
    if not report.cites and not allow_empty:
        print("error: no cites found. That is not a pass — the tool verified "
              "nothing. Pass --allow-empty if a tree with no cites is what you "
              "meant (landing the mechanism before the migration, say).",
              file=sys.stderr)
        return 1

    try:
        rendered = _document(config, report, fmt)
    except Exception as exc:                    # noqa: BLE001 — reported, not raised
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = config.root / config.output

    if frozen:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current == rendered:
            print(f"  {config.output} is current", file=sys.stderr)
            return 0
        print(f"error: {config.output} is out of date. Run `apycite extract`.",
              file=sys.stderr)
        sys.stdout.writelines(difflib.unified_diff(
            current.splitlines(keepends=True), rendered.splitlines(keepends=True),
            fromfile=f"{config.output} (committed)", tofile="(scanned)"))
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(f"  wrote {config.output}", file=sys.stderr)
    return 0


def verify(config: Config, *, strict_redirects: bool = False,
           strict_repos: bool = False, refresh: bool = False,
           as_json: bool = False) -> int:
    """Scan, then check every quote against the source that is supposed to say it.

    Deliberately not the default: fetching a few hundred specs on every push is
    antisocial. `extract --frozen` and `ratchet` are what a pull request runs;
    this is what a nightly job runs.
    """
    import json

    from apysource import check_graph
    from apysource.verification import failed, json_report, print_report
    from apysource.yaml_input import graph_from_data

    import yaml

    report = _scan(config)
    if _complain(report):
        return 1
    if not report.cites:
        print("error: no cites found — nothing to verify.", file=sys.stderr)
        return 1

    try:
        document = yaml.safe_load(_document(config, report))
    except Exception as exc:                    # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1

    results = check_graph(graph_from_data(document, origin="(apycite)"),
                          force=refresh, strict_redirects=strict_redirects,
                          strict_repos=strict_repos)
    assert not isinstance(results, tuple)

    if as_json:
        print(json.dumps(json_report(results), indent=2, ensure_ascii=False))
    else:
        print_report(results, title="apycite — the sources still say this")

    return 1 if failed(results) else 0


def ratchet(config: Config, *, write: bool = False, init: bool = False) -> int:
    """Fail if a file *enters* the baseline, or if it left and nobody said so."""
    if not config.ratchet_scope or not config.ratchet_baseline:
        print("error: [ratchet] needs both 'scope' and 'baseline'", file=sys.stderr)
        return 1

    report = _scan(config)
    if _complain(report):
        return 1

    scanned = baseline.in_scope(
        [str(p.relative_to(config.root)) for p in report.parsed],
        config.ratchet_scope, config.ratchet_exclude)
    cited = {found.site.file for found in report.cites}
    uncited = [f for f in scanned if f not in cited]

    path = config.root / config.ratchet_baseline
    exists = path.exists()

    # Creating a baseline and updating one are different acts, and giving them
    # one flag is how a new uncited rule gets in: delete the file, run --write,
    # and the ratchet silently re-forms around whatever is there now. Creating
    # is a one-time migration step, and it says so.
    if init:
        if exists:
            print(f"error: {config.ratchet_baseline} already exists. --init "
                  f"creates a baseline; --write shrinks one.", file=sys.stderr)
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        baseline.write(path, uncited)
        print(f"  ratchet: baseline created with {len(uncited)} of "
              f"{len(scanned)} files to migrate", file=sys.stderr)
        return 0

    if not exists:
        print(f"error: no baseline at {config.ratchet_baseline}. Run "
              f"`apycite ratchet --init` once to create it — it will list the "
              f"{len(uncited)} file(s) in scope that have no cite yet, and from "
              f"then on that list may only shrink.", file=sys.stderr)
        return 1

    listed = baseline.read(path)
    state = baseline.compare(uncited, listed, scanned)

    if state.ok:
        print(f"  ratchet: {len(state.remaining)} of {len(scanned)} files still "
              f"to migrate", file=sys.stderr)
        return 0

    if write:
        if state.entered:
            # The teeth. `--write` may only ever remove.
            print("error: these files are in scope and carry no cite:",
                  file=sys.stderr)
            for name in state.entered:
                print(f"    {name}", file=sys.stderr)
            print("  --write will not add them to the baseline. A new rule with "
                  "no citation is the thing the baseline exists to catch; adding "
                  "it here would be the tool helping you not notice.",
                  file=sys.stderr)
            return 1
        baseline.write(path, uncited)
        print(f"  ratchet: baseline shrunk to {len(uncited)} files "
              f"(-{len(state.left) + len(state.vanished)})", file=sys.stderr)
        return 0

    for name in state.entered:
        print(f"error: {name} is in scope and has no cite. Add one, or — if this "
              f"is deliberate — add it to {config.ratchet_baseline} by hand, "
              f"where a reviewer will see it.", file=sys.stderr)
    for name in state.left:
        print(f"error: {name} now has cites but is still in "
              f"{config.ratchet_baseline}. Run `apycite ratchet --write`.",
              file=sys.stderr)
    for name in state.vanished:
        print(f"error: {config.ratchet_baseline} names {name}, which no longer "
              f"exists. Run `apycite ratchet --write`.", file=sys.stderr)

    return 1


def styles(config: Config, *, path: str | None = None) -> int:
    """Print the style table — or say which style one file gets, and by which rule.

    This is what makes the "no comment style for .zig" refusal actionable. Being
    told a lookup failed, without being told how the lookup works, leaves someone
    guessing at a config key.
    """
    if path is not None:
        match = get_comment_style(Path(path), config.styles)
        name = match.style.SHORTHAND if match.style else "(none)"
        print(f"{path}: {name} — {match.why}")
        if match.style is None:
            print(f"\nA cite in this file would fail the run. Register a style:\n"
                  f'\n  [styles]\n  "{Path(path).suffix}" = "c"\n'
                  f"\nKnown styles: {', '.join(sorted(NAME_STYLE_MAP))}")
            return 1
        return 0

    by_style: dict[str, list[str]] = {}
    for ext, style in EXTENSION_STYLE_MAP.items():
        by_style.setdefault(style.SHORTHAND, []).append(ext)
    for name, style in FILENAME_STYLE_MAP.items():
        by_style.setdefault(style.SHORTHAND, []).append(name)

    for shorthand in sorted(by_style):
        style = NAME_STYLE_MAP[shorthand]
        single = style.SINGLE_LINE or "—"
        start, _, end = style.MULTI_LINE
        block = f"{start} {end}" if start else "—"
        print(f"  {shorthand:<8} {single:<4} {block:<10} "
              f"{' '.join(sorted(by_style[shorthand]))}")

    return 0
