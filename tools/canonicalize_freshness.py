"""Checked helper for migrating the legacy application freshness call sites.

The tool is intentionally fail-closed: it does not modify files. It scans the
repository for legacy freshness authorities and reports the remaining call
sites so a human/CI review can approve the exact surgical edits.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    "MAX_SIGNAL_AGE_HOURS",
    "def is_signal_too_old",
    "def get_signal_age_str",
    "diff_hr = int(diff_min / 60)",
)


def scan() -> list[tuple[str, int, str]]:
    findings = []
    for path in sorted(ROOT.rglob("*.py")):
        if ".git" in path.parts or path.name == Path(__file__).name:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(pattern in line for pattern in PATTERNS):
                findings.append((str(path.relative_to(ROOT)), lineno, line.strip()))
    return findings


def main() -> int:
    findings = scan()
    if not findings:
        print("No legacy freshness authorities found.")
        return 0
    print("Legacy freshness authorities/call sites still present:")
    for path, lineno, line in findings:
        print(f"{path}:{lineno}: {line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
