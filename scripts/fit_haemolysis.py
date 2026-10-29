"""Fit and validate the haemolysis-risk model used by EPIC-AMP.

Labels are taken from the haemolysis text already stored in data/peptides.json
(sourced from DRAMP/dbAMP/UniProt records):

  haemolytic      quantified HC50/HD50/LC50/MHC/EC50 <= 50 uM
  not haemolytic  explicit "no haemolytic activity" statement, or a value > 200 uM

Anything between 50 and 200 uM is ambiguous and is left out.

Validation follows the usual pitfalls for peptide models:
  * similarity-aware split  - sequences are single-linkage clustered at >= 60%
                              identity and whole clusters are held out, so a test
                              peptide never has a near-duplicate in training.
                              The gap against a random split measures leakage.
  * class imbalance         - class weights in the loss; base rate reported.
  * uncertainty             - bootstrap confidence interval on the held-out AUC.
  * calibration             - Brier score and a reliability table.
  * applicability domain    - distance in standardised feature space to the
                              nearest training peptides, with the 95th percentile
                              of training distances shipped as the threshold.

The fitted coefficients and these diagnostics are written into the data file so
the browser scores sequences with exactly the same features.

Usage: python3 scripts/fit_haemolysis.py data/peptides.json
"""
import json, math, random, re, sys

path = sys.argv[1]
blob = json.load(open(path))
records = blob['records']

NONE = re.compile(r'\b(no|non-?|not|without|lack(ing)?|free of|absence of)\b[^.;]{0,40}\b(h(a)?emoly|lysis)', re.I)
QUANT = re.compile(r'\b(HC50|HD50|LC50|MHC|EC50)\b\s*[=<>~]?\s*([\d.]+)\s*'
                   r'(µM|uM|μM|µm|μm|µg/ml|ug/ml|μg/ml|µg/mL|μg/mL)?', re.I)

KD = {'A':1.8,'R':-4.5,'N':-3.5,'D':-3.5,'C':2.5,'Q':-3.5,'E':-3.5,'G':-0.4,'H':-3.2,'I':4.5,'L':3.8,'K':-3.9,
      'M':1.9,'F':2.8,'P':-1.6,'S':-0.8,'T':-0.7,'W':-0.9,'Y':-1.3,'V':4.2}
EISEN = {'A':0.62,'R':-2.53,'N':-0.78,'D':-0.90,'C':0.29,'Q':-0.85,'E':-0.74,'G':0.48,'H':-0.40,'I':1.38,'L':1.06,
         'K':-1.50,'M':0.64,'F':1.19,'P':0.12,'S':-0.18,'T':-0.05,'W':0.81,'Y':0.26,'V':1.08}
PKA = {'nterm':8.6,'cterm':3.6,'K':10.8,'R':12.5,'H':6.5,'D':3.9,'E':4.1,'C':8.5,'Y':10.1}
RES_MASS = {'A':71.08,'R':156.19,'N':114.10,'D':115.09,'C':103.14,'E':129.12,'Q':128.13,'G':57.05,'H':137.14,
            'I':113.16,'L':113.16,'K':128.17,'M':131.19,'F':147.18,'P':97.12,'S':87.08,'T':101.11,'W':186.21,
            'Y':163.18,'V':99.13}

FEATURES = ['length', 'charge', 'gravy', 'muH', 'aromatic', 'trp', 'hydrophobic', 'maxwin', 'lys', 'arg']
IDENTITY_CUTOFF = 0.60


def charge7(seq):
    z = 1 / (1 + 10 ** (7 - PKA['nterm'])) - 1 / (1 + 10 ** (PKA['cterm'] - 7))
    for ch in seq:
        if ch in 'KRH':
            z += 1 / (1 + 10 ** (7 - PKA[ch]))
        elif ch in 'DECY':
            z -= 1 / (1 + 10 ** (PKA[ch] - 7))
    return z


def moment(seq, window=11):
    best, n = 0.0, min(window, len(seq))
    for s in range(0, len(seq) - n + 1):
        x = sum(EISEN[c] * math.cos(math.radians(i * 100)) for i, c in enumerate(seq[s:s + n]))
        y = sum(EISEN[c] * math.sin(math.radians(i * 100)) for i, c in enumerate(seq[s:s + n]))
        best = max(best, math.hypot(x, y) / n)
    return best


def feats(seq):
    n = len(seq)
    frac = lambda s: sum(c in s for c in seq) / n
    maxwin = max((sum(KD[c] for c in seq[i:i + 9]) / 9) for i in range(max(1, n - 8)))
    return [n / 50, charge7(seq) / 5, sum(KD[c] for c in seq) / n, moment(seq),
            frac('FWY'), frac('W'), frac('AVILMFW'), maxwin / 4.5, frac('K'), frac('R')]


def to_micromolar(value, unit, seq):
    v = float(value)
    if unit and 'g/m' in unit.lower():
        v = v * 1000 / (18.0 + sum(RES_MASS[c] for c in seq))
    return v


def identity(a, b):
    """1 - normalised Levenshtein distance."""
    if abs(len(a) - len(b)) / max(len(a), len(b)) > 1 - IDENTITY_CUTOFF:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1 - prev[-1] / max(len(a), len(b))


# ── labelled set ────────────────────────────────────────────────────────────
rows = []
for r in records:
    seq, text = r[1], (r[5] or '')
    if not text or not 10 <= len(seq) <= 60:
        continue
    m = QUANT.search(text)
    if m:
        uM = to_micromolar(m.group(2), m.group(3), seq)
        if uM <= 50:
            rows.append({'x': feats(seq), 'y': 1, 'seq': seq})
        elif uM > 200:
            rows.append({'x': feats(seq), 'y': 0, 'seq': seq})
    elif NONE.search(text):
        rows.append({'x': feats(seq), 'y': 0, 'seq': seq})

# drop exact duplicate sequences, keeping the first label seen
seen, uniq = set(), []
for r in rows:
    if r['seq'] not in seen:
        seen.add(r['seq'])
        uniq.append(r)
dupes = len(rows) - len(uniq)
rows = uniq
pos = sum(r['y'] for r in rows)
print(f'labelled peptides: {len(rows)} ({pos} haemolytic, {len(rows) - pos} not, {dupes} duplicate sequences dropped)')
print(f'base rate: {pos / len(rows):.3f}')

# ── single-linkage clusters at >= 60% identity ──────────────────────────────
parent = list(range(len(rows)))


def find(i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


for i in range(len(rows)):
    for j in range(i + 1, len(rows)):
        if identity(rows[i]['seq'], rows[j]['seq']) >= IDENTITY_CUTOFF:
            a, b = find(i), find(j)
            if a != b:
                parent[a] = b
clusters = {}
for i in range(len(rows)):
    clusters.setdefault(find(i), []).append(i)
print(f'clusters at >={IDENTITY_CUTOFF:.0%} identity: {len(clusters)} '
      f'(largest {max(len(v) for v in clusters.values())} peptides)')

dim = len(FEATURES)


def fit(train, epochs=4000, lr=0.15, lam=0.02):
    mean = [sum(r['x'][j] for r in train) / len(train) for j in range(dim)]
    std = [max(1e-6, (sum((r['x'][j] - mean[j]) ** 2 for r in train) / len(train)) ** 0.5) for j in range(dim)]
    norm = lambda x: [(x[j] - mean[j]) / std[j] for j in range(dim)]
    npos = sum(r['y'] for r in train) or 1
    nneg = len(train) - npos or 1
    wpos, wneg = len(train) / (2 * npos), len(train) / (2 * nneg)
    w, b = [0.0] * dim, 0.0
    Z = [(norm(r['x']), r['y'], wpos if r['y'] else wneg) for r in train]
    for _ in range(epochs):
        gw, gb, tot = [0.0] * dim, 0.0, 0.0
        for z, y, cw in Z:
            p = 1 / (1 + math.exp(-(sum(w[j] * z[j] for j in range(dim)) + b)))
            e = (p - y) * cw
            for j in range(dim):
                gw[j] += e * z[j]
            gb += e
            tot += cw
        for j in range(dim):
            w[j] -= lr * (gw[j] / tot + lam * w[j])
        b -= lr * gb / tot
    return {'mean': mean, 'std': std, 'w': w, 'b': b}


def predict(model, x):
    z = [(x[j] - model['mean'][j]) / model['std'][j] for j in range(dim)]
    return 1 / (1 + math.exp(-(sum(model['w'][j] * z[j] for j in range(dim)) + model['b'])))


def auc_of(pairs):
    p1 = [p for p, y in pairs if y]
    p0 = [p for p, y in pairs if not y]
    if not p1 or not p0:
        return float('nan')
    return sum((a > b) + 0.5 * (a == b) for a in p1 for b in p0) / (len(p1) * len(p0))


def split_eval(name, folds):
    """folds: list of (train_rows, test_rows)."""
    preds = []
    for train, test in folds:
        m = fit(train)
        preds += [(predict(m, r['x']), r['y']) for r in test]
    auc = auc_of(preds)
    acc = sum((p >= 0.5) == bool(y) for p, y in preds) / len(preds)
    brier = sum((p - y) ** 2 for p, y in preds) / len(preds)
    print(f'{name}: n={len(preds)} AUC={auc:.3f} accuracy={acc:.3f} Brier={brier:.3f}')
    return preds, auc


random.seed(7)
idx = list(range(len(rows)))

# random 5-fold (optimistic: near-duplicates can straddle the split)
random.shuffle(idx)
rand_folds = []
for k in range(5):
    test_i = set(idx[k::5])
    rand_folds.append(([rows[i] for i in idx if i not in test_i], [rows[i] for i in sorted(test_i)]))
rand_preds, rand_auc = split_eval('random 5-fold          ', rand_folds)

# cluster-aware 5-fold (honest: whole similarity clusters held out together)
cl = list(clusters.values())
random.shuffle(cl)
buckets = [[] for _ in range(5)]
for n, c in enumerate(sorted(cl, key=len, reverse=True)):
    buckets[min(range(5), key=lambda b: len(buckets[b]))] += c
clus_folds = []
for k in range(5):
    test_i = set(buckets[k])
    clus_folds.append(([rows[i] for i in range(len(rows)) if i not in test_i], [rows[i] for i in sorted(test_i)]))
clus_preds, clus_auc = split_eval(f'cluster-aware 5-fold   ', clus_folds)
print(f'leakage from similarity: AUC drops {rand_auc - clus_auc:+.3f} when near-duplicates are separated')

# bootstrap CI on the cluster-aware predictions
boots = []
for _ in range(2000):
    sample = [clus_preds[random.randrange(len(clus_preds))] for _ in range(len(clus_preds))]
    a = auc_of(sample)
    if a == a:
        boots.append(a)
boots.sort()
lo, hi = boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots))]
print(f'bootstrap 95% CI for cluster-aware AUC: {lo:.3f} to {hi:.3f}')

# Platt scaling fitted on the cluster-aware out-of-fold predictions, so the
# reported probability matches the observed rate rather than the raw logit.
def fit_platt(preds):
    a, b = 1.0, 0.0
    for _ in range(3000):
        ga = gb = 0.0
        for p, y in preds:
            logit = math.log(max(p, 1e-6) / max(1 - p, 1e-6))
            q = 1 / (1 + math.exp(-(a * logit + b)))
            ga += (q - y) * logit
            gb += (q - y)
        a -= 0.05 * ga / len(preds)
        b -= 0.05 * gb / len(preds)
    return a, b


platt_a, platt_b = fit_platt(clus_preds)
apply_platt = lambda p: 1 / (1 + math.exp(-(platt_a * math.log(max(p, 1e-6) / max(1 - p, 1e-6)) + platt_b)))
clus_preds = [(apply_platt(p), y) for p, y in clus_preds]
brier_cal = sum((p - y) ** 2 for p, y in clus_preds) / len(clus_preds)
print(f'Platt scaling: a={platt_a:.3f} b={platt_b:.3f} -> Brier {brier_cal:.3f}')

print('\ncalibration after scaling (cluster-aware out-of-fold):')
bins = [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]
reliability = []
for lo_b, hi_b in bins:
    sel = [(p, y) for p, y in clus_preds if lo_b <= p < hi_b]
    if not sel:
        continue
    predicted = sum(p for p, _ in sel) / len(sel)
    observed = sum(y for _, y in sel) / len(sel)
    reliability.append({'bin': f'{lo_b:.0%}-{hi_b if hi_b <= 1 else 1:.0%}', 'n': len(sel),
                        'predicted': round(predicted, 3), 'observed': round(observed, 3)})
    print(f'  {lo_b:.0%}-{min(hi_b,1):.0%}  n={len(sel):3d}  mean predicted {predicted:.2f}  observed {observed:.2f}')

# ── final model on everything + applicability domain ────────────────────────
final = fit(rows)
norm_all = [[(r['x'][j] - final['mean'][j]) / final['std'][j] for j in range(dim)] for r in rows]


def knn_distance(z, exclude=None):
    ds = []
    for i, t in enumerate(norm_all):
        if i == exclude:
            continue
        ds.append(math.sqrt(sum((z[j] - t[j]) ** 2 for j in range(dim))))
    ds.sort()
    return sum(ds[:5]) / 5


train_d = sorted(knn_distance(z, exclude=i) for i, z in enumerate(norm_all))
ad_threshold = train_d[int(0.95 * len(train_d))]
print(f'\napplicability domain: mean distance to 5 nearest training peptides, '
      f'95th percentile = {ad_threshold:.2f} (median {train_d[len(train_d)//2]:.2f})')

print('\nsanity check on well-characterised peptides:')
for name, seq in [('Melittin (strongly haemolytic)', 'GIGAVLKVLTTGLPALISWIKRKRQQ'),
                  ('Gramicidin S-like (haemolytic)', 'VKLFPWFNKFLGKVLKVL'),
                  ('LL-37 (moderately haemolytic)', 'LLGDFFRKSKEKIGKEFKRIVQRIKDFLRNLVPRTES'),
                  ('Magainin-2 (selective)', 'GIGKFLHSAKKFGKAFVGEIMNS'),
                  ('Cecropin A (selective)', 'KWKLFKKIEKVGQNIRDGIIKAGPAVAVVGQATQIAK')]:
    print(f'  {apply_platt(predict(final, feats(seq))) * 100:5.1f}%  {name}')

blob['meta']['haemolysis_model'] = {
    'name': 'EPIC-AMP haemolysis risk v2',
    'type': 'logistic regression, class-weighted, L2',
    'features': FEATURES,
    'mean': [round(v, 6) for v in final['mean']],
    'std': [round(v, 6) for v in final['std']],
    'weights': [round(v, 6) for v in final['w']],
    'bias': round(final['b'], 6),
    'labelled': len(rows),
    'positives': pos,
    'base_rate': round(pos / len(rows), 3),
    'clusters': len(clusters),
    'identity_cutoff': IDENTITY_CUTOFF,
    'auc_random_cv': round(rand_auc, 3),
    'auc_cluster_cv': round(clus_auc, 3),
    'auc_ci95': [round(lo, 3), round(hi, 3)],
    'brier': round(brier_cal, 3),
    'platt': [round(platt_a, 6), round(platt_b, 6)],
    'reliability': reliability,
    'ad_threshold': round(ad_threshold, 3),
    'ad_reference': [[round(v, 4) for v in z] for z in norm_all],
    'labels': 'HC50/HD50/LC50/MHC/EC50 <= 50 uM counted as haemolytic; explicit "no haemolytic activity" or > 200 uM counted as not',
    'provenance': 'Fitted by scripts/fit_haemolysis.py on haemolysis annotations in DRAMP, dbAMP and UniProt records',
    'limitations': 'Trained on published values measured under varied protocols, red-cell sources and peptide concentrations. '
                   'Ranks candidates; does not replace a haemolysis assay.',
}
json.dump(blob, open(path, 'w'), separators=(',', ':'), ensure_ascii=False)
print('\nmodel and diagnostics written to', path)
