# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""What to call a fragment, given the file that cites it.

This is the module that would have broken the first rule anyone migrated, and
the spike never noticed because its two cites happened to land in different
files.

apysource's ``_Minter`` refuses two fragments whose labels slugify identically —
it must, because two citations with one identity silently become one, and the
one that survives carries the other's snippet. The prototype's rule gave *every*
cite in a file the same label (the file's stem). A rule with two enforcing
branches, both citing RFC 9110, would have produced two fragments called
``client_host_header`` under one source, and ``apysource check`` would have
refused the file apycite had just written.

So labels are unique **by construction**, and the disambiguation is deterministic
— sorted by what the citation *says*, not by where it is written. A label that
moved every time someone inserted a line above it would churn the generated YAML
on every unrelated edit. The file and line live in ``cited_by``, where they are
free to move.
"""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

from apycite.config import LabelRule

DEFAULT_RULES = [LabelRule("**/*", "{path}")]


def label_for(rel: str, rules: list[LabelRule]) -> str:
    """The base label a cite in this file gets. First matching rule wins."""
    path = PurePosixPath(rel)
    fields = {
        "path": rel,
        "stem": path.stem,
        "name": path.name,
        "parent": str(path.parent),
    }

    for rule in rules or DEFAULT_RULES:
        if fnmatch.fnmatch(rel, rule.match):
            return rule.template.format(**fields)

    return rel


def disambiguate(base: str, index: int) -> str:
    """``host_header``, ``host_header (2)``, ``host_header (3)``.

    Not ``host_header:29``. A line number in a label makes the label move when
    the code above it moves, and the generated YAML would then diff on edits
    that changed no citation at all.
    """
    return base if index == 0 else f"{base} ({index + 1})"
