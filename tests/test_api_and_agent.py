"""API and agent tests. The agent is tested with a fake Claude client, so no API key is needed."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from raroc import agent
from raroc.api import app
from raroc.rag import search

client = TestClient(app)


def test_health_and_metrics():
    assert client.get("/health").json()["accounts"] == 7020
    r = client.get("/metrics")
    assert "http_requests_total" in r.text


def test_request_id_header_propagates():
    r = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"


def test_key_relationships_endpoint():
    rows = client.get("/relationships/key").json()
    assert len(rows) == 10
    assert any(r["watch_list"] for r in rows)


def test_relationship_404():
    assert client.get("/relationships/R999").status_code == 404


def test_price_endpoint_and_validation():
    ok = client.post("/price", json={"amount": 20e6, "rating": 5, "relationship_id": "R002"})
    assert ok.status_code == 200 and "recommended_spread" in ok.json()
    assert client.post("/price", json={"rating": 42}).status_code == 422


def test_api_key_enforced(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "s3cret")
    assert client.get("/portfolio/summary").status_code == 401
    assert client.get("/portfolio/summary", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # health stays open


def test_policy_search_cites_sections():
    top = search("who approves a pricing exception below floor")[0]
    assert top["citation"].endswith("Pricing Exceptions and Approvals")


# ---------- agent loop with a scripted fake client ------------------------------------------
def _block(**kw):
    return SimpleNamespace(**kw)


def _msg(content, stop):
    usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop, usage=usage, model="fake-model")


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})  # snapshot
        return self.script.pop(0)


def test_agent_runs_tools_and_returns_answer(monkeypatch):
    monkeypatch.setattr(agent, "MODEL", "fake-model")
    script = [
        _msg([_block(type="tool_use", id="t1", name="get_relationship",
                     input={"relationship_id": "R007"}),
              _block(type="tool_use", id="t2", name="search_policy",
                     input={"query": "watch list"})], "tool_use"),
        _msg([_block(type="text", text="Blue Mesa is on the watch list.")], "end_turn"),
    ]
    fake = FakeClient(script)
    r = agent.ask("How is Blue Mesa doing?", client=fake)
    assert r.answer == "Blue Mesa is on the watch list."
    assert [c["tool"] for c in r.tool_calls] == ["get_relationship", "search_policy"]
    # both tool results returned in ONE user message
    results = fake.calls[1]["messages"][-1]["content"]
    assert len(results) == 2 and all(x["type"] == "tool_result" for x in results)
    assert r.usage["input_tokens"] == 200


def test_agent_tool_errors_go_back_to_model(monkeypatch):
    monkeypatch.setattr(agent, "MODEL", "fake-model")
    script = [
        _msg([_block(type="tool_use", id="t1", name="get_relationship",
                     input={"relationship_id": "R999"})], "tool_use"),
        _msg([_block(type="text", text="Not found.")], "end_turn"),
    ]
    fake = FakeClient(script)
    r = agent.ask("R999?", client=fake)
    assert r.tool_calls[0]["is_error"] is True
    assert fake.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_agent_handles_refusal(monkeypatch):
    monkeypatch.setattr(agent, "MODEL", "fake-model")
    fake = FakeClient([_msg([], "refusal")])
    assert "declined" in agent.ask("x", client=fake).answer


@pytest.mark.parametrize("tool", [t["name"] for t in agent.TOOLS])
def test_every_tool_has_handler(tool):
    assert tool in agent._HANDLERS


def test_model_settings_via_api():
    base = client.get("/portfolio/summary").json()
    params = {"capital_basis": "regulatory", "basel_approach": "SA"}
    reg = client.get("/portfolio/summary", params=params).json()
    tot = lambda s: next(r for r in s["by_product"] if r["product"] == "Total Portfolio")  # noqa: E731
    assert reg["model_settings"]["basel_approach"] == "SA"
    assert tot(reg)["raroc"] < tot(base)["raroc"]
    assert client.get("/portfolio/summary", params={"basel_approach": "Basel IV"}).status_code == 422
    priced = client.post("/price", json={"amount": 2e7, "rating": 5, "relationship_id": "R002",
                                          "model": {"capital_basis": "regulatory"}}).json()
    assert priced["at_recommended"]["capital_basis"] == "regulatory"


def test_model_reference_endpoints():
    f = client.get("/models/ecap-factors").json()
    assert f["table"]["5"]["7"] > f["table"]["5"]["1"]
    p = client.get("/models/pit-factors", params={"cycle_shift": -1}).json()
    energy = next(r for r in p if r["industry"] == "Energy")
    assert energy["pd_pit_rating_5"] > energy["pd_ttc_rating_5"]


def test_curves_endpoint():
    c = client.get("/curves").json()
    ten = {p["tenor_yrs"]: p for p in c["points"]}
    assert ten[1.0]["ftp"] == pytest.approx(ten[1.0]["sofr"] + ten[1.0]["liquidity_premium"], abs=1e-6)
    assert c["floating_index"] == "1M Term SOFR"
