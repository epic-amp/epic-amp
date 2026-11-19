#!/usr/bin/env python3
"""
Merge the DBAASP cache into an existing data/peptides.json.

This is incremental on purpose. build_peptides.py rebuilds the whole file from
the DRAMP, dbAMP and UniProt source downloads; this script needs only the built
file and the DBAASP cache, so adding DBAASP does not mean re-downloading three
other databases.

    python3 scripts/fetch_dbaasp.py data/dbaasp_cache.json
    python3 scripts/merge_dbaasp.py data/peptides.json data/dbaasp_cache.json

It writes in place after a successful merge, and refuses to write anything if
the result would be smaller than what it started with.

Merge rule, the same one build_peptides.py uses: the first database to supply a
field keeps it. DBAASP is appended last, so it fills gaps and never overwrites
a curated DRAMP or dbAMP value. Where a sequence is new, the whole record comes
from DBAASP.

Attribution is mandatory under DBAASP's terms, so the source entry written into
meta carries the acknowledgement text and the citation.
"""

import json
import math
import re
import sys

CANON = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
MIN_LEN, MAX_LEN = 10, 100
MAX_IDS_PER_DB = 3
DB_ORDER = ["DRAMP", "dbAMP", "UniProt", "DBAASP"]

F = {"id": 0, "seq": 1, "name": 2, "activity": 3, "targets": 4, "hemolysis": 5, "pdb": 6,
     "pmid": 7, "sources": 8, "cytotoxicity": 9, "chemistry": 10, "origin": 11,
     "family": 12, "binding_target": 13}

PKA = {"nterm": 8.6, "cterm": 3.6, "K": 10.8, "R": 12.5, "H": 6.5,
       "D": 3.9, "E": 4.1, "C": 8.5, "Y": 10.1}
KD = {"A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5, "G": -0.4,
      "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6, "S": -0.8,
      "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2}
EISEN = {"A": 0.62, "R": -2.53, "N": -0.78, "D": -0.90, "C": 0.29, "Q": -0.85, "E": -0.74,
         "G": 0.48, "H": -0.40, "I": 1.38, "L": 1.06, "K": -1.50, "M": 0.64, "F": 1.19,
         "P": 0.12, "S": -0.18, "T": -0.05, "W": 0.81, "Y": 0.26, "V": 1.08}


def charge7(seq):
    z = 1 / (1 + 10 ** (7 - PKA["nterm"])) - 1 / (1 + 10 ** (PKA["cterm"] - 7))
    for ch in seq:
        if ch in "KRH":
            z += 1 / (1 + 10 ** (7 - PKA[ch]))
        elif ch in "DECY":
            z -= 1 / (1 + 10 ** (PKA[ch] - 7))
    return z


def moment(seq):
    x = sum(EISEN[c] * math.cos(math.radians(i * 100)) for i, c in enumerate(seq))
    y = sum(EISEN[c] * math.sin(math.radians(i * 100)) for i, c in enumerate(seq))
    return math.hypot(x, y) / len(seq)


def percentiles(values):
    v = sorted(values)
    return [round(v[min(len(v) - 1, int(q / 100 * len(v)))], 3) for q in range(0, 101)]


def clip(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    peptides_path, cache_path = sys.argv[1], sys.argv[2]

    with open(peptides_path, encoding="utf-8") as f:
        data = json.load(f)
    records, meta = data["records"], data["meta"]
    before = len(records)
    print("existing: %d records" % before)

    with open(cache_path, encoding="utf-8") as f:
        cache = json.load(f)
    incoming = list(cache.get("records", {}).values())
    print("DBAASP cache: %d records" % len(incoming))

    by_seq = {r[F["seq"]]: r for r in records}
    added = filled = skipped = 0
    gap_counts = {"targets": 0, "hemolysis": 0, "cytotoxicity": 0, "name": 0, "pmid": 0, "pdb": 0}

    for d in incoming:
        seq = (d.get("seq") or "").strip().upper()
        if not CANON.match(seq) or not MIN_LEN <= len(seq) <= MAX_LEN:
            skipped += 1
            continue
        acc = str(d.get("id") or "").strip()
        if not acc:
            skipped += 1
            continue

        rec = by_seq.get(seq)
        if rec is None:
            rec = [acc, seq, clip(d.get("name"), 90), "", clip(d.get("targets"), 700),
                   clip(d.get("hemolysis"), 400), " ".join(d.get("pdb") or [])[:23],
                   str(d.get("pmid") or ""), [["DBAASP", acc]], clip(d.get("cytotoxicity"), 400),
                   [], "", "", ""]
            records.append(rec)
            by_seq[seq] = rec
            added += 1
            continue

        ids = [s[1] for s in rec[F["sources"]] if s[0] == "DBAASP"]
        if acc not in ids and len(ids) < MAX_IDS_PER_DB:
            rec[F["sources"]].append(["DBAASP", acc])
        touched = False
        for key, limit in (("name", 90), ("targets", 700), ("hemolysis", 400), ("cytotoxicity", 400)):
            if not rec[F[key]] and d.get(key):
                rec[F[key]] = clip(d[key], limit)
                gap_counts[key] += 1
                touched = True
        if not rec[F["pmid"]] and d.get("pmid"):
            rec[F["pmid"]] = str(d["pmid"])
            gap_counts["pmid"] += 1
            touched = True
        if d.get("pdb"):
            have = rec[F["pdb"]].split()
            for p in d["pdb"]:
                if p not in have and len(have) < 4:
                    have.append(p)
                    gap_counts["pdb"] += 1
                    touched = True
            rec[F["pdb"]] = " ".join(have)
        if touched:
            filled += 1

    # keep sources in database order so record[0] stays the primary accession
    rank = {db: i for i, db in enumerate(DB_ORDER)}
    for r in records:
        r[F["sources"]].sort(key=lambda s: rank.get(s[0], 99))
        r[F["id"]] = r[F["sources"]][0][1]

    print("added %d new sequences, filled gaps in %d existing ones, skipped %d"
          % (added, filled, skipped))
    print("  gaps filled by field:", gap_counts)

    if len(records) < before:
        sys.exit("refusing to write: result (%d) is smaller than the input (%d)" % (len(records), before))

    seqs = [r[F["seq"]] for r in records]
    meta["reference_distribution"] = {
        "n": len(seqs),
        "length": percentiles([len(x) for x in seqs]),
        "charge": percentiles([charge7(x) for x in seqs]),
        "gravy": percentiles([sum(KD[c] for c in x) / len(x) for x in seqs]),
        "muH": percentiles([moment(x) for x in seqs]),
        "hydrophobic": percentiles([100 * sum(c in "AVILMFWP" for c in x) / len(x) for x in seqs]),
    }
    meta["records"] = len(records)
    meta.setdefault("source_records_used", {})["DBAASP"] = added + filled
    srcs = [s for s in meta.get("sources", []) if s.get("db") != "DBAASP"]
    srcs.append({
        "db": "DBAASP",
        "dataset": "Database of Antimicrobial Activity and Structure of Peptides",
        "license": "Open: may be accessed, downloaded, copied, used, adapted and redistributed "
                   "without restriction; acknowledgement of DBAASP as the source is required "
                   "(https://dbaasp.org/terms-and-conditions)",
        "url": "https://dbaasp.org/",
        "acknowledgement": "Data were obtained from the DBAASP (https://dbaasp.org) which is an "
                           "open-access AMP data resource supported by I. Beritashvili Center of "
                           "Experimental Biomedicine (IBCEB), Tbilisi, Georgia and the National "
                           "Institute of Allergy and Infectious Diseases (NIAID) Office of Cyber "
                           "Infrastructure and Computational Biology (OCICB) in Bethesda, MD. These "
                           "data were collected and submitted by members of the DBAASP team.",
        "citation": "Pirtskhalava M, Amstrong AA, Grigolava M, Chubinidze M, Alimbarashvili E, "
                    "Vishnepolsky B, Gabrielian A, Rosenthal A, Hurt DE, Tartakovsky M. DBAASP v3: "
                    "database of antimicrobial/cytotoxic activity and structure of peptides as a "
                    "resource for development of new therapeutics. Nucleic Acids Res. 2021; "
                    "49(D1):D288-D297. doi:10.1093/nar/gkaa991.",
    })
    meta["sources"] = srcs

    tmp = peptides_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "records": records}, f, separators=(",", ":"), ensure_ascii=False)
    import os
    os.replace(tmp, peptides_path)
    multi = sum(1 for r in records if len({s[0] for s in r[F["sources"]]}) > 1)
    print("wrote %s: %d sequences (%d in two or more databases)" % (peptides_path, len(records), multi))


if __name__ == "__main__":
    main()
