# The follow-up email, and what EPIC-AMP does with personal data

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

## 2. How the 48-hour delay works without a scheduler

Brevo's transactional endpoint takes a `scheduledAt` timestamp **up to 72 hours
ahead**, and lets you cancel by an identifier you supply yourself
(<https://developers.brevo.com/docs/schedule-batch-sendings>). 48 < 72, so the
delay is the mail provider's job:

1. The visitor ticks the box. The browser records the moment of ticking.
2. After the analysis, the browser asks the Space to `schedule_feedback`.
3. The Space asks the consent ledger whether it may (see §3), mints a UUIDv4,
   and hands Brevo the message with `scheduledAt = now + 48 h` and
   `batchId = <that UUID>`.
4. Brevo holds it and sends it 48 hours later. Nothing on our side runs in
   between, so there is nothing to miss a tick, retry twice, or wake up wrong.
5. The UUID is the unsubscribe token. `/unsubscribe?t=<uuid>` asks the Space to
   `DELETE /v3/smtp/email/<uuid>`, which removes it from Brevo's queue if it has
   not gone out, and the ledger records the suppression either way.

A UUIDv4 is unguessable, so the token works as a capability: the cancel link
needs no login, no password and no reply, and it cannot be used to cancel
anybody else's.

## 3. Duplicate prevention is a real lock, not a hope

`scripts/consent_ledger.gs` is a **separate** Apps Script web app with its own
spreadsheet — deliberately not the analysis log, because it is different data
with a different purpose and a different retention period.

Every claim runs inside `LockService.getScriptLock()`, so the check and the
write are one step and two simultaneous submissions cannot both be told to
proceed. It refuses when:

- the address has ever used a cancel link → `unsubscribed` (permanent), or
- that address already has a follow-up pending → `already_pending`.

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
informed, and the follow-up email itself repeats why it was sent. Everything
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
| `FOLLOWUP_DELAY_HOURS` | `48` (clamped to 70 max, because Brevo's limit is 72) |

`/send` is unchanged, so the report email keeps working while you do this.

**C. The site.** Deploy as usual. `unsubscribe.html` is served at `/unsubscribe`
because `vercel.json` sets `cleanUrls`.

**D. Retention for the old log.** Set the three constants at the top of
`scripts/analysis_log_retention.gs` to match the real sheet, run `dryRunPurge()`
and read the output, then `installRetentionTrigger()`.

**E. Check it end to end.** Set `FOLLOWUP_DELAY_HOURS=1` in the Space, run one
analysis with the box ticked against an address you own, confirm the row in the
ledger says `scheduled`, use the cancel link, confirm the row says
`unsubscribed` and that nothing arrives. Then set it back to 48.

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
another person's address and cause one email 48 hours later. The dedup means at
most one pending email per address, the message says why it was sent and offers
one-click cancellation, and nothing is ever sent twice. The same is already true
of the report email. If that is not acceptable, the next step is a challenge on
submission (captcha or proof of work) or per-IP rate limiting at the Space.

## 7. What was verified, and what was not

Verified by running it:

- Space logic — 30 cases: valid/invalid addresses, consent-log down, consent-log
  refusing, Brevo refusing, Brevo unreachable, malformed and non-v4 tokens,
  already-sent, and the exact payload handed to Brevo (48.00 h ahead, batchId,
  `List-Unsubscribe`, cancel link in both HTML and plain text, no key in body).
- Ledger logic — 27 cases, Google services stubbed: wrong/empty secret, bad JSON,
  unknown action, first claim, duplicate while pending, case and whitespace
  variants of the same address, a different address, mark, unsubscribe,
  permanent suppression, an expired pending row not blocking, lock contention,
  no plaintext address in the sheet, and the purge keeping cancellations.
- Front end — in a real browser: the box is unchecked by default, its wording
  carries the purpose and the cancellation, Clear unticks it, no scheduling call
  happens when it is not ticked, the scheduling path runs when it is, failure is
  reported honestly when the mailer is unreachable, the report still downloads,
  and the unsubscribe page handles all four of its states. The privacy-notice
  assertions were dropped when the notice was removed.

**Not verified, because it cannot be from here:** nothing is deployed. The Apps
Script was tested against stubs, not Google's runtime; the Space was tested
against a stubbed `requests`, so no real Brevo call was made. Step 5E is the
test that matters and only you can run it.
