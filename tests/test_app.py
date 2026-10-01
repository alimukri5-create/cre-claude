import json, os
from types import SimpleNamespace as NS
from streamlit.testing.v1 import AppTest
from core import memo


def test_investigate_tab_runs_with_fake_model(monkeypatch, tmp_path):
    os.environ["OPENROUTER_API_KEY"] = "test"
    script = [
        [NS(id="1", function=NS(name="add_lead", arguments=json.dumps(dict(text="Who is the seller?", why="unknown", priority=1))))],
        [NS(id="2", function=NS(name="close_lead", arguments=json.dumps(dict(id=1, outcome="X Ltd"))))],
        [NS(id="3", function=NS(name="finish", arguments=json.dumps(dict(summary="All done", next_steps="Call agent"))))],
    ]
    it = iter(script)

    def create(**kw):
        return NS(choices=[NS(message=NS(content="", tool_calls=next(it), reasoning_details=None))], usage=NS(total_tokens=5))
    fake = NS(chat=NS(completions=NS(create=create)))
    import core.runner as runner
    monkeypatch.setattr(runner, "_client", lambda: fake)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file("/home/claude/cre-claude/app.py", default_timeout=30)
    at.run()
    at.sidebar.text_input[0].set_value("Test deal").run()
    assert not at.exception
    btn = [b for b in at.button if b.label == "Start investigating"][0]
    btn.click().run()
    assert not at.exception, at.exception
    assert any("All done" in i.value for i in at.info)


def test_memo_includes_investigation():
    m = memo.build_memo({"name": "d"}, {}, "", {"summary": "S", "findings": [{"label": "SOURCED", "kind": "fact", "claim": "C", "source": "doc"}],
                                               "leads": [{"status": "open", "priority": 1, "text": "L"}], "next_steps": "N"})
    assert "## Investigation" in m and "C (doc)" in m and "P1: L" in m
