# Third-party notices

EPIC-AMP is a static web page. It bundles no third-party source code in the
repository; the libraries below are loaded from public CDNs at run time, and the
services are called from the visitor's browser. Licences were checked on
2026-10-29 at the URLs given.

## JavaScript libraries (loaded from CDN)

| Component | Version | Licence | Source |
|---|---|---|---|
| 3Dmol.js | 2.4.2 | BSD-3-Clause ("3Dmol.js incorporates code from GLmol, Three.js, and jQuery and is licensed under a BSD-3-Clause license", Copyright (c) 2014 University of Pittsburgh and contributors) | https://github.com/3dmol/3Dmol.js |
| jsPDF | 2.5.1 | MIT | https://github.com/parallax/jsPDF |
| jsPDF-AutoTable | 3.5.23 | MIT | https://github.com/simonbengtsson/jsPDF-AutoTable |
| @gradio/client | ESM build from esm.sh | ISC (npm metadata); the Gradio project is Apache-2.0 | https://github.com/gradio-app/gradio |
| Font Awesome Free | 6.0.0 | Icons CC BY 4.0, fonts SIL OFL 1.1, code MIT | https://github.com/FortAwesome/Font-Awesome |
| IBM Plex Sans / IBM Plex Mono / Source Code Pro | Google Fonts | SIL Open Font License 1.1 | https://fonts.google.com |

## Peptide data redistributed in `data/peptides.json`

This file is a processed subset: standard amino acids only, 10–100 residues,
identical sequences merged, annotation text shortened. It is **not** an official
release of any of these databases, and EPIC-AMP is not affiliated with or
endorsed by them.

| Source | Licence / terms | Attribution required |
|---|---|---|
| DRAMP 5.0, General dataset | CC BY 4.0 (stated on dramp.cpu-bioinfor.org) | Ma T, Huang Y, Liu H, Wu W, Ren L, Akhtar F, Nawaz M, Hua Z, Zheng H, Lao X. DRAMP 5.0. *Nucleic Acids Research* 2026; gkag989. doi:10.1093/nar/gkag989. PMID 42876369 |
| dbAMP 3.0 | "dbAMP data are licensed for academic use free of charge" (dbAMP LICENSE file). Commercial use is **not** granted. | Yao L, Guan J, Xie P, Chung CR, *et al.* dbAMP 3.0. *Nucleic Acids Research* 2025; 53(D1):D364–D376. doi:10.1093/nar/gkae1019. PMID 39540425 |
| UniProtKB/Swiss-Prot (keyword KW-0929), release 2026_03 | CC BY 4.0 | The UniProt Consortium. UniProt: the Universal Protein Knowledgebase in 2025. *Nucleic Acids Research* 2025; 53(D1):D609–D617. doi:10.1093/nar/gkae1010. PMID 39552041 |

**Commercial-use limitation:** because dbAMP is licensed for academic use only,
`data/peptides.json` as a whole must not be used commercially. Remove the
dbAMP-sourced records before any commercial deployment.

## External services called from the browser

No data is sent to these services unless the visitor triggers the relevant
action. Each call sends only the peptide sequence being analysed.

| Service | Used for | Terms |
|---|---|---|
| Hugging Face Space `nonzeroexit/AMP-Classifier` | AMP classification and MIC prediction | Operated by the EPIC-AMP authors |
| Hugging Face Space `nonzeroexit/AMP-Mailer` | Emailing the PDF report | Operated by the EPIC-AMP authors |
| RCSB Protein Data Bank (`files.rcsb.org`) | Experimental structures | Data released to the public domain (CC0) — https://www.rcsb.org/pages/usage-policy |
| AlphaFold Protein Structure Database (EMBL-EBI) | Predicted structures | CC BY 4.0. Varadi M, *et al.* *Nucleic Acids Research* 2024; 52(D1):D368–D375. doi:10.1093/nar/gkad1011 |
| ESM Metagenomic Atlas (`api.esmatlas.com`) | ESMFold structure prediction of the visitor's sequence | Public endpoint operated by Meta. **No terms of use are published at the endpoint**; the ESM code itself is MIT. Treated as a best-effort third-party service, and the interface tells the visitor their sequence is sent there. |
| PubMed, DRAMP, dbAMP, UniProt websites | Outbound links only | No data sent |

## Structure prediction referenced by the interface

| Component | Licence | Attribution |
|---|---|---|
| ESMFold / ESM | MIT (facebookresearch/esm) | Lin Z, *et al.* Evolutionary-scale prediction of atomic-level protein structure with a language model. *Science* 2023; 379:1123–1130. doi:10.1126/science.ade2574 |
| AlphaFold Protein Structure Database | CC BY 4.0 | Varadi M, *et al.* AlphaFold Protein Structure Database in 2024. *Nucleic Acids Research* 2024; 52(D1):D368–D375. doi:10.1093/nar/gkad1011 |

EPIC-AMP does **not** bundle, redistribute or execute AlphaFold2 or ColabFold.
It reads precomputed models from the AlphaFold Database, and it can open a
structure file the user produced elsewhere. See `docs/STRUCTURE.md`.

## Models

| Model | Origin | Licence |
|---|---|---|
| AMP classifier and per-organism MIC regressors | Developed by the EPIC-AMP authors, hosted on Hugging Face | Authors' own |

## Models evaluated but deliberately not integrated

See `docs/EXTERNAL_MODELS.md` for the full assessment.

| Tool | Why not integrated |
|---|---|
| HemoPI2 (Rathore *et al.*, *Commun Biol* 8:176, 2025) | Code is GPL-3.0, but the trained weights are distributed separately as `Model.zip` from the authors' web server **with no licence stated**. Redistributing or deploying those weights would assume a permission that has not been granted. |
| ToxinPred3 (Rathore *et al.*, *Comput Biol Med* 2024;179:108926) | GPL-3.0 and technically suitable, but it predicts general peptide toxicity, not the cytotoxicity (CC50) endpoint claimed, and running it needs a Python backend this static site does not have. |
