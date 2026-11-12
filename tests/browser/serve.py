"""Serve the real wizard with a synthetic Bluetooth fan at /preview.

Run: python tests/browser/serve.py, then open http://localhost:18765/preview.
The test adapter is never included in the published web/ directory.
"""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/coway_local/provisioning/return":
            content = b'<!doctype html><html lang="en"><title>Home Assistant return preview</title><h1>Returned to Home Assistant automatically</h1><p>Simulated return received after Bluetooth reported success. No Submit step.</p><a href="/preview">Run preview again</a></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return
        if path in ("/preview", "/mock-bluetooth.mjs"):
            if path == "/preview":
                content = (ROOT / "web/index.html").read_text().replace(
                    '<script type="module" src="./app.mjs',
                    '<script type="module" src="./mock-bluetooth.mjs"></script>\n'
                    '<script type="module" src="./app.mjs',
                ).encode()
                kind = "text/html"
            else:
                content = (ROOT / "tests/browser/mock-bluetooth.mjs").read_bytes()
                kind = "text/javascript"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return
        super().do_GET()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 18765), partial(Handler, directory=ROOT / "web"))
    print("Wizard preview: http://localhost:18765/preview", flush=True)
    server.serve_forever()
