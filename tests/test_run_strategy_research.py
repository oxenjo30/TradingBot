"""Smoke/behavior tests for scripts/run_strategy_research.py (Task 11).

Deterministic, NO-NETWORK. These lock the evidence script's load-bearing
guarantees so the research runner cannot silently regress into fabricating a PASS:

  - the synthetic fallback path actually EXERCISES the full pipeline (geometry ->
    grid sweep -> PortfolioBacktester with real fills/costs -> statistical gate),
    i.e. it produces closed trades and a bootstrap interval;
  - a synthetic / data-limited run is FORCED to INCONCLUSIVE regardless of a
    numerically positive interval (honesty over optics, §17 / §19.13);
  - the runner NEVER enables a strategy, NEVER writes the live DB (persist=None),
    NEVER places an order.
"""
import importlib
from decimal import Decimal

import pytest

from server import research as R
from server import statistics as S
from server.backtest_models import CostModel

sr = importlib.import_module("scripts.run_strategy_research")

D = Decimal


def _reduced(asset_class):
    """A reduced but structurally-valid geometry so the test is fast yet fits >=2
    folds + a holdout (mirrors the Task 9 fold-packing lesson)."""
    if asset_class == "stock":
        return R.FoldGeometry(
            asset_class="stock", min_years=8, train_years=4,
            validation_months=12, advance_months=12, holdout_months=24,
            embargo_periods=5, max_lookback_periods=252,
            days_per_year=252, days_per_month=21)
    return R.FoldGeometry(
        asset_class="crypto", min_years=5, train_years=3,
        validation_months=6, advance_months=6, holdout_months=12,
        embargo_periods=2, max_lookback_periods=200,
        days_per_year=365, days_per_month=30)


@pytest.mark.parametrize("asset_class", ["stock", "crypto"])
def test_synthetic_pipeline_executes_and_is_inconclusive(asset_class):
    geo = _reduced(asset_class)
    syms = sr.STOCK_UNIVERSE if asset_class == "stock" else sr.CRYPTO_UNIVERSE
    provider = "alpaca" if asset_class == "stock" else "binance"
    data = sr._synthetic(asset_class, syms, geo, provider,
                         seed_base=0 if asset_class == "stock" else 100)

    # synthetic runs are ALWAYS flagged INCONCLUSIVE at the source.
    assert data.forced_inconclusive is True
    assert data.source == "synthetic"
    # every symbol got a deterministic content fingerprint.
    assert set(data.fingerprints) == set(syms)
    assert all(fp.startswith("sha256:") for fp in data.fingerprints.values())

    bt = sr._make_backtest_fn(data, CostModel.baseline(asset_class))
    plan = R.build_folds(data.calendar, geo)
    grid = R.predeclared_grid(asset_class)

    # The pipeline must actually TRADE on the pre-holdout window (proves fills,
    # costs, FIFO, metrics all run — not a zero-signal no-op).
    mid = grid[len(grid) // 2]
    res = bt(params=mid, window=plan.pre_holdout, from_cash=True, role="training")
    assert len(res["trades"]) > 0, "synthetic infra demo must execute trades"
    assert isinstance(res["net_return"], Decimal)
    assert isinstance(res["max_drawdown"], Decimal)

    # Holdout is scored and yields a daily-return series the gate can bootstrap.
    h = bt(params=mid, window=plan.holdout, from_cash=True, role="holdout")
    assert len(h["daily_returns"]) > 0
    lo, pt, hi = S.moving_block_bootstrap_ci(h["daily_returns"],
                                             S.STOCK_BLOCK if asset_class == "stock"
                                             else S.CRYPTO_BLOCK, seed=7)
    # a valid interval exists; classify_ci returns a real verdict enum.
    assert S.classify_ci(lo, hi) in (S.GateVerdict.PASS, S.GateVerdict.FAIL,
                                     S.GateVerdict.INCONCLUSIVE)


def test_forced_inconclusive_overrides_positive_interval(monkeypatch):
    """Even if the bootstrap interval is wholly positive, a synthetic/data-limited
    sleeve must NOT report PASS. Proves honesty-over-optics is enforced in code."""
    geo = _reduced("crypto")
    data = sr._synthetic("crypto", sr.CRYPTO_UNIVERSE, geo, "binance", seed_base=100)
    assert data.forced_inconclusive

    # Drive acquire() down the synthetic branch by making the real path raise.
    def _boom(*_a, **_k):
        raise RuntimeError("no creds in test")
    monkeypatch.setattr(sr, "_try_real_crypto", _boom)

    got = sr.acquire("crypto", geo)
    assert got.source == "synthetic"
    assert got.forced_inconclusive is True

    result = sr.run_sleeve("crypto", geo, R.predeclared_grid("crypto"))
    # The gate may compute a positive lower bound on the trending synthetic data,
    # but the reported verdict MUST be INCONCLUSIVE.
    assert result.verdict == "INCONCLUSIVE"
    assert result.source == "synthetic"


def test_acquire_never_crashes_without_credentials(monkeypatch):
    """A missing/invalid credential is CAUGHT and recorded, never raised."""
    def _boom(*_a, **_k):
        raise RuntimeError("crypto not initialised — DB_SECRET_KEY missing or invalid")
    monkeypatch.setattr(sr, "_try_real_stock", _boom)
    monkeypatch.setattr(sr, "_try_real_crypto", _boom)

    for ac in ("stock", "crypto"):
        data = sr.acquire(ac, _reduced(ac))
        assert data.source == "synthetic"
        assert data.forced_inconclusive is True
        assert any("real data unavailable" in lim for lim in data.limitations)


def test_safe_error_redacts_credential_like_tokens():
    """A recorded failure reason must never surface an API-key-like token, even if
    a third-party exception echoed one (defence-in-depth)."""
    leaked = "AKIA1234567890ABCDEFG_this_is_a_fake_secret_value"
    err = RuntimeError(f"binance auth failed apiKey={leaked} signature=deadbeefcafebabe")
    out = sr._safe_error(err)
    assert leaked not in out
    assert "deadbeefcafebabe" not in out
    assert "<redacted>" in out
    assert out.startswith("RuntimeError:")


def test_acquire_failure_reason_is_sanitized(monkeypatch):
    """acquire() records the sanitized reason (via _safe_error), not the raw str."""
    secret_like = "SUPERSECRETKEY0123456789ABCDEF"

    def _boom(*_a, **_k):
        raise RuntimeError(f"decrypt ok but feed rejected key {secret_like}")
    monkeypatch.setattr(sr, "_try_real_crypto", _boom)

    data = sr.acquire("crypto", _reduced("crypto"))
    assert data.source == "synthetic"
    joined = " ".join(data.limitations) + " " + data.reason
    assert secret_like not in joined
    assert "real data unavailable" in joined


def test_backtest_fn_uses_persist_none_and_touches_no_live_db():
    """run_sleeve wires run_walk_forward with persist=None — no DB writes at all."""
    import server.research as research_mod
    calls = {"persist": 0}
    orig = research_mod.run_walk_forward

    def _spy(*args, **kwargs):
        # persist must be None (the evidence script never persists to live DB).
        assert kwargs.get("persist") is None
        calls["persist"] += 1
        return orig(*args, **kwargs)

    research_mod.run_walk_forward = _spy
    try:
        sr.run_sleeve("crypto", _reduced("crypto"), R.predeclared_grid("crypto"))
    finally:
        research_mod.run_walk_forward = orig
    assert calls["persist"] == 1
