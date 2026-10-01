# CRE investigative DD

Run: `export ANTHROPIC_API_KEY=...` then `streamlit run app.py`.
Tests: `python3 -m pytest -q tests`.

- `frameworks/*.md` — one editable file per framework (the method). `00_honesty_rules.md` applies to every run. `questions.md` is the standing question list.
- `core/calc.py` — all arithmetic (hard floor, scenario-weighted IRR, price for target return). Tested.
- `core/runner.py` — sends a framework + deal + data room to Claude (with web search), returns findings with SOURCED/ESTIMATE/UNVERIFIED labels.
- `app.py` — Streamlit front end. Deals persist in `deals/`.
