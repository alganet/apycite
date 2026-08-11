# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Usage: apycite [-c apycite.toml] <command> [flags]"""

from __future__ import annotations

import sys
from pathlib import Path

from apycite import config as config_module
from apycite.cli import commands

USAGE = """Usage: apycite [-c apycite.toml] <command> [flags]

  extract [--frozen] [--allow-empty]   scan the tree and write the citations file
          [--format yaml|turtle]
  verify  [--refresh] [--format json]  check every quote against its source
          [--strict-redirects] [--strict-repos]
          [--strict-supersession]
  ratchet [--init] [--write]           enforce the migration baseline
  styles  [--path FILE]                which comment style a file gets, and why

A cite is a comment:

  // cite(RFC 9112 § 3.2): "A client MUST send a Host header field ..."

`extract` writes an apysource sources file; `apysource check` verifies it.
`verify` does both in one pass.

`--format turtle` writes the same citations as RDF instead — the map from your
code to the sentences it implements, publishable and mergeable if the sources
file sets a `base:`. It is the only RDF form that is byte-stable, so it is the
only one `--frozen` can compare.
"""


def _flag(args: list[str], name: str) -> tuple[bool, list[str]]:
    if name in args:
        return True, [a for a in args if a != name]
    return False, args


def _value(args: list[str], name: str) -> tuple[str | None, list[str]]:
    """A flag given without its value is refused, not ignored.

    A flag that silently does nothing is worse than one that fails: the user
    believes the run was configured, and it was not.
    """
    if name not in args:
        return None, args
    i = args.index(name)
    if i + 1 >= len(args) or args[i + 1].startswith("--"):
        print(f"error: {name} requires a value", file=sys.stderr)
        raise SystemExit(2)
    return args[i + 1], args[:i] + args[i + 2:]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    config_path, args = _value(args, "-c")
    if config_path is None:
        config_path, args = _value(args, "--config")

    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    name, args = args[0], args[1:]

    root = Path.cwd()
    path = Path(config_path) if config_path else config_module.find(root)
    if config_path and not Path(config_path).exists():
        print(f"error: no such config: {config_path}", file=sys.stderr)
        return 2

    try:
        config = config_module.load(path, root)
    except config_module.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if name == "extract":
            frozen, args = _flag(args, "--frozen")
            allow_empty, args = _flag(args, "--allow-empty")
            fmt, args = _value(args, "--format")
            if fmt is not None and fmt not in config_module.OUTPUT_FORMATS:
                known = ", ".join(sorted(config_module.OUTPUT_FORMATS))
                print(f"error: unknown --format {fmt!r} (known: {known})",
                      file=sys.stderr)
                return 2
            return commands.extract(config, frozen=frozen,
                                    allow_empty=allow_empty, fmt=fmt)

        if name == "verify":
            refresh, args = _flag(args, "--refresh")
            redirects, args = _flag(args, "--strict-redirects")
            repos, args = _flag(args, "--strict-repos")
            superseded, args = _flag(args, "--strict-supersession")
            fmt, args = _value(args, "--format")
            if fmt not in (None, "json"):
                print(f"error: unknown --format {fmt!r} (only 'json')", file=sys.stderr)
                return 2
            return commands.verify(config, refresh=refresh,
                                   strict_redirects=redirects, strict_repos=repos,
                                   strict_supersession=superseded,
                                   as_json=fmt == "json")

        if name == "ratchet":
            write, args = _flag(args, "--write")
            init, args = _flag(args, "--init")
            return commands.ratchet(config, write=write, init=init)

        if name == "styles":
            target, args = _value(args, "--path")
            return commands.styles(config, path=target)

    except KeyboardInterrupt:  # pragma: no cover
        return 130

    print(f"error: unknown command {name!r}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
