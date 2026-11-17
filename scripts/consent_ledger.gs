/**
 * EPIC-AMP follow-up consent ledger.
 *
 * A Google Apps Script web app bound to its own spreadsheet. It is the only
 * place that remembers anything about the optional follow-up email:
 *
 *   - that someone consented, when, and to which version of the notice
 *   - that one request is still pending, so a second click cannot book a second
 *     email (the check and the write happen inside one LockService lock)
 *   - that someone cancelled, so no later analysis can ever book another
 *
 * The address itself is NOT stored. We keep an HMAC-SHA256 of it under a salt
 * held in Script Properties. That is enough to recognise the same address again
 * and not enough to send anything to it.
 *
 * Only the mailer Space talks to this script, server to server, with a shared
 * secret. Nothing here is reachable from a browser and no address is ever
 * returned in a response.
 *
 * ---------------------------------------------------------------------------
 * SETUP
 *   1. Create a new spreadsheet, Extensions -> Apps Script, paste this file.
 *   2. Project Settings -> Script properties, add:
 *        SHARED_SECRET     a long random string (also set CONSENT_LOG_SECRET
 *                          to the same value in the Hugging Face Space)
 *        EMAIL_HASH_SALT   a different long random string (never change it, or
 *                          old rows stop matching)
 *        RETENTION_MONTHS  24   (how long a consent record is kept)
 *   3. Run setup() once and accept the permission prompt. It creates the sheet
 *      headers and installs the daily retention trigger.
 *   4. Deploy -> New deployment -> Web app, execute as Me, access "Anyone".
 *      Put the /exec URL in the Space as CONSENT_LOG_URL.
 *
 * Keep this deployment separate from the analysis-log script. Different data,
 * different purpose, different retention.
 * ---------------------------------------------------------------------------
 */

var SHEET_NAME = 'consent';
var HEADERS = ['token', 'email_sha256', 'consent_at', 'consent_version',
               'scheduled_for', 'status', 'brevo_message_id', 'unsubscribed_at',
               'created_at', 'purge_after', 'detail'];
var COL = {};
for (var i = 0; i < HEADERS.length; i++) COL[HEADERS[i]] = i;

/* ----------------------------------------------------------------- setup -- */

function setup() {
  var props = PropertiesService.getScriptProperties();
  ['SHARED_SECRET', 'EMAIL_HASH_SALT'].forEach(function (k) {
    if (!props.getProperty(k)) throw new Error('Set the script property ' + k + ' first.');
  });
  if (!props.getProperty('RETENTION_MONTHS')) props.setProperty('RETENTION_MONTHS', '24');
  sheet();
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'purgeExpired') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('purgeExpired').timeBased().everyDays(1).atHour(3).create();
  return 'ready';
}

function sheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) sh = ss.insertSheet(SHEET_NAME);
  if (sh.getLastRow() === 0) {
    sh.appendRow(HEADERS);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold');
  }
  return sh;
}

/* ------------------------------------------------------------- utilities -- */

function nowIso() { return new Date().toISOString(); }

function prop(name, fallback) {
  var v = PropertiesService.getScriptProperties().getProperty(name);
  return (v === null || v === '') ? fallback : v;
}

/** Length-safe comparison, so a wrong secret leaks nothing through timing. */
function secretOk(given) {
  var want = prop('SHARED_SECRET', '');
  if (!want || typeof given !== 'string' || given.length !== want.length) return false;
  var diff = 0;
  for (var i = 0; i < want.length; i++) diff |= want.charCodeAt(i) ^ given.charCodeAt(i);
  return diff === 0;
}

function emailHash(email) {
  var salt = prop('EMAIL_HASH_SALT', '');
  if (!salt) throw new Error('EMAIL_HASH_SALT is not set');
  var normalised = String(email || '').trim().toLowerCase();
  var bytes = Utilities.computeHmacSha256Signature(normalised, salt);
  var hex = '';
  for (var i = 0; i < bytes.length; i++) {
    var b = (bytes[i] + 256) % 256;
    hex += (b < 16 ? '0' : '') + b.toString(16);
  }
  return hex;
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function rows(sh) {
  var last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, HEADERS.length).getValues();
}

function findRowByToken(sh, token) {
  var data = rows(sh);
  for (var i = data.length - 1; i >= 0; i--) {
    if (String(data[i][COL.token]) === token) return { index: i + 2, values: data[i] };
  }
  return null;
}

function addMonths(date, months) {
  var d = new Date(date.getTime());
  d.setMonth(d.getMonth() + months);
  return d;
}

/* ------------------------------------------------------------- endpoints -- */

function doGet() {
  // Deliberately says nothing about the data it holds.
  return reply({ ok: true, service: 'epic-amp consent ledger' });
}

function doPost(e) {
  var body;
  try {
    body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (err) {
    return reply({ ok: false, error: 'bad_json' });
  }
  if (!secretOk(body.secret)) return reply({ ok: false, error: 'unauthorised' });

  switch (body.action) {
    case 'claim':       return reply(handleClaim(body));
    case 'mark':        return reply(handleMark(body));
    case 'unsubscribe': return reply(handleUnsubscribe(body));
    default:            return reply({ ok: false, error: 'unknown_action' });
  }
}

/**
 * Decide whether one more follow-up may be booked for this address, and record
 * the consent if so. The lock makes the decision and the write one step, so two
 * simultaneous submissions cannot both be told to proceed.
 */
function handleClaim(body) {
  if (!body.email || !body.token) return { ok: false, proceed: false, reason: 'missing_fields' };

  var lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return { ok: false, proceed: false, reason: 'busy' };
  try {
    var sh = sheet();
    var hash = emailHash(body.email);
    var now = new Date();
    var data = rows(sh);

    for (var i = 0; i < data.length; i++) {
      if (String(data[i][COL.email_sha256]) !== hash) continue;
      var status = String(data[i][COL.status]);
      if (status === 'unsubscribed') return { ok: true, proceed: false, reason: 'unsubscribed' };
      if (status === 'claimed' || status === 'scheduled') {
        var due = new Date(data[i][COL.scheduled_for]);
        if (!isNaN(due.getTime()) && due > now) {
          return { ok: true, proceed: false, reason: 'already_pending' };
        }
      }
    }

    var months = parseInt(prop('RETENTION_MONTHS', '24'), 10) || 24;
    var row = [];
    row[COL.token]            = String(body.token);
    row[COL.email_sha256]     = hash;
    row[COL.consent_at]       = String(body.consent_at || nowIso());
    row[COL.consent_version]  = String(body.consent_version || 'unversioned');
    row[COL.scheduled_for]    = String(body.scheduled_for || '');
    row[COL.status]           = 'claimed';
    row[COL.brevo_message_id] = '';
    row[COL.unsubscribed_at]  = '';
    row[COL.created_at]       = nowIso();
    row[COL.purge_after]      = addMonths(now, months).toISOString();
    row[COL.detail]           = '';
    sh.appendRow(row);

    return { ok: true, proceed: true, token: String(body.token) };
  } catch (err) {
    return { ok: false, proceed: false, reason: 'error' };
  } finally {
    lock.releaseLock();
  }
}

/** Follow-up on a claim: scheduled (with Brevo's id) or failed. */
function handleMark(body) {
  if (!body.token) return { ok: false, error: 'missing_token' };
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return { ok: false, error: 'busy' };
  try {
    var sh = sheet();
    var hit = findRowByToken(sh, String(body.token));
    if (!hit) return { ok: true, found: false };
    if (body.status) sh.getRange(hit.index, COL.status + 1).setValue(String(body.status));
    if (body.message_id) sh.getRange(hit.index, COL.brevo_message_id + 1).setValue(String(body.message_id));
    if (body.detail) sh.getRange(hit.index, COL.detail + 1).setValue(String(body.detail).slice(0, 200));
    return { ok: true, found: true };
  } finally {
    lock.releaseLock();
  }
}

/**
 * Someone used the cancel link. The row becomes a permanent suppression: the
 * hash stays so we can recognise the address, everything else is cleared, and
 * the retention purge leaves it alone.
 */
function handleUnsubscribe(body) {
  if (!body.token) return { ok: false, error: 'missing_token' };
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return { ok: false, error: 'busy' };
  try {
    var sh = sheet();
    var hit = findRowByToken(sh, String(body.token));
    if (!hit) return { ok: true, found: false };
    var wasPending = String(hit.values[COL.status]) === 'scheduled' ||
                     String(hit.values[COL.status]) === 'claimed';
    sh.getRange(hit.index, COL.status + 1).setValue('unsubscribed');
    sh.getRange(hit.index, COL.unsubscribed_at + 1).setValue(nowIso());
    sh.getRange(hit.index, COL.brevo_message_id + 1).setValue('');
    sh.getRange(hit.index, COL.purge_after + 1).setValue('');
    return { ok: true, found: true, was_pending: wasPending };
  } finally {
    lock.releaseLock();
  }
}

/* ------------------------------------------------------------- retention -- */

/**
 * Daily. Deletes consent records past their retention date. Cancellations are
 * kept, because forgetting one would mean emailing someone who said no; they
 * are a bare hash with no address, date or sequence attached.
 */
function purgeExpired() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return;
  try {
    var sh = sheet();
    var data = rows(sh);
    var now = new Date();
    var removed = 0;
    for (var i = data.length - 1; i >= 0; i--) {
      if (String(data[i][COL.status]) === 'unsubscribed') continue;
      var cutoff = new Date(data[i][COL.purge_after]);
      if (!isNaN(cutoff.getTime()) && cutoff <= now) {
        sh.deleteRow(i + 2);
        removed++;
      }
    }
    if (removed) console.log('purged ' + removed + ' expired consent record(s)');
  } finally {
    lock.releaseLock();
  }
}
