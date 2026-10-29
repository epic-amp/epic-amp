# EPIC-AMP v3

The deployed site plus new browser-side peptide analysis tools.

## What's new

| Feature | Where | Notes |
|---|---|---|
| Physicochemical profile | **Properties** tab | Mass, net charge at any pH, C-terminal amide toggle, pI, GRAVY, hydrophobic moment μH, Boman index, aromaticity, ε280, and a charge-vs-pH curve |
| Helical wheel | **Helical Wheel** tab | 100°/residue wheel with a μH arrow. Click a residue (or type a letter) to mutate it. Undo, copy, SVG download |
| Known-peptide record view | **Known Peptides** tab | Click any row for the full source record: activity tags, assay text with linked PubMed refs, haemolysis, cytotoxicity, chemistry/modifications, Needleman–Wunsch alignment against the query |
| Filters | **Known Peptides** tab | MIC data · 3D structure · toxicity · chemistry · database |
| AMP context percentiles | **Properties** tab | Charge, μH, GRAVY, hydrophobic %, length placed against the distribution of all 28,258 known peptides (precomputed at build time) |
| Similar known peptides | **Known Peptides** tab | Top 10 of 28,258 unique peptides merged from DRAMP, dbAMP 3.0 and UniProtKB/Swiss-Prot, by edit distance or physicochemical descriptors. Runs in a Web Worker. Links to each database entry, PubMed and RCSB PDB |
| Literature cross-check | Results Dashboard | After a prediction, shows the closest known peptide and flags exact matches and novel sequences |
| Side-by-side view | 3D Structure step | Known structure and your ESMFold model shown in two synced-style viewers |
| Structure superposition | 3D Structure step | Sequence-guided alignment + Kabsch (Horn quaternion) fit of Cα atoms against your ESMFold model; reports backbone RMSD and coverage |
| Developability | **Developability** step | Haemolysis risk from a model fitted here (AUC 0.744, similarity-aware CV, calibrated), toxicity evidence from similar published peptides, protease cleavage map, selectivity window |
| Variant design | **Variant Design** step | Single-substitution scan (19 × length) and controlled paired variants, configurable constraints, Pareto ranking over risk/charge/μH/protease sites, trade-off plot |
| Guided analysis | **Analysis** tab | 6 steps with a progress bar and Back/Next buttons: Sequence → Properties → Helical Wheel → Known Peptides → 3D Structure → Submit & Email |
| 3D structure | Step 5 | Interactive 3Dmol.js viewer: ESMFold prediction of the user's sequence, experimental PDB and AlphaFold structures of similar known peptides. Hover/click residues, styles, colouring (type, pLDDT confidence, rainbow, hydrophobicity), surface, spin, PNG/PDB download |
| Exports | Sequence bar at the top of each analysis tab | CSV / JSON / FASTA with profile, prediction and neighbors |
| PDF report | Section 1 | Adds a physicochemical profile table and the top 5 known-peptide neighbors |

Citations and licenses for all three databases are in About → Data Sources, in the PDF report and in CSV/JSON exports. Keep those credits.

## Files

```
index.html        ← the whole app (replaces the old one)
data/peptides.json ← 28,258 peptides from DRAMP + dbAMP + UniProt (7.3 MB, ~1.4 MB gzipped, loaded only on search)
scripts/build_peptides.py ← rebuilds data/peptides.json
scripts/fit_haemolysis.py ← fits + validates the haemolysis model into that file
docs/VALIDATION.md        ← leakage, calibration, applicability domain, limits
docs/EXTERNAL_MODELS.md   ← HemoPI2 / ToxinPred3 assessment and why they are not integrated
THIRD_PARTY_NOTICES.md    ← licences for every library, dataset and service
vercel.json, *.png, *.jpg  ← unchanged, copied from the live site
```

## Deploy

`README.md` and `scripts/` are listed in `.vercelignore`, so they stay on your computer and are not published.

Predictions connect directly from the browser to the Hugging Face Space
(`nonzeroexit/AMP-Classifier`) with `@gradio/client`, the same way as the earlier version.
No server-side `api/` route is needed, so this folder can be deployed as-is:
drag it onto https://vercel.com/new, or run `vercel --prod` inside it.
To keep the same URL, deploy it to the existing epic-amp-v2 project.

## Rebuilding the peptide data

`data/peptides.json` merges three sources (identical sequences are combined):

| Database | Download | License |
|---|---|---|
| DRAMP 5.0, General dataset | https://dramp.cpu-bioinfor.org/downloads/ | CC BY 4.0 |
| dbAMP 3.0 (`dbAMP2024.zip` → `dbAMP3_pepinfo.xlsx`) | https://ycclab.cuhk.edu.cn/dbAMP/download2024.php | Free for academic use |
| UniProtKB/Swiss-Prot, keyword KW-0929, release 2026_03 | rest.uniprot.org (query in the script's docstring) | CC BY 4.0 |

Unzip each .xlsx into a folder, then run:
`python3 scripts/build_peptides.py <dramp_dir> <dbamp_dir> <uniprot.tsv> data/peptides.json`

Not included: APD (all rights reserved, so ask the authors for permission), CAMP (no bulk download, so contact the authors),
ADAM (server offline), and DBAASP (no license found).

## Models and validation

`scripts/fit_haemolysis.py` fits the haemolysis-risk model and writes it, with its
diagnostics, into `data/peptides.json`. It uses only the Python standard library
and takes about 50 seconds:

```bash
python3 scripts/fit_haemolysis.py data/peptides.json
```

Validation is similarity-aware: sequences are clustered at 60% identity and whole
clusters are held out, which costs 0.059 AUC against a random split. The honest
figure is AUC 0.744 (95% CI 0.701–0.788). See `docs/VALIDATION.md`.

## Licensing note

`data/peptides.json` includes dbAMP records, which are licensed for **academic use
only**. Remove them before any commercial deployment. Full details in
`THIRD_PARTY_NOTICES.md`.
