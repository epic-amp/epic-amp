/**
 * Retention for the EXISTING analysis log (the sheet that already receives
 * {email, label, confidence, sequence} from index.html).
 *
 * The privacy notice in the app now says that log is kept for 12 months. That
 * sentence is only true once this is installed, because the current script
 * appends rows and never deletes any. Install it or change the notice.
 *
 * This file is written blind: the live script was not in the repository, so the
 * sheet name and the column that holds the date are placeholders. Open the sheet,
 * set the three constants, run dryRunPurge() and read the log before you let
 * purgeOldAnalysisRows() delete anything.
 *
 * If the sheet has no date column at all, add one and record a timestamp on
 * every new row first; rows with no date are left alone by design, so nothing
 * is deleted on a guess.
 */

var LOG_SHEET_NAME  = 'Sheet1';   // <- the tab the webhook writes to
var LOG_DATE_COLUMN = 1;          // <- 1-based column holding the row's date
var LOG_KEEP_MONTHS = 12;         // <- must match the privacy notice

function installRetentionTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'purgeOldAnalysisRows') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('purgeOldAnalysisRows').timeBased().everyDays(1).atHour(4).create();
  return 'daily retention trigger installed';
}

function dryRunPurge()           { return sweep(false); }
function purgeOldAnalysisRows()  { return sweep(true); }

function sweep(reallyDelete) {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return 'busy';
  try {
    var sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(LOG_SHEET_NAME);
    if (!sh) throw new Error('No sheet named ' + LOG_SHEET_NAME);
    var last = sh.getLastRow();
    if (last < 2) return 'nothing to do';

    var cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - LOG_KEEP_MONTHS);
    var values = sh.getRange(2, LOG_DATE_COLUMN, last - 1, 1).getValues();

    var doomed = [], undated = 0;
    for (var i = 0; i < values.length; i++) {
      var d = values[i][0];
      if (!(d instanceof Date)) d = new Date(d);
      if (isNaN(d.getTime())) { undated++; continue; }   // never guess: keep it
      if (d < cutoff) doomed.push(i + 2);
    }
    if (reallyDelete) {
      for (var j = doomed.length - 1; j >= 0; j--) sh.deleteRow(doomed[j]);
    }
    var msg = (reallyDelete ? 'deleted ' : 'would delete ') + doomed.length +
              ' row(s) older than ' + cutoff.toISOString().slice(0, 10) +
              '; kept ' + undated + ' row(s) with no readable date';
    console.log(msg);
    return msg;
  } finally {
    lock.releaseLock();
  }
}
