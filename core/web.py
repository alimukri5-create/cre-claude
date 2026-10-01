"""Web tools for the investigator: safe URL fetching and search through OpenRouter's web plugin."""
import ipaddress, socket
from urllib.parse import urljoin, urlparse

import requests

from .companies_house import pdf_to_text, xhtml_to_text

UA = "Mozilla/5.0 (compatible; CRE-DD-research/1.0)"
MAX_BYTES = 6_000_000


class WebError(RuntimeError):
    pass


def check_url(url: str):
    """Refuse non-http(s) URLs and anything that resolves to a private, loopback or internal address."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise WebError("Only http(s) URLs are allowed.")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        raise WebError(f"Cannot resolve {p.hostname}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise WebError("Refusing to fetch a private or internal address.")


def fetch_url(url: str) -> str:
    """Download a page or PDF and return plain text. Follows up to 5 redirects, checking each hop."""
    r = None
    for _ in range(6):
        check_url(url)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25, allow_redirects=False, stream=True)
        if r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("Location", ""))
            continue
        break
    else:
        raise WebError("Too many redirects.")
    if r.status_code >= 400:
        raise WebError(f"HTTP {r.status_code} from {url}")
    data = b""
    for chunk in r.iter_content(65536):
        data += chunk
        if len(data) > MAX_BYTES:
            break
    ctype = (r.headers.get("Content-Type") or "").lower()
    if "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf"):
        return pdf_to_text(data)
    return xhtml_to_text(data.decode(r.encoding or "utf-8", errors="replace"))


def search(client, model: str, query: str, max_results: int = 6) -> str:
    """Web search via OpenRouter's web plugin. Returns the answer text plus the source URLs."""
    resp = client.chat.completions.create(
        model=model, max_tokens=2500,
        messages=[{"role": "user", "content":
                   f"Search the web and report what you find about: {query}\n"
                   "Give the key facts, dates and numbers, and name the source of each. "
                   "If nothing relevant turns up, say so. Do not guess."}],
        extra_body={"plugins": [{"id": "web", "max_results": max_results}]},
    )
    msg = resp.choices[0].message
    out = msg.content or ""
    urls, seen = [], set()
    for a in getattr(msg, "annotations", None) or []:
        a = a if isinstance(a, dict) else getattr(a, "model_dump", lambda: {})()
        uc = a.get("url_citation") or {}
        u = uc.get("url")
        if u and u not in seen:
            seen.add(u)
            urls.append(f"- {uc.get('title') or ''} {u}".strip())
    return out + ("\n\nSources:\n" + "\n".join(urls) if urls else "")
