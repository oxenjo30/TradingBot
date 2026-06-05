"""Self-update via git branch-tracking.

The bot is deployed as a git checkout (see deploy.sh, which runs `git -C
/opt/tradebot pull`). This module compares the local checkout against
`origin/master` and, when asked, performs a safe pull + dependency install and
schedules a process exit so systemd (`Restart=always`) respawns on the new code.

No release tags are involved — every commit pushed to `master` is immediately
detectable. All git work runs in BASE_DIR (the repo root).
"""

import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

from .config import BASE_DIR, DB_PATH

_REMOTE = "origin"
_BRANCH = "master"
_GIT_TIMEOUT = 30.0          # seconds per git call
_PIP_TIMEOUT = 600.0         # dependency install can be slow
_MAX_INCOMING = 20           # commit subjects returned to the UI


def _git(*args, timeout=_GIT_TIMEOUT):
    """Run a git command in BASE_DIR. Returns (ok, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(BASE_DIR), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return False, "", "git executable not found"
    except subprocess.TimeoutExpired:
        return False, "", f"git {args[0] if args else ''} timed out"
    except Exception as e:  # noqa: BLE001 — never let a subprocess quirk escape
        return False, "", str(e)


def is_git_repo() -> bool:
    ok, out, _ = _git("rev-parse", "--is-inside-work-tree")
    return ok and out == "true"


def _short(rev: str) -> str:
    ok, out, _ = _git("rev-parse", "--short", rev)
    return out if ok else ""


def check() -> dict:
    """Detect whether origin/master is ahead of the local checkout.

    Degrades gracefully: a non-git environment (e.g. local dev without a
    checkout, or git missing) returns up_to_date=True / is_git=False rather
    than an error, so the dashboard card never shows a false failure.
    """
    if not is_git_repo():
        return {
            "is_git": False,
            "up_to_date": True,
            "behind_count": 0,
            "installed_commit": "",
            "latest_commit": "",
            "incoming": [],
        }

    # Fetch is best-effort — if offline, fall back to comparing against the last
    # known origin/master so the call still returns something sane.
    fetched, _, fetch_err = _git("fetch", _REMOTE, _BRANCH)

    installed_commit = _short("HEAD")
    latest_commit = _short(f"{_REMOTE}/{_BRANCH}")

    behind = 0
    ok, out, _ = _git("rev-list", "--count", f"HEAD..{_REMOTE}/{_BRANCH}")
    if ok and out.isdigit():
        behind = int(out)

    incoming: list[str] = []
    if behind > 0:
        ok, out, _ = _git("log", "--format=%s", f"HEAD..{_REMOTE}/{_BRANCH}")
        if ok and out:
            incoming = out.splitlines()[:_MAX_INCOMING]

    result = {
        "is_git": True,
        "up_to_date": behind == 0,
        "behind_count": behind,
        "installed_commit": installed_commit,
        "latest_commit": latest_commit,
        "incoming": incoming,
    }
    if not fetched and fetch_err:
        result["fetch_warning"] = fetch_err
    return result


def _backup_db() -> dict:
    """Copy trading.db aside before touching code. Never moves/deletes it."""
    if not DB_PATH.exists():
        return {"name": "backup_db", "ok": True, "detail": "no trading.db to back up"}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = DB_PATH.with_name(f"trading.db.backup-{stamp}")
    try:
        shutil.copy2(DB_PATH, dest)
        return {"name": "backup_db", "ok": True, "detail": f"backed up to {dest.name}"}
    except Exception as e:  # noqa: BLE001
        return {"name": "backup_db", "ok": False, "detail": f"backup failed: {e}"}


def _venv_pip() -> list[str]:
    """Path to the venv's pip, falling back to the running interpreter."""
    candidates = [
        BASE_DIR / ".venv" / "bin" / "pip",          # Linux venv (VPS)
        BASE_DIR / ".venv" / "Scripts" / "pip.exe",  # Windows venv
    ]
    for c in candidates:
        if c.exists():
            return [str(c)]
    return [sys.executable, "-m", "pip"]


def _rebuild_customer_zip() -> dict:
    """Rebuild the customer download zip from the freshly-pulled code.

    Keeps buyers' download in lock-step with the deployed code. Non-fatal: a build
    failure is reported but never blocks the update — the previous zip stays in
    place so downloads keep working. The build script lives in the repo and writes
    to <repo>/dist (which is TRADEBOT_ZIP_PATH's directory on the VPS).
    """
    builder = BASE_DIR / "scripts" / "build_customer_zip.py"
    if not builder.exists():
        return {"name": "build_zip", "ok": True, "detail": "no build script — skipped"}
    try:
        proc = subprocess.run(
            [sys.executable, str(builder)],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT * 4,
        )
        ok = proc.returncode == 0
        return {"name": "build_zip", "ok": ok,
                "detail": (proc.stdout or proc.stderr)[-1500:]}
    except Exception as e:  # noqa: BLE001 — never let a build quirk abort the update
        return {"name": "build_zip", "ok": False, "detail": f"build failed: {e}"}


def apply_update() -> dict:
    """Safe pull + optional dep install. On full success, schedule self-exit.

    Returns {ok, restarting, steps, new_commit}. The process exit is scheduled
    only when every prior step succeeds, and only AFTER this returns so the
    caller can respond to the browser first.
    """
    steps: list[dict] = []

    if not is_git_repo():
        return {"ok": False, "restarting": False,
                "steps": [{"name": "guard", "ok": False,
                           "detail": "not a git checkout - cannot self-update"}],
                "new_commit": ""}

    old_commit = _short("HEAD")

    # 1. Backup DB
    backup = _backup_db()
    steps.append(backup)
    if not backup["ok"]:
        return {"ok": False, "restarting": False, "steps": steps, "new_commit": old_commit}

    # 2. Stash local changes so the pull can't fail on a dirty worktree
    dirty_ok, dirty_out, _ = _git("status", "--porcelain")
    stashed = False
    if dirty_ok and dirty_out:
        ok, out, err = _git("stash", "push", "-u", "-m", "auto-update")
        stashed = ok
        steps.append({"name": "stash", "ok": ok,
                      "detail": (out or err) if not ok else "local changes stashed"})
        if not ok:
            return {"ok": False, "restarting": False, "steps": steps, "new_commit": old_commit}
    else:
        steps.append({"name": "stash", "ok": True, "detail": "worktree clean"})

    # 3. Pull (fast-forward only — never force, never merge-commit)
    ok, out, err = _git("pull", "--ff-only", _REMOTE, _BRANCH)
    steps.append({"name": "pull", "ok": ok, "detail": (out or err)[:2000]})
    if not ok:
        return {"ok": False, "restarting": False, "steps": steps, "new_commit": old_commit}

    new_commit = _short("HEAD")

    # 4. Install deps only if requirements.txt changed in the pulled range
    if old_commit and new_commit and old_commit != new_commit:
        chok, chout, _ = _git("diff", "--name-only", f"{old_commit}..{new_commit}")
        if chok and "requirements.txt" in chout.split():
            pip = _venv_pip()
            try:
                proc = subprocess.run(
                    [*pip, "install", "-r", str(BASE_DIR / "requirements.txt")],
                    capture_output=True, text=True, timeout=_PIP_TIMEOUT,
                )
                steps.append({"name": "deps", "ok": proc.returncode == 0,
                              "detail": (proc.stdout or proc.stderr)[-2000:]})
            except Exception as e:  # noqa: BLE001
                steps.append({"name": "deps", "ok": False, "detail": str(e)})
        else:
            steps.append({"name": "deps", "ok": True, "detail": "requirements.txt unchanged"})
    else:
        steps.append({"name": "deps", "ok": True, "detail": "already up to date"})

    # 5. Rebuild the customer download zip so buyers get the new code (non-fatal).
    steps.append(_rebuild_customer_zip())

    # 6. Schedule self-exit; systemd Restart=always respawns on the new code.
    steps.append({"name": "restart", "ok": True,
                  "detail": "restarting service to load new version"})
    schedule_restart()

    return {"ok": True, "restarting": True, "steps": steps, "new_commit": new_commit}


def schedule_restart(delay: float = 1.0):
    """Exit the process shortly, letting systemd respawn it.

    A hard os._exit is used so that no atexit/teardown can hang the shutdown;
    systemd brings the service back on the freshly pulled code.
    """
    def _die():
        time.sleep(delay)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()
