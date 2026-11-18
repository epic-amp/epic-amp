"""
EPIC-AMP mailer Space.

Three endpoints:
  /send               - the report email (unchanged)
  /send_survey        - sends ONE survey invitation at once, on explicit consent
  /unsubscribe_survey - records "do not send me these" from the link inside it

One invitation per address per survey round, ever. There is no queue, no cron
and no mailing list: the address is not kept anywhere, and the ledger holds only
a salted hash of it, which is enough to avoid inviting the same person twice.

Secrets come from the Space's environment, never from the browser:
  BREVO_API_KEY       (required)
  SURVEY_URL          (required, or nothing is sent) the survey to link to
  SURVEY_ROUND        default 1; bump it to invite past recipients to a new one
  CONSENT_LOG_URL     Apps Script /exec URL that owns the consent sheet
  CONSENT_LOG_SECRET  shared secret for that script
  SITE_URL            default https://epic-amp-v2.vercel.app
"""

import gradio as gr
import os
import re
import uuid
from datetime import datetime, timezone

import requests

BREVO_KEY  = os.environ["BREVO_API_KEY"]
FROM_EMAIL = "epicamp.response@gmail.com"
FROM_NAME  = "EPIC-AMP"
REPLY_TO   = "epicamp.sup@gmail.com"

CONSENT_URL    = os.environ.get("CONSENT_LOG_URL", "").strip()
CONSENT_SECRET = os.environ.get("CONSENT_LOG_SECRET", "").strip()
SITE_URL       = os.environ.get("SITE_URL", "https://epic-amp-v2.vercel.app").rstrip("/")

# Set this to the live survey. While it is empty, /send_survey refuses, so a
# missing link can never go out in an email.
SURVEY_URL   = os.environ.get("SURVEY_URL", "").strip()
SURVEY_ROUND = (os.environ.get("SURVEY_ROUND", "1").strip() or "1")[:20]

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
      <div style="background:#ffffff;border:1px solid #d0daea;border-top:none;padding:24px;border-radius:0 0 10px 10px">
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
#  2. the survey invitation
# --------------------------------------------------------------------------- #
def _survey_html(survey_url, unsubscribe_url):
    return f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:560px;margin:auto;color:#1a2540;line-height:1.65">
      <div style="background:#00285a;padding:20px 22px;border-radius:10px 10px 0 0">
        <h2 style="color:#fff;margin:0;font-size:19px">Your EPIC-AMP feedback survey</h2>
      </div>
      <div style="background:#ffffff;border:1px solid #d0daea;border-top:none;padding:22px;border-radius:0 0 10px 10px">
        <p>Dear Researcher,</p>
        <p>Thank you for using EPIC-AMP. You asked for our feedback survey when you ran
           your analysis, so here it is &mdash; it is short, and what you tell us decides
           what we build next.</p>
        <p style="text-align:center;margin:26px 0">
          <a href="{survey_url}"
             style="display:inline-block;background:#0056a6;color:#fff;text-decoration:none;
                    padding:13px 30px;border-radius:6px;font-weight:600;font-size:15px">
            Open the survey
          </a>
        </p>
        <p style="font-size:13px;color:#4a5778;text-align:center;word-break:break-all">
          Or paste this into your browser:<br><a href="{survey_url}" style="color:#1a6fc4">{survey_url}</a>
        </p>
        <p>If you would rather just tell us directly, a reply to this message reaches us too.</p>
        <p style="margin-top:20px">Thank you,<br><strong>The EPIC-AMP Team</strong><br>
           <span style="color:#666;font-size:13px">Bioinformatics &amp; Computational Biology Unit (BCBU)</span></p>
        <hr style="border:none;border-top:1px solid #e0e6f0;margin:22px 0">
        <p style="color:#888;font-size:11px;margin:0">
          Zewail City of Science and Technology &middot; BCBU &middot; Giza, Egypt &middot;
          <a href="mailto:{REPLY_TO}" style="color:#1a6fc4">{REPLY_TO}</a><br><br>
          <a href="{unsubscribe_url}" style="color:#1a6fc4">Do not send me these again</a>
        </p>
      </div>
    </div>
    """


def _survey_text(survey_url, unsubscribe_url):
    return (
        "Dear Researcher,\n\n"
        "Thank you for using EPIC-AMP. You asked for our feedback survey when you\n"
        "ran your analysis, so here it is - it is short, and what you tell us\n"
        "decides what we build next.\n\n"
        "Open the survey:\n%s\n\n"
        "If you would rather just tell us directly, a reply to this message\n"
        "reaches us too.\n\n"
        "Thank you,\nThe EPIC-AMP Team\n"
        "Bioinformatics & Computational Biology Unit (BCBU)\n"
        "Zewail City of Science and Technology, Giza, Egypt\n\n"
        "---\n"
        "Do not send me these again: %s\n" % (survey_url, unsubscribe_url)
    )


def send_survey(to_email, consent_at, consent_version):
    """Send one survey invitation now. sent:<token> | skipped:<why> | error:<why>."""
    to_email = (to_email or "").strip()
    if not EMAIL_RE.match(to_email):
        return "error:invalid_email"

    # An invitation with no survey behind it is worse than no invitation.
    if not SURVEY_URL:
        return "error:survey_not_configured"

    consent_at = (consent_at or "").strip()[:40] or datetime.now(timezone.utc).isoformat()
    consent_version = (consent_version or "").strip()[:40] or "unversioned"

    # No consent ledger means no provable consent, and no way to tell whether
    # this person has already been invited or has opted out. So: send nothing.
    if not CONSENT_URL or not CONSENT_SECRET:
        return "error:consent_log_not_configured"

    token = str(uuid.uuid4())
    claim = _consent(
        "claim",
        email=to_email,
        consent_at=consent_at,
        consent_version=consent_version,
        token=token,
        survey_round=SURVEY_ROUND,
    )
    if claim is None:
        return "error:consent_log_unreachable"
    if not claim.get("proceed"):
        return "skipped:%s" % (claim.get("reason") or "refused")

    unsubscribe_url = "%s/unsubscribe?t=%s" % (SITE_URL, token)
    try:
        resp = _brevo("POST", BREVO_SEND, json={
            "sender":      {"email": FROM_EMAIL, "name": FROM_NAME},
            "to":          [{"email": to_email}],
            "replyTo":     {"email": REPLY_TO, "name": FROM_NAME},
            "subject":     "Your EPIC-AMP feedback survey",
            "htmlContent": _survey_html(SURVEY_URL, unsubscribe_url),
            "textContent": _survey_text(SURVEY_URL, unsubscribe_url),
            "batchId":     token,
            "headers":     {"List-Unsubscribe": "<%s>" % unsubscribe_url},
        })
    except Exception as exc:                      # noqa: BLE001
        _consent("mark", token=token, status="failed", detail=repr(exc)[:120])
        return "error:brevo_unreachable"

    if resp.status_code not in (200, 201, 202):
        _consent("mark", token=token, status="failed", detail="HTTP %s" % resp.status_code)
        print("brevo survey send failed %s: %s" % (resp.status_code, resp.text[:300]))
        return "error:brevo:%s" % resp.status_code

    message_id = ""
    try:
        message_id = (resp.json() or {}).get("messageId", "") or ""
    except Exception:                             # noqa: BLE001
        pass
    _consent("mark", token=token, status="sent", message_id=str(message_id)[:120])
    return "sent:%s" % token


def unsubscribe_survey(token):
    """From the link in the email. unsubscribed | unknown | error:<why>.

    The invitation is sent at once, so there is never anything queued at Brevo to
    recall. What this does is make the choice stick: the ledger marks the address
    hash as opted out, and no later analysis or survey round can invite it again.
    """
    token = (token or "").strip().lower()
    if not UUID_RE.match(token):
        return "error:invalid_token"

    record = _consent("unsubscribe", token=token)
    if record is None:
        return "error:consent_log_unreachable"
    if not record.get("ok"):
        return "error:%s" % (record.get("error") or "refused")
    return "unsubscribed" if record.get("found") else "unknown"


# --------------------------------------------------------------------------- #
#  Gradio surface
# --------------------------------------------------------------------------- #
with gr.Blocks() as demo:
    gr.Markdown(
        "### EPIC-AMP mailer\n"
        "Internal service for https://epic-amp-v2.vercel.app. "
        "`/send` delivers a report. `/send_survey` sends one consented survey "
        "invitation (round %s). `/unsubscribe_survey` opts an address out.%s"
        % (SURVEY_ROUND, "" if SURVEY_URL else "  \n\n**SURVEY_URL is not set, so no invitation will be sent.**")
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
    with gr.Tab("Survey"):
        with gr.Row():
            sv_email   = gr.Text(label="Recipient Email")
            sv_consent = gr.Text(label="Consent timestamp (ISO 8601)")
            sv_version = gr.Text(label="Consent notice version")
        sv_result = gr.Text(label="Status")
        gr.Button("Send survey invitation").click(
            fn=send_survey,
            inputs=[sv_email, sv_consent, sv_version],
            outputs=sv_result,
            api_name="send_survey",
        )
        un_token  = gr.Text(label="Unsubscribe token")
        un_result = gr.Text(label="Status")
        gr.Button("Unsubscribe").click(
            fn=unsubscribe_survey,
            inputs=[un_token],
            outputs=un_result,
            api_name="unsubscribe_survey",
        )

demo.launch(ssr_mode=False)
