import json
from types import SimpleNamespace as NS

import pytest
from core import web
from core.agent import Board, Investigator, compact


def call(name, args, cid=None):
    return NS(id=cid or f"c_{name}", function=NS(name=name, arguments=json.dumps(args)))


class FakeClient:
    """Scripted model: each entry is a list of tool calls (or [] for a plain reply)."""
    def __init__(self, script):
        self.script, self.i, self.seen = script, 0, []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.seen.append(kw)
        calls = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        msg = NS(content="thinking", tool_calls=calls or None, reasoning_details=None)
        return NS(choices=[NS(message=msg)], usage=NS(total_tokens=10))


def inv(script, docs=None, board=None, **kw):
    return Investigator({"name": "x"}, docs or {}, board or Board(), FakeClient(script), "m", use_web=False, **kw)


def test_finding_lead_close_finish():
    i = inv([
        [call("record_finding", dict(claim="Rent is 100", kind="fact", label="SOURCED", source="IM p2", source_type="primary", confidence="high"))],
        [call("add_lead", dict(text="Who is seller?", why="unknown", priority=1))],
        [call("close_lead", dict(id=1, outcome="Found: X Ltd"))],
        [call("finish", dict(summary="done", next_steps="call agent"))],
    ])
    b = i.run("goal", max_steps=10)
    assert len(b.findings) == 1 and b.leads[0]["status"] == "closed"
    assert i.finished and b.summary == "done" and b.steps == 4 and len(b.trail) == 4


def test_inference_cannot_be_sourced_and_sourced_needs_source():
    i = inv([[]])
    r = i.execute("record_finding", dict(claim="a", kind="inference", label="SOURCED", source="x", source_type="primary", confidence="high"))
    assert r.startswith("REJECTED")
    r = i.execute("record_finding", dict(claim="a", kind="fact", label="SOURCED", source=" ", source_type="primary", confidence="high"))
    assert r.startswith("REJECTED")
    assert i.board.findings == []
    ok = dict(claim="a", kind="fact", label="SOURCED", source="doc", source_type="primary", confidence="high")
    assert i.execute("record_finding", ok).startswith("Recorded")
    assert i.execute("record_finding", ok).startswith("Duplicate")


def test_unknown_tool_and_bad_args_do_not_crash():
    i = inv([[]])
    assert "Unknown tool" in i.execute("nope", {})
    assert "missing argument" in i.execute("web_search", {})


def test_finish_warns_once_about_open_p1_leads():
    i = inv([[]])
    i.execute("add_lead", dict(text="seller", why="w", priority=1))
    assert "NOT FINISHED" in i.execute("finish", dict(summary="s", next_steps="n"))
    assert not i.finished
    assert i.execute("finish", dict(summary="s", next_steps="n")) == "Investigation finished."
    assert i.finished


def test_max_steps_enforced_and_stop_message():
    script = [[call("add_lead", dict(text="t", why="w", priority=2))]]
    i = inv(script)
    b = i.run("g", max_steps=3)
    assert b.steps == 3 and not i.finished and "step limit" in b.summary


def test_stops_after_two_replies_without_tools():
    i = inv([[]])
    b = i.run("g", max_steps=10)
    assert b.steps == 2


def test_search_documents_and_read():
    i = inv([[]], docs={"acc": "Note 21\n  Related   party transactions\nloan notes redeemed 13 July 2027"})
    assert "13 July 2027" in i.execute("search_documents", {"term": "related party"})
    assert "No matches" in i.execute("search_documents", {"term": "zzz"})
    assert "redeemed" in i.execute("read_document", {"name": "acc", "start": 0, "length": 100})
    assert "No such document" in i.execute("read_document", {"name": "zz"})


def test_ssrf_refused():
    i = inv([[]])
    for u in ["http://127.0.0.1/x", "http://169.254.169.254/latest", "file:///etc/passwd", "http://localhost:8501"]:
        assert i.execute("fetch_url", {"url": u}).startswith("TOOL ERROR"), u
    with pytest.raises(web.WebError):
        web.check_url("http://10.0.0.5/")


def test_long_results_are_capped_with_marker():
    i = inv([[]], docs={"d": "x" * 50000}, result_chars=1000)
    out = i.execute("search_documents", {"term": "x"})
    assert len(out) < 3000
    big = i._cap("y" * 5000)
    assert "TRUNCATED" in big


def test_compact_shortens_old_tool_results_only():
    msgs = [{"role": "tool", "content": "a" * 1000, "tool_call_id": str(n)} for n in range(10)]
    compact(msgs, keep=3)
    assert all(len(m["content"]) < 500 for m in msgs[:7])
    assert all(len(m["content"]) == 1000 for m in msgs[7:])


def test_board_roundtrip_and_resume_brief():
    i = inv([[call("add_lead", dict(text="seller", why="w", priority=1))], [call("finish", dict(summary="s", next_steps="n"))]])
    i.run("g", max_steps=5)
    d = json.loads(json.dumps(i.board.to_dict()))
    b2 = Board.from_dict(d)
    assert b2.leads == i.board.leads and "seller" in b2.brief()
    assert Board.from_dict({"bogus": 1}).findings == []


def test_bad_json_arguments_reported():
    bad = NS(id="c1", function=NS(name="add_lead", arguments="{not json"))
    i = inv([[bad], [call("finish", dict(summary="s", next_steps="n"))]])
    b = i.run("g", max_steps=4)
    assert b.trail[0]["preview"].startswith("TOOL ERROR")
