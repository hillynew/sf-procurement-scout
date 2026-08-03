"""Go Deep: input building, report normalization, caching. No network."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from src.ai import deep_dive
from src.models.opportunity import Document, Opportunity


def make_opp(**kw) -> Opportunity:
    defaults = dict(
        source_id="test-src",
        source_name="Test Source",
        title="Roof Replacement — City Hall",
        url="https://example.gov/roof",
        county="broward",
        agency="City of Testville",
        status="open",
        due_date=datetime.utcnow() + timedelta(days=14),
        posted_date=date.today(),
    )
    defaults.update(kw)
    return Opportunity(**defaults)


RAW_REPORT = {
    "overview": "Re-roof city hall.",
    "dollar_amounts": [
        {"label": "Engineer's estimate", "amount": "$1,200,000", "source": "ITB p.2"},
        {"label": "no amount key means dropped"},
        "not a dict",
    ],
    "key_dates": [{"label": "Bid due", "date": "2026-09-01"}],
    "scope_items": ["Tear-off", 42, "  ", "Install TPO"],
    "requirements": [{"category": "bonding", "item": "5% bid bond"},
                     {"category": "other"}],
    "evaluation": "not a list",
    "contacts": [{"name": "Pat Buyer", "email": "pat@example.gov"}],
    "documents_reviewed": [{"name": "ITB.pdf", "gist": "Main terms."}],
    "red_flags": ["Tight schedule"],
    "open_questions": [],
    "fit_assessment": "  Good fit for mid-size roofers. ",
}


def test_normalize_report_guarantees_shapes():
    got = deep_dive.normalize_report(RAW_REPORT)
    assert got["overview"] == "Re-roof city hall."
    assert got["dollar_amounts"] == [
        {"label": "Engineer's estimate", "amount": "$1,200,000", "source": "ITB p.2"}]
    assert got["scope_items"] == ["Tear-off", "42", "Install TPO"]
    assert got["requirements"] == [{"category": "bonding", "item": "5% bid bond"}]
    assert got["evaluation"] == []
    assert got["contacts"] == [{"name": "Pat Buyer", "email": "pat@example.gov"}]
    assert got["fit_assessment"] == "Good fit for mid-size roofers."


def test_normalize_report_survives_garbage():
    got = deep_dive.normalize_report({})
    assert got["overview"] == ""
    for key in ("dollar_amounts", "key_dates", "scope_items", "requirements",
                "evaluation", "contacts", "documents_reviewed", "red_flags",
                "open_questions"):
        assert got[key] == []


def test_build_deep_input_without_documents():
    text, read = deep_dive.build_deep_input(make_opp())
    assert read == 0
    assert "SCRAPED LISTING" in text
    assert "No documents could be read" in text


def test_build_deep_input_reads_pdfs(monkeypatch):
    opp = make_opp(documents=[
        Document(name="ITB.pdf", url="https://example.gov/itb.pdf", kind="document"),
        Document(name="Photos.zip", url="https://example.gov/photos.zip", kind="document"),
    ])
    # fetch_text returns '' for non-PDF payloads (the zip); text for the PDF.
    monkeypatch.setattr("src.pdf_extract.fetch_text",
                        lambda url, **kw: "PDF BODY TEXT" if url.endswith(".pdf") else "")
    text, read = deep_dive.build_deep_input(opp)
    assert read == 1
    assert "DOCUMENT 1: ITB.pdf" in text
    assert "PDF BODY TEXT" in text


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from src.db import engine as db_engine

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    db_engine.reset_engine()
    from src.db import store

    store.bootstrap()
    yield store
    db_engine.reset_engine()


def test_deep_dive_store_roundtrip_and_prune(db):
    assert db.get_deep_dive("opp1") is None
    db.put_deep_dive("opp1", content_hash="h1", model="claude-haiku-4-5",
                     prompt_version=1, report={"overview": "x"},
                     input_chars=100, docs_read=3)
    got = db.get_deep_dive("opp1")
    assert got["report"]["overview"] == "x"
    assert got["docs_read"] == 3
    # Version gate hides it, prune deletes it.
    assert db.get_deep_dive("opp1", min_prompt_version=2) is None
    assert db.prune_deep_dives(2) == 1
    assert db.get_deep_dive("opp1") is None


def test_run_deep_dive_caches_by_content(db, monkeypatch):
    monkeypatch.setenv("SF_SCOUT_ANTHROPIC_KEY", "test-key")
    calls = []

    def fake_call(model, text):
        calls.append(model)
        return dict(RAW_REPORT)

    monkeypatch.setattr(deep_dive, "_call_claude", fake_call)
    opp = make_opp()

    first = deep_dive.run_deep_dive(opp)
    assert first["cached"] is False
    assert first["report"]["overview"] == "Re-roof city hall."
    assert calls == [deep_dive.DEFAULT_MODEL]

    second = deep_dive.run_deep_dive(opp)
    assert second["cached"] is True
    assert calls == [deep_dive.DEFAULT_MODEL]  # no second API call

    third = deep_dive.run_deep_dive(opp, force=True)
    assert third["cached"] is False
    assert len(calls) == 2


def test_run_deep_dive_requires_key(db, monkeypatch):
    monkeypatch.delenv("SF_SCOUT_ANTHROPIC_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no_api_key"):
        deep_dive.run_deep_dive(make_opp())


# ---------------------------------------------------------------------------
# On-demand detail enrichment
# ---------------------------------------------------------------------------


class _DetailAdapter:
    """Stands in for a real adapter that can enrich one bid."""

    source_id = "sample"
    supports_detail = True

    def __init__(self, docs=None, boom=False):
        self.docs = docs or []
        self.boom = boom
        self.calls = 0

    def fetch_detail(self, opp):
        self.calls += 1
        if self.boom:
            raise RuntimeError("portal blocked this client")
        opp.documents = list(self.docs)
        opp.detail_fetched = True


def _patch_adapters(monkeypatch, adapter):
    import src.sources.registry as registry

    monkeypatch.setattr(registry, "get_adapters", lambda *a, **k: [adapter])


def test_ensure_detail_enriches_a_bid_the_capped_pass_missed(monkeypatch, opp_factory):
    """The whole point: no documents means the dive can only read the listing."""
    from src.models.opportunity import Document
    from web.api.bids import ensure_detail

    doc = Document(name="ITB package.pdf", url="https://example.com/a.pdf")
    adapter = _DetailAdapter(docs=[doc])
    _patch_adapters(monkeypatch, adapter)
    monkeypatch.setattr("src.db.store.save_opportunity", lambda opp: True)

    opp = opp_factory(source_id="sample", detail_fetched=False, documents=[])
    assert ensure_detail(opp) is True
    assert adapter.calls == 1
    assert [d.name for d in opp.documents] == ["ITB package.pdf"]


def test_ensure_detail_skips_a_bid_already_enriched(monkeypatch, opp_factory):
    from web.api.bids import ensure_detail

    adapter = _DetailAdapter()
    _patch_adapters(monkeypatch, adapter)

    opp = opp_factory(source_id="sample", detail_fetched=True)
    assert ensure_detail(opp) is False
    assert adapter.calls == 0, "a second request for data we already have"


def test_ensure_detail_survives_a_failing_portal(monkeypatch, opp_factory):
    """An un-enriched dive still beats no dive at all."""
    from web.api.bids import ensure_detail

    adapter = _DetailAdapter(boom=True)
    _patch_adapters(monkeypatch, adapter)

    opp = opp_factory(source_id="sample", detail_fetched=False)
    assert ensure_detail(opp) is False


def test_ensure_detail_ignores_sources_without_a_detail_page(monkeypatch, opp_factory):
    from web.api.bids import ensure_detail

    adapter = _DetailAdapter()
    adapter.supports_detail = False
    _patch_adapters(monkeypatch, adapter)

    opp = opp_factory(source_id="sample", detail_fetched=False)
    assert ensure_detail(opp) is False
    assert adapter.calls == 0


# ---------------------------------------------------------------------------
# Portal-specific document headers
# ---------------------------------------------------------------------------


def test_document_headers_reach_the_download(monkeypatch):
    """MFMP serves its SPA shell unless the download asks for it as XHR.

    The failure this guards is silent: an HTML-first Accept gets a 200 that is
    not a PDF, `fetch_text` correctly returns '', and the dive reports the bid
    as simply having no documents.
    """
    seen = {}

    def _reader(url, **kw):
        seen[url] = kw.get("headers")
        return "PDF BODY TEXT"

    monkeypatch.setattr("src.pdf_extract.fetch_text", _reader)
    monkeypatch.setattr(
        "src.sources.registry.document_headers",
        lambda source_id: (("Accept", "application/json, text/plain, */*"),),
    )

    opp = make_opp(documents=[
        Document(name="ITB.pdf", url="https://example.gov/itb.pdf", kind="document"),
    ])
    deep_dive.build_deep_input(opp)
    assert seen["https://example.gov/itb.pdf"] == {
        "Accept": "application/json, text/plain, */*"
    }


def test_a_source_without_quirks_sends_no_extra_headers(monkeypatch):
    seen = {}

    def _reader(url, **kw):
        seen[url] = kw.get("headers")
        return "PDF BODY TEXT"

    monkeypatch.setattr("src.pdf_extract.fetch_text", _reader)
    monkeypatch.setattr("src.sources.registry.document_headers", lambda source_id: ())

    opp = make_opp(documents=[
        Document(name="ITB.pdf", url="https://example.gov/itb.pdf", kind="document"),
    ])
    deep_dive.build_deep_input(opp)
    assert seen["https://example.gov/itb.pdf"] == {}


def test_mfmp_declares_the_accept_its_portal_requires():
    """Verified against a live attachment: this Accept is the whole difference."""
    from src.sources.registry import document_headers

    assert dict(document_headers("mfmp_vbs")) == {
        "Accept": "application/json, text/plain, */*"
    }


def test_document_headers_is_empty_for_an_unknown_source():
    from src.sources.registry import document_headers

    assert dict(document_headers("no_such_source")) == {}
