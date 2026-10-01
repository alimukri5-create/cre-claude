"""Runs one framework against a deal using Claude (with web search). Returns structured findings.

The model does research and judgement. It does NOT do the deal arithmetic: that is core/calc.py.
"""
import json, os, re
import anthropic

MODEL = os.environ.get("CRE_MODEL", "claude-sonnet-5-5")

OUTPUT_SPEC = """
Return your answer as a single JSON object (no prose outside it) with this shape:
{
  "summary": "3-6 sentence plain-English conclusion for this framework",
  "findings": [
    {"claim": "...", "kind": "fact|inference|estimate", "label": "SOURCED|ESTIMATE|UNVERIFIED",
     "source": "URL or document name + page, or empty", "confidence": "high|medium|low"}
  ],
  "calculator_inputs": {},      // numbers the calculator needs, each with its own label; empty if none
  "red_flags": ["..."],
  "data_room_requests": ["questions to put to the vendor; prefix deal-critical ones with *"],
  "could_not_access": ["sources you needed but could not read"]
}
Never invent a source. If you could not verify something, label it UNVERIFIED.
"""


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Set ANTHROPIC_API_KEY (console.anthropic.com) before running a framework.")
    return anthropic.Anthropic(api_key=key)


def build_prompt(deal: dict, docs: dict, framework_text: str, prior: dict | None, honesty: str) -> str:
    parts = [
        "You are an investigative due-diligence analyst for a UK commercial property buyer. "
        "The buyer wants asymmetric, evidence-led analysis, not a standard institutional template.",
        "## Honesty rules\n" + honesty,
        "## Deal\n" + json.dumps(deal, indent=2),
    ]
    if docs:
        parts.append("## Data room documents (extracted text)\n" + "\n\n".join(
            f"### {n}\n{t[:60000]}" for n, t in docs.items()))
    if prior:
        parts.append("## Findings so far from earlier frameworks (summaries)\n" + "\n".join(
            f"- {k}: {v.get('summary','')}" for k, v in prior.items()))
    parts.append("## Framework to run now\n" + framework_text)
    parts.append(OUTPUT_SPEC)
    return "\n\n".join(parts)


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"summary": text.strip(), "findings": [], "parse_error": True}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"summary": text.strip(), "findings": [], "parse_error": True}


def run_framework(deal, docs, fw_id, fw_text, honesty, prior=None, use_web=True, max_searches=8):
    kwargs = {}
    if use_web:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}]
    resp = _client().messages.create(
        model=MODEL, max_tokens=8000,
        messages=[{"role": "user", "content": build_prompt(deal, docs, fw_text, prior, honesty)}],
        **kwargs,
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    result = parse_json(text)
    result["framework"] = fw_id
    return result
