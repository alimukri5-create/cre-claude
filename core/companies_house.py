"""Companies House official API client + 'dossier' builder.

Free key: developer.company-information.service.gov.uk. Auth = HTTP basic, key as username, blank password.
A dossier is plain text (profile, officers, controllers, charges, filing history, latest accounts text)
that drops straight into the data room so every framework can read it as a primary source.
"""
import io, os, re
from html.parser import HTMLParser

import requests

API = "https://api.company-information.service.gov.uk"
TIMEOUT = 30


class CHError(RuntimeError):
    pass


def _auth():
    key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    if not key:
        raise CHError("Set COMPANIES_HOUSE_API_KEY (developer.company-information.service.gov.uk) to use Companies House lookups.")
    return (key, "")


def _get(url, params=None, accept="application/json", stream=False):
    r = requests.get(url, params=params, auth=_auth(), headers={"Accept": accept}, timeout=TIMEOUT, allow_redirects=True)
    if r.status_code == 404:
        raise CHError(f"Not found: {url}")
    if r.status_code == 401:
        raise CHError("Companies House rejected the API key (401). Check COMPANIES_HOUSE_API_KEY.")
    if r.status_code == 429:
        raise CHError("Companies House rate limit hit (600 requests / 5 min). Wait a few minutes.")
    if r.status_code >= 400:
        raise CHError(f"Companies House error {r.status_code} for {url}")
    return r


def _json(path, params=None):
    return _get(f"{API}{path}", params).json()


def norm_number(s: str) -> str:
    """Company numbers are 8 chars; pad numeric ones with leading zeros."""
    s = s.strip().upper().replace(" ", "")
    return s.zfill(8) if s.isdigit() else s


def looks_like_number(s: str) -> bool:
    s = s.strip().replace(" ", "")
    return bool(re.fullmatch(r"[A-Za-z]{0,2}\d{6,8}", s))


def search(query: str, n: int = 8):
    items = _json("/search/companies", {"q": query, "items_per_page": n}).get("items", [])
    return [{"number": i.get("company_number"), "name": i.get("title"), "status": i.get("company_status"),
             "address": i.get("address_snippet", "")} for i in items]


# ---------- accounts text extraction ----------
class _Text(HTMLParser):
    BLOCK = {"p", "div", "tr", "br", "li", "h1", "h2", "h3", "h4", "table", "section"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "ix:header"):
            self.skip += 1
        elif tag in ("td", "th"):
            self.out.append(" | ")
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "ix:header"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def xhtml_to_text(markup: str) -> str:
    p = _Text()
    p.feed(markup)
    text = "".join(p.out)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    return "\n".join(f"[p{i+1}] " + (pg.extract_text() or "") for i, pg in enumerate(r.pages))


def read_filing(filing: dict) -> str:
    """Fetch the document behind a filing-history item and return its text. Prefers iXBRL (real text) over PDF."""
    meta_url = (filing.get("links") or {}).get("document_metadata")
    if not meta_url:
        return "[no document attached to this filing]"
    meta = _get(meta_url).json()
    resources = meta.get("resources", {})
    content_url = (meta.get("links") or {}).get("document")
    if not content_url:
        return "[document has no content link]"
    if "application/xhtml+xml" in resources:
        r = _get(content_url, accept="application/xhtml+xml")
        return xhtml_to_text(r.text)
    if "application/pdf" in resources:
        r = _get(content_url, accept="application/pdf")
        text = pdf_to_text(r.content)
        if len(re.sub(r"\[p\d+\]|\s", "", text)) < 200:
            return "[PDF has almost no extractable text: probably scanned. Needs OCR or manual reading.]"
        return text
    return f"[no readable format available: {list(resources)}]"


# ---------- dossier ----------
def _addr(a):
    return ", ".join(str(a[k]) for k in ("address_line_1", "address_line_2", "locality", "postal_code") if a and a.get(k))


def build_dossier(number: str, accounts_chars: int = 90_000, filings: int = 30) -> dict:
    """Returns {"name":..., "number":..., "text":..., "notes":[...]} for one company."""
    n = norm_number(number)
    prof = _json(f"/company/{n}")
    name = prof.get("company_name", n)
    notes, L = [], [f"# Companies House dossier: {name} ({n})", "Source: Companies House official API (primary source).", ""]

    acc = prof.get("accounts", {}) or {}
    la = acc.get("last_accounts", {}) or {}
    L += ["## Profile",
          f"Status: {prof.get('company_status')} | Type: {prof.get('type')} | Incorporated: {prof.get('date_of_creation')}",
          f"Registered office: {_addr(prof.get('registered_office_address'))}",
          f"SIC: {', '.join(prof.get('sic_codes', []) or [])}",
          f"Last accounts made up to: {la.get('made_up_to')} ({la.get('type')}) | Next accounts due: {acc.get('next_due')} | Overdue: {acc.get('overdue')}",
          f"Has charges: {prof.get('has_charges')} | Has insolvency history: {prof.get('has_insolvency_history')}", ""]

    try:
        off = _json(f"/company/{n}/officers", {"items_per_page": 100}).get("items", [])
        L.append("## Officers")
        for o in sorted(off, key=lambda x: (x.get("resigned_on") or "9999", x.get("name", ""))):
            L.append(f"- {o.get('name')} | {o.get('officer_role')} | appointed {o.get('appointed_on')} | resigned {o.get('resigned_on') or 'current'}")
        L.append("")
    except CHError as e:
        notes.append(f"officers: {e}")

    try:
        pscs = _json(f"/company/{n}/persons-with-significant-control", {"items_per_page": 100}).get("items", [])
        L.append("## Persons with significant control")
        for p in pscs:
            L.append(f"- {p.get('name')} | {p.get('kind')} | {', '.join(p.get('natures_of_control', []))} | notified {p.get('notified_on')} | ceased {p.get('ceased_on') or 'current'}")
        L.append("")
    except CHError as e:
        notes.append(f"PSC: {e}")

    try:
        ch = _json(f"/company/{n}/charges").get("items", [])
        L.append("## Charges (secured lending against the company)")
        if not ch:
            L.append("None registered.")
        for c in ch:
            who = "; ".join(p.get("name", "") for p in c.get("persons_entitled", []))
            L.append(f"- {c.get('status')} | created {c.get('created_on')} | delivered {c.get('delivered_on')} | "
                     f"satisfied {c.get('satisfied_on') or 'no'} | in favour of: {who} | {(c.get('classification') or {}).get('description', '')}")
        L.append("")
    except CHError as e:
        notes.append(f"charges: {e}")

    fh = []
    try:
        fh = _json(f"/company/{n}/filing-history", {"items_per_page": filings}).get("items", [])
        L.append(f"## Filing history (latest {len(fh)})")
        for f in fh:
            L.append(f"- {f.get('date')} | {f.get('category')} | {f.get('type')} | {f.get('description')}")
        L.append("")
    except CHError as e:
        notes.append(f"filing history: {e}")

    # latest accounts, read in full
    accounts = [f for f in fh if f.get("category") == "accounts"]
    if not accounts:
        try:
            accounts = _json(f"/company/{n}/filing-history", {"category": "accounts", "items_per_page": 5}).get("items", [])
        except CHError:
            accounts = []
    if accounts:
        latest = accounts[0]
        try:
            text = read_filing(latest)
            if len(text) > accounts_chars:
                notes.append(f"accounts text truncated from {len(text):,} to {accounts_chars:,} characters")
                text = text[:accounts_chars]
            L += [f"## Latest filed accounts (filed {latest.get('date')}, {latest.get('description')})", text, ""]
            if text.startswith("["):
                notes.append(f"accounts not readable: {text}")
        except CHError as e:
            notes.append(f"could not read accounts: {e}")
            L += ["## Latest filed accounts", f"[COULD NOT READ: {e}]", ""]
    else:
        L += ["## Latest filed accounts", "[No accounts filing found. Company may be exempt or newly formed.]", ""]

    return {"name": name, "number": n, "text": "\n".join(L), "notes": notes}
