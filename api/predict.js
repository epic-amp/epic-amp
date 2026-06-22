// /api/predict.js
//
// Vercel serverless API route that proxies AMP classification requests
// from the browser to the Hugging Face Gradio Space.
//
// Why: the browser blocks cross-origin requests from epic-amp-v2.vercel.app
// to nonzeroexit-amp-classifier.hf.space due to CORS. Routing the call
// through this server-side proxy keeps the browser → API call same-origin,
// and the server → HF call has no CORS check at all.
//
// Place this file at:  /api/predict.js   (in your Vercel project root)
// Then the frontend calls:  POST /api/predict   with body { sequence: "..." }

const SPACE_BASE = "https://nonzeroexit-amp-classifier.hf.space";
// Gradio 5.x prefixes API routes with /gradio_api (visible in /config as
// "api_prefix":"/gradio_api"). The named endpoint is "predict".
const PREDICT_ENDPOINT = "/gradio_api/call/predict";

export const config = {
  // Allow up to 60 seconds — Spaces can be slow on cold start
  maxDuration: 60,
};

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "Method not allowed. Use POST." });
  }

  const { sequence } = req.body || {};
  if (typeof sequence !== "string" || !sequence.trim()) {
    return res.status(400).json({ error: "Missing 'sequence' string in body." });
  }

  try {
    // Step 1: submit the job to the Space (returns an event_id)
    const submitRes = await fetch(`${SPACE_BASE}${PREDICT_ENDPOINT}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data: [sequence] }),
    });

    if (!submitRes.ok) {
      const text = await submitRes.text();
      return res.status(502).json({
        error: `HF Space rejected the request (${submitRes.status}).`,
        detail: text.slice(0, 500),
      });
    }

    const submitJson = await submitRes.json();
    const eventId = submitJson.event_id;
    if (!eventId) {
      return res.status(502).json({
        error: "HF Space returned no event_id.",
        detail: JSON.stringify(submitJson).slice(0, 500),
      });
    }

    // Step 2: stream the result back (Gradio uses SSE)
    const resultRes = await fetch(
      `${SPACE_BASE}${PREDICT_ENDPOINT}/${eventId}`,
      { method: "GET" }
    );

    if (!resultRes.ok) {
      const text = await resultRes.text();
      return res.status(502).json({
        error: `HF Space result-fetch failed (${resultRes.status}).`,
        detail: text.slice(0, 500),
      });
    }

    // SSE format: lines like  "event: complete\ndata: [\"...\"]"
    const text = await resultRes.text();
    const lines = text.split("\n");

    let lastDataLine = null;
    let eventType = null;
    for (const ln of lines) {
      if (ln.startsWith("event:")) eventType = ln.slice(6).trim();
      else if (ln.startsWith("data:")) lastDataLine = ln.slice(5).trim();
    }

    if (eventType === "error" || !lastDataLine) {
      return res.status(502).json({
        error: "HF Space returned an error or empty result.",
        detail: text.slice(0, 800),
      });
    }

    let parsed;
    try {
      parsed = JSON.parse(lastDataLine);
    } catch {
      return res.status(502).json({
        error: "Could not parse HF Space result.",
        detail: lastDataLine.slice(0, 500),
      });
    }

    // parsed is the data array; the first element is the result string
    const resultText = Array.isArray(parsed) ? parsed[0] : parsed;
    return res.status(200).json({ result: resultText });
  } catch (err) {
    return res.status(500).json({
      error: "Proxy failed to reach HF Space.",
      detail: String(err && err.message ? err.message : err),
    });
  }
}
