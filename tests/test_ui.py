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
