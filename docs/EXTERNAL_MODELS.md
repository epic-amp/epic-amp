# External model assessment

Each candidate was assessed for scientific suitability, licensing, integration
method, computational requirements and limitations before any code was written.
Facts here were read from the sources cited on 2026-10-29; nothing is inferred.

---

## 1. HemoPI2 — haemolysis — **not integrated**

**What it is.** Web server and standalone from Raghava's group (IIIT-Delhi)
predicting haemolytic activity against mammalian red blood cells. Regression
(Random Forest) predicts HC50/EC50 in µM; classification offers RF on Pfeature
composition, ESM2-t6 embeddings, and hybrids with MERCI motifs.
Citation: Rathore AS, Kumar N, Choudhury S, *et al.* "Prediction of hemolytic
peptides and their hemolytic concentration." *Commun Biol* 8, 176 (2025).
doi:10.1038/s42003-025-07615-w

**Scientific suitability.** High. Trained on 1,926 experimentally validated
haemolytic peptides (1,540 cross-validation, 386 independent, per the download
page). It predicts an actual HC50 rather than a class, which is what the
selectivity window in EPIC-AMP needs.
*We could not verify its reported AUROC/MCC*: the Nature article redirects to a
login page, and the figures are not printed on the web server pages.

**Licensing status — the blocker.**
- Code: `https://github.com/raghavagps/hemopi2` carries a full **GPL-3.0**
  `LICENSE.txt`.
- Weights: **not in the repository.** The README states the model directory was
  "compressed and uploaded on our webserver", distributed as `Model.zip` from
  `https://webs.iiitd.edu.in/raghava/hemopi2/download.html`.
  **That page states no licence at all**, and neither does the web server.
- The site's "Vision" statement ("we envision a future where all resources
  freely accessible…") is an aspiration, not a licence grant.

Publicly downloadable is not the same as openly licensed. Redeploying those
weights inside our own service would assume a permission nobody has given.

**If you want it, the clean route** (requires a decision you must make, not me):
1. Email the authors (Prof. G.P.S. Raghava, IIIT-Delhi) asking for written
   permission to redistribute `Model.zip` inside a hosted service, or
2. Use only the GPL-3.0 code with weights **you** retrain on openly licensed
   haemolysis data, or
3. Link out to their web server so the user runs it themselves — no
   redistribution, no licence question.

**Integration method if permission is granted.** A separate Hugging Face Space
(Python), called from the browser exactly like the existing AMP classifier. The
RF regression path needs only scikit-learn, pandas and numpy. The default
classification path additionally needs PyTorch, transformers and the ESM library
— far heavier, and ESM2 embeddings on CPU are slow.

**Limitations to carry into the UI if integrated.** Trained on published HC50
values measured under varied protocols and red-cell sources; GPL-3.0 means any
code you convey must also be GPL-3.0.

---

## 2. ToxinPred3 — general toxicity — **not integrated**

**What it is.** Raghava-group peptide toxicity classifier.
Citation: Rathore AS, *et al.* *Comput Biol Med* 2024;179:108926. PMID 39038391.
Trained on 5,518 toxic and 5,518 non-toxic peptides (4,414 + 4,414 training,
1,104 + 1,104 independent, per the download page).

**Reported performance** (from the PubMed abstract, on the authors' own 20%
independent split): Extra Trees on composition features AUROC 0.95, MCC 0.78;
motif + ML hybrid AUROC 0.98, MCC 0.81.

**Licensing.** `https://github.com/raghavagps/toxinpred3` carries a full
**GPL-3.0** `LICENSE`, and unlike HemoPI2 the compressed model ships in the
repository. A `toxinpred3` package exists on PyPI (v1.4, ~10 MB wheel, so
weights are bundled) but **its PyPI metadata states no licence**.

**Why it is not integrated.**
1. **Wrong endpoint.** It predicts "toxic / non-toxic", largely learned from
   venom and toxin sequences. It is not a cytotoxicity (CC50, mammalian cell
   line) model, so presenting it as the cytotoxicity feature you asked for would
   misrepresent what it measures.
2. **No backend.** EPIC-AMP is a static page plus a Hugging Face Space. Running
   ToxinPred3 needs a Python service — straightforward to add as a second Space,
   but it is a deployment decision with a running cost, not a code change.

**Integration method if you want it.** Separate Hugging Face Space:
`pip install toxinpred3`, wrap `toxinpred3.py` in a Gradio endpoint, call it
from the browser. Stack is scikit-learn + pandas + numpy + the bundled MERCI
binary; no GPU. Expect ~1 s per peptide.

---

## 3. Cytotoxicity (CC50) — **no suitable validated model found**

**What was looked for.** A model predicting cytotoxic concentration against
mammalian cell lines, and a redistributable dataset to train one.

**What exists.**
- **DBAASP** (`https://dbaasp.org`) records antimicrobial *and* haemolytic /
  cytotoxic activities. Its terms are unusually permissive and were confirmed
  verbatim: *"DBAASP data is openly available and may be accessed, downloaded,
  copied, used, adapted, and redistributed without restriction. In return, users
  must acknowledge DBAASP as the source."* **This corrects an earlier note in
  this project that said DBAASP had no licence — it does, and it is open.**
  We could not confirm record counts or the exact CC50/cell-line fields, because
  those pages render dynamically and the REST documentation page returned only a
  stub.
- **HAPPENN**: no authoritative source located.
- No CC-licensed peptide cytotoxicity dataset was identified.

**Honest limitation.** Cytotoxicity is cell-line dependent (HeLa, HEK293,
fibroblasts and red cells give different answers), assay dependent (MTT, LDH,
trypan blue) and exposure dependent. A single "cytotoxicity score" without
naming the cell line and assay is close to meaningless. That is why this is not
shipped as a number.

**Reproducible pipeline if you want to build one** — the honest version:
1. Pull DBAASP records with cytotoxicity measurements through its REST API, and
   record the citation requirement.
2. Keep only entries with a named cell line and a numeric CC50 in µM; convert
   µg/ml using the peptide mass.
3. Model **one cell line at a time** (likely only HEK293 and HeLa will have
   enough records). Report n per model and refuse to ship any with n < 300.
4. Split by sequence-identity clusters, exactly as `scripts/fit_haemolysis.py`
   already does, so near-duplicates cannot leak across folds.
5. Report cluster-aware AUC with a bootstrap CI, calibrate on out-of-fold
   predictions, and ship an applicability-domain threshold.
6. Publish the training script in this repo so the numbers are reproducible.

Step 3 is the gate. If the data does not support a model, the right outcome is
not to ship one.

---

## Outcome

No haemolysis or cytotoxicity prediction ships in EPIC-AMP.

A logistic haemolysis model was fitted here on 499 published peptides with
measured HC50 values and validated with similarity-aware cross-validation
(AUC 0.744, 95% CI 0.701–0.788, Platt-calibrated). It was removed at the
project owner's decision: an AUC in the mid-0.7s ranks candidates but is not
strong enough to put a safety number in front of a user, and a weak prediction
beside well-validated ones devalues the whole tool. The model, its fitting
script and its validation write-up remain in the repository history.

Measured haemolysis and cytotoxicity values from the literature are still shown
in the Known Peptides records, because those are published measurements rather
than predictions.
