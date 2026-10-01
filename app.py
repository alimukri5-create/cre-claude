import json, os
from pathlib import Path
import streamlit as st

from core import calc
from core.docs import to_text
from core.frameworks import honesty_rules, list_frameworks
from core.memo import build_memo
from core.runner import run_framework

DEALS = Path(__file__).parent / "deals"
DEALS.mkdir(exist_ok=True)

st.set_page_config(page_title="CRE Investigative DD", layout="wide")
st.title("CRE investigative due diligence")

# ---------- hosting: secrets + password gate ----------
try:
    _sec = dict(st.secrets)
except Exception:
    _sec = {}
if _sec.get("OPENROUTER_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = _sec["OPENROUTER_API_KEY"]
if _sec.get("COMPANIES_HOUSE_API_KEY") and not os.environ.get("COMPANIES_HOUSE_API_KEY"):
    os.environ["COMPANIES_HOUSE_API_KEY"] = _sec["COMPANIES_HOUSE_API_KEY"]
if _sec.get("APP_PASSWORD"):
    if st.session_state.get("authed") is not True:
        pw = st.text_input("Password", type="password")
        if pw and pw == _sec["APP_PASSWORD"]:
            st.session_state["authed"] = True
            st.rerun()
        st.stop()

# ---------- deal selection / persistence ----------
def slug(s): return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-") or "deal"
def load(name):
    p = DEALS / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None
def save(name, state): (DEALS / f"{name}.json").write_text(json.dumps(state, indent=2))

with st.sidebar:
    st.header("Deal")
    existing = sorted(p.stem for p in DEALS.glob("*.json"))
    pick = st.selectbox("Open deal", ["(new)"] + existing)
    new_name = st.text_input("New deal name", "", placeholder="272 Gunnersbury Avenue") if pick == "(new)" else ""
    key = slug(new_name) if pick == "(new)" and new_name else (pick if pick != "(new)" else None)
    st.divider()
    use_web = st.toggle("Web search", True)
    from core.runner import DEFAULT_MODEL
    model = st.text_input("Model (OpenRouter ID)", DEFAULT_MODEL, help="Copy the exact ID from openrouter.ai/models, e.g. anthropic/claude-sonnet-4.5")
    if not os.environ.get("OPENROUTER_API_KEY"):
        st.warning("OPENROUTER_API_KEY is not set. Frameworks can't run until it is.")

if not key:
    st.info("Name a new deal (or open one) in the sidebar to start.")
    st.stop()

state = load(key) or {"deal": {"name": new_name or key}, "docs": {}, "results": {}, "calc": {}}
deal, docs, results = state["deal"], state["docs"], state["results"]

tab_deal, tab_run, tab_calc, tab_memo = st.tabs(["1 Deal & data room", "2 Run frameworks", "3 Calculator", "4 Memo"])

# ---------- 1. deal + data room ----------
with tab_deal:
    c1, c2 = st.columns(2)
    deal["name"] = c1.text_input("Name", deal.get("name", ""))
    deal["address"] = c1.text_input("Address", deal.get("address", ""))
    deal["asset_type"] = c1.text_input("Asset type", deal.get("asset_type", "single-let office"))
    deal["tenant"] = c1.text_input("Tenant (and company number if known)", deal.get("tenant", ""))
    deal["seller"] = c2.text_input("Seller / agent", deal.get("seller", ""))
    deal["asking_price"] = c2.text_input("Asking / guide price", deal.get("asking_price", ""))
    deal["lease_summary"] = c2.text_area("Lease summary (rent, expiry, breaks, reviews, 1954 Act)", deal.get("lease_summary", ""), height=100)
    deal["notes"] = st.text_area("Anything else the model should know (agent claims, your hunches, what the seller said)", deal.get("notes", ""), height=100)

    # ---- Companies House ----
    st.subheader("Companies House (primary source)")
    st.caption("Search a company by name or number. The dossier (officers, owners, charges, filing history and the full text of the latest filed accounts) is added to the data room, so every framework reads it.")
    if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
        st.info("Add COMPANIES_HOUSE_API_KEY to your Streamlit secrets to turn this on.")
    else:
        from core import companies_house as ch
        q = st.text_input("Company name or number", key="ch_q", placeholder="05047798  or  Brompton Technology")
        c1_, c2_ = st.columns([1, 3])
        if c1_.button("Look up", disabled=not q):
            try:
                if ch.looks_like_number(q):
                    with st.spinner("Reading Companies House filings (this can take a minute)..."):
                        d = ch.build_dossier(q)
                    docs[f"CH dossier - {d['name']} ({d['number']})"] = d["text"]
                    st.session_state["ch_hits"], st.session_state["ch_notes"] = [], d["notes"]
                    st.success(f"Added dossier for {d['name']} ({d['number']}).")
                else:
                    st.session_state["ch_hits"] = ch.search(q)
                    st.session_state["ch_notes"] = []
            except ch.CHError as e:
                st.error(str(e))
        hits = st.session_state.get("ch_hits") or []
        if hits:
            labels = [f"{h['name']} ({h['number']}) - {h['status']} - {h['address']}" for h in hits]
            sel = st.selectbox("Pick the right company", labels, key="ch_pick")
            if st.button("Fetch dossier for selected"):
                h = hits[labels.index(sel)]
                try:
                    with st.spinner("Reading Companies House filings (this can take a minute)..."):
                        d = ch.build_dossier(h["number"])
                    docs[f"CH dossier - {d['name']} ({d['number']})"] = d["text"]
                    st.session_state["ch_hits"], st.session_state["ch_notes"] = [], d["notes"]
                    st.success(f"Added dossier for {d['name']} ({d['number']}).")
                except ch.CHError as e:
                    st.error(str(e))
        for n_ in st.session_state.get("ch_notes") or []:
            st.warning(n_)

    ups = st.file_uploader("Data room / IM / accounts (PDF, DOCX, TXT)", accept_multiple_files=True)
    for u in ups or []:
        docs[u.name] = to_text(u.name, u.getvalue())
    if docs:
        st.caption(f"{len(docs)} document(s) loaded: " + ", ".join(f"{n} ({len(t):,} chars)" for n, t in docs.items()))
        bad = [n for n, t in docs.items() if t.startswith("[COULD NOT READ")]
        if bad: st.error("Could not read: " + ", ".join(bad))

# ---------- 2. run frameworks ----------
with tab_run:
    fws = list_frameworks()
    st.caption("Each framework is a plain text file in /frameworks. Edit the file to change what it asks.")
    chosen = [fid for fid, title, _ in fws if st.checkbox(title, value=fid in results, key=f"cb_{fid}")]
    if st.button("Run selected", type="primary", disabled=not chosen):
        honesty = honesty_rules()
        for fid, title, text in fws:
            if fid not in chosen: continue
            with st.spinner(f"Running: {title}"):
                try:
                    results[fid] = run_framework(deal, docs, fid, text, honesty, prior=results, use_web=use_web, model=model)
                except Exception as e:
                    results[fid] = {"summary": f"FAILED: {e}", "findings": [], "error": True}
            save(key, state)
    for fid, title, _ in fws:
        r = results.get(fid)
        if not r: continue
        with st.expander(title, expanded=False):
            if r.get("truncated") or r.get("parse_error"):
                st.warning("This answer was cut off or came back in the wrong format, so findings may be missing. Re-run it, or pick a model with a larger output limit.")
            st.write(r.get("summary", ""))
            for f in r.get("findings", []):
                st.markdown(f"**{f.get('label','?')}** · {f.get('kind','?')} · {f.get('source_type','?')} · {f.get('confidence','?')} — {f.get('claim','')}  \n<small>{f.get('source','')}</small>", unsafe_allow_html=True)
            if r.get("red_flags"): st.error("\n".join(f"• {x}" for x in r["red_flags"]))
            if r.get("calculator_inputs"): st.json(r["calculator_inputs"])
            if r.get("could_not_access"): st.warning("Could not access: " + "; ".join(r["could_not_access"]))

# ---------- 3. calculator ----------
with tab_calc:
    st.caption("All arithmetic here is plain code (core/calc.py), tested. The model supplies judgement inputs; it never computes returns.")
    c = state["calc"]
    a, b, d = st.columns(3)
    price = a.number_input("Headline price £", 0.0, 1e9, float(c.get("price", 10_000_000)), 50_000.0)
    rent = a.number_input("Passing rent £ pa", 0.0, 1e8, float(c.get("rent", 1_224_000)), 10_000.0)
    yrs = a.number_input("Years of term certain", 0.0, 50.0, float(c.get("yrs", 5.5)), 0.1)
    sdlt = b.number_input("SDLT rate", 0.0, 0.2, float(c.get("sdlt", 0.05)), 0.005, format="%.3f")
    fees = b.number_input("Fees/VAT rate", 0.0, 0.1, float(c.get("fees", 0.0176)), 0.001, format="%.4f")
    target = b.number_input("Target unlevered return", 0.0, 0.5, float(c.get("target", 0.095)), 0.005, format="%.3f")
    deposit = d.number_input("Rent deposit £", 0.0, 1e8, float(c.get("deposit", 0.0)), 10_000.0)
    land = d.number_input("Bare land value, net of demolition £", 0.0, 1e9, float(c.get("land", 0.0)), 50_000.0)
    empty = d.number_input("Empty-building value £", 0.0, 1e9, float(c.get("empty", 0.0)), 50_000.0)
    cost = calc.all_in_cost(price, sdlt, fees)

    st.subheader("Hard floor")
    h = calc.hard_floor(cost, rent, yrs, deposit, land, empty)
    m = st.columns(4)
    m[0].metric("All-in cost", f"£{cost:,.0f}")
    m[1].metric("Certain cash (rent + deposit)", f"£{h['certain_cash']:,.0f}")
    m[2].metric("Money at risk", f"£{h['money_at_risk']:,.0f}")
    m[3].metric("Land cover / empty cover", f"{h['land_cover']:.2f}x / {h['empty_cover']:.2f}x")
    st.caption(f"Cost fully recovered even if the office thesis fails only up to all-in £{h['break_even_cost_land_floor']:,.0f}. NIY on all-in: {rent/cost:.2%}.")

    st.subheader("Probability-weighted outcomes")
    st.caption("Exit values are at the end of the term certain (year = years above) unless the tenant fails, then sale at the failure year.")
    base = [
        {"name": "Renews", "probability": 0.35, "exit_value": 11_000_000, "fail_year": 0.0},
        {"name": "Leaves, re-let", "probability": 0.25, "exit_value": 9_500_000, "fail_year": 0.0},
        {"name": "Leaves, sold empty", "probability": 0.30, "exit_value": 7_400_000, "fail_year": 0.0},
        {"name": "Tenant fails", "probability": 0.10, "exit_value": 6_000_000, "fail_year": 3.0},
    ]
    import pandas as pd
    st.caption("fail_year > 0 means rent stops then and the sale happens then. Probabilities must sum to 1.")
    edited = st.data_editor(pd.DataFrame(c.get("scenarios", base)), num_rows="dynamic", width="stretch")
    rows = edited.dropna(subset=["name"]).to_dict("records")
    st.warning("Defaults are placeholders. Replace them with the inputs from the framework runs.", icon="⚠️")
    try:
        scs, fy = [], {}
        for r_ in rows:
            t_exit = r_["fail_year"] if r_["fail_year"] else yrs
            scs.append(calc.Scenario(r_["name"], r_["probability"], [(t_exit, r_["exit_value"])]))
            if r_["fail_year"]: fy[r_["name"]] = r_["fail_year"]
        eirr = calc.expected_irr(cost, rent, yrs, scs, fy)
        maxp = calc.price_for_target(target, rent, yrs, scs, fy, sdlt, fees)
        k = st.columns(3)
        k[0].metric("Probability-weighted IRR", f"{eirr:.2%}" if eirr is not None else "n/a")
        k[1].metric(f"Max price for {target:.1%}", f"£{maxp:,.0f}")
        k[2].metric("Exit value needed for target (rent only)", f"£{calc.exit_value_needed(cost, target, rent, yrs):,.0f}")
        st.subheader("Price needed for each target return")
        tbl = [{"target": f"{t:.1%}", "max headline price": f"£{calc.price_for_target(t, rent, yrs, scs, fy, sdlt, fees):,.0f}"} for t in (0.07, 0.08, 0.09, 0.10, 0.11)]
        st.table(tbl)
        calc_summary = (f"All-in cost £{cost:,.0f}; NIY {rent/cost:.2%}; money at risk £{h['money_at_risk']:,.0f}; "
                        f"probability-weighted IRR {eirr:.2%}; max price for {target:.1%}: £{maxp:,.0f}.") if eirr is not None else ""
    except Exception as e:
        st.error(f"Check the scenario table: {e}")
        calc_summary = ""
    state["calc"] = dict(price=price, rent=rent, yrs=yrs, sdlt=sdlt, fees=fees, target=target, deposit=deposit,
                         land=land, empty=empty, scenarios=[dict(r_) for r_ in rows], summary=calc_summary)

# ---------- 4. memo ----------
with tab_memo:
    memo = build_memo(deal, results, state["calc"].get("summary", ""))
    st.markdown(memo)
    st.download_button("Download memo (.md)", memo, file_name=f"{key}-memo.md")

save(key, state)
