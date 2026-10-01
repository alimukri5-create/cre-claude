"""Runs one framework against a deal using Claude (with web search). Returns structured findings.

The model does research and judgement. It does NOT do the deal arithmetic: that is core/calc.py.
"""
import datetime, json, os, re
from openai import OpenAI  # OpenRouter speaks the OpenAI protocol

DEFAULT_MODEL = os.environ.get("CRE_MODEL", "anthropic/claude-sonnet-4.5")  # change in the app sidebar; exact IDs at openrouter.ai/models

OUTPUT_SPEC = """
Return your answer as a single JSON object (no prose outside it) with this shape:
{
  "summary": "3-6 sentence plain-English conclusion for this framework",
  "findings": [
    {"claim": "...", "kind": "fact|inference|estimate", "label": "SOURCED|ESTIMATE|UNVERIFIED",
     "source": "URL or document name + page, or empty", "source_type": "primary|aggregator|news", "confidence": "high|medium|low"}
  ],
  "calculator_inputs": {},      // numbers the calculator needs, each with its own label; empty if none
  "red_flags": ["..."],
  "data_room_requests": ["questions to put to the vendor; prefix deal-critical ones with *"],
  "could_not_access": ["sources you needed but could not read"]
}
Label rules:
- SOURCED = the claim is stated directly in a source you actually read; put the source in "source" and set "source_type" to primary (Companies House/Land Registry/VOA/council/IM or data-room document), aggregator, or news.
- A claim with "kind":"inference" must NEVER be labelled SOURCED. Label it ESTIMATE (reasoning on sourced facts) or UNVERIFIED.
- Prefer primary sources. If you only saw an aggregator, say so in "source_type" and lower the confidence.
- Never calculate percentages, ratios or months of cover yourself: give the raw figures and dates and say what they imply in words. The app does the arithmetic.
- Do not write "almost certainly", "clearly" or similar unless a source says it.
- Never invent a source. If you could not verify something, label it UNVERIFIED.
"""


def _client():
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Set OPENROUTER_API_KEY (openrouter.ai/keys) before running a framework.")
    return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")


DOC_LIMIT = 400_000  # characters per document sent to the model (~100k tokens). Raise for long accounts; costs more.


def fit(text: str, limit: int) -> str:
    """Never silently truncate: if text is cut, say so inside the text the model reads."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[TRUNCATED: showing first {limit:,} of {len(text):,} characters. Later notes are NOT visible. Say so if you need them.]"


def build_prompt(deal: dict, docs: dict, framework_text: str, prior: dict | None, honesty: str, doc_limit: int = DOC_LIMIT) -> str:
    parts = [
        "You are an investigative due-diligence analyst for a UK commercial property buyer. "
        "The buyer wants asymmetric, evidence-led analysis, not a standard institutional template.",
        "## Honesty rules\n" + honesty,
        f"Today's date is {datetime.date.today().isoformat()}. Compare every deadline, expiry and filing date you read against it, and say plainly which have already passed and what that means.",
        "## Deal\n" + json.dumps(deal, indent=2),
    ]
    if docs:
        parts.append("## Data room documents (extracted text)\n" + "\n\n".join(
            f"### {n}\n{fit(t, doc_limit)}" for n, t in docs.items()))
    if prior:
        parts.append("## Findings so far from earlier frameworks (summaries)\n" + "\n".join(
            f"- {k}: {v.get('summary','')}" for k, v in prior.items()))
    parts.append("## Framework to run now\n" + framework_text)
    parts.append(OUTPUT_SPEC)
    return "\n\n".join(parts)


_CITE = re.compile(r"</?cite[^>]*>")


def clean(obj):
    """Remove <cite index=...> tags that web-search models leave inside strings."""
    if isinstance(obj, str):
        return _CITE.sub("", obj).strip()
    if isinstance(obj, list):
        return [clean(x) for x in obj]
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    return obj


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"summary": text.strip(), "findings": [], "parse_error": True}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"summary": text.strip(), "findings": [], "parse_error": True}


def run_framework(deal, docs, fw_id, fw_text, honesty, prior=None, use_web=True, max_searches=8, model=None, doc_limit=DOC_LIMIT):
    extra = {"plugins": [{"id": "web", "max_results": max_searches}]} if use_web else {}
    resp = _client().chat.completions.create(
        model=model or DEFAULT_MODEL, max_tokens=16000,
        messages=[{"role": "user", "content": build_prompt(deal, docs, fw_text, prior, honesty, doc_limit)}],
        extra_body=extra,
    )
    choice = resp.choices[0]
    text = choice.message.content or ""
    result = clean(parse_json(text))
    if getattr(choice, "finish_reason", None) == "length":
        result["truncated"] = True
    result["framework"] = fw_id
    result["model"] = model or DEFAULT_MODEL
    return result
