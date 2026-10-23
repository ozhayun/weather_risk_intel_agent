from streamlit.testing.v1 import AppTest


def test_ui_shows_setup_hint_when_api_is_down(monkeypatch):
    monkeypatch.setenv("API_URL", "http://127.0.0.1:9")  # nothing listens here
    at = AppTest.from_file("../ui/app.py", default_timeout=15).run()
    assert not at.exception
    assert any("uvicorn" in e.value for e in at.error)
