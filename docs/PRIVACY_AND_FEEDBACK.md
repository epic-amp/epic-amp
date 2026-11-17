# The survey invitation, and what EPIC-AMP does with personal data

Written for whoever runs EPIC-AMP next, and for a lawyer reviewing it.
Everything below was read from the code and from the providers' own
documentation on 2026-11-17. Where something is an assumption, it says so.

---

## 1. What the code actually is

The feature request assumed a backend, a database, SendGrid, and Vercel Cron.
None of those exist. What is actually deployed:

| Assumed | Reality |
|---|---|
| A backend / API routes | **None.** `index.html`, `data/`, images, `vercel.json`. The old `api/predict.js` was deleted when predictions moved back to a direct browser connection. |
| A database | **None.** One static `data/peptides.json`. |
| SendGrid | **Not used anywhere.** Mail goes through the Hugging Face Space `nonzeroexit/AMP-Mailer`, which calls **Brevo** (`api.brevo.com`) with `BREVO_API_KEY` from the Space's environment. |
| Vercel Cron / a scheduled function | **Not configured.** `vercel.json` has no `functions` and no `crons` block; it is static hosting with two security headers and a cache rule. |
| Somewhere to store consent | The closest thing is a Google Apps Script web app that appends `{email, label, confidence, sequence[:50]}` to a private Google Sheet. |

So the feature was built on what is there, and it needs **no cron job, no queue
and no database**.

## 2. One invitation, sent at once

The invitation goes out as soon as the analysis finishes. There is no delay, no
queue and no scheduler:

1. The visitor ticks the box. The browser records the moment of ticking.
2. After the analysis, the browser asks the Space to `send_survey`.
3. The Space refuses unless `SURVEY_URL` is set — an invitation with no survey
   behind it is worse than no invitation — then asks the ledger whether this
   address may be invited (§3), mints a UUIDv4, and mails it through Brevo.
4. That UUID is the opt-out token. `/unsubscribe?t=<uuid>` records the choice in
   the ledger, and no later analysis or survey round can reach that address.

A UUIDv4 is unguessable, so the opt-out link works as a capability: it needs no
login, no password and no reply, and it cannot be used against anybody else.

Nothing is queued at Brevo, so there is never anything to recall. What the
opt-out does is make the choice stick for the future.

## 3. Duplicate prevention is a real lock, not a hope

`scripts/consent_ledger.gs` is a **separate** Apps Script web app with its own
spreadsheet — deliberately not the analysis log, because it is different data
with a different purpose and a different retention period.

Every claim runs inside `LockService.getScriptLock()`, so the check and the
write are one step and two simultaneous submissions cannot both be told to
proceed. It refuses when:

- the address has ever used a cancel link → `unsubscribed` (permanent), or
- that address was already invited to this survey round → `already_invited`.
  Bumping `SURVEY_ROUND` opens a new round, so people who have not opted out can
  be invited to a genuinely new survey later.

The lock timing out refuses too. If the ledger cannot be reached at all, the
Space schedules **nothing** — no provable consent means no email.

**The address is not stored.** The ledger keeps `HMAC-SHA256(lowercased address,
salt)`, with the salt in Script Properties. That is enough to recognise the same
person asking again, and not enough to write to them. It also means the consent
sheet is not a list of researchers' email addresses sitting in Google Drive.

The ledger stores both `consent_at` (from the visitor's clock, so indicative)
and `created_at` (server time, authoritative).

## 4. Where every piece of personal data goes

| Data | Lawful basis used | Processor | Stated retention | Enforced by |
|---|---|---|---|---|
| Peptide sequence | Performing the service asked for | Hugging Face; Meta's ESMFold if the 3D step is opened | Not stored by us | n/a |
| Email address, to send the report | Performing the service asked for | Brevo | Not kept by us after delivery | Brevo |
| Analysis log: address, label, confidence, first 50 residues | — see §6.4 | Google Sheets | 12 months *intended* | `scripts/analysis_log_retention.gs` — **not installed yet** |
| Follow-up consent | Consent (Art. 6(1)(a)) | Google Sheets, hashed | 24 months; cancellations kept as a bare hash | `purgeExpired()` daily trigger in `consent_ledger.gs` |

No cookies, no analytics, no trackers, no `localStorage` — verified by grep, not
assumed.

**None of this is disclosed to visitors.** A privacy notice setting out this
table was added to the About tab and then removed at the project owner's
request on 2026-11-17. The consent checkbox still states the purpose, the
frequency and that it can be cancelled, which is what makes that consent
informed, and the invitation itself repeats why it was sent. Everything
else in this table is now undisclosed. See §6.4.

## 5. Deploying it

**A. The consent ledger.** New spreadsheet → Extensions → Apps Script → paste
`scripts/consent_ledger.gs`. Set script properties `SHARED_SECRET`,
`EMAIL_HASH_SALT` (two different long random strings) and `RETENTION_MONTHS=24`.
Run `setup()` once. Deploy as a web app, execute as **Me**, access **Anyone**.
Keep the `/exec` URL.

> Never change `EMAIL_HASH_SALT` afterwards. Every stored hash, including every
> suppression, stops matching and people who cancelled could be emailed again.

**B. The Space.** Replace `app.py` in `nonzeroexit/AMP-Mailer` with
`space/app.py`. Add these as **Settings → Secrets**, never in the file:

| Secret | Value |
|---|---|
| `BREVO_API_KEY` | already set |
| `CONSENT_LOG_URL` | the `/exec` URL from step A |
| `CONSENT_LOG_SECRET` | the same string as `SHARED_SECRET` |
| `SITE_URL` | `https://epic-amp-v2.vercel.app` |
| `SURVEY_URL` | the live survey. **While it is empty nothing is sent at all.** |
| `SURVEY_ROUND` | `1`; bump it to invite past recipients to a new survey |

`/send` is unchanged, so the report email keeps working while you do this.

**C. The site.** Deploy as usual. `unsubscribe.html` is served at `/unsubscribe`
because `vercel.json` sets `cleanUrls`.

**D. Retention for the old log.** Set the three constants at the top of
`scripts/analysis_log_retention.gs` to match the real sheet, run `dryRunPurge()`
and read the output, then `installRetentionTrigger()`.

**E. Turn it on.** The box is hidden until `SURVEY_ENABLED = true` in
`index.html`, so set `SURVEY_URL` in the Space first, then flip that constant.
In that order the box never offers something that cannot be delivered.

**F. Check it end to end.** Run one analysis with the box ticked against an
address you own. Confirm the invitation arrives, the ledger row says `sent`, a
second run with the same address is refused as `already_invited`, and the
opt-out link flips the row to `unsubscribed` and blocks a third.

## 6. For legal review — not compliance advice

I am not a lawyer and this is not a compliance opinion. These are the points
where a decision is needed rather than a code change.

**6.1 The controller is in Egypt, and the request mentioned Italy.** Nothing in
the project explains the Italian angle, so it is recorded here as an open
question rather than answered. The controller is BCBU at Zewail City, Giza.
If the tool is offered to people in the EU, GDPR can apply extraterritorially
(Art. 3(2)(a)), and where it does, Art. 27 requires a representative
established in the EU. Egypt's own Personal Data Protection Law (Law 151/2020)
applies in any case and has its own consent, notice and licensing provisions.
If an Italian institution is a joint controller, or Italian users are
specifically targeted, the Codice Privacy and the Garante's guidance come in
too. **Whether a representative, a DPO, a registration or a specific form of
informativa is required is a question for counsel in each of those
jurisdictions.**

**6.2 Is a feedback request "direct marketing"?** Under the ePrivacy Directive
(Art. 13) and the Italian implementation, unsolicited commercial email needs
prior consent, and supervisory authorities differ on whether a satisfaction
survey counts. We did not rely on that distinction: the email goes only on an
unticked-by-default, specific, informed opt-in, which is the conservative
reading. Worth confirming that the wording in the app reads as consent for
*this* purpose and nothing wider.

**6.3 Consent is recorded as a hash, on purpose.** Art. 7(1) asks the controller
to be able to demonstrate consent. The ledger can: given an address, the hash
reproduces and the row shows the timestamp and the notice version. It cannot
produce a list of addresses that consented. **Confirm counsel is content with
proof-on-presentation rather than a retained address list** — the alternative is
storing researchers' addresses in Google Drive for 24 months, which is worse.

**6.4 The analysis log is the real exposure, and there is no notice.** The app
sends every entered address, with the label, confidence and the first 50
residues, to a Google Sheet. There is **no notice of any kind** in the app: one
was written and then removed at the owner's request, so this is the position as
it stands.

- GDPR Art. 13 and Art. 14 require this information to be given to the person
  at the point of collection, not held in a repository file. **A reviewer will
  look for it first.** Restoring it is one revert; a three-line version naming
  what is stored, for how long, and who to write to would also do.
- The remaining points stand regardless of the notice:

- Rows collected before today were collected without that transparency. Whether
  to purge them is a decision for counsel; it is one menu action.
- Its lawful basis is left blank in §4 on purpose. "So we can see the tool is
  working" is a legitimate interest argument that needs a balancing test, or the
  logging should be minimised instead.
- **Recommended, and deliberately not done without being asked:** stop logging
  the plaintext address. A salted hash answers "how many distinct users" just as
  well and removes the liability entirely. One line in `index.html`.
- Nothing enforces 12 months, or any other period, until step 5D is done. The
  log currently grows without limit.

**6.5 Transfers.** Brevo is in the EU (France). Google and Hugging Face process
outside the EU and Egypt. Standard contractual clauses and processor terms need
checking for each.

**6.6 The sequence may be unpublished work.** Not personal data, but the notice
now states plainly that the sequence goes to Hugging Face and, on the 3D step,
to Meta's public ESMFold endpoint, so researchers can judge that for themselves.

**6.7 Residual abuse risk — a product risk, not a legal one.** The Space's
endpoints are public, as they must be for a static site. Someone could submit
another person's address and cause one invitation. The dedup means one per
address per round, the message says why it was sent and offers a one-click
opt-out, and nothing is ever sent twice. The same is already true of the report
email. If that is not acceptable, the next step is a challenge on submission
(captcha or proof of work) or per-IP rate limiting at the Space.

## 7. What was verified, and what was not

Verified by running it:

- Space logic — 20 cases: valid/invalid addresses, `SURVEY_URL` unset (refuses
  and touches nothing), ledger down, ledger refusing, Brevo refusing, Brevo
  unreachable, malformed and non-v4 tokens, and the exact payload handed to
  Brevo (no `scheduledAt`, batchId, `List-Unsubscribe`, survey link and opt-out
  link in both HTML and plain text, no key in the body).
- Ledger logic — 29 cases, Google services stubbed: wrong/empty secret, bad
  JSON, unknown action, first claim, the same address refused twice in a round,
  case and whitespace variants, a different address, mark, unsubscribe,
  permanent opt-out, a new round inviting a past recipient, an opt-out
  outliving a new round, lock contention, no plaintext address in the sheet,
  and the purge keeping opt-outs.
- Front end — 19 cases in a real browser, in both states of `SURVEY_ENABLED`:
  off, the box is absent and a full run sends nothing; on, it is unchecked by
  default, the wording names the survey and the single email, Clear unticks it,
  no call reaches the survey endpoint when it is not ticked, the send path runs
  when it is, failure is reported honestly when the mailer is unreachable, the
  report still downloads, and the unsubscribe page handles its states.

**Not verified, because it cannot be from here:** nothing is deployed. The Apps
Script was tested against stubs, not Google's runtime; the Space was tested
against a stubbed `requests`, so no real Brevo call was made. Step 5E is the
test that matters and only you can run it.
