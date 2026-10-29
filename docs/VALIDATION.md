# Validation of the EPIC-AMP haemolysis-risk model

Reproduce everything here with:

```bash
python3 scripts/fit_haemolysis.py data/peptides.json   # ~50 s, standard library only
```

The script prints every number below and writes the fitted model plus its
diagnostics into `data/peptides.json` under `meta.haemolysis_model`, which is
what the browser reads. Nothing is hand-entered.

## 1. Data and labels

Labels are extracted from the haemolysis annotation text already redistributed
in this repository (DRAMP, dbAMP, UniProt records).

| | |
|---|---|
| Labelled peptides | **499** (10–60 residues) |
| Haemolytic | 171 — quantified HC50 / HD50 / LC50 / MHC / EC50 **≤ 50 µM** |
| Not haemolytic | 328 — explicit "no haemolytic activity" statement, or a value **> 200 µM** |
| Left out | values between 50 and 200 µM (genuinely ambiguous) |
| Duplicate sequences | 0 after de-duplication |
| Base rate | 0.343 |

µg/ml values are converted to µM using the peptide's own mass.

**Known data-quality limits.** These values come from different laboratories,
red-cell sources (human, sheep, rabbit) and incubation protocols. The 50 µM and
200 µM boundaries are a judgement call, not a standard. Negative statements
("no haemolysis observed") rarely state the concentration tested, so some
"non-haemolytic" labels mean only "not haemolytic at whatever was tried".

## 2. Sequence-similarity leakage

AMP datasets are full of near-duplicate analogues, so a random split flatters a
model badly. Sequences were single-linkage clustered at **≥ 60 % identity**
(normalised Levenshtein), giving **188 clusters** from 499 peptides — the
largest holds 41 peptides. Whole clusters are held out together.

| Split | AUC | Accuracy | Brier |
|---|---|---|---|
| Random 5-fold | 0.803 | 0.743 | 0.185 |
| **Cluster-aware 5-fold** | **0.744** | 0.675 | 0.202 |

**Leakage = 0.059 AUC.** The cluster-aware figure is the one reported in the
interface. Had we published the random-split number it would have overstated
performance by about six points.

Bootstrap 95 % CI on the cluster-aware AUC (2,000 resamples): **0.701 – 0.788**.

## 3. Class imbalance

34 % positives. The loss is class-weighted (`len/2n` per class), so the model is
not biased toward the majority "non-haemolytic" class. Accuracy is reported
alongside AUC because accuracy alone is misleading at this base rate.

## 4. Calibration

Raw logistic outputs were over-confident at the top end (predicted 69 % →
observed 48 %). Platt scaling was fitted **on the cluster-aware out-of-fold
predictions only** (a = 0.851, b = −0.563), never on training-fold outputs.

| Predicted band | n | Mean predicted | Observed rate |
|---|---|---|---|
| 0–20 % | 127 | 0.10 | 0.09 |
| 20–40 % | 205 | 0.31 | 0.33 |
| 40–60 % | 101 | 0.48 | 0.47 |
| 60–80 % | 64 | 0.69 | 0.66 |
| 80–100 % | 2 | 0.82 | 1.00 |

Brier score improves 0.202 → **0.189**. A displayed "30 %" now means roughly
three in ten such peptides were haemolytic in the training literature.

Note the top band holds only 2 peptides — the model almost never emits a
confident high score, which is itself a limitation.

## 5. Applicability domain

For each query the mean Euclidean distance to its 5 nearest training peptides is
computed in standardised feature space. The 95th percentile of that distance
within the training set (**2.28**; median 1.00) is shipped as a threshold.
Beyond it the interface shows a warning that the score is unreliable rather than
silently printing a number.

## 6. What the model learned

Coefficients on standardised features, largest first:

| Feature | Weight | Direction |
|---|---|---|
| Most hydrophobic 9-residue window | **+0.99** | raises risk |
| Hydrophobicity (GRAVY) | +0.72 | raises risk |
| Tryptophan content | +0.46 | raises risk |
| Aromatic content | +0.44 | raises risk |
| Hydrophobic moment (best 11-residue window) | +0.29 | raises risk |
| Net charge at pH 7 | +0.07 | ~neutral |
| Arginine, lysine, hydrophobic %, length | −0.09 to +0.04 | negligible |

This is consistent with the membrane biology: a long contiguous hydrophobic
stretch plus aromatic anchors drives insertion into cholesterol-rich mammalian
membranes.

## 7. Sanity check on well-characterised peptides

Calibrated output of the final model:

| Peptide | Risk | Expected |
|---|---|---|
| Gramicidin S-like | 69 % | haemolytic ✓ |
| Melittin | 47 % | strongly haemolytic — **underestimated** |
| Cecropin A | 45 % | selective — **overestimated** |
| Magainin-2 | 30 % | selective ✓ |
| LL-37 | 20 % | moderately haemolytic — **underestimated** |

Three of five land correctly; melittin and LL-37 are underestimated and
cecropin A is overestimated. This is the honest picture of a 499-sample
sequence-only model: **useful for ranking candidates, not for declaring one
safe.**

## 8. What this model is not

- Not an experimental measurement, and never presented as one.
- Not applicable outside 10–60 residues or outside the applicability domain.
- Not a cytotoxicity model — mammalian cell-line toxicity is a different
  endpoint (see `docs/EXTERNAL_MODELS.md`).
- Not externally validated against a held-out benchmark from another source;
  that remains the most valuable next step.

## Recommended further validation

1. Test against the HemoPI2 independent dataset (386 peptides) as a true
   external benchmark, after resolving the licence question for that data.
2. Have a wet-lab partner measure HC50 for 10–20 peptides spanning the score
   range, including a few flagged out-of-domain.
3. Re-fit per red-cell source once enough records specify it.
4. Compare against HemoPI2 predictions on the same sequences to see whether a
   1,926-peptide model with ESM embeddings materially outperforms this one.
