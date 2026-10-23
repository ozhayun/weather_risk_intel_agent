import pytest
from fastapi.testclient import TestClient

from app.agent.pipeline import Agent
from app.agent.schemas import Answer, QueryPlan
from app.api.main import build_app
from tests.fakes import FakeLLM

RANK = QueryPlan.model_validate({"action": {"tool": "rank_hubs", "hazard": "winter"}})


def client_with(responses) -> TestClient:
    llm = FakeLLM(list(responses))
    return TestClient(build_app(agent_factory=lambda ctx: Agent(llm, ctx)))


@pytest.fixture
def client():
    with client_with([RANK, Answer(text="ok"), RANK, Answer(text="ok")]) as c:
        yield c


def test_health_ok(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["llm_ready"] is True
    assert body["dataset"]["window_end"] == "2025-12-31"
    assert body["scoring_version"]


def test_hubs_returns_15_sorted_by_rank(client):
    hubs = client.get("/hubs").json()
    assert len(hubs) == 15
    assert [h["overall_rank"] for h in hubs] == list(range(1, 16))


def test_hub_detail_and_alias(client):
    assert client.get("/hubs/dallas").json()["hub_id"] == "dallas"
    assert client.get("/hubs/St. Louis").json()["hub_id"] == "st_louis"


def test_hub_detail_404(client):
    assert client.get("/hubs/tokyo").status_code == 404


def test_rankings_midwest_winter_has_6_rows(client):
    body = client.get("/rankings", params={"hazard": "winter", "region": "midwest"}).json()
    assert len(body["rows"]) == 6
    assert body["rows"][0]["hub_id"] == "minneapolis"


def test_rankings_bad_hazard_422(client):
    assert client.get("/rankings", params={"hazard": "earthquake"}).status_code == 422


def test_chat_assigns_session_and_returns_answer(client):
    body = client.post("/chat", json={"message": "winter ranking?"}).json()
    assert body["session_id"] and body["answer"]["text"] == "ok"
    assert body["plan"]["action"]["tool"] == "rank_hubs"
    assert body["result"]["kind"] == "rank"


def test_chat_reuses_session(client):
    first = client.post("/chat", json={"message": "a"}).json()["session_id"]
    second = client.post("/chat", json={"message": "b", "session_id": first}).json()
    assert second["session_id"] == first


@pytest.mark.parametrize("message", ["", "x" * 1001])
def test_chat_rejects_bad_message_422(client, message):
    assert client.post("/chat", json={"message": message}).status_code == 422


def test_chat_503_when_llm_unavailable():
    def broken(ctx):
        raise RuntimeError("Missing credentials")

    with TestClient(build_app(agent_factory=broken)) as c:
        response = c.post("/chat", json={"message": "hi"})
        assert response.status_code == 503
        assert "OPENAI_API_KEY" in response.json()["detail"]
        assert c.get("/hubs").status_code == 200
        assert c.get("/health").json()["llm_ready"] is False


@pytest.mark.parametrize("top_n", [0, -1])
def test_rankings_rejects_non_positive_top_n(client, top_n):
    assert client.get("/rankings", params={"top_n": top_n}).status_code == 422
