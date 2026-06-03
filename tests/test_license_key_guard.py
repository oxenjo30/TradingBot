# tests/test_license_key_guard.py
"""Guard + instrumentation around clearing the stored license_key.

The stored license_key has been mysteriously emptied multiple times, forcing the
user to re-enter it. The only code that writes an empty value is the deactivate
endpoint, but we could not reproduce the clobber from static analysis. So we add
instrumentation: any call that empties license_key is logged with a full stack
trace and an audit row, so the NEXT occurrence is captured with its caller.
"""
import logging


def test_set_license_key_empty_logs_stacktrace_and_audits(tmp_path, monkeypatch, caplog):
    import server.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "guard.db")
    db.init_db()

    # First store a real key (non-empty path must NOT warn/audit).
    with caplog.at_level(logging.WARNING):
        db.set_license_key("REAL-KEY-123")
    assert db.get_license_key() == "REAL-KEY-123"
    assert not any("license_key" in r.message for r in caplog.records), (
        "storing a real key must not emit the clear-warning"
    )

    # Now clear it — this MUST log a stack-traced warning and write an audit row.
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        db.set_license_key("")
    assert db.get_license_key() == ""  # deactivate still works

    warned = [r for r in caplog.records if "license_key cleared" in r.message.lower()]
    assert warned, "clearing license_key must emit a WARNING with a stack trace"
    # The warning must carry stack info so we can see WHO cleared it.
    assert any(r.stack_info or r.exc_info for r in warned), (
        "the clear-warning must include stack info to identify the caller"
    )

    # And an audit row must exist so the user has a durable, timestamped record.
    audits = db.list_audit(limit=10)
    assert any("clear" in a.get("action", "").lower()
               and "license" in (a.get("category", "") + a.get("action", "")).lower()
               for a in audits), (
        "clearing license_key must be recorded in the audit log"
    )
