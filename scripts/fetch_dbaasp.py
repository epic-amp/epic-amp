#!/usr/bin/env python3
"""
Fetch DBAASP into a local cache that scripts/build_peptides.py can merge.

DBAASP's data access policy, read verbatim at
https://dbaasp.org/terms-and-conditions on 2026-11-19:

    "DBAASP data is openly available and may be accessed, downloaded, copied,
    used, adapted, and redistributed without restriction. In return, users must
    acknowledge DBAASP as the source in publications, presentations, datasets,
    software, and other public materials that use DBAASP data or tools."
    "This acknowledgement requirement applies whether the data is used in its
    original form or after modification, combination with other data, or
    redistribution."

So redistribution is permitted and attribution is mandatory. The acknowledgement
and the citation are in THIRD_PARTY_NOTICES.md and in the app's About tab.

Two phases, both resumable, because the API gives summaries in bulk but the
measured activities only one peptide at a time:

  1. /peptides          paginated summaries -> every id, name, sequence
  2. /peptides/{id}     only for sequences that survive the EPIC-AMP filter,
                        for the MIC values, target strains and haemolysis

Usage:
    python3 scripts/fetch_dbaasp.py data/dbaasp_cache.json
    python3 scripts/fetch_dbaasp.py data/dbaasp_cache.json --list-only
    python3 scripts/fetch_dbaasp.py data/dbaasp_cache.json --limit 500

Stdlib only, like the rest of the build. Re-running resumes: anything already
in the cache is not fetched again.
"""

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

API = "https://dbaasp.org"
PAGE = 200
CANON = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
MIN_LEN, MAX_LEN = 10, 100
PAUSE = 0.12          # be a polite guest on someone else's server
WORKERS = 8           # the detail endpoint is latency-bound; 8 in flight is modest
SAVE_EVERY = 200
RETRIES = 3
UA = "epic-amp-dataset-builder/1.0"


def get(path, tries=RETRIES):
    url = API + path
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            if attempt == tries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
            print("  retry %d/%d after %r" % (attempt + 2, tries, exc), file=sys.stderr)
    return None


def fetch_summaries():
    """Every peptide the API will list, as {id, name, sequence, ...}."""
    first = get("/peptides?limit=1&offset=0")
    total = first.get("totalCount", 0)
    print("DBAASP reports %d peptides" % total)
    out, offset = [], 0
    while offset < total:
        page = get("/peptides?limit=%d&offset=%d" % (PAGE, offset))
        rows = page.get("data") or []
        if not rows:
            break
        out.extend(rows)
        offset += len(rows)
        print("\r  summaries %d/%d" % (len(out), total), end="", file=sys.stderr)
        time.sleep(PAUSE)
    print(file=sys.stderr)
    return out


def usable(row):
    seq = (row.get("sequence") or "").strip().upper()
    return bool(CANON.match(seq)) and MIN_LEN <= len(seq) <= MAX_LEN


def text_targets(detail):
    """One readable line per measured activity, strain and all."""
    out = []
    for a in detail.get("targetActivities") or []:
        measure = ((a.get("activityMeasureGroup") or {}).get("name") or "").strip()
        species = ((a.get("targetSpecies") or {}).get("name") or "").strip()
        conc = (a.get("concentration") or "").strip()
        unit = ((a.get("unit") or {}).get("name") or "").strip()
        if not species:
            continue
        if measure and conc:
            out.append("%s (%s=%s%s)" % (species, measure, conc, (" " + unit) if unit else ""))
        else:
            out.append(species)
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return "; ".join(uniq)


def text_lysis(detail, want_blood):
    """Haemolysis and cytotoxicity are the same table in DBAASP, split by target cell."""
    out = []
    for a in detail.get("hemoliticCytotoxicActivities") or []:
        cell = ((a.get("targetCell") or {}).get("name")
                if isinstance(a.get("targetCell"), dict) else a.get("targetCell")) or ""
        cell = str(cell).strip()
        is_blood = bool(re.search(r"erythrocyte|rbc|blood|haemolys|hemolys", cell, re.I))
        if is_blood != want_blood:
            continue
        measure = (a.get("activityMeasureForLysisGroup") or a.get("activityMeasureForLysisValue") or "")
        if isinstance(measure, dict):
            measure = measure.get("name") or ""
        conc = (a.get("concentration") or "").strip()
        unit = ((a.get("unit") or {}).get("name") or "") if isinstance(a.get("unit"), dict) else (a.get("unit") or "")
        bit = cell or "cells"
        if measure and conc:
            bit += " (%s=%s%s)" % (str(measure).strip(), conc, (" " + str(unit).strip()) if unit else "")
        out.append(bit)
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return "; ".join(uniq)


def compact(detail, summary):
    pdbs = []
    for p in detail.get("pdbs") or []:
        code = (p.get("pdbId") or p.get("name") or p.get("id") if isinstance(p, dict) else p) or ""
        code = str(code).strip().upper()
        if re.match(r"^[0-9][A-Z0-9]{3}$", code) and code not in pdbs:
            pdbs.append(code)
    pmid = ""
    for art in detail.get("articles") or []:
        if isinstance(art, dict) and art.get("pubmedId"):
            pmid = str(art["pubmedId"]).strip()
            break
    return {
        "id": detail.get("dbaaspId") or summary.get("dbaaspId") or detail.get("id"),
        "seq": (detail.get("sequence") or summary.get("sequence") or "").strip().upper(),
        "name": (detail.get("name") or summary.get("name") or "").strip(),
        "targets": text_targets(detail),
        "hemolysis": text_lysis(detail, True),
        "cytotoxicity": text_lysis(detail, False),
        "pdb": pdbs[:4],
        "pmid": pmid,
        "synthesis": (detail.get("synthesisType") or {}).get("name", "") if isinstance(detail.get("synthesisType"), dict) else "",
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    out_path = args[0]
    list_only = "--list-only" in flags
    cap = next((int(f.split("=", 1)[1]) for f in flags if f.startswith("--limit=")), None)
    if cap is None and "--limit" in flags:
        cap = int(sys.argv[sys.argv.index("--limit") + 1])

    cache = {"records": {}, "meta": {}}
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            cache = json.load(f)
        cache.setdefault("records", {})
        print("resuming: %d peptides already cached" % len(cache["records"]))

    summaries = fetch_summaries()
    keep = [r for r in summaries if usable(r)]
    print("%d of %d pass the EPIC-AMP filter (canonical residues, %d-%d long)"
          % (len(keep), len(summaries), MIN_LEN, MAX_LEN))
    if list_only:
        return

    todo = [r for r in keep if str(r.get("id")) not in cache["records"]]
    if cap:
        todo = todo[:cap]
    print("fetching detail for %d peptides (%d already cached)" % (len(todo), len(keep) - len(todo)))

    lock = threading.Lock()
    state = {"done": 0, "failed": 0, "t0": time.time()}

    def one(row):
        pid = str(row.get("id"))
        try:
            detail = get("/peptides/%s" % pid)
        except Exception as exc:                          # noqa: BLE001
            with lock:
                state["failed"] += 1
            return pid, None, exc
        return pid, compact(detail, row), None

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(one, r): r for r in todo}
            for fut in as_completed(futures):
                pid, rec, err = fut.result()
                with lock:
                    if rec is not None:
                        cache["records"][pid] = rec
                    state["done"] += 1
                    n = state["done"]
                    if n % 50 == 0:
                        rate = n / max(1e-6, time.time() - state["t0"])
                        left = (len(todo) - n) / max(1e-6, rate)
                        print("\r  detail %d/%d  %.0f/s  ~%d min left  (%d failed)"
                              % (n, len(todo), rate, left / 60, state["failed"]),
                              end="", file=sys.stderr)
                    if n % SAVE_EVERY == 0:
                        save(out_path, cache)
    except KeyboardInterrupt:
        print("\ninterrupted - saving what we have", file=sys.stderr)
    print(file=sys.stderr)
    if state["failed"]:
        print("%d peptides could not be fetched; re-run to retry just those" % state["failed"])
    save(out_path, cache)
    print("wrote %s with %d peptides" % (out_path, len(cache["records"])))


def save(path, cache):
    cache["meta"] = {
        "source": "DBAASP (https://dbaasp.org)",
        "fetched": time.strftime("%Y-%m-%d"),
        "licence": "Open; redistribution permitted, acknowledgement of DBAASP required "
                   "(https://dbaasp.org/terms-and-conditions, read 2026-11-19)",
        "count": len(cache["records"]),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
