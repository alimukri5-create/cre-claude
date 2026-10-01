import sys, pathlib, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest
from core import companies_house as ch


def test_norm_and_looks_like_number():
    assert ch.norm_number("5047798") == "05047798"
    assert ch.norm_number("sc 123456") == "SC123456"
    assert ch.looks_like_number("05047798") and ch.looks_like_number("SC123456")
    assert not ch.looks_like_number("Brompton Technology")


def test_missing_key_message(monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    with pytest.raises(ch.CHError, match="COMPANIES_HOUSE_API_KEY"):
        ch._auth()


def test_auth_is_basic_key_blank_password(monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "abc")
    assert ch._auth() == ("abc", "")


IXBRL = """<html><body><ix:header><div>HIDDEN_FACTS 999</div></ix:header>
<h1>Carallon Limited</h1><p>Debtors: amounts owed by connected companies</p>
<table><tr><td>Connected company</td><td>8,920,000</td></tr></table><script>var x=1</script></body></html>"""


def test_xhtml_to_text_skips_hidden_and_keeps_table():
    t = ch.xhtml_to_text(IXBRL)
    assert "HIDDEN_FACTS" not in t and "var x" not in t
    assert "amounts owed by connected companies" in t
    assert "Connected company | 8,920,000" in t.replace("\n", " ").replace("  ", " ") or "8,920,000" in t


class FakeResp:
    def __init__(self, data=None, text="", content=b"", status=200):
        self._d, self.text, self.content, self.status_code = data, text, content, status
    def json(self): return self._d


def fake_get_factory():
    def fake_get(url, params=None, accept="application/json", stream=False):
        if url.endswith("/company/05047798"):
            return FakeResp({"company_name": "CARALLON LIMITED", "company_status": "active", "type": "ltd",
                             "date_of_creation": "2004-02-18", "registered_office_address": {"address_line_1": "272 Gunnersbury Avenue", "postal_code": "W4 2LL"},
                             "accounts": {"last_accounts": {"made_up_to": "2025-07-31", "type": "full"}, "next_due": "2027-04-30", "overdue": False}, "has_charges": True})
        if url.endswith("/officers"):
            return FakeResp({"items": [{"name": "WAGNER, William", "officer_role": "director", "appointed_on": "2010-01-01", "resigned_on": "2026-01-30"}]})
        if url.endswith("/persons-with-significant-control"):
            return FakeResp({"items": [{"name": "Carallon Holdings Ltd", "kind": "corporate-entity-person-with-significant-control", "natures_of_control": ["ownership-of-shares-75-to-100-percent"], "notified_on": "2016-04-06"}]})
        if url.endswith("/charges"):
            return FakeResp({"items": [{"status": "outstanding", "created_on": "2024-11-01", "persons_entitled": [{"name": "Some Bank plc"}], "classification": {"description": "Debenture"}}]})
        if url.endswith("/filing-history"):
            return FakeResp({"items": [
                {"date": "2025-08-19", "category": "accounts", "type": "AA", "description": "accounts-with-accounts-type-full",
                 "links": {"document_metadata": "https://document-api.example/document/abc"}},
                {"date": "2026-04-07", "category": "officers", "type": "TM01", "description": "termination-director"}]})
        if url == "https://document-api.example/document/abc":
            return FakeResp({"resources": {"application/xhtml+xml": {}, "application/pdf": {}}, "links": {"document": "https://document-api.example/document/abc/content"}})
        if url.endswith("/content"):
            assert accept == "application/xhtml+xml"
            return FakeResp(text=IXBRL)
        raise AssertionError("unexpected url " + url)
    return fake_get


def test_dossier_end_to_end_with_mock(monkeypatch):
    monkeypatch.setattr(ch, "_get", fake_get_factory())
    d = ch.build_dossier("5047798")
    t = d["text"]
    assert d["name"] == "CARALLON LIMITED" and d["number"] == "05047798"
    assert "272 Gunnersbury Avenue" in t
    assert "resigned 2026-01-30" in t
    assert "Some Bank plc" in t and "Debenture" in t
    assert "8,920,000" in t               # accounts text was actually read
    assert "HIDDEN_FACTS" not in t
    assert d["notes"] == []


def test_dossier_survives_unreadable_accounts(monkeypatch):
    base = fake_get_factory()
    def flaky(url, params=None, accept="application/json", stream=False):
        if url.endswith("/content"):
            raise ch.CHError("boom")
        return base(url, params, accept, stream)
    monkeypatch.setattr(ch, "_get", flaky)
    d = ch.build_dossier("05047798")
    assert "COULD NOT READ" in d["text"] and any("could not read accounts" in n for n in d["notes"])


def test_search_parsing(monkeypatch):
    monkeypatch.setattr(ch, "_json", lambda path, params=None: {"items": [{"title": "BROMPTON TECHNOLOGY LIMITED", "company_number": "08016277", "company_status": "active", "address_snippet": "London"}]})
    assert ch.search("brompton")[0]["number"] == "08016277"
