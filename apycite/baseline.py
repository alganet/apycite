# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The ratchet: a list of files that have no cites yet, and may only get shorter.

Adopting cites across a codebase that already has hundreds of rules is not a
branch, it is a campaign. The baseline is what makes the campaign monotone: a
committed, sorted list of the in-scope files that still carry **zero** cites.
Shrinking it is the migration.

The teeth are in ``--write``, which **may only remove lines**. Adding a file to
the baseline requires a human to edit the file, which shows up in review as what
it is: a new rule shipped without a citation. Left to CI discipline, that is the
rule everyone agrees to and nobody enforces on a Friday.

When the baseline empties, the permanent rule — *every file in scope carries at
least one cite* — is already being enforced, with no new code and no second
mechanism to keep in step with this one.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

HEADER = [
    "# Files in scope that carry no cite yet. This list may only ever shrink.",
    "# Shrinking it is the migration; `apycite ratchet --write` will not add to it.",
]


@dataclass
class Ratchet:
    """What changed since the baseline was written."""

    entered: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)
    vanished: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.entered or self.left or self.vanished)


def read(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )


def write(path: Path, files: list[str]) -> None:
    body = "\n".join([*HEADER, *sorted(files)])
    path.write_text(body + "\n", encoding="utf-8")


def in_scope(
    files: list[str], scope: str, exclude: list[str] | None = None,
) -> list[str]:
    """The files the ratchet is answerable for.

    ``exclude`` exists because a directory of rules usually also contains a file
    that is not one: ``mod.rs``, ``__init__.py``, ``index.ts``. It enforces
    nothing, so it can never earn a citation, and without a way to say so it sits
    in the baseline forever — which makes the baseline permanently non-empty and
    the end of a migration unreachable. Excluding a file is a claim that it has no
    normative content, and it is written in the config where a reviewer sees it.
    """
    return sorted(
        f for f in files
        if fnmatch.fnmatch(f, scope)
        and not any(fnmatch.fnmatch(f, pattern) for pattern in exclude or [])
    )


def compare(uncited: list[str], baseline: list[str], scanned: list[str]) -> Ratchet:
    """The four things that can have happened, and three of them fail the run.

    A file that *left* the baseline and was not removed from it is a failure too,
    and that is the part people find surprising. A stale baseline is a validator
    validating nothing: it claims to be the list of un-migrated files, and it is
    no longer that list. It has stopped being able to catch a regression, and it
    would say nothing about having stopped.
    """
    uncited_now = set(uncited)      # in scope, and carrying no cite
    listed = set(baseline)          # what the committed baseline says
    exists = set(scanned)           # in scope, and still on disk

    return Ratchet(
        # A new rule with no cites, or a migrated one that lost its last cite.
        entered=sorted(uncited_now - listed),
        # Migrated, but the baseline was not shrunk to say so.
        left=sorted((listed & exists) - uncited_now),
        # The baseline names a file that is gone.
        vanished=sorted(listed - exists),
        # Still to do.
        remaining=sorted(listed & uncited_now),
    )
