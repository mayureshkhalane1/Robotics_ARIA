"""Keep only the latest N run logs whitelisted in .gitignore.

Run logs (``logs/run_*.log``) are git-ignored wholesale; this rewrites a marked
block in ``.gitignore`` so that only the most recent N are un-ignored (and thus
committable).  It runs automatically when the UI server
(``python -m src.ui.server``) shuts down, so the whitelist always reflects the
latest runs and old logs never accumulate in the repo.

Why a program at all?  ``.gitignore`` is purely pattern-based — it cannot
express "the latest N files by time".  This small helper sorts the logs by
modification time and maintains the whitelist for it.

Can also be run on its own:  ``python -m src.common.log_retention [N]``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List

from src.common.config import PROJECT_ROOT, LOGS_PATH

# The managed block in .gitignore lives between these markers; everything
# between them is rewritten on each call, so do not hand-edit it.
_BEGIN = "# >>> ARIA log-whitelist >>>"
_END = "# <<< ARIA log-whitelist <<<"
_DEFAULT_KEEP = 5


def _latest_run_logs(keep: int) -> List[Path]:
    """The `keep` most recently MODIFIED run logs (newest first)."""
    logs = sorted(
        LOGS_PATH.glob("run_*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return logs[:keep]


def update_log_whitelist(keep: int = _DEFAULT_KEEP) -> None:
    """Rewrite the managed block in ``.gitignore`` so only the latest `keep` run
    logs are whitelisted.  Idempotent and never raises — on shutdown we must not
    crash the process, so failures are logged instead.

    `keep` can be overridden with the ``ARIA_LOG_KEEP`` environment variable.
    """
    try:
        keep = max(0, int(os.getenv("ARIA_LOG_KEEP", keep)))
        gitignore = PROJECT_ROOT / ".gitignore"
        if not gitignore.exists():
            return

        latest = _latest_run_logs(keep)
        # Repo-relative, forward-slash paths (git wants POSIX separators).
        rels = [f"!{p.relative_to(PROJECT_ROOT).as_posix()}" for p in latest]
        block = [_BEGIN, *rels, _END]

        original = gitignore.read_text()
        lines = original.splitlines()
        if _BEGIN in lines and _END in lines:
            b, e = lines.index(_BEGIN), lines.index(_END)
            new_lines = lines[:b] + block + lines[e + 1:]
        else:
            # No markers yet — append a fresh block after a blank separator.
            sep = [""] if (lines and lines[-1] != "") else []
            new_lines = lines + sep + block

        new_text = "\n".join(new_lines) + "\n"
        if new_text != original:
            gitignore.write_text(new_text)
            print(f"[log-retention] .gitignore now whitelists the {len(rels)} "
                  f"latest run log(s): {[p.name for p in latest]}")
    except Exception as e:  # never break shutdown
        print(f"[log-retention] could not update .gitignore: {e}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_KEEP
    update_log_whitelist(n)
