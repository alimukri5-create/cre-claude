def build_memo(deal: dict, results: dict, calc_summary: str = "") -> str:
    """Assemble framework results into one markdown memo. Pure formatting, no model call."""
    L = [f"# Due diligence memo: {deal.get('name','(unnamed deal)')}", ""]
    if calc_summary:
        L += ["## Calculator output", calc_summary, ""]
    flags = [f for r in results.values() for f in r.get("red_flags", [])]
    if flags:
        L += ["## Red flags", *[f"- {f}" for f in flags], ""]
    for fw_id, r in results.items():
        L += [f"## {fw_id.split('_',1)[-1].replace('_',' ').title()}", r.get("summary", ""), ""]
        for f in r.get("findings", []):
            src = f" ([source]({f['source']}))" if str(f.get("source", "")).startswith("http") else (f" ({f['source']})" if f.get("source") else "")
            L.append(f"- **{f.get('label','?')}** / {f.get('kind','?')}: {f.get('claim','')}{src}")
        if r.get("could_not_access"):
            L += ["", "_Could not access:_ " + "; ".join(r["could_not_access"])]
        L.append("")
    reqs = [q for r in results.values() for q in r.get("data_room_requests", [])]
    if reqs:
        L += ["## Data-room checklist (* = deal-critical)", *[f"- [ ] {q}" for q in reqs], ""]
    return "\n".join(L)
