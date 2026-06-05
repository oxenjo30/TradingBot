#!/usr/bin/env python3
"""Compute and apply semantic-version bumps to server/version.py.

Versioning scheme (driven by the commit message via the prepare-commit-msg hook,
or run manually):

    major  : / feat!: / "BREAKING CHANGE"  ->  major   v1.0.0 -> v2.0.0
    feat   :                                ->  minor   v1.0.0 -> v1.1.0
    fix/docs/refactor/perf/style/etc.       ->  patch   v1.0.0 -> v1.0.1
    temp/chore/wip/build/ci/test            ->  none    (no bump)

Usage:
    python scripts/bump_version.py major|minor|patch     # explicit bump
    python scripts/bump_version.py --from-message "<msg>" # decide from a commit msg
    python scripts/bump_version.py --show                 # print current version

Prints the new version on stdout, or the unchanged version if no bump applies.
Exit code is always 0 unless version.py can't be read/written.
"""
import re
import sys
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "server" / "version.py"
_VER_RE = re.compile(r'INSTALLED_VERSION\s*=\s*["\']v?(\d+)\.(\d+)\.(\d+)["\']')


def read_version() -> tuple[int, int, int]:
    text = VERSION_FILE.read_text(encoding="utf-8")
    m = _VER_RE.search(text)
    if not m:
        raise SystemExit(f"Could not find INSTALLED_VERSION in {VERSION_FILE}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def write_version(major: int, minor: int, patch: int) -> str:
    new = f"v{major}.{minor}.{patch}"
    text = VERSION_FILE.read_text(encoding="utf-8")
    text = _VER_RE.sub(f'INSTALLED_VERSION = "{new}"', text)
    VERSION_FILE.write_text(text, encoding="utf-8")
    return new


def bump_kind_from_message(msg: str) -> str | None:
    """Return 'major' | 'minor' | 'patch' | None for a commit message."""
    first = msg.strip().splitlines()[0].strip().lower() if msg.strip() else ""
    body = msg.lower()

    # Explicit no-bump prefixes (scratch / housekeeping commits)
    if re.match(r'^(temp|chore|wip|build|ci|test|release)(\(.+\))?!?:', first):
        return None

    # Major: "feat!:" / "fix!:" (any type with !), "major:", or BREAKING CHANGE in body
    if re.match(r'^[a-z]+(\(.+\))?!:', first) or first.startswith("major:") or "breaking change" in body:
        return "major"

    # Minor: a new feature
    if re.match(r'^feat(\(.+\))?:', first):
        return "minor"

    # Patch: fix, docs, refactor, perf, style, and anything else that ships
    if re.match(r'^(fix|docs|refactor|perf|style|revert)(\(.+\))?:', first):
        return "patch"

    # Unrecognized prefix -> treat as patch so versions still move on real changes.
    # (If you want unrecognized commits to NOT bump, return None here instead.)
    return "patch"


def apply_bump(kind: str) -> str:
    major, minor, patch = read_version()
    if kind == "major":
        major, minor, patch = major + 1, 0, 0
    elif kind == "minor":
        minor, patch = minor + 1, 0
    elif kind == "patch":
        patch += 1
    else:
        return f"v{major}.{minor}.{patch}"  # no change
    return write_version(major, minor, patch)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    if argv[0] == "--show":
        major, minor, patch = read_version()
        print(f"v{major}.{minor}.{patch}")
        return 0

    if argv[0] == "--from-message":
        msg = argv[1] if len(argv) > 1 else ""
        kind = bump_kind_from_message(msg)
        if kind is None:
            major, minor, patch = read_version()
            print(f"v{major}.{minor}.{patch}")  # unchanged
            return 0
        print(apply_bump(kind))
        return 0

    if argv[0] in ("major", "minor", "patch"):
        print(apply_bump(argv[0]))
        return 0

    print(f"Unknown argument: {argv[0]}\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
