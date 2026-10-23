"""Merge DRAMP, dbAMP and UniProt antimicrobial peptides into one compact JSON for EPIC-AMP.

Usage:
  python3 build_peptides.py <dramp_unzipped_xlsx_dir> <dbamp_unzipped_xlsx_dir> <uniprot.tsv> <out.json>

- DRAMP:   General dataset (.xlsx) from https://dramp.cpu-bioinfor.org/downloads/, unzipped.
- dbAMP:   dbAMP3_pepinfo.xlsx from https://ycclab.cuhk.edu.cn/dbAMP/download2024.php, unzipped.
- UniProt: reviewed entries with keyword KW-0929 (Antimicrobial), TSV from rest.uniprot.org with fields
           accession,protein_name,organism_name,sequence,ft_peptide,xref_pdb,lit_pubmed_id,cc_function
Records with identical sequences are merged; each keeps links to every database that lists it.
"""
import csv, json, re, sys, xml.etree.ElementTree as ET

dramp_dir, dbamp_dir, uniprot_tsv, out = sys.argv[1:5]
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
CANON = re.compile(r'^[ACDEFGHIKLMNPQRSTVWY]+$')
MIN_LEN, MAX_LEN = 10, 100
MAX_IDS_PER_DB = 3


def read_xlsx(src):
    strings = []
    for _, el in ET.iterparse(f'{src}/xl/sharedStrings.xml'):
        if el.tag == NS + 'si':
            strings.append(''.join(t.text or '' for t in el.iter(NS + 't')))
            el.clear()

    def col(ref):
        n = 0
        for ch in re.match(r'[A-Z]+', ref).group():
            n = n * 26 + ord(ch) - 64
        return n - 1

    rows, header = [], None
    for _, el in ET.iterparse(f'{src}/xl/worksheets/sheet1.xml'):
        if el.tag != NS + 'row':
            continue
        vals = {}
        for c in el.findall(NS + 'c'):
            v = c.find(NS + 'v')
            if v is not None:
                vals[col(c.get('r'))] = strings[int(v.text)] if c.get('t') == 's' else v.text
        if header is None:
            header = [vals.get(i, '') for i in range(max(vals) + 1)]
        else:
            rows.append({header[i]: vals.get(i, '') for i in range(len(header))})
        el.clear()
    return rows


def clip(s, n):
    s = re.sub(r'#{2,}', '; ', s or '')
    s = re.sub(r'\s*;\s*;+', '; ', s)
    s = re.sub(r'\s+', ' ', s.strip()).strip('; ')
    low = s.lower()
    if low in ('', 'none', 'not found', 'no entry found', 'not included yet', 'not available') \
            or re.match(r'^no\s[\w\s-]*(information|data)\s*(found|available|presented)?[.\s]*$', low) \
            or re.match(r'^no\s[\w\s-]*(found|available)\s*(in the reference\(s\).*)?$', low):
        return ''
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def first_pmid(s):
    m = re.search(r'\b\d{5,9}\b', s or '')
    return m.group() if m else ''


def pdb_ids(s):
    return re.findall(r'\b[0-9][A-Za-z0-9]{3}\b', s or '')


merged = {}   # seq -> record dict
counts = {}


def add(db, acc, seq, name='', activity='', targets='', hemo='', pdb=(), pmid='',
        cyto='', chem=(), origin='', family='', binding=''):
    seq = (seq or '').strip().upper()
    if not CANON.match(seq) or not MIN_LEN <= len(seq) <= MAX_LEN:
        return
    counts[db] = counts.get(db, 0) + 1
    r = merged.setdefault(seq, {'name': '', 'activity': '', 'targets': '', 'hemo': '', 'pdb': [], 'pmid': '',
                                'cyto': '', 'chem': [], 'origin': '', 'family': '', 'binding': '', 'src': {}})
    ids = r['src'].setdefault(db, [])
    if acc not in ids and len(ids) < MAX_IDS_PER_DB:
        ids.append(acc)
    # First database to supply a field wins (DRAMP is loaded first, then dbAMP, then UniProt)
    for k, v in (('name', name), ('activity', activity), ('targets', targets), ('hemo', hemo), ('pmid', pmid),
                 ('cyto', cyto), ('origin', origin), ('family', family), ('binding', binding)):
        if not r[k] and v:
            r[k] = v
    if chem and not r['chem'] and any(chem):
        r['chem'] = list(chem)
    for p in pdb:
        if p.upper() not in r['pdb'] and len(r['pdb']) < 4:
            r['pdb'].append(p.upper())


# ── DRAMP General ──
for row in read_xlsx(dramp_dir):
    chem = [clip(row.get('Linear/Cyclic/Branched'), 40), clip(row.get('N-terminal_Modification'), 60),
            clip(row.get('C-terminal_Modification'), 60), clip(row.get('Other_Modifications'), 90),
            clip(row.get('Stereochemistry'), 40)]
    add('DRAMP', row['DRAMP_ID'], row.get('Sequence'), clip(row.get('Name'), 90), clip(row.get('Activity'), 200),
        clip(row.get('Target_Organism'), 700), clip(row.get('Hemolytic_activity'), 400),
        pdb_ids(row.get('PDB_ID')), first_pmid(row.get('Pubmed_ID')),
        clip(row.get('Cytotoxicity'), 400), chem, clip(row.get('Source'), 120),
        clip(row.get('Family'), 120), clip(row.get('Binding_Traget'), 120))

# ── dbAMP 3.0 ──
for row in read_xlsx(dbamp_dir):
    sources = set(t.strip() for t in (row.get('Source') or '').split('&&'))
    names = [t.strip() for t in (row.get('Name') or '').split('&&') if t.strip()]
    name = next((t for t in names if t not in sources and not t.lower().startswith('synthetic construct')),
                names[0] if names else '')
    targets = '; '.join(t.strip() for t in (row.get('Targets') or '').split('&&') if t.strip())
    add('dbAMP', row['dbAMP_ID'], row.get('Seq'), clip(name, 90), '', clip(targets, 700), '', pdb_ids(row.get('PDB')),
        origin=clip(next((t for t in sources if t), ''), 120))

# ── UniProt (reviewed, KW-0929); use annotated mature peptides when present ──
with open(uniprot_tsv, newline='') as f:
    for row in csv.DictReader(f, delimiter='\t'):
        full = row['Sequence']
        name = clip(re.sub(r'\s*\(.*$', '', row['Protein names']), 90)
        func = clip(re.sub(r'^FUNCTION:\s*', '', row.get('Function [CC]', '')).split(' {')[0], 140)
        pmid = first_pmid(row.get('PubMed ID'))
        pdbs = pdb_ids(row.get('PDB'))
        peptides = re.findall(r'PEPTIDE (\d+)\.\.(\d+);\s*/note="([^"]*)"', row.get('Peptide', ''))
        if peptides:
            for a, b, note in peptides:
                add('UniProt', row['Entry'], full[int(a) - 1:int(b)], clip(note, 90) or name, func, '', '', pdbs, pmid,
                    origin=clip(row.get('Organism', ''), 120))
        else:
            add('UniProt', row['Entry'], full, name, func, '', '', pdbs, pmid,
                origin=clip(row.get('Organism', ''), 120))

DB_ORDER = ['DRAMP', 'dbAMP', 'UniProt']
records = []
for seq, r in merged.items():
    src = [[db, i] for db in DB_ORDER for i in r['src'].get(db, [])]
    records.append([src[0][1], seq, r['name'], r['activity'], r['targets'], r['hemo'], ' '.join(r['pdb']), r['pmid'], src,
                    r['cyto'], r['chem'], r['origin'], r['family'], r['binding']])

# Reference distributions of known AMPs, so a query can be placed in context
RES_MASS = {'A':71.0788,'R':156.1875,'N':114.1038,'D':115.0886,'C':103.1388,'E':129.1155,'Q':128.1307,'G':57.0519,
            'H':137.1411,'I':113.1594,'L':113.1594,'K':128.1741,'M':131.1926,'F':147.1766,'P':97.1167,'S':87.0782,
            'T':101.1051,'W':186.2132,'Y':163.1760,'V':99.1326}
PKA = {'nterm':8.6,'cterm':3.6,'K':10.8,'R':12.5,'H':6.5,'D':3.9,'E':4.1,'C':8.5,'Y':10.1}
KD = {'A':1.8,'R':-4.5,'N':-3.5,'D':-3.5,'C':2.5,'Q':-3.5,'E':-3.5,'G':-0.4,'H':-3.2,'I':4.5,'L':3.8,'K':-3.9,
      'M':1.9,'F':2.8,'P':-1.6,'S':-0.8,'T':-0.7,'W':-0.9,'Y':-1.3,'V':4.2}
EISEN = {'A':0.62,'R':-2.53,'N':-0.78,'D':-0.90,'C':0.29,'Q':-0.85,'E':-0.74,'G':0.48,'H':-0.40,'I':1.38,'L':1.06,
         'K':-1.50,'M':0.64,'F':1.19,'P':0.12,'S':-0.18,'T':-0.05,'W':0.81,'Y':0.26,'V':1.08}


def charge7(seq):
    z = 1 / (1 + 10 ** (7 - PKA['nterm'])) - 1 / (1 + 10 ** (PKA['cterm'] - 7))
    for ch in seq:
        if ch in 'KRH':
            z += 1 / (1 + 10 ** (7 - PKA[ch]))
        elif ch in 'DECY':
            z -= 1 / (1 + 10 ** (PKA[ch] - 7))
    return z


def moment(seq):
    import math
    x = sum(EISEN[c] * math.cos(math.radians(i * 100)) for i, c in enumerate(seq))
    y = sum(EISEN[c] * math.sin(math.radians(i * 100)) for i, c in enumerate(seq))
    return math.hypot(x, y) / len(seq)


def percentiles(values):
    v = sorted(values)
    return [round(v[min(len(v) - 1, int(q / 100 * len(v)))], 3) for q in range(0, 101)]


dist_seqs = [r[1] for r in records]
reference = {
    'n': len(dist_seqs),
    'length': percentiles([len(x) for x in dist_seqs]),
    'charge': percentiles([charge7(x) for x in dist_seqs]),
    'gravy': percentiles([sum(KD[c] for c in x) / len(x) for x in dist_seqs]),
    'muH': percentiles([moment(x) for x in dist_seqs]),
    'hydrophobic': percentiles([100 * sum(c in 'AVILMFWP' for c in x) / len(x) for x in dist_seqs]),
}

meta = {
    'reference_distribution': reference,
    'fields': ['id', 'seq', 'name', 'activity', 'targets', 'hemolysis', 'pdb', 'pmid', 'sources',
               'cytotoxicity', 'chemistry', 'origin', 'family', 'binding_target'],
    'chemistry_fields': ['form', 'n_terminus', 'c_terminus', 'other_modifications', 'stereochemistry'],
    'records': len(records),
    'source_records_used': counts,
    'filter': f'canonical amino acids only, {MIN_LEN}-{MAX_LEN} residues (the range accepted by the EPIC-AMP classifier); identical sequences merged; text fields shortened',
    'sources': [
        {'db': 'DRAMP', 'dataset': 'General', 'license': 'CC BY 4.0', 'url': 'https://dramp.cpu-bioinfor.org/',
         'citation': 'Ma T, et al. DRAMP 5.0. Nucleic Acids Res. 2026; gkag989. doi:10.1093/nar/gkag989. PMID: 42876369.'},
        {'db': 'dbAMP', 'dataset': '3.0 (2024)', 'license': 'Free for academic use (dbAMP license)', 'url': 'https://ycclab.cuhk.edu.cn/dbAMP/',
         'citation': 'Yao L, et al. dbAMP 3.0: updated resource of antimicrobial activity and structural annotation of peptides in the post-pandemic era. Nucleic Acids Res. 2025; 53(D1):D364-D376. doi:10.1093/nar/gkae1019. PMID: 39540425.'},
        {'db': 'UniProt', 'dataset': 'UniProtKB/Swiss-Prot, keyword KW-0929 (Antimicrobial)', 'license': 'CC BY 4.0', 'url': 'https://www.uniprot.org/',
         'citation': 'The UniProt Consortium. UniProt: the Universal Protein Knowledgebase in 2025. Nucleic Acids Res. 2025; 53(D1):D609-D617. doi:10.1093/nar/gkae1010. PMID: 39552041.'},
    ],
}
with open(out, 'w') as f:
    json.dump({'meta': meta, 'records': records}, f, separators=(',', ':'), ensure_ascii=False)
multi = sum(1 for r in records if len({s[0] for s in r[8]}) > 1)
print('used per db:', counts, '| unique sequences:', len(records), '| in 2+ databases:', multi)
