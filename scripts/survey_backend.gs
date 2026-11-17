/**
 * EPIC-AMP feedback survey — storage, validation and Excel export.
 *
 * A Google Apps Script web app bound to its own private spreadsheet.
 *
 *   Anonymous visitors  can POST one response. They cannot read anything: the
 *                       web app never returns a stored response, and the
 *                       spreadsheet is private to its owner.
 *   Administrators      are whoever you share the spreadsheet with. They read
 *                       it in Sheets and export .xlsx from the custom menu.
 *                       There is no admin password and no admin URL, because
 *                       Google's own sign-in already does that job.
 *
 * There is no database credential anywhere in this design, so there is none to
 * leak. The site holds only this script's /exec URL, which accepts writes and
 * serves nothing.
 *
 * ---------------------------------------------------------------------------
 * SETUP
 *   1. New spreadsheet -> Extensions -> Apps Script -> paste this file.
 *   2. Project Settings -> Script properties:
 *        FORM_SECRET        long random string (signs the anti-spam tokens)
 *        RETENTION_MONTHS   24
 *        MAX_PER_HOUR       60   (whole-site cap on accepted responses)
 *   3. Run setup() once and accept the prompts.
 *   4. Deploy -> New deployment -> Web app, execute as Me, access "Anyone".
 *      Put the /exec URL into feedback.html as SURVEY_ENDPOINT.
 *   5. Keep the spreadsheet private. Share it only with the people who should
 *      read responses. Sharing it IS granting admin access.
 * ---------------------------------------------------------------------------
 */

var SHEET_NAME   = 'responses';
var SURVEY_VERSION = '1';

/* The server decides what is acceptable. Anything not on these lists is
   rejected rather than cleaned up, so a crafted payload cannot invent values. */
var CHOICES = {
  q1_background: ['Undergraduate student', 'Master’s student', 'PhD student',
                  'Researcher / Professor', 'Bioinformatician', 'Other'],
  q2_ease:       ['Very difficult', 'Difficult', 'Neutral', 'Easy', 'Very easy'],
  q4_usefulness: ['Not useful', 'Slightly useful', 'Moderately useful',
                  'Very useful', 'Extremely useful'],
  q5_clarity:    ['Very poor', 'Poor', 'Acceptable', 'Good', 'Excellent'],
  q6_issues:     ['No', 'Yes'],
  q7_workflow:   ['Definitely', 'Probably', 'Not sure', 'Probably not', 'No'],
  q10_followup:  ['Yes', 'No']
};

var FEATURES = ['AMP classification', 'MIC prediction',
                'Physicochemical properties analysis', 'Helical wheel visualization',
                'Peptide mutation', 'Known peptide comparison',
                '3D structure visualization', 'SHAP / LIME interpretability',
                'PDF report generation'];

var TEXT_LIMITS = { q6_detail: 1000, q8_most_valuable: 500, q9_suggestions: 2000 };

var HEADERS = ['timestamp', 'response_id', 'survey_version',
               'q1_background', 'q2_ease', 'q3_features', 'q4_usefulness',
               'q5_clarity', 'q6_issues', 'q6_detail', 'q7_workflow',
               'q8_most_valuable', 'q9_suggestions',
               'q10_followup', 'followup_email', 'consent_at', 'consent_version'];

/* ----------------------------------------------------------------- setup -- */

function setup() {
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('FORM_SECRET')) throw new Error('Set the script property FORM_SECRET first.');
  if (!props.getProperty('RETENTION_MONTHS')) props.setProperty('RETENTION_MONTHS', '24');
  if (!props.getProperty('MAX_PER_HOUR')) props.setProperty('MAX_PER_HOUR', '60');
  sheet();
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'purgeOldResponses') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('purgeOldResponses').timeBased().everyDays(1).atHour(3).create();
  return 'ready';
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('EPIC-AMP Survey')
    .addItem('Export responses to Excel (.xlsx)', 'exportResponsesXlsx')
    .addItem('Count responses', 'countResponses')
    .addToUi();
}

function sheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) sh = ss.insertSheet(SHEET_NAME);
  if (sh.getLastRow() === 0) {
    sh.appendRow(HEADERS);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold').setBackground('#f0f4fa');
    sh.getRange(1, 1, 1, HEADERS.length).setFontColor('#003f7d');
  }
  return sh;
}

function prop(name, fallback) {
  var v = PropertiesService.getScriptProperties().getProperty(name);
  return (v === null || v === '') ? fallback : v;
}

/* ------------------------------------------------------------- utilities -- */

function hex(bytes) {
  var out = '';
  for (var i = 0; i < bytes.length; i++) {
    var b = (bytes[i] + 256) % 256;
    out += (b < 16 ? '0' : '') + b.toString(16);
  }
  return out;
}

function sign(value) {
  return hex(Utilities.computeHmacSha256Signature(String(value), prop('FORM_SECRET', '')));
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * A spreadsheet treats a leading =, +, -, @ or control character as a formula.
 * A response is data, never a formula, so neutralise it on the way in. Doing
 * this at write time means the stored cell and every export of it are safe.
 */
function deFormula(text) {
  var t = String(text === null || text === undefined ? '' : text);
  t = t.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '');   // control chars
  if (/^[=+\-@\t\r]/.test(t)) t = '’' + t;
  return t;
}

/** Collapses runs of whitespace and trims to a hard maximum. */
function clean(text, max) {
  var t = String(text === null || text === undefined ? '' : text);
  t = t.replace(/\r\n/g, '\n').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  return t.length > max ? t.slice(0, max) : t;
}

/* --------------------------------------------------------- anti-spam token -- */

/**
 * The page asks for a token when it loads and sends it back with the response.
 * The token is its own issue time plus an HMAC of it, so nothing has to be
 * stored to verify it. It proves three things: the page was actually loaded,
 * the person spent at least MIN_SECONDS on it, and it has not been replayed.
 */
var MIN_SECONDS = 10;
var MAX_SECONDS = 4 * 3600;

function issueToken() {
  var nonce = Utilities.getUuid();
  var issued = Date.now();
  var payload = nonce + '.' + issued;
  return payload + '.' + sign(payload);
}

function checkToken(token) {
  var parts = String(token || '').split('.');
  if (parts.length !== 3) return 'malformed';
  var payload = parts[0] + '.' + parts[1];
  if (sign(payload) !== parts[2]) return 'bad_signature';
  var issued = Number(parts[1]);
  if (!issued) return 'malformed';
  var age = (Date.now() - issued) / 1000;
  if (age < MIN_SECONDS) return 'too_fast';
  if (age > MAX_SECONDS) return 'expired';
  var cache = CacheService.getScriptCache();
  var key = 'tok_' + parts[0];
  if (cache.get(key)) return 'replayed';
  cache.put(key, '1', Math.ceil(MAX_SECONDS) + 60);
  return 'ok';
}

/** A whole-site ceiling, so a flood cannot fill the sheet even with valid tokens. */
function underHourlyCap() {
  var cache = CacheService.getScriptCache();
  var key = 'cap_' + Math.floor(Date.now() / 3600000);
  var n = Number(cache.get(key) || '0');
  if (n >= Number(prop('MAX_PER_HOUR', '60'))) return false;
  cache.put(key, String(n + 1), 7200);
  return true;
}

/* ------------------------------------------------------------- endpoints -- */

/** Serves a token and nothing else. There is no read endpoint, by design. */
function doGet(e) {
  var action = (e && e.parameter && e.parameter.action) || '';
  if (action === 'token') return reply({ ok: true, token: issueToken() });
  return reply({ ok: true, service: 'epic-amp survey' });
}

function doPost(e) {
  var body;
  try {
    body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (err) {
    return reply({ ok: false, error: 'bad_request' });
  }

  // Honeypot: a field no real person can see, so anything in it is a bot.
  if (String(body.website || '').length > 0) return reply({ ok: true, stored: false });

  var tok = checkToken(body.token);
  if (tok !== 'ok') return reply({ ok: false, error: tok });

  var v = validate(body);
  if (v.error) return reply({ ok: false, error: 'invalid', field: v.error });

  // Counted only once a response is about to be stored, so a flood of
  // malformed payloads cannot burn the hour's budget for real people.
  if (!underHourlyCap()) return reply({ ok: false, error: 'rate_limited' });

  var lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return reply({ ok: false, error: 'busy' });
  try {
    var sh = sheet();
    var months = parseInt(prop('RETENTION_MONTHS', '24'), 10) || 24;
    var row = [];
    row.push(new Date().toISOString());
    row.push(Utilities.getUuid());
    row.push(SURVEY_VERSION);
    row.push(v.r.q1_background);
    row.push(v.r.q2_ease);
    row.push(v.r.q3_features.join('; '));
    row.push(v.r.q4_usefulness);
    row.push(v.r.q5_clarity);
    row.push(v.r.q6_issues);
    row.push(deFormula(v.r.q6_detail));
    row.push(v.r.q7_workflow);
    row.push(deFormula(v.r.q8_most_valuable));
    row.push(deFormula(v.r.q9_suggestions));
    row.push(v.r.q10_followup);
    row.push(deFormula(v.r.followup_email));
    row.push(v.r.consent_at);
    row.push(v.r.consent_version);
    sh.appendRow(row);
    return reply({ ok: true, stored: true });
  } catch (err) {
    return reply({ ok: false, error: 'server' });
  } finally {
    lock.releaseLock();
  }
}

/* ------------------------------------------------------------ validation -- */

var EMAIL_RE = /^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$/;

function validate(body) {
  var r = {};

  // single-choice questions: must be exactly one of the server's own strings
  for (var key in CHOICES) {
    if (!CHOICES.hasOwnProperty(key)) continue;
    var got = String(body[key] === undefined || body[key] === null ? '' : body[key]);
    if (CHOICES[key].indexOf(got) === -1) return { error: key };
    r[key] = got;
  }

  // q3: at least one known feature, no duplicates, nothing invented
  var feats = body.q3_features;
  if (!feats || Object.prototype.toString.call(feats) !== '[object Array]' || !feats.length) {
    return { error: 'q3_features' };
  }
  if (feats.length > FEATURES.length) return { error: 'q3_features' };
  var seen = {}, chosen = [];
  for (var i = 0; i < feats.length; i++) {
    var f = String(feats[i]);
    if (FEATURES.indexOf(f) === -1 || seen[f]) return { error: 'q3_features' };
    seen[f] = true;
    chosen.push(f);
  }
  r.q3_features = chosen;

  // free text: required where the survey requires it, always length-capped
  r.q6_detail = clean(body.q6_detail, TEXT_LIMITS.q6_detail);
  if (r.q6_issues === 'Yes' && !r.q6_detail) return { error: 'q6_detail' };
  if (r.q6_issues === 'No') r.q6_detail = '';

  r.q8_most_valuable = clean(body.q8_most_valuable, TEXT_LIMITS.q8_most_valuable);
  if (!r.q8_most_valuable) return { error: 'q8_most_valuable' };
  r.q9_suggestions = clean(body.q9_suggestions, TEXT_LIMITS.q9_suggestions);

  // q10: an address is stored only on an explicit yes AND an explicit consent
  r.followup_email = '';
  r.consent_at = '';
  r.consent_version = '';
  if (r.q10_followup === 'Yes') {
    var email = String(body.followup_email || '').trim();
    if (!EMAIL_RE.test(email)) return { error: 'followup_email' };
    if (body.contact_consent !== true) return { error: 'contact_consent' };
    r.followup_email  = email.slice(0, 120);
    r.consent_at      = clean(body.consent_at, 40) || new Date().toISOString();
    r.consent_version = clean(body.consent_version, 40) || 'unversioned';
  }
  return { r: r };
}

/* ------------------------------------------------------- admin: export -- */

/**
 * Builds a real .xlsx of every response and puts it in the owner's Drive.
 * Only someone who can already open this spreadsheet can run it, because it
 * runs from the spreadsheet's own menu under their Google account.
 */
function exportResponsesXlsx() {
  var ui = SpreadsheetApp.getUi();
  var src = sheet();
  var last = src.getLastRow();
  if (last < 2) { ui.alert('No responses to export yet.'); return; }

  var values = src.getRange(1, 1, last, HEADERS.length).getValues();
  var stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd_HHmm');
  var name = 'EPIC-AMP_survey_responses_' + stamp;

  // A temporary spreadsheet holding only the responses, so the exported file is
  // the data and nothing else.
  var tmp = SpreadsheetApp.create(name);
  var out = tmp.getSheets()[0];
  out.setName('responses');
  out.getRange(1, 1, values.length, HEADERS.length).setValues(values);
  out.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold').setBackground('#f0f4fa').setFontColor('#003f7d');
  out.setFrozenRows(1);
  out.autoResizeColumns(1, HEADERS.length);
  SpreadsheetApp.flush();

  var url = 'https://docs.google.com/spreadsheets/d/' + tmp.getId() + '/export?format=xlsx';
  var blob = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  }).getBlob().setName(name + '.xlsx');

  var file = DriveApp.createFile(blob);
  DriveApp.getFileById(tmp.getId()).setTrashed(true);   // keep only the .xlsx

  ui.alert('Export ready',
    (last - 1) + ' response(s) exported to your Drive as:\n\n' + name + '.xlsx\n\n' + file.getUrl(),
    ui.ButtonSet.OK);
  return file.getUrl();
}

function countResponses() {
  var n = Math.max(0, sheet().getLastRow() - 1);
  SpreadsheetApp.getUi().alert(n + ' response(s) stored.');
  return n;
}

/* ------------------------------------------------------------- retention -- */

/** Daily. Deletes responses past the retention period. */
function purgeOldResponses() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return;
  try {
    var sh = sheet();
    var last = sh.getLastRow();
    if (last < 2) return;
    var months = parseInt(prop('RETENTION_MONTHS', '24'), 10) || 24;
    var cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - months);
    var stamps = sh.getRange(2, 1, last - 1, 1).getValues();
    var removed = 0;
    for (var i = stamps.length - 1; i >= 0; i--) {
      var d = new Date(stamps[i][0]);
      if (!isNaN(d.getTime()) && d < cutoff) { sh.deleteRow(i + 2); removed++; }
    }
    if (removed) console.log('purged ' + removed + ' response(s) past retention');
  } finally {
    lock.releaseLock();
  }
}
