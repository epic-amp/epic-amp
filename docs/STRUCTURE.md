# Structure prediction module

## What the module does now

| Source | How it is obtained | Confidence | Runs where |
|---|---|---|---|
| **ESMFold** (unchanged) | `POST https://api.esmatlas.com/foldSequence/v1/pdb/` with the query sequence | pLDDT in the B-factor column, 0–1 scale | Meta's public endpoint |
| **RCSB PDB** | `files.rcsb.org/download/<ID>.pdb`, falling back to `.cif` | None (experimental) | Browser fetch |
| **AlphaFold DB** | `alphafold.ebi.ac.uk/api/prediction/<UniProt>` for peptides matched to a UniProt entry | pLDDT, 0–100 scale | Browser fetch |
| **AlphaFold2 / ColabFold** *(new)* | You run the official notebook, then load the file here | pLDDT read from the B-factor column | Google Colab, by you |
| **Any other model** *(new)* | Load a `.pdb`, `.cif`, `.mmcif` or `.ent` file | Auto-detected if present | Your machine only |

All five can be superposed against each other, exported as PDB or PNG, viewed
side by side, and coloured by confidence, residue type, secondary structure,
hydrophobicity or rainbow.

## Why AlphaFold2 is not run by this site

This was investigated before any code was written. Findings, with sources:

**Licences are not the obstacle.** ColabFold is MIT
(`https://github.com/sokrypton/ColabFold/blob/main/LICENSE`, "Copyright (c) 2021
Sergey Ovchinnikov"). AlphaFold2's code is Apache-2.0 and its README states:
*"While the AlphaFold code is licensed under the Apache 2.0 License, the
AlphaFold parameters and CASP15 prediction data are made available under the
terms of the CC BY 4.0 license."* Both permit reuse with attribution.

**The obstacles are the API, the hardware and privacy.**

1. **No public folding API is documented.** Neither the ColabFold README, its
   wiki, nor the MsaServer directory documents a REST endpoint, request schema,
   authentication or CORS policy for running a prediction. Full prediction is
   documented only through the `colabfold_batch` Python CLI.
2. **The public MSA server asks not to be used this way.** The wiki states:
   *"Using the server is free, however, has a few limitations. For example, we
   rate-limit requests to ensure one user does not overload the server and that
   you should not requests MSAs from multiple IPs. Thus large-scale structure
   predictions should not be done with the public MSA server."* A public web app
   folding on behalf of every visitor is exactly that pattern.
3. **AlphaFold2 cannot run in a browser.** Its README requires Linux, an NVIDIA
   GPU and up to 3 TB of disk for the databases.
4. **The one hosted endpoint needs a secret.** NVIDIA NIM documents
   `https://health.api.nvidia.com/v1/biology/deepmind/alphafold2`, but it
   requires `Authorization: Bearer $NVIDIA_API_KEY`. A static site cannot hold a
   key without handing it to every visitor. Its free-tier terms were also not
   stated on the page we read.
5. **Privacy.** Any MSA-based method sends the sequence to a third-party server
   to search databases. ColabFold's own wiki warns: *"you might not be allowed
   to send your protein sequences to a third-party server."* For unpublished
   peptides that is the user's decision, not ours to make silently.

**The implemented solution.** EPIC-AMP copies the sequence and opens the
official ColabFold notebook, where the user runs AlphaFold2 themselves on free
Colab GPUs under their own Google account and their own judgement about sending
the sequence out. The resulting file is then loaded back here for visualisation
and comparison. This adds AlphaFold2 as a real option with no licence
assumption, no key exposure, no load on anyone's free MSA server, and no
unannounced transfer of sequence data.

## Costs

| Path | Cost |
|---|---|
| ESMFold, RCSB, AlphaFold DB | Free, no account |
| ColabFold hand-off | Free Colab tier; a short peptide takes a few minutes |
| File upload | Free, entirely local |
| NVIDIA NIM (not implemented) | API key required, pricing not published on the page checked |

## Confidence reporting

Predicted models show mean pLDDT and a **per-residue bar chart** under the
viewer, using the standard AlphaFold bands (>90 very high, 70–90 confident,
50–70 low, <50 very low). Uploaded files are scanned for a plausible confidence
column: B-factors in 0–100 or 0–1 with real variation are treated as pLDDT;
anything else is shown as coordinates only, with no invented confidence.

Experimental PDB entries deliberately show no confidence plot, because their
B-factors mean something different.

## The short-peptide caveat

Whenever a **predicted** model under 30 residues is displayed, the panel states
that short peptides are often unstructured in water and fold only on contact
with a membrane, so a single conformation is one plausible model rather than
"the structure". This matters for AMPs specifically: most are helical only in
membrane-mimetic environments, and both AlphaFold2 and ESMFold will still return
a confident-looking helix.

## Error handling

| Case | Behaviour |
|---|---|
| ESMFold busy or slow | Automatic retry, then a message with a "Try again" button |
| RCSB has no `.pdb` | Falls back to `.cif` |
| AlphaFold has no model | States it plainly for that UniProt accession |
| Request hangs | 30 s timeout (90 s for ESMFold) via `AbortController` |
| Upload: wrong extension | Rejected, with the accepted list |
| Upload: over 8 MB | Rejected |
| Upload: no atom records | Rejected rather than opening an empty viewer |
| Viewer hidden | Draw calls are skipped, so no WebGL framebuffer errors |

## Verified facts behind this document

- ColabFold licence and MSA-server wording: GitHub repo, LICENSE and wiki, read 2026-10-29.
- AlphaFold2 code/parameter licences: the project README, same date.
- NVIDIA NIM endpoint and auth: `https://build.nvidia.com/deepmind/alphafold2`, same date.
- Citations: Mirdita M, *et al. Nature Methods* 2022, doi:10.1038/s41592-022-01488-1;
  Jumper J, *et al. Nature* 2021, doi:10.1038/s41586-021-03819-2.

We could not read the ColabFold paper or the AlphaFold2 paper full text (publisher
login walls), so no performance figures from them are quoted anywhere in the app.
