"""Repo-hygiene gate (iteration 210): .env.example must stay in sync with Settings.

README delegates the full configuration list to ``.env.example`` ("See
.env.example for the full list") — the file is the contract. This pin fails
whenever a Settings field gains no entry there (undiscoverable config) or an
active (uncommented) entry stops matching a real field (dead variable shipped
as copy-paste config).

The file's convention: optional keys appear commented with a placeholder
(``# TUSHARE_TOKEN=...``); a commented entry still counts as documented.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENTRY = re.compile(r"^(#)?\s*([A-Z][A-Z0-9_]+)=")


def _parse_env_example() -> tuple[set[str], set[str]]:
    """Return (documented names incl. commented, active names only)."""
    documented, active = set(), set()
    for line in (_REPO_ROOT / ".env.example").read_text().splitlines():
        if match := _ENTRY.match(line):
            documented.add(match.group(2))
            if match.group(1) is None:
                active.add(match.group(2))
    return documented, active


def test_every_settings_field_is_documented_in_env_example() -> None:
    documented, _ = _parse_env_example()
    missing = {field.upper() for field in Settings.model_fields} - documented
    assert not missing, (
        "Settings fields absent from .env.example (README calls it the full "
        f"list): {sorted(missing)}"
    )


def test_active_env_example_entries_are_real_settings_fields() -> None:
    _, active = _parse_env_example()
    fields = {field.upper() for field in Settings.model_fields}
    dead = active - fields
    assert not dead, f"Active .env.example entries with no Settings field: {sorted(dead)}"
