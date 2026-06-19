# Phase 21A — Audit Framework V2: Research Design Document

**Status:** Design / pre-implementation
**Author context:** Quant-PM resource-allocation review, post Phase 20A
**Date:** 2026-06-19

**Premise:** The bottleneck is measurement, not models. Phase 21A's deliverable
is **not a verdict on any model** — it is a *validated measurement instrument*.
You don't trust a thermometer to measure an unknown temperature until you've
checked it against known ones. That framing drives every decision below, and it
is the entire reason the pass/fail criteria in §10 are about the audit, not
about Regime V1.

---

## Framing: what we are and aren't building

**In scope:** an offline research library that can score *any* classifier against
forward excess returns with honest uncertainty.

**Explicitly out of scope:** any production wiring, any new MCP tool, any change
to `recommend_trade`, any tuning of V1 (ADX/EMA/RSI). Phase 21A touches `scripts/`
and `tests/` only. This keeps the resource allocation clean and the deliverable
falsifiable.

---

## 1. Exact architecture changes

The current `regime_audit.py` fuses four concerns into one script. V2 splits them
so the classifier becomes a pluggable component and the measurement engine becomes
model-agnostic. This single change is what converts a V1-specific script into a
reusable lab.

```
scripts/audit/
├── data.py        Universe loader, ticker map, local cache, benchmark series, coverage report
├── classify.py    Classifier protocol + adapters: V1 (_classify_regime), random-control, (later) RS/vol
├── evaluate.py    Forward returns (absolute + excess), per-regime + cross-sectional metrics
├── inference.py   Block bootstrap, run-level permutation null, IC time-series stats
├── report.py      Per-symbol, pooled, and inference tables
└── run.py         Orchestrator (replaces today's main())
```

Key structural moves:

- **Pluggable classifier.** Define a `Classifier = Callable[[dict], tuple[str, float | None]]`
  returning `(label, score)`. V1 returns `(regime, confidence)`; a score-based
  model (RS) returns `(bucket, continuous_score)`. This is what lets the *same*
  engine test V1, the null control, and future models — the property that makes
  the audit a lab.
- **Data caching layer.** Download the universe once to a versioned local store
  (parquet/CSV); audits read from cache. This kills three problems at once:
  download flakiness, irreproducibility, and the TATAMOTORS-style *silent*
  failure (cache build explicitly reports coverage and fails loud).
- **Richer row schema.** Replace `ClassificationRow` with a row carrying
  `symbol, date, regime, score, ret_{5,10,20}d, bench_ret_{5,10,20}d,
  excess_{5,10,20}d, run_id`. `run_id` lets inference resample at the run level
  (critical — see §5).
- **Two-tier metrics.** Per-symbol (today's view) *and* pooled cross-sectional
  (new, and the one that matters).

---

## 2. Exact metrics to add

Keep the existing descriptive metrics (n, runs, time%, DA). Add the inferential
and cross-sectional ones — these are the upgrade:

| Metric | Why it's added |
|---|---|
| **Mean forward excess return** per regime (5/10/20d), with 95% CI | Strips market drift — the contamination that broke V1's read |
| **Information Coefficient (IC)** | Per-date cross-sectional Spearman(score, forward excess return); the gold-standard signal metric |
| **IC IR (information ratio)** | mean(IC)/std(IC)·√N — tells you if the signal is *consistently* informative, not just on average |
| **Decile spread** (D10−D1 forward excess) + CI | The definitive cross-sectional test (§6) |
| **Per-regime t-stat vs zero excess**, autocorrelation-corrected | Replaces the meaningless categorical labels (INCEPTION_FAILURE on n=11) |
| **Hit rate on excess** + CI | Fraction of observations beating benchmark |
| **Turnover / classifications-per-year** | Transaction-cost proxy; a signal that flips daily is uninvestable even if "predictive" |
| **Coverage / data-quality block** | Symbols loaded, classification yield, NaN rejects — silent failure becomes loud |

Headline metric is **pooled 10d excess-return IC with IR** — pre-register it
(§9 on multiple testing).

---

## 3. Excess-return evaluation vs NIFTY

Definition: `excess_Hd = stock_forward_return_Hd − benchmark_forward_return_Hd`,
over the **same calendar dates**.

Three implementation subtleties that are easy to get wrong:

- **Align by trading date, not index offset.** Holidays and per-symbol missing
  candles desync positional indices. Forward windows must be computed on
  date-aligned series, with the benchmark sliced to the *same dates* as the stock
  window. A naive `closes[i+10]` on both series will silently mismatch.
- **Benchmark = ^NSEI (price index).** Document that this is price, not
  total-return — the missing dividend yield (~1–1.5%/yr on Nifty) is a small known
  drift in excess returns. Acceptable for V2; flag it.
- **Beta = 1 (raw excess) for V2.** Beta-adjusted excess (subtract β·market) is
  tempting but adds estimation noise and a researcher degree of freedom. Default
  to raw excess, document the choice, defer beta-adjustment to a sensitivity
  check. Don't gold-plate the first instrument.

Excess return becomes the **primary** basis for single-stock regimes; absolute
return is retained only as a secondary diagnostic.

---

## 4. Expanding 4 → Nifty 50/100

- **Fixed constituent list** from a snapshot date, stored as a verified
  `NSE symbol → yfinance ticker` map. Validate every ticker resolves *before* the
  audit runs; fail loudly on any unresolved (the TATAMOTORS lesson,
  institutionalized).
- **Survivorship bias — name it.** Using *today's* Nifty 50 tests stocks that
  survived into the index. This **inflates** apparent edge. Acceptable for a first
  pass only if documented with its direction; the real fix (point-in-time
  constituents) is expensive and deferred. This is a stated limitation, not a
  hidden one.
- **Coverage gate.** A run with <90% of the universe successfully evaluated is
  marked **invalid**, not silently averaged.
- **Compute is not the constraint** — 100 symbols × ~1000 candles walk-forward is
  trivial. Download *reliability* is the constraint, which the cache solves.

---

## 5. Confidence interval methodology

This is the statistical heart of V2 and the most common place these audits
silently lie. Overlapping forward windows are heavily autocorrelated; naive IID
standard errors understate uncertainty by multiples and manufacture false
significance.

- **Run-level / block resampling, never day-level.** Resampling individual days
  destroys the autocorrelation structure, shrinks the null variance, and inflates
  significance. Resample whole **runs** (or stationary blocks ≥ the forward
  horizon, e.g. 10–20 days). `run_id` in the schema exists for exactly this.
- **For per-regime mean excess return:** stationary/circular block bootstrap →
  empirical 95% CI (BCa preferred over percentile for skewed return distributions).
- **For IC:** compute the *time series* of per-date cross-sectional ICs (these are
  far less autocorrelated), then mean IC with **Newey–West SE** (lag ≈ horizon) or
  a block bootstrap on the IC series. This is the standard equity-quant approach
  and the cleanest inference available.
- Every headline number ships with a 95% CI. An effect is "real" only if its CI
  excludes zero **and** it clears the permutation null (§7).

---

## 6. Decile analysis methodology

Requires a **continuous score**, which is why the classifier protocol returns one.

- Each date, cross-sectionally rank all symbols by score into deciles D1…D10.
- Forward excess return per decile, averaged across dates.
- Tests: (a) **monotonicity** — Spearman of decile rank vs mean forward excess;
  (b) **D10−D1 spread** with block-bootstrap CI.

Important asymmetry to surface as a finding: **V1 is categorical (6 regimes), not
a rankable continuous score, so it cannot receive a full decile treatment** — only
the per-regime bucket metric. Score-based models (relative strength) get the full
decile test. That categorical models are *structurally harder to evaluate
rigorously* is itself an argument for continuous signals in V2-and-beyond.

---

## 7. Random-control baseline

The null model — and the audit's own validation harness.

- **Primary null: run-level label permutation.** Hold the marginal regime
  frequencies fixed, randomly reassign labels **at the run level** (not day level —
  same autocorrelation reasoning as §5), recompute all metrics. Repeat N≈1000 →
  empirical null distribution per metric.
- A real signal's statistic must fall outside the null (e.g., >97.5th percentile
  two-sided).
- **Why this is non-negotiable:** it directly answers "could this result arise from
  a model with zero information but the same structure?" If V1's numbers sit inside
  the permutation null, they're noise — full stop.

This control is also how the audit validates *itself* (§10): random labels must
*fail* at the correct rate.

---

## 8. Implementation effort

Realistic, one engineer, including tests and review:

| Component | Effort |
|---|---|
| Data layer (universe, ticker map, cache, benchmark alignment, coverage) | 2–3 d |
| Pluggable classifier refactor + richer schema | 1–2 d |
| Excess returns + per-regime metrics + IC | 2 d |
| **Inference layer (block bootstrap, run-level permutation, NW SE)** | **3–4 d** ← schedule risk |
| Decile analysis | 1 d |
| Reporting + preserve/extend the existing 27 regression tests | 2–3 d |

**Total ≈ 12–17 working days → ~3 calendar weeks.** The inference layer is the
risk; everything else is mechanical. Budget accordingly and don't let the
bootstrap get rushed — a wrong SE is worse than no SE because it lies with
confidence.

---

## 9. Risks and failure modes

- **Autocorrelation mishandled → false significance.** The dominant risk.
  Mitigation: run-level resampling, validated by the null-calibration check in §10.
- **Survivorship bias** (current-constituent universe) inflates edge. Mitigation:
  documented; point-in-time deferred.
- **Multiple testing.** Many regimes × horizons × symbols inflates false positives.
  Mitigation: **pre-register the primary metric** (pooled 10d excess-return IC/IR);
  everything else is secondary/exploratory and reported as such, with the test
  count disclosed.
- **Researcher degrees of freedom** (block size, decile count, beta choice,
  lookback). Mitigation: pre-register defaults, run sensitivity analysis on block
  size, don't tune to a pretty result.
- **Single macro epoch (2022–2025).** Even a perfect audit speaks only to one
  regime of history. Mitigation: extend history where data allows; explicitly cap
  external-validity claims.
- **The seductive failure:** a beautiful audit that is still *underpowered* to
  detect any real edge. Mitigation: the a-priori power check in §10 — done *before*
  trusting any verdict.

---

## 10. Pass/fail: when is the AUDIT (not the model) statistically useful?

The criteria are about the instrument. The audit graduates only when all four hold:

1. **Null calibration.** Run the random control through the full pipeline. The
   audit must reject the true null at ~5% — no more. If random labels "pass" >5% of
   the time, the inference is broken (almost always autocorrelation) and the audit
   is **not yet usable**. This is the single most important check.
2. **Planted-signal recovery.** Inject a synthetic classifier that peeks at a
   *noisy* version of the actual forward return (known, tunable edge). The audit
   must detect it at the expected significance. If it can't recover a *known* edge,
   it can't find a real one.
3. **A-priori power / minimum detectable effect.** Given universe size, history,
   and return volatility (with autocorrelation-correct SE), compute the MDE at 80%
   power / 5% significance. The audit is useful only if MDE ≤ an economically
   meaningful edge — target detect-ability of roughly a **10d excess spread
   ~0.3–0.5%** or **IC ~0.03 at IR ≥ 0.5**. If MDE is larger than any plausible
   real edge, expand universe/history *before* trusting any result.
4. **Reproducibility & coverage.** Seeded → identical outputs; CIs stable across
   reruns; ≥90% universe coverage with all ticker failures surfaced.

Only when (1)∩(2)∩(3)∩(4) hold do you point the instrument at V1, relative
strength, or volatility and believe the reading.

---

## PM resource note & decision gate

This is three weeks of pure offline research with zero production risk and a
falsifiable deliverable: *a measurement instrument validated against null,
planted-signal, and power benchmarks.* It is the correct allocation precisely
because every downstream model decision is worthless without it — Phase 20A proved
that the expensive way.

**Explicit gate at the end of 21A:** if the power check (criterion 3) shows the
audit *cannot* detect a meaningful edge even with Nifty 100 over available history,
that is a first-class finding — it tells you the retrospective-audit path has a
hard ceiling and that **forward logging becomes the only road to truth**,
redirecting the roadmap before you sink a month into Relative Strength V2 on an
instrument that can't measure it. Build the thermometer, then check that it can
actually read the temperatures you care about, *before* you trust any verdict it
produces.

---

## Appendix: relationship to Phase 20A

Phase 20A (`scripts/regime_audit.py`, committed `64539c4`) established the
walk-forward methodology, warmup/tail-exclusion handling, no-look-ahead guards,
and the run-start vs continuation diagnostic. Its negative finding on EMA20/EMA50
+ ADX is retained as the **baseline reference** that V2 must reproduce under
stricter inference. V2 supersedes the metrics and inference layers; it does not
discard the walk-forward engine or its 27 regression tests, which carry forward.

---

## UPDATE — Phase 21 cheap screen ran first; Audit V2 deferred

**Decision reversal (resource allocation):** before building V2, we ran the
*minimum viable experiment* — a crude cross-sectional screen — because V2's
rigor only earns its keep on *marginal* effects (0.3–0.8% / 10d), and a cheap
screen can detect or rule out a *large* effect in days. See
`scripts/cross_sectional_screen.py` (23 tests).

### Screen design (cheap, no heavy inference)

- Universe: Nifty 50 (48/50 loaded; `TATAMOTORS.NS`, `LTIM.NS` transient yfinance
  failures — 96% coverage, gate passed).
- Window: 2022-01-01 → 2026-01-01; benchmark `^NSEI`; 46,464 obs over 968 dates.
- Signals, ranked cross-sectionally into quintiles each date:
  - `RS_6m` — trailing 126d return (headline momentum)
  - `RS_12m1` — 252d return skip-21 (classic 12-1 momentum)
  - `Vol_63` — 63d realized volatility (low-vol anomaly)
- Outcome: forward EXCESS return vs NIFTY (date-aligned). Rank on raw trailing
  return (identical cross-sectional order to excess), measure excess on the
  outcome.

### Result (negative)

| Signal | 10d Q5−Q1 | Monotone? |
|---|---|---|
| RS_6m | **−0.286%** | no |
| RS_12m1 | **−0.141%** | no |

Both momentum spreads negative (mild reversal, not momentum), non-monotone
(hump-shaped: Q2 best, Q4 worst — the signature of noise), below transaction
costs. `Vol_63` showed high-vol outperformance (+0.29% / 10d Q5−Q1) — almost
certainly **beta in a rising market + survivorship**, not alpha; the screen
measures raw, not risk-adjusted, excess. **No large, monotone, tradeable
directional edge.**

### Adversarial review (assume the negative is wrong)

Checked 10 failure modes against the implementation. Key conclusions:
- Backtest bugs overwhelmingly produce spurious *large positive* results; a
  *small negative* is the hardest thing for a bug to fake.
- Lookahead is guarded **and** would push toward false-positive, not -negative.
- Benchmark subtraction is a per-date constant → **cancels in the Q5−Q1 spread**
  (momentum spread is benchmark-invariant by construction).
- The one bug that *could* invert a real positive into our negative — quintile
  **orientation** (sort direction) — is now locked by a direct regression test
  (`test_quintile_orientation_high_signal_lands_in_q5`).
- Survivorship **inflates** momentum, so finding nothing despite it strengthens
  the negative.
- Legitimate methodology caveats: 2022 was a momentum-crash regime; excluded
  `TATAMOTORS` was a momentum winner (biases spread slightly down). These mean
  the finding may *understate* momentum in other regimes — not that a large
  exploitable edge is hidden.

**Probability the negative is mostly a bug: ~3–4% (< 10%).** Roadmap decision is
robust across genuine / methodology / bug cases.

### Scoped conclusion (do not overclaim)

> No large, monotone, tradeable cross-sectional momentum or volatility edge
> exists on Nifty 50 over 2022–2025. This does not prove momentum never works on
> NSE in any regime; it proves no edge large and stable enough to justify
> building directional-prediction infrastructure now.

### Consequences

- **Audit V2 is deferred / not built.** The observed effects are below 0.3% AND
  non-monotone — outside the band where V2's rigor changes any decision.
- **Directional-prediction research track paused.** Pivot future work to: risk
  management, journaling, execution discipline, options/volatility structure.
- Screen committed as `feat(research): Phase 21 cross-sectional screen`.
