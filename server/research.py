"""Task 9 — Walk-forward research orchestration (spec §11.2, §19.10, §19.13).

Pure, deterministic orchestration for anchored walk-forward validation with a
final untouched holdout. NO network, NO global state. This is research/reporting
infrastructure ONLY: it produces PASS/FAIL evidence and NEVER enables a strategy
and NEVER touches the live engine.

Fold geometry (spec §19.10, §19.13 "Fold boundaries"):
  STOCK  — require 10 complete years; final holdout = latest 24 complete months;
           anchored folds start with 5 training years and add 1-year validation
           windows advancing yearly; 5-session embargo; 252-session max lookback.
  CRYPTO — require 6 complete years; final holdout = latest 12 complete months;
           anchored folds start with 3 training years and add 6-month validation
           windows; 2-day embargo; 200-day max lookback (EMA200).

Key invariants enforced here:
  - The final holdout is scored EXACTLY ONCE, after parameters are frozen on ALL
    pre-holdout data. It is NEVER used for any training/validation call.
  - Every OOS validation fold begins from CASH; parameters are FIXED within a fold.
  - A 5-session (stock) / 2-day (crypto) embargo sits UNSCORED between parameter
    selection and validation; the max-lookback history before validation is
    warm-up only and produces no scored returns.
  - Fold returns are chained GEOMETRICALLY in timestamp order into ONE OOS curve.
  - Predeclared coarse grids only; selection maximizes training Calmar subject to
    training drawdown <= 5%, then lower turnover, then lexicographic params.
  - EVERY attempted configuration is persisted.

The orchestrator is parameterized by a `backtest_fn(*, params, window, from_cash,
role)` callable so it can be driven with a deterministic stub in unit tests (no
real 10-year data run — that happens in Task 11). `window` is a `DateWindow`;
`role` is one of "training" | "validation" | "holdout".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

D = Decimal

# Approximate calendar sizing used by the DEFAULT geometry (spec real values). The
# real Task 11 data run supplies the actual session calendar; these constants only
# translate "years/months" into session counts for the anchored windows.
STOCK_SESSIONS_PER_YEAR = 252
STOCK_SESSIONS_PER_MONTH = 21
CRYPTO_DAYS_PER_YEAR = 365
CRYPTO_DAYS_PER_MONTH = 30

TRAINING_DRAWDOWN_CAP = D("-0.05")  # training drawdown must be at/above -5%


class InsufficientHistory(Exception):
    """The supplied calendar is shorter than the geometry's minimum requirement."""


# ── date windows / folds ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DateWindow:
    start: date
    end: date


@dataclass(frozen=True)
class Fold:
    index: int
    train: DateWindow
    validation: DateWindow          # the SCORED validation window (post-embargo)
    embargo: DateWindow | None      # unscored embargo region (may be empty)
    embargo_periods: int
    warmup_periods: int


@dataclass
class WalkForwardPlan:
    folds: list[Fold]
    holdout: DateWindow
    pre_holdout: DateWindow


# ── fold geometry config ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FoldGeometry:
    """Anchored walk-forward geometry. DEFAULT constructors return the real spec
    values (§19.10); tests may pass reduced sizes for speed/determinism."""
    asset_class: str
    min_years: int
    train_years: int
    validation_months: int
    advance_months: int
    holdout_months: int
    embargo_periods: int
    max_lookback_periods: int
    days_per_year: int
    days_per_month: int

    @classmethod
    def stock_default(cls) -> "FoldGeometry":
        return cls(
            asset_class="stock",
            min_years=10,
            train_years=5,
            validation_months=12,      # 1-year validation windows
            advance_months=12,         # advance yearly
            holdout_months=24,         # latest 24 complete months
            embargo_periods=5,         # 5 sessions
            max_lookback_periods=252,  # prior-252 breakout is the max lookback
            days_per_year=STOCK_SESSIONS_PER_YEAR,
            days_per_month=STOCK_SESSIONS_PER_MONTH,
        )

    @classmethod
    def crypto_default(cls) -> "FoldGeometry":
        return cls(
            asset_class="crypto",
            min_years=6,
            train_years=3,
            validation_months=6,       # 6-month validation windows
            advance_months=6,          # advance every six months
            holdout_months=12,         # latest 12 complete months
            embargo_periods=2,         # 2 days
            max_lookback_periods=200,  # EMA200 is the max lookback
            days_per_year=CRYPTO_DAYS_PER_YEAR,
            days_per_month=CRYPTO_DAYS_PER_MONTH,
        )

    # derived session counts
    @property
    def holdout_periods(self) -> int:
        return self.holdout_months * self.days_per_month

    @property
    def train_periods(self) -> int:
        return self.train_years * self.days_per_year

    @property
    def validation_periods(self) -> int:
        return self.validation_months * self.days_per_month

    @property
    def advance_periods(self) -> int:
        return self.advance_months * self.days_per_month

    @property
    def min_periods(self) -> int:
        return self.min_years * self.days_per_year


# ── fold construction ────────────────────────────────────────────────────────────

def build_folds(calendar: list[date], geo: FoldGeometry) -> WalkForwardPlan:
    """Construct the anchored walk-forward plan + final holdout for `calendar`.

    Anchored (expanding-window) folds: every fold's training window starts at the
    common anchor (calendar[0]); the training END advances by `advance_periods`
    fold-over-fold. Each fold's SCORED validation window follows its training window
    after an unscored `embargo_periods` gap, and NEVER overlaps the final holdout
    (the latest `holdout_periods` sessions). The max-lookback history before each
    validation window is warm-up only (unscored)."""
    n = len(calendar)
    if n < geo.min_periods:
        raise InsufficientHistory(
            f"{geo.asset_class}: need >= {geo.min_periods} sessions "
            f"({geo.min_years}y), got {n}"
        )

    holdout_start_idx = n - geo.holdout_periods
    if holdout_start_idx <= 0:
        raise InsufficientHistory(
            f"{geo.asset_class}: holdout of {geo.holdout_periods} leaves no "
            f"pre-holdout data"
        )
    holdout = DateWindow(calendar[holdout_start_idx], calendar[-1])
    pre_holdout = DateWindow(calendar[0], calendar[holdout_start_idx - 1])

    folds: list[Fold] = []
    idx = 0
    train_end_idx = geo.train_periods  # exclusive index of first bar past training
    while True:
        # training window [0, train_end_idx)
        if train_end_idx >= holdout_start_idx:
            break
        train = DateWindow(calendar[0], calendar[train_end_idx - 1])

        # embargo occupies the first `embargo_periods` sessions after training.
        embargo_start_idx = train_end_idx
        embargo_end_idx = min(embargo_start_idx + geo.embargo_periods,
                              holdout_start_idx)
        embargo = None
        if geo.embargo_periods > 0 and embargo_end_idx > embargo_start_idx:
            embargo = DateWindow(calendar[embargo_start_idx],
                                 calendar[embargo_end_idx - 1])

        # scored validation window starts after the embargo and runs for
        # validation_periods, clamped to the pre-holdout boundary.
        val_start_idx = embargo_end_idx
        val_end_idx = min(val_start_idx + geo.validation_periods,
                          holdout_start_idx)
        if val_end_idx <= val_start_idx:
            break
        validation = DateWindow(calendar[val_start_idx], calendar[val_end_idx - 1])

        folds.append(Fold(
            index=idx, train=train, validation=validation, embargo=embargo,
            embargo_periods=geo.embargo_periods,
            warmup_periods=geo.max_lookback_periods,
        ))
        idx += 1
        train_end_idx += geo.advance_periods

    if not folds:
        raise InsufficientHistory(
            f"{geo.asset_class}: no complete walk-forward fold fits before the "
            f"holdout"
        )
    return WalkForwardPlan(folds=folds, holdout=holdout, pre_holdout=pre_holdout)


def session_gap(calendar: list[date], a: date, b: date) -> int:
    """Number of sessions strictly between `a` and `b` on `calendar`, inclusive of
    the endpoints as a span: index(b) - index(a). Used to assert the embargo."""
    return calendar.index(b) - calendar.index(a)


# ── predeclared parameter grids (§19.10) ─────────────────────────────────────────

_STOCK_GRID = {
    "breakout": [126, 252],
    "volume": [D("1.0"), D("1.2"), D("1.4")],
    "trail_atr": [D("2.5"), D("3.0"), D("3.5")],
}
_CRYPTO_GRID = {
    "breakout": [40, 55, 70],
    "exit_low": [15, 20, 30],
    "trail_atr": [D("3.0"), D("3.5"), D("4.0")],
}


def predeclared_grid(asset_class: str) -> list[dict]:
    """The predeclared coarse grid for the asset class, in lexicographic order
    (§19.10). Other strategy parameters stay fixed and are not part of the grid."""
    ac = (asset_class or "").lower()
    if ac == "stock":
        spec = _STOCK_GRID
        order = ("breakout", "volume", "trail_atr")
    elif ac == "crypto":
        spec = _CRYPTO_GRID
        order = ("breakout", "exit_low", "trail_atr")
    else:
        raise ValueError(f"unknown asset_class for grid: {asset_class!r}")
    out: list[dict] = []
    for a in spec[order[0]]:
        for b in spec[order[1]]:
            for c in spec[order[2]]:
                out.append({order[0]: a, order[1]: b, order[2]: c})
    # already generated in lexicographic order because the spec lists are sorted.
    return out


def _param_key(params: dict) -> tuple:
    """A deterministic lexicographic sort key over a param dict's values."""
    return tuple(_sortable(params[k]) for k in sorted(params.keys()))


def _sortable(v):
    if isinstance(v, Decimal):
        return (0, v)
    if isinstance(v, (int, float)):
        return (0, D(str(v)))
    return (1, str(v))


# ── selection rule (§19.10) ──────────────────────────────────────────────────────

def select_params(attempts: list[dict]) -> dict | None:
    """Select the best attempt: maximize training Calmar subject to training max
    drawdown <= 5% (i.e. drawdown >= -0.05); tie-break by LOWER turnover; then by
    LEXICOGRAPHIC params (§19.10). Returns the winning attempt dict, or None when
    no attempt satisfies the drawdown cap."""
    eligible = [a for a in attempts
                if _to_dec(a["max_drawdown"]) >= TRAINING_DRAWDOWN_CAP]
    if not eligible:
        return None
    # sort by (-calmar, turnover, lexicographic params); Decimal-safe.
    def _key(a):
        return (
            -_to_dec(a["calmar"]),           # higher Calmar first
            _to_dec(a["turnover"]),          # then lower turnover
            _param_key(a["params"]),         # then lexicographic params
        )
    return sorted(eligible, key=_key)[0]


def _to_dec(v) -> Decimal:
    return v if isinstance(v, Decimal) else D(str(v))


# ── OOS chaining ─────────────────────────────────────────────────────────────────

def chain_returns(fold_returns: list[Decimal]) -> Decimal:
    """Chain per-fold net returns geometrically into one aggregate OOS return
    (§19.13): prod(1 + r_i) - 1."""
    acc = D("1")
    for r in fold_returns:
        acc *= (D("1") + _to_dec(r))
    return acc - D("1")


# ── orchestrator ─────────────────────────────────────────────────────────────────

@dataclass
class WalkForwardResult:
    folds: list[dict]
    oos_return: Decimal
    frozen_params: dict | None
    holdout: dict | None
    attempts: list[dict] = field(default_factory=list)


def run_walk_forward(*, calendar: list[date], geometry: FoldGeometry,
                     grid: list[dict], backtest_fn,
                     persist=None) -> WalkForwardResult:
    """Run the anchored walk-forward + final holdout.

    For each fold: attempt EVERY grid point on the training window (persisting each
    attempt), select params by the §19.10 rule, then run the SCORED validation
    window ONCE from cash with the frozen params. Chain the per-fold validation
    returns geometrically into one OOS return.

    After all folds, freeze params by selecting on ALL pre-holdout data (one more
    training pass over the whole pre-holdout window), then evaluate the holdout
    EXACTLY ONCE from cash with those frozen params. The holdout window is NEVER
    passed to a training/validation call.

    `backtest_fn(*, params, window, from_cash, role)` returns a result dict with at
    least "net_return", "calmar", "max_drawdown", "turnover". `persist(attempt)` is
    called for every attempt (training, validation, holdout) if supplied.
    """
    persist = persist or (lambda *_a, **_k: None)
    plan = build_folds(calendar, geometry)

    all_attempts: list[dict] = []

    def _record(role, params, window, result, from_cash):
        attempt = {
            "role": role,
            "params": dict(params),
            "window_start": window.start.isoformat(),
            "window_end": window.end.isoformat(),
            "from_cash": from_cash,
            "net_return": result.get("net_return"),
            "calmar": result.get("calmar"),
            "max_drawdown": result.get("max_drawdown"),
            "turnover": result.get("turnover"),
        }
        all_attempts.append(attempt)
        persist(attempt)
        return attempt

    fold_summaries: list[dict] = []
    fold_returns: list[Decimal] = []

    for fold in plan.folds:
        # 1) training: attempt every grid point (refit on this fold's training
        #    window only — the anchored expanding window preceding validation).
        train_attempts = []
        for params in grid:
            res = backtest_fn(params=params, window=fold.train,
                              from_cash=True, role="training")
            _record("training", params, fold.train, res, True)
            train_attempts.append({
                "params": dict(params),
                "calmar": res.get("calmar", D("0")),
                "max_drawdown": res.get("max_drawdown", D("0")),
                "turnover": res.get("turnover", D("0")),
            })

        selected = select_params(train_attempts)

        # 2) validation: ONE run from cash with the frozen params for this fold.
        val_return = D("0")
        val_summary = {"fold": fold.index, "selected": None, "net_return": D("0")}
        if selected is not None:
            vres = backtest_fn(params=selected["params"], window=fold.validation,
                               from_cash=True, role="validation")
            _record("validation", selected["params"], fold.validation, vres, True)
            val_return = _to_dec(vres.get("net_return", D("0")))
            val_summary = {
                "fold": fold.index,
                "selected": dict(selected["params"]),
                "net_return": val_return,
                "validation_start": fold.validation.start.isoformat(),
                "validation_end": fold.validation.end.isoformat(),
            }
        fold_summaries.append(val_summary)
        fold_returns.append(val_return)

    oos_return = chain_returns(fold_returns)

    # 3) FREEZE: select params on ALL pre-holdout data (one training pass over the
    #    whole pre-holdout window). This is done BEFORE the holdout is ever touched.
    freeze_attempts = []
    for params in grid:
        res = backtest_fn(params=params, window=plan.pre_holdout,
                          from_cash=True, role="training")
        _record("training", params, plan.pre_holdout, res, True)
        freeze_attempts.append({
            "params": dict(params),
            "calmar": res.get("calmar", D("0")),
            "max_drawdown": res.get("max_drawdown", D("0")),
            "turnover": res.get("turnover", D("0")),
        })
    frozen = select_params(freeze_attempts)
    frozen_params = dict(frozen["params"]) if frozen is not None else None

    # 4) HOLDOUT: evaluate EXACTLY ONCE from cash with the frozen params. If no
    #    params could be selected, the holdout is not scored (candidate fails).
    holdout_summary = None
    if frozen_params is not None:
        hres = backtest_fn(params=frozen_params, window=plan.holdout,
                           from_cash=True, role="holdout")
        _record("holdout", frozen_params, plan.holdout, hres, True)
        holdout_summary = {
            "params": frozen_params,
            "net_return": _to_dec(hres.get("net_return", D("0"))),
            "max_drawdown": _to_dec(hres.get("max_drawdown", D("0"))),
            "window_start": plan.holdout.start.isoformat(),
            "window_end": plan.holdout.end.isoformat(),
        }

    return WalkForwardResult(
        folds=fold_summaries,
        oos_return=oos_return,
        frozen_params=frozen_params,
        holdout=holdout_summary,
        attempts=all_attempts,
    )
