# The EPIC-AMP feedback survey

Written for whoever deploys and runs this. Read §1 before anything else: the
request this was built from assumed infrastructure that does not exist.

---

## 1. What was asked for, and what was actually built

| Asked for | What exists | What was built instead |
|---|---|---|
| "Store responses in the existing database/backend" | **No database. No backend.** The site is `index.html` plus static files on Vercel. | A private Google Sheet, written through an Apps Script web app — the same pattern already used elsewhere in this project. |
| "Implement database Row Level Security (RLS)" | RLS is a PostgreSQL feature. **There is no PostgreSQL.** | The same guarantee by other means: anonymous visitors can only write, the web app has no read endpoint, and the spreadsheet is private to its owner. See §4. Chosen by the project owner over adding Supabase. |
| "Database migration" | Nothing to migrate. | `setup()` in `scripts/survey_backend.gs` creates the sheet and its headers. |
| "Prepare a SendGrid email template" | **SendGrid is not used.** Mail goes through **Brevo**. | `space/survey_invitation_email.html` — provider-neutral table HTML that pastes into Brevo, and would work in SendGrid unchanged. |
| "Authorized administrators" | No auth system, and none was added. | Administrators are whoever the spreadsheet is shared with. Google's sign-in is the auth. There is no admin page, no admin URL and no admin password to leak. |
| Vercel serverless functions | None configured. | None added. The page talks to Apps Script directly. |

Everything else was built as asked.

## 2. The pieces

| File | Runs where | Job |
|---|---|---|
| `feedback.html` | Vercel, served at `/feedback` | The survey: ten questions, one per screen |
| `scripts/survey_backend.gs` | Apps Script, bound to a private spreadsheet | Tokens, validation, storage, `.xlsx` export, retention |
| `space/survey_invitation_email.html` | Nothing — you send it by hand | A manual invitation |
| `space/app.py` | Hugging Face Space | The separate, consent-gated automatic invitation (`docs/PRIVACY_AND_FEEDBACK.md`) |

## 3. Deploying it

**A. The spreadsheet and the script.**
1. New Google spreadsheet → Extensions → Apps Script → paste `scripts/survey_backend.gs`.
2. Project Settings → Script properties:

   | Property | Value |
   |---|---|
   | `FORM_SECRET` | a long random string; signs the anti-spam tokens |
   | `RETENTION_MONTHS` | `24` |
   | `MAX_PER_HOUR` | `60` |

3. Run `setup()` once and accept the permission prompt.
4. Deploy → New deployment → **Web app**, execute as **Me**, access **Anyone**.
   Copy the `/exec` URL.
5. **Keep the spreadsheet private.** Sharing it is how you grant admin access, so
   share it only with people who should read responses.

**B. The page.** Put that `/exec` URL into `feedback.html`:

```js
var SURVEY_ENDPOINT = 'https://script.google.com/macros/s/.../exec';
```

While it is empty the survey does not open at all — visitors get "the survey is
not open yet" and the support address. An answer can never be collected with
nowhere to put it.

**C. Vercel.** Deploy as usual. `vercel.json` already sets `cleanUrls`, so
`feedback.html` is served at `/feedback`. No new configuration, no functions, no
environment variables, no build step.

**D. Test the cross-origin call before announcing it.** This is the one part
that cannot be verified from a development machine. Apps Script answers a POST
with `Content-Type: text/plain` without a CORS preflight, which is why the page
sends it that way — but confirm it against your own deployment: open
`/feedback`, complete it, and check the row appears. If the browser console
shows a CORS error, re-deploy the Apps Script as a **new version** with access
"Anyone" (the commonest cause is a deployment still set to "Anyone with a
Google account").

**E. Optional — link the invitation.** If you use the automatic invitation,
set `SURVEY_URL` in the Hugging Face Space to
`https://epic-amp-v2.vercel.app/feedback` and set `SURVEY_ENABLED = true` in
`index.html`.

## 4. Security

### What protects what

| Requirement | How it is met |
|---|---|
| Anonymous users can submit but not read | The web app has no read endpoint. `doGet` returns a token or a one-line service name, nothing else, whatever parameters it is given. |
| Only authorised admins can read and export | The spreadsheet is private to its owner. The export runs from the spreadsheet's own menu, under the signed-in account. |
| No service-role keys or credentials in frontend code | **There are none anywhere in this design.** The page holds one URL that accepts writes and serves nothing. |
| Server-side validation | Every single-choice answer must match the server's own string exactly; anything else is rejected rather than cleaned. Multi-select is checked against a fixed list, deduplicated and length-capped. The page's own checks are convenience only. |
| Input sanitisation | Control characters stripped, whitespace collapsed, hard length caps (1000 / 500 / 2000). |
| Rate limiting | A whole-site hourly cap, counted only when a response is about to be stored, so a flood of malformed payloads cannot burn the budget for real users. |
| Anti-spam | A signed token issued on page load (proves the page was loaded, enforces a minimum ten seconds, expires after four hours, single-use so it cannot be replayed) plus an off-screen honeypot field. A bot that fills the honeypot gets a success response and is silently dropped. |
| SQL injection | Not applicable: there is no SQL. |
| XSS | Responses are never rendered back to any visitor. The page escapes everything it injects. Admins read responses in Sheets, which renders them as text. |
| Excel formula injection | Any value starting with `=`, `+`, `-`, `@`, tab or carriage return is prefixed at write time, so both the sheet and every export of it are inert. |
| No unnecessary personal data | No IP address, no user agent, no referrer, no screen size, no locale, no cookies, no analytics. The sheet has seventeen columns and none of them is an identifier we were not given deliberately. |
| An email only on consent | Stored only when question 10 is "Yes" **and** a separate consent box is ticked **and** the address parses. Answering "No" with an address in the payload stores nothing — tested. |
| Retention | A daily trigger deletes responses past `RETENTION_MONTHS`. |

### Test results

`scripts/survey_backend.gs`, 45 cases against stubbed Google services:

```
tokens          missing, malformed, forged signature, submitted instantly,
                expired, first use accepted, replay rejected
honeypot        looks accepted to the bot, nothing written
validation      unknown and empty single-choice values, multi-select empty /
                non-array / invented / duplicated, conditional detail required,
                required short answer, optional long answer
the email       "Yes" needs an address, rejects a malformed one, needs explicit
                consent, stores address and consent time when given,
                "No" + an address in the payload stores nothing
injection       = + - @ tab prefixes all neutralised, ordinary text untouched,
                <script> stored inert as data, control characters stripped,
                over-long answer capped at 2000
minimisation    no ip/agent/referrer column, row width matches the header
limits          hourly cap blocks the 4th when set to 3, lock contention fails closed
exposure        doGet returns no data, issues a token, no action reads responses
retention       expired response purged, recent ones kept
```

`feedback.html`, 72 cases in a real browser:

```
unconfigured    the survey does not open, no question renders, support address offered
flow            intro, auto-advance on choice, keyboard 1-9, progress and dots,
                every question's gate, both conditional reveals
the wire        honeypot empty, token present, exact server strings, array for
                multi-select, consent flag and ISO timestamp, and no invented
                ip/agent/referrer/screen/locale field
"No" path       no email field ever shown, nothing sent, no consent recorded
errors          too_fast, expired, rate_limited, invalid and server each explained
                in plain words, and resubmitting stays possible
duplicate       a replayed submission shows thanks, not an error
phone           no horizontal scroll at 390px, scale stacks, chips wrap,
                tap targets at least 40px
```

### What this does not claim

Not "100% secure". Specifically:

- **Nothing here is deployed, so nothing is proven end to end.** The Apps Script
  was tested against stubs, not Google's runtime. Step 3D is the test that matters.
- **The anti-spam measures raise the cost of abuse; they do not stop a determined
  attacker.** Someone willing to load the page, wait ten seconds and submit can
  send one junk response per token. The hourly cap bounds the damage; it does not
  prevent it. If the survey is attacked, add a CAPTCHA.
- **An honest respondent can still lie,** and one person can respond repeatedly
  from different sessions. This is a feedback survey, not a ballot.
- **Apps Script quotas apply.** A very large volume of submissions will hit
  Google's daily limits before it hits ours.
- **Whoever can open the spreadsheet can read every response,** including any
  email addresses given at question 10. Sharing it is the access control, so
  share it carefully.

## 5. Getting the responses out

In the spreadsheet: **EPIC-AMP Survey → Export responses to Excel (.xlsx)**.

It builds a clean copy with formatted headers, converts it to a real `.xlsx`,
saves it to your Drive and shows you the link. It includes the timestamp, every
answer, the follow-up choice, and the consent timestamp and version where one
was given. **Count responses** in the same menu gives a quick total.

The menu only appears for someone who can already open the spreadsheet, and it
runs as them. There is no export URL, so there is nothing to guess or share by
accident.

## 6. Privacy

- The survey is anonymous. No IP address, no user agent, no cookies, no analytics.
- An email address is stored only on an explicit "Yes" plus a separate ticked
  consent box, and the page says what it will be used for and that it goes on no
  mailing list.
- Responses are deleted after `RETENTION_MONTHS` (24 by default).
- **Open point:** there is no privacy notice in the main app. One was written and
  removed at the owner's request, so the data map in
  `docs/PRIVACY_AND_FEEDBACK.md` §4 is the only place this is written down.
  The survey page states its own handling inline, which covers the survey, but
  not the analysis log. See `docs/PRIVACY_AND_FEEDBACK.md` §6.4.
