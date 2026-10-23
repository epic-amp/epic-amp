"""Fit a haemolysis-risk model on the haemolysis values recorded in the peptide data.

Labels come from the source annotation text: a quantified HC50/HD50/LC50 at or below
50 uM counts as haemolytic, an explicit "no haemolytic activity" statement or a value
above 200 uM counts as non-haemolytic. Everything in between is left out.

Fits L2-regularised logistic regression by gradient descent (standard library only),
reports held-out accuracy and AUC, and writes the coefficients into the data file so
the browser can score a sequence with the same features.

Usage: python3 fit_haemolysis.py data/peptides.json
"""
import json, math, random, re, sys

path = sys.argv[1]
blob = json.load(open(path))
records = blob['records']

NONE = re.compile(r'\b(no|non-?|not|without|lack(ing)?|free of|absence of)\b[^.;]{0,40}\b(h(a)?emoly|lysis)', re.I)
QUANT = re.compile(r'\b(HC50|HD50|LC50|MHC|EC50)\b\s*[=<>~]?\s*([\d.]+)\s*(µM|uM|μM|µm|μm|µg/ml|ug/ml|μg/ml|µg/mL|μg/mL)?', re.I)

KD = {'A':1.8,'R':-4.5,'N':-3.5,'D':-3.5,'C':2.5,'Q':-3.5,'E':-3.5,'G':-0.4,'H':-3.2,'I':4.5,'L':3.8,'K':-3.9,
      'M':1.9,'F':2.8,'P':-1.6,'S':-0.8,'T':-0.7,'W':-0.9,'Y':-1.3,'V':4.2}
EISEN = {'A':0.62,'R':-2.53,'N':-0.78,'D':-0.90,'C':0.29,'Q':-0.85,'E':-0.74,'G':0.48,'H':-0.40,'I':1.38,'L':1.06,
         'K':-1.50,'M':0.64,'F':1.19,'P':0.12,'S':-0.18,'T':-0.05,'W':0.81,'Y':0.26,'V':1.08}
PKA = {'nterm':8.6,'cterm':3.6,'K':10.8,'R':12.5,'H':6.5,'D':3.9,'E':4.1,'C':8.5,'Y':10.1}

FEATURES = ['length', 'charge', 'gravy', 'muH', 'aromatic', 'trp', 'hydrophobic', 'maxwin', 'lys', 'arg']


def charge7(seq):
    z = 1 / (1 + 10 ** (7 - PKA['nterm'])) - 1 / (1 + 10 ** (PKA['cterm'] - 7))
    for ch in seq:
        if ch in 'KRH':
            z += 1 / (1 + 10 ** (7 - PKA[ch]))
        elif ch in 'DECY':
            z -= 1 / (1 + 10 ** (PKA[ch] - 7))
    return z


def moment(seq, window=11):
    best = 0.0
    n = min(window, len(seq))
    for s in range(0, len(seq) - n + 1):
        x = sum(EISEN[c] * math.cos(math.radians(i * 100)) for i, c in enumerate(seq[s:s + n]))
        y = sum(EISEN[c] * math.sin(math.radians(i * 100)) for i, c in enumerate(seq[s:s + n]))
        best = max(best, math.hypot(x, y) / n)
    return best


def feats(seq):
    n = len(seq)
    frac = lambda s: sum(c in s for c in seq) / n
    win = 9
    maxwin = max((sum(KD[c] for c in seq[i:i + win]) / win) for i in range(max(1, n - win + 1)))
    return [n / 50, charge7(seq) / 5, sum(KD[c] for c in seq) / n, moment(seq),
            frac('FWY'), frac('W'), frac('AVILMFW'), maxwin / 4.5, frac('K'), frac('R')]


def to_micromolar(value, unit, seq):
    v = float(value)
    if unit and 'g/m' in unit.lower():
        mass = 18.0 + sum({'A':71.08,'R':156.19,'N':114.10,'D':115.09,'C':103.14,'E':129.12,'Q':128.13,'G':57.05,
                           'H':137.14,'I':113.16,'L':113.16,'K':128.17,'M':131.19,'F':147.18,'P':97.12,'S':87.08,
                           'T':101.11,'W':186.21,'Y':163.18,'V':99.13}[c] for c in seq)
        v = v * 1000 / mass          # ug/ml -> uM
    return v


rows = []
for r in records:
    seq, text = r[1], (r[5] or '')
    if not text or not 10 <= len(seq) <= 60:
        continue
    m = QUANT.search(text)
    if m:
        uM = to_micromolar(m.group(2), m.group(3), seq)
        if uM <= 50:
            rows.append((feats(seq), 1, seq))
        elif uM > 200:
            rows.append((feats(seq), 0, seq))
    elif NONE.search(text):
        rows.append((feats(seq), 0, seq))

random.seed(7)
random.shuffle(rows)
pos = sum(y for _, y, _ in rows)
print(f'labelled peptides: {len(rows)} ({pos} haemolytic, {len(rows) - pos} not)')

split = int(len(rows) * 0.75)
train, test = rows[:split], rows[split:]
dim = len(FEATURES)
mean = [sum(r[0][j] for r in train) / len(train) for j in range(dim)]
std = [max(1e-6, (sum((r[0][j] - mean[j]) ** 2 for r in train) / len(train)) ** 0.5) for j in range(dim)]
norm = lambda x: [(x[j] - mean[j]) / std[j] for j in range(dim)]

w = [0.0] * dim
b = 0.0
lr, lam = 0.15, 0.02
for epoch in range(4000):
    gw = [0.0] * dim
    gb = 0.0
    for x, y, _ in train:
        z = norm(x)
        pred = 1 / (1 + math.exp(-(sum(w[j] * z[j] for j in range(dim)) + b)))
        err = pred - y
        for j in range(dim):
            gw[j] += err * z[j]
        gb += err
    for j in range(dim):
        w[j] -= lr * (gw[j] / len(train) + lam * w[j])
    b -= lr * gb / len(train)

def prob(x):
    z = norm(x)
    return 1 / (1 + math.exp(-(sum(w[j] * z[j] for j in range(dim)) + b)))

def evaluate(data, name):
    preds = [(prob(x), y) for x, y, _ in data]
    acc = sum((p >= 0.5) == bool(y) for p, y in preds) / len(preds)
    P = [p for p, y in preds if y],
    pos_s = [p for p, y in preds if y]
    neg_s = [p for p, y in preds if not y]
    pairs = [(a > b_) + 0.5 * (a == b_) for a in pos_s for b_ in neg_s]
    auc = sum(pairs) / len(pairs) if pairs else float('nan')
    print(f'{name}: n={len(data)} accuracy={acc:.3f} AUC={auc:.3f}')
    return auc

evaluate(train, 'train')
auc = evaluate(test, 'held-out')

print('\nsanity check on known peptides:')
for name, seq in [('Melittin (strongly haemolytic)', 'GIGAVLKVLTTGLPALISWIKRKRQQ'),
                  ('Magainin-2 (selective)', 'GIGKFLHSAKKFGKAFVGEIMNS'),
                  ('LL-37 (moderately haemolytic)', 'LLGDFFRKSKEKIGKEFKRIVQRIKDFLRNLVPRTES'),
                  ('Cecropin A (selective)', 'KWKLFKKIEKVGQNIRDGIIKAGPAVAVVGQATQIAK'),
                  ('Gramicidin S-like (haemolytic)', 'VKLFPWFNKFLGKVLKVL')]:
    print(f'  {prob(feats(seq)) * 100:5.1f}%  {name}')

blob['meta']['haemolysis_model'] = {
    'features': FEATURES, 'mean': [round(v, 6) for v in mean], 'std': [round(v, 6) for v in std],
    'weights': [round(v, 6) for v in w], 'bias': round(b, 6),
    'labelled': len(rows), 'positives': pos, 'heldout_auc': round(auc, 3),
    'labels': 'HC50/HD50/LC50 <= 50 uM counted as haemolytic; explicit "no haemolytic activity" or > 200 uM counted as not',
}
json.dump(blob, open(path, 'w'), separators=(',', ':'), ensure_ascii=False)
print('\nmodel written to', path)
