import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from core.runner import clean, parse_json


def test_clean_strips_cite_tags_everywhere():
    d = {"summary": 'a <cite index="1-2">quoted</cite> b', "findings": [{"claim": '<cite index="58-10">X | 99.41 %</cite>'}]}
    out = clean(d)
    assert "<cite" not in str(out) and "</cite>" not in str(out)
    assert out["findings"][0]["claim"] == "X | 99.41 %"

def test_clean_leaves_numbers_alone():
    assert clean({"n": 5, "l": [1, "x"]}) == {"n": 5, "l": [1, "x"]}

def test_parse_json_survives_garbage():
    assert parse_json("no json here")["parse_error"] is True
    assert parse_json('x {"summary": "ok"} y')["summary"] == "ok"


def test_prompt_contains_todays_date():
    import datetime
    from core.runner import build_prompt
    p = build_prompt({"name": "x"}, {}, "# fw", None, "rules")
    assert datetime.date.today().isoformat() in p


def test_fit_never_truncates_silently():
    from core.runner import fit
    assert fit("abc", 10) == "abc"
    out = fit("x" * 100, 10)
    assert out.startswith("x" * 10) and "TRUNCATED" in out and "100" in out

def test_prompt_marks_truncated_docs():
    from core.runner import build_prompt
    p = build_prompt({"name": "x"}, {"long.txt": "y" * 500}, "# fw", None, "rules", doc_limit=100)
    assert "TRUNCATED" in p
    p2 = build_prompt({"name": "x"}, {"short.txt": "y" * 50}, "# fw", None, "rules", doc_limit=100)
    assert "TRUNCATED" not in p2
