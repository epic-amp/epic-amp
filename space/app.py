"""
EPIC-AMP mailer Space.

Three endpoints:
  /send              - the report email (unchanged)
  /schedule_feedback - books ONE follow-up email ~48 h out, on explicit consent
  /cancel_feedback   - cancels/suppresses it from the link inside that email

There is no cron job and no queue. Brevo's transactional API accepts a
`scheduledAt` up to 72 hours ahead and lets us cancel by the `batchId` we mint,
so the 48 h delay and the unsubscribe are both handled by the mail provider.
Docs: https://developers.brevo.com/docs/schedule-batch-sendings

Secrets come from the Space's environment, never from the browser:
  BREVO_API_KEY        (required)
  CONSENT_LOG_URL      Apps Script /exec URL that owns the consent sheet
  CONSENT_LOG_SECRET   shared secret for that script
  SITE_URL             default https://epic-amp-v2.vercel.app
  FOLLOWUP_DELAY_HOURS default 48
"""

import gradio as gr
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import requests

BREVO_KEY  = os.environ["BREVO_API_KEY"]
FROM_EMAIL = "epicamp.response@gmail.com"
FROM_NAME  = "EPIC-AMP"
REPLY_TO   = "epicamp.sup@gmail.com"

CONSENT_URL    = os.environ.get("CONSENT_LOG_URL", "").strip()
CONSENT_SECRET = os.environ.get("CONSENT_LOG_SECRET", "").strip()
SITE_URL       = os.environ.get("SITE_URL", "https://epic-amp-v2.vercel.app").rstrip("/")

# Brevo refuses a scheduledAt more than 72 h out; stay clear of the edge.
DELAY_HOURS = max(1.0, min(70.0, float(os.environ.get("FOLLOWUP_DELAY_HOURS", "48"))))

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")
UUID_RE  = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

BREVO_SEND = "https://api.brevo.com/v3/smtp/email"


# --------------------------------------------------------------------------- #
#  consent sheet (Apps Script).  Server-to-server, so the secret and the
#  address never reach a browser and there is no CORS to work around.
# --------------------------------------------------------------------------- #
def _consent(action, **fields):
    """Returns the script's parsed reply, or None if it could not be reached."""
    if not CONSENT_URL or not CONSENT_SECRET:
        return None
    body = {"action": action, "secret": CONSENT_SECRET}
    body.update(fields)
    try:
        r = requests.post(CONSENT_URL, json=body, timeout=20)
        if r.status_code != 200:
            print("consent log HTTP %s: %s" % (r.status_code, r.text[:200]))
            return None
        return r.json()
    except Exception as exc:                      # noqa: BLE001
        print("consent log unreachable: %r" % (exc,))
        return None


def _brevo(method, url, **kw):
    headers = {"api-key": BREVO_KEY, "Content-Type": "application/json"}
    return requests.request(method, url, headers=headers, timeout=25, **kw)


# --------------------------------------------------------------------------- #
#  1. the report email - behaviour unchanged
# --------------------------------------------------------------------------- #
def send_report(to_email, pdf_b64, label, confidence, sequence):
    is_amp = 'AMP' in label and 'Non' not in label
    label_color = '#2e7d32' if is_amp else '#c62828'

    html_content = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:auto;color:#1a2540;line-height:1.6">
      <div style="background:#00285a;padding:22px;border-radius:10px 10px 0 0">
        <h2 style="color:#fff;margin:0">EPIC-AMP Analysis Report</h2>
        <p style="color:#a0c8ff;margin:6px 0 0;font-size:14px">Explainable Antimicrobial Peptide Classification Platform</p>
      </div>
      <div style="border:1px solid #d0daea;border-top:none;padding:24px;border-radius:0 0 10px 10px">
        <p>Dear Researcher,</p>
        <p>Your peptide sequence has been successfully analyzed using the <strong>EPIC-AMP platform</strong>. Please find your detailed PDF report attached.</p>
        <table style="width:100%;border-collapse:collapse;margin:18px 0;font-size:14px">
          <tr style="background:#00285a;color:#fff">
            <td style="padding:10px 14px;font-weight:bold;width:40%">Metric</td>
            <td style="padding:10px 14px;font-weight:bold">Result</td>
          </tr>
          <tr style="background:#f0f4fa">
            <td style="padding:10px 14px;font-weight:bold">Classification</td>
            <td style="padding:10px 14px;font-weight:bold;color:{label_color}">{label}</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;font-weight:bold">Confidence Score</td>
            <td style="padding:10px 14px">{confidence}</td>
          </tr>
          <tr style="background:#f0f4fa">
            <td style="padding:10px 14px;font-weight:bold">Input Sequence</td>
            <td style="padding:10px 14px;font-family:monospace;font-size:12px;word-break:break-all;color:#003f7d">{sequence}</td>
          </tr>
        </table>
        <p>The attached PDF includes LIME feature attributions, MIC predictions, and global SHAP feature importance.</p>
        <p>For questions reach us at <a href="mailto:epicamp.sup@gmail.com" style="color:#1a6fc4">epicamp.sup@gmail.com</a>.</p>
        <p style="margin-top:20px">Best regards,<br><strong>The EPIC-AMP Team</strong><br>
        <span style="color:#666;font-size:13px">Bioinformatics &amp; Computational Biology Unit (BCBU)</span></p>
        <hr style="border:none;border-top:1px solid #e0e6f0;margin:24px 0">
        <p style="color:#888;font-size:11px;margin:0">
          Zewail City of Science and Technology &middot; BCBU &middot; Giza, Egypt<br>
          <a href="mailto:epicamp.sup@gmail.com" style="color:#1a6fc4">epicamp.sup@gmail.com</a><br>
          <span style="color:#bbb">This is an automated message &mdash; please do not reply directly.</span>
        </p>
      </div>
    </div>
    """

    resp = _brevo("POST", BREVO_SEND, json={
        "sender":      {"email": FROM_EMAIL, "name": FROM_NAME},
        "to":          [{"email": to_email}],
        "subject":     f"EPIC-AMP Analysis Report — {label}",
        "htmlContent": html_content,
        "attachment":  [{"content": pdf_b64, "name": "EPIC-AMP_Report.pdf"}],
    })
    return "sent" if resp.status_code == 201 else f"error:{resp.status_code}:{resp.text}"


# --------------------------------------------------------------------------- #
#  2. the follow-up email
# --------------------------------------------------------------------------- #
def _followup_html(cancel_url, consent_at):
    return f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:560px;margin:auto;color:#1a2540;line-height:1.65">
      <div style="background:#00285a;padding:20px 22px;border-radius:10px 10px 0 0">
        <h2 style="color:#fff;margin:0;font-size:19px">How did EPIC-AMP work out?</h2>
      </div>
      <div style="border:1px solid #d0daea;border-top:none;padding:22px;border-radius:0 0 10px 10px">
        <p>Dear Researcher,</p>
        <p>You ran a peptide through EPIC-AMP a couple of days ago and asked us to check back
           once. This is that one email &mdash; there will not be another.</p>
        <p style="margin:18px 0;padding:14px 16px;background:#f0f4fa;border-left:3px solid #0056a6;border-radius:6px">
           <strong>Was the result useful to you, and is there anything that got in your way?</strong><br>
           <span style="font-size:13px;color:#4a5778">A one-line reply to this message is plenty. We read every one.</span>
        </p>
        <p>If you would rather not have been asked, that is useful to know too &mdash; just use the
           link at the bottom and we will not do it again.</p>
        <p style="margin-top:20px">Thank you,<br><strong>The EPIC-AMP Team</strong><br>
           <span style="color:#666;font-size:13px">Bioinformatics &amp; Computational Biology Unit (BCBU)</span></p>
        <hr style="border:none;border-top:1px solid #e0e6f0;margin:22px 0">
        <p style="color:#888;font-size:11px;margin:0">
          You are getting this because you ticked the optional follow-up box on
          epic-amp-v2.vercel.app on {consent_at}. It is the only reason we hold your address.<br>
          Zewail City of Science and Technology &middot; BCBU &middot; Giza, Egypt &middot;
          <a href="mailto:{REPLY_TO}" style="color:#1a6fc4">{REPLY_TO}</a><br><br>
          <a href="{cancel_url}" style="color:#1a6fc4">Cancel this and do not ask me again</a>
        </p>
      </div>
    </div>
    """


def _followup_text(cancel_url, consent_at):
    return (
        "Dear Researcher,\n\n"
        "You ran a peptide through EPIC-AMP a couple of days ago and asked us to check\n"
        "back once. This is that one email - there will not be another.\n\n"
        "Was the result useful to you, and is there anything that got in your way?\n"
        "A one-line reply to this message is plenty.\n\n"
        "Thank you,\nThe EPIC-AMP Team\n"
        "Bioinformatics & Computational Biology Unit (BCBU)\n"
        "Zewail City of Science and Technology, Giza, Egypt\n\n"
        "---\n"
        "You are getting this because you ticked the optional follow-up box on\n"
        "epic-amp-v2.vercel.app on %s. It is the only reason we hold your address.\n"
        "Cancel and do not ask again: %s\n" % (consent_at, cancel_url)
    )


def schedule_feedback(to_email, consent_at, consent_version):
    """Book one follow-up email. Returns scheduled:<token> | skipped:<why> | error:<why>."""
    to_email = (to_email or "").strip()
    if not EMAIL_RE.match(to_email):
        return "error:invalid_email"

    consent_at = (consent_at or "").strip()[:40] or datetime.now(timezone.utc).isoformat()
    consent_version = (consent_version or "").strip()[:40] or "unversioned"

    # No consent ledger means no provable consent, so send nothing at all.
    if not CONSENT_URL or not CONSENT_SECRET:
        return "error:consent_log_not_configured"

    token = str(uuid.uuid4())
    when  = datetime.now(timezone.utc) + timedelta(hours=DELAY_HOURS)
    when_s = when.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"

    # Claim first. The script holds a lock while it checks the suppression list and
    # any still-pending request for this address, so two clicks cannot both win.
    claim = _consent(
        "claim",
        email=to_email,
        consent_at=consent_at,
        consent_version=consent_version,
        token=token,
        scheduled_for=when_s,
    )
    if claim is None:
        return "error:consent_log_unreachable"
    if not claim.get("proceed"):
        return "skipped:%s" % (claim.get("reason") or "refused")

    cancel_url = "%s/unsubscribe?t=%s" % (SITE_URL, token)
    try:
        resp = _brevo("POST", BREVO_SEND, json={
            "sender":      {"email": FROM_EMAIL, "name": FROM_NAME},
            "to":          [{"email": to_email}],
            "replyTo":     {"email": REPLY_TO, "name": FROM_NAME},
            "subject":     "How did EPIC-AMP work out for you?",
            "htmlContent": _followup_html(cancel_url, consent_at[:10]),
            "textContent": _followup_text(cancel_url, consent_at[:10]),
            "scheduledAt": when_s,
            "batchId":     token,
            "headers":     {"List-Unsubscribe": "<%s>" % cancel_url},
        })
    except Exception as exc:                      # noqa: BLE001
        _consent("mark", token=token, status="failed", detail=repr(exc)[:120])
        return "error:brevo_unreachable"

    if resp.status_code not in (200, 201, 202):
        _consent("mark", token=token, status="failed",
                 detail="HTTP %s" % resp.status_code)
        print("brevo schedule failed %s: %s" % (resp.status_code, resp.text[:300]))
        return "error:brevo:%s" % resp.status_code

    message_id = ""
    try:
        message_id = (resp.json() or {}).get("messageId", "") or ""
    except Exception:                             # noqa: BLE001
        pass
    _consent("mark", token=token, status="scheduled", message_id=str(message_id)[:120])
    return "scheduled:%s" % token


def cancel_feedback(token):
    """From the link in the email. cancelled | already_sent | unknown | error:<why>."""
    token = (token or "").strip().lower()
    if not UUID_RE.match(token):
        return "error:invalid_token"

    # Record the choice first: even if Brevo is unreachable, the suppression stands
    # and no later analysis can schedule another email for this address.
    record = _consent("unsubscribe", token=token)

    try:
        resp = _brevo("DELETE", "https://api.brevo.com/v3/smtp/email/%s" % token)
        code = resp.status_code
    except Exception as exc:                      # noqa: BLE001
        print("brevo cancel unreachable: %r" % (exc,))
        return "cancelled" if record and record.get("ok") else "error:brevo_unreachable"

    if code in (200, 204):
        return "cancelled"
    if code in (400, 404):
        # Already delivered, or past its window: nothing left in the queue.
        return "already_sent" if record and record.get("found") else "unknown"
    print("brevo cancel HTTP %s: %s" % (code, resp.text[:200]))
    return "error:brevo:%s" % code


# --------------------------------------------------------------------------- #
#  Gradio surface
# --------------------------------------------------------------------------- #
with gr.Blocks() as demo:
    gr.Markdown(
        "### EPIC-AMP mailer\n"
        "Internal service for https://epic-amp-v2.vercel.app. "
        "`/send` delivers a report. `/schedule_feedback` books one consented "
        "follow-up for ~%g h later. `/cancel_feedback` cancels it." % DELAY_HOURS
    )
    with gr.Tab("Report"):
        with gr.Row():
            to_email   = gr.Text(label="Recipient Email")
            pdf_b64    = gr.Text(label="PDF Base64")
            label_in   = gr.Text(label="Label")
            confidence = gr.Text(label="Confidence")
            sequence   = gr.Text(label="Sequence")
        result = gr.Text(label="Status")
        gr.Button("Send").click(
            fn=send_report,
            inputs=[to_email, pdf_b64, label_in, confidence, sequence],
            outputs=result,
            api_name="send",
        )
    with gr.Tab("Follow-up"):
        with gr.Row():
            fb_email   = gr.Text(label="Recipient Email")
            fb_consent = gr.Text(label="Consent timestamp (ISO 8601)")
            fb_version = gr.Text(label="Consent notice version")
        fb_result = gr.Text(label="Status")
        gr.Button("Schedule").click(
            fn=schedule_feedback,
            inputs=[fb_email, fb_consent, fb_version],
            outputs=fb_result,
            api_name="schedule_feedback",
        )
        cancel_token  = gr.Text(label="Unsubscribe token")
        cancel_result = gr.Text(label="Status")
        gr.Button("Cancel").click(
            fn=cancel_feedback,
            inputs=[cancel_token],
            outputs=cancel_result,
            api_name="cancel_feedback",
        )

demo.launch(ssr_mode=False)
