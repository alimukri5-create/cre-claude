"""Lead-following investigator.

A model with tools works a case board: it records findings, opens leads from them, pursues the leads with
tools (web search, page fetch, Companies House, data-room search), closes them, and repeats until the
important leads are closed or the step budget runs out. Honesty rules are enforced in code, not just asked for.
"""
import datetime, json, re
from dataclasses import dataclass, field, asdict

from . import companies_house as ch
from . import web

KINDS = {"fact", "inference", "estimate"}
LABELS = {"SOURCED", "ESTIMATE", "UNVERIFIED"}


@dataclass
class Board:
    goal: str = ""
    findings: list = field(default_factory=list)   # {id, claim, kind, label, source, source_type, confidence}
    leads: list = field(default_factory=list)      # {id, text, why, priority, status, outcome}
    trail: list = field(default_factory=list)      # {step, tool, args, preview}
    summary: str = ""
    next_steps: str = ""
    runs: int = 0
    steps: int = 0
    tokens: int = 0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        b = cls()
        for k, v in (d or {}).items():
            if hasattr(b, k):
                setattr(b, k, v)
        return b

    def open_leads(self, priority=None):
        return [l for l in self.leads if l["status"] == "open" and (priority is None or l["priority"] == priority)]

    def brief(self, max_findings=80):
        lines = []
        if self.summary:
            lines.append(f"Previous summary: {self.summary}")
        if self.findings:
            lines.append(f"Findings so far ({len(self.findings)}):")
            for f in self.findings[-max_findings:]:
                lines.append(f"  F{f['id']} [{f['label']}/{f['kind']}] {f['claim'][:220]} ({f['source'][:80]})")
        if self.leads:
            lines.append("Leads:")
            for l in self.leads:
                tail = f" -> {l['outcome']}" if l["outcome"] else ""
                lines.append(f"  L{l['id']} P{l['priority']} {l['status'].upper()}: {l['text'][:200]}{tail[:200]}")
        return "\n".join(lines) if lines else "Empty board: nothing found yet."


def _tool(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


S = {"type": "string"}
TOOLS = {
    "web_search": _tool("web_search", "Search the web (news, planning portals, council reports, company announcements, agents' listings). Returns facts with source URLs.", {"query": S}, ["query"]),
    "fetch_url": _tool("fetch_url", "Download a web page or PDF by URL and read its text. Use for primary sources found by search (committee reports, planning documents, filings).", {"url": S}, ["url"]),
    "companies_house_search": _tool("companies_house_search", "Find UK companies by name. Returns company numbers.", {"query": S}, ["query"]),
    "companies_house_dossier": _tool("companies_house_dossier", "Pull a full Companies House dossier for a company number (profile, officers, controllers, charges, filing history, latest accounts text). Added to the data room; search it with search_documents.", {"number": S}, ["number"]),
    "search_documents": _tool("search_documents", "Search every document in the data room (IM, lease, accounts, dossiers) for a word or phrase. Ignores case and extra spaces. Use before relying on any quote.", {"term": S}, ["term"]),
    "read_document": _tool("read_document", "Read part of a data-room document.", {"name": S, "start": {"type": "integer"}, "length": {"type": "integer"}}, ["name"]),
    "record_finding": _tool("record_finding", "Record one finding on the case board. Do this as you go. Rules (enforced): an inference can never be labelled SOURCED; SOURCED needs a source.",
                            {"claim": S, "kind": {"type": "string", "enum": sorted(KINDS)}, "label": {"type": "string", "enum": sorted(LABELS)},
                             "source": S, "source_type": {"type": "string", "enum": ["primary", "aggregator", "news", "buyer_supplied", "none"]},
                             "confidence": {"type": "string", "enum": ["high", "medium", "low"]}},
                            ["claim", "kind", "label", "source", "source_type", "confidence"]),
    "add_lead": _tool("add_lead", "Open a new lead: something a finding implies must be checked. priority 1 = could change the price or kill the deal.",
                      {"text": S, "why": S, "priority": {"type": "integer", "enum": [1, 2, 3]}}, ["text", "why", "priority"]),
    "close_lead": _tool("close_lead", "Close a lead with its outcome (what you found, or why it is a dead end).", {"id": {"type": "integer"}, "outcome": S}, ["id", "outcome"]),
    "finish": _tool("finish", "End the investigation with a summary and recommended next steps.", {"summary": S, "next_steps": S}, ["summary", "next_steps"]),
}


def compact(messages, keep=6, stub=350):
    """Shrink old tool results so long investigations stay affordable. Findings live on the board, not in the chat."""
    tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for i in tool_idx[:-keep]:
        c = messages[i]["content"]
        if len(c) > stub:
            messages[i] = {**messages[i], "content": c[:stub] + " [older result shortened; findings are on the case board]"}
    return messages


class Investigator:
    def __init__(self, deal, docs, board, client, model, use_web=True, checklists="", honesty="",
                 result_chars=8000, on_event=None, search_model=None):
        self.deal, self.docs, self.board = deal, docs, board
        self.client, self.model, self.search_model = client, model, search_model or model
        self.use_web, self.checklists, self.honesty = use_web, checklists, honesty
        self.result_chars, self.on_event = result_chars, on_event or (lambda e: None)
        self.finished, self._finish_warned, self.step = False, False, 0

    # ----- tool availability -----
    def tool_specs(self):
        import os
        names = ["search_documents", "read_document", "record_finding", "add_lead", "close_lead", "finish"]
        if self.use_web:
            names = ["web_search", "fetch_url"] + names
        if os.environ.get("COMPANIES_HOUSE_API_KEY"):
            names = ["companies_house_search", "companies_house_dossier"] + names
        return [TOOLS[n] for n in names], names

    def system_prompt(self, names):
        return (
            "You are an investigative due-diligence analyst for a UK commercial property buyer. The buyer wants asymmetric, "
            "evidence-led analysis, not a template.\n\n"
            "HOW TO WORK. Work like a detective, one lead at a time. Every finding should raise a question: what else must be true "
            "if this is true, who else is involved, what happens next, what would contradict it. Turn each into a lead with add_lead "
            "and pursue it with your tools. Record findings with record_finding AS YOU GO. Close each lead with close_lead and its outcome. "
            "Dead ends and things you could not access are findings too (label UNVERIFIED).\n"
            "Look beyond the documents: the neighbouring buildings (who occupies them, what was let, sold, left empty or redeveloped, "
            "and what their planning applications and council committee reports say), the identity and incentives of the seller, "
            "the people and companies connected to the tenant, and the wider market. Prefer primary sources. Check any figure you rely on "
            "with search_documents or read_document before recording it.\n"
            "Do not stop at the first answer. Stop when your priority-1 leads are closed or the budget is nearly spent, then call finish.\n\n"
            f"TOOLS AVAILABLE: {', '.join(names)}.\n"
            f"Today's date is {datetime.date.today().isoformat()}. Compare deadlines and dates against it.\n"
            "Do not do arithmetic in prose: quote raw figures with dates.\n\n"
            "## Honesty rules\n" + self.honesty +
            ("\n\n## Coverage checklists (guidance on what a full investigation covers; prioritise what matters, you need not finish all)\n" + self.checklists if self.checklists else "")
        )

    # ----- tool execution -----
    def _cap(self, text):
        if len(text) <= self.result_chars:
            return text
        return text[: self.result_chars] + f"\n[TRUNCATED: {len(text):,} characters in total. Use search_documents or read_document for the rest.]"

    def execute(self, name, args):
        b = self.board
        try:
            if name == "web_search":
                return self._cap(web.search(self.client, self.search_model, args["query"]))
            if name == "fetch_url":
                return self._cap(web.fetch_url(args["url"]))
            if name == "companies_house_search":
                hits = ch.search(args["query"])
                return "\n".join(f"{h['number']} | {h['name']} | {h['status']} | {h['address']}" for h in hits) or "No matches."
            if name == "companies_house_dossier":
                d = ch.build_dossier(args["number"])
                key = f"CH dossier - {d['name']} ({d['number']})"
                self.docs[key] = d["text"]
                notes = ("\nNotes: " + "; ".join(d["notes"])) if d["notes"] else ""
                return self._cap(d["text"][:6000]) + f"\n\n[Full dossier saved to the data room as '{key}' ({len(d['text']):,} characters). Use search_documents / read_document to read the accounts.]" + notes
            if name == "search_documents":
                pat = re.compile(r"\s+".join(re.escape(w) for w in args["term"].split()), re.I)
                out = []
                for n, t in self.docs.items():
                    ms = list(pat.finditer(t))
                    for m in ms[:5]:
                        out.append(f"[{n}] @{m.start()}: ..." + t[max(0, m.start() - 200): m.end() + 350].replace("\n", " ") + "...")
                    if len(ms) > 5:
                        out.append(f"[{n}] ({len(ms)} matches in total; showing 5)")
                return self._cap("\n".join(out) or f"No matches for '{args['term']}' in {len(self.docs)} documents.")
            if name == "read_document":
                if args["name"] not in self.docs:
                    return "No such document. Available: " + "; ".join(self.docs)
                s0 = int(args.get("start") or 0)
                ln = min(int(args.get("length") or 8000), 12000)
                t = self.docs[args["name"]]
                return f"[{args['name']} characters {s0}-{s0 + ln} of {len(t):,}]\n" + t[s0:s0 + ln]
            if name == "record_finding":
                kind, label = args.get("kind"), args.get("label")
                if kind not in KINDS or label not in LABELS:
                    return f"REJECTED: kind must be one of {sorted(KINDS)} and label one of {sorted(LABELS)}."
                if kind == "inference" and label == "SOURCED":
                    return "REJECTED: an inference cannot be labelled SOURCED. Record the sourced facts separately, then record the inference as ESTIMATE or UNVERIFIED."
                if label == "SOURCED" and not (args.get("source") or "").strip():
                    return "REJECTED: SOURCED needs a source (URL, or document name and note)."
                claim = (args.get("claim") or "").strip()
                if not claim:
                    return "REJECTED: empty claim."
                if any(f["claim"].strip().lower() == claim.lower() for f in b.findings):
                    return "Duplicate: already recorded."
                fid = len(b.findings) + 1
                b.findings.append({"id": fid, "claim": claim, "kind": kind, "label": label, "source": args.get("source", ""),
                                   "source_type": args.get("source_type", "none"), "confidence": args.get("confidence", "medium")})
                self.on_event({"type": "finding", "step": self.step, "finding": b.findings[-1]})
                return f"Recorded F{fid}."
            if name == "add_lead":
                lid = len(b.leads) + 1
                b.leads.append({"id": lid, "text": args["text"], "why": args.get("why", ""), "priority": int(args.get("priority", 2)), "status": "open", "outcome": ""})
                self.on_event({"type": "lead", "step": self.step, "lead": b.leads[-1]})
                return f"Opened L{lid}."
            if name == "close_lead":
                for l in b.leads:
                    if l["id"] == int(args["id"]):
                        l["status"], l["outcome"] = "closed", args.get("outcome", "")
                        return f"Closed L{l['id']}."
                return "No such lead id."
            if name == "finish":
                p1 = b.open_leads(1)
                if p1 and not self._finish_warned:
                    self._finish_warned = True
                    return ("NOT FINISHED YET: you still have open priority-1 leads: " + "; ".join(f"L{l['id']} {l['text'][:80]}" for l in p1) +
                            ". Pursue or close them (a dead end is a valid outcome), then call finish again.")
                b.summary, b.next_steps, self.finished = args.get("summary", ""), args.get("next_steps", ""), True
                return "Investigation finished."
            return f"Unknown tool '{name}'. Available tools are listed in the system prompt."
        except (ch.CHError, web.WebError) as e:
            return f"TOOL ERROR: {e}"
        except KeyError as e:
            return f"TOOL ERROR: missing argument {e}"
        except Exception as e:  # never let one bad call end the investigation
            return f"TOOL ERROR ({type(e).__name__}): {e}"

    # ----- main loop -----
    def run(self, goal, steer="", max_steps=25):
        b = self.board
        b.goal, b.runs = goal, b.runs + 1
        specs, names = self.tool_specs()
        docs_list = "\n".join(f"- {n} ({len(t):,} characters)" for n, t in self.docs.items()) or "(none)"
        user = (f"## Goal\n{goal}\n\n" + (f"## Steer from the buyer\n{steer}\n\n" if steer else "") +
                f"## Deal\n{json.dumps(self.deal, indent=2)}\n\n## Data room\n{docs_list}\n\n## Case board\n{b.brief()}\n\n"
                "Begin. Open leads from what you already know, then pursue the highest-priority ones.")
        messages = [{"role": "system", "content": self.system_prompt(names)}, {"role": "user", "content": user}]
        nudges = 0
        for step in range(1, max_steps + 1):
            self.step = step
            if step == max_steps - 1:
                messages.append({"role": "user", "content": "Two steps left. Record any unrecorded findings, close or note open leads, then call finish."})
            resp = self.client.chat.completions.create(model=self.model, messages=messages, tools=specs, tool_choice="auto", max_tokens=6000)
            b.steps += 1
            b.tokens += getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            a = {"role": "assistant", "content": msg.content or ""}
            if calls:
                a["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls]
            rd = getattr(msg, "reasoning_details", None)
            if rd:
                a["reasoning_details"] = rd
            messages.append(a)
            if msg.content:
                self.on_event({"type": "thought", "step": step, "text": msg.content})
            if not calls:
                nudges += 1
                if nudges >= 2:
                    break
                messages.append({"role": "user", "content": "Use your tools to continue the investigation. If you are done, call finish."})
                continue
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = None
                result = "TOOL ERROR: arguments were not valid JSON." if args is None else self.execute(c.function.name, args)
                b.trail.append({"step": b.steps, "tool": c.function.name, "args": json.dumps(args)[:300] if args is not None else "bad json", "preview": result[:300]})
                self.on_event({"type": "tool", "step": step, "name": c.function.name, "args": args, "preview": result[:300]})
                messages.append({"role": "tool", "tool_call_id": c.id, "content": result})
            compact(messages)
            if self.finished:
                break
        if not self.finished and not b.summary:
            b.summary = f"(Stopped at the step limit with {len(b.open_leads())} open leads. Continue to pursue them.)"
        return b
