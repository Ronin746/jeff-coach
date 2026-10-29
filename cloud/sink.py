"""Finto Discord per la prova in cloud: riceve i messaggi che Sydney e Remy manderebbero e li scrive su file.

Gira su 127.0.0.1:8765. Il workflow punta i webhook qui finché la variabile del repo CLOUD_ALERT_LIVE
non vale "true". Ogni messaggio diventa una riga JSON in cloud/sink_out.jsonl: {ora, bot, embeds}.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent / "sink_out.jsonl"
ROME = ZoneInfo("Europe/Rome")


class H(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw)
        except Exception:
            body = {"raw": raw[:2000].decode("utf-8", "replace")}
        bot = self.path.strip("/").split("?")[0] or "?"
        row = {"ora": datetime.now(ROME).strftime("%Y-%m-%d %H:%M:%S"), "bot": bot,
               "embeds": [{"title": e.get("title"), "description": e.get("description")}
                          for e in (body.get("embeds") or [])] or body}
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[finto discord] {bot}: {json.dumps(row['embeds'], ensure_ascii=False)[:500]}", flush=True)
        out = b'{"id": "0", "channel_id": "0"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    HTTPServer(("127.0.0.1", port), H).serve_forever()
