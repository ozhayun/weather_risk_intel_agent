import pytest
from streamlit.testing.v1 import AppTest


def test_ui_shows_setup_hint_when_api_is_down(monkeypatch):
    monkeypatch.setenv("API_URL", "http://127.0.0.1:9")  # nothing listens here
    at = AppTest.from_file("../ui/app.py", default_timeout=15).run()
    assert not at.exception
    assert any("uvicorn" in e.value for e in at.error)


def test_ui_survives_non_json_server_error(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Broken(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Server Error")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Broken)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("API_URL", f"http://127.0.0.1:{server.server_port}")
    at = AppTest.from_file("../ui/app.py", default_timeout=15).run()
    server.shutdown()
    assert not at.exception
    assert any("Internal Server Error" in e.value for e in at.error)


@pytest.fixture
def live_api(monkeypatch):
    """Real FastAPI app with a fake LLM, served on a random local port."""
    import socket
    import threading
    import time

    import uvicorn

    from app.agent.pipeline import Agent
    from app.agent.schemas import Answer, QueryPlan
    from app.api.main import build_app
    from tests.fakes import FakeLLM

    plan = QueryPlan.model_validate({"action": {"tool": "rank_hubs", "hazard": "winter"}})
    answer = Answer(
        text="Minneapolis leads.", suggested_followups=["Why is Minneapolis's risk medium?"]
    )
    llm = FakeLLM([plan, answer] * 5)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = build_app(agent_factory=lambda ctx: Agent(llm, ctx))
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    monkeypatch.setenv("API_URL", f"http://127.0.0.1:{port}")
    yield llm
    server.should_exit = True


def test_sidebar_ranking_shows_all_15_hubs_without_scrolling(live_api):
    at = AppTest.from_file("../ui/app.py", default_timeout=15).run()
    table = at.sidebar.dataframe[0]
    assert len(table.value) == 15
    assert list(table.value.columns) == [
        "#",
        "hub",
        "region",
        "Overall Risk",
        "label",
        "Dominant Hazard",
    ]
    assert at.sidebar.header[0].value == "Hub Multi-Hazard risk ranking"


def test_example_question_runs_a_turn_and_reenables_input(live_api):
    at = AppTest.from_file("../ui/app.py", default_timeout=15).run()
    at.sidebar.button(key="ex-0").click().run()
    assert not at.exception
    assert [m["role"] for m in at.session_state.messages] == ["user", "assistant"]
    assert at.session_state.busy is False
    assert at.chat_input[0].proto.disabled is False


def test_followup_button_sends_followup(live_api):
    at = AppTest.from_file("../ui/app.py", default_timeout=15).run()
    at.chat_input[0].set_value("winter ranking").run()
    at.button(key="fu-1-0").click().run()
    assert at.session_state.messages[-2]["content"] == "Why is Minneapolis's risk medium?"
