#!/usr/bin/env python3
"""Tiny local file server (127.0.0.1 only) so a browser page can fetch big files that the Chrome file tool refuses (>10 MB).
  serve_files.py DIR [PORT]   -> http://127.0.0.1:8899/<file>   (CORS enabled; stop with Ctrl-C / kill)"""
import functools, os, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
d = os.path.abspath(sys.argv[1]); port = int(sys.argv[2]) if len(sys.argv) > 2 else 8899
class H(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Private-Network", "true"); self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()
    def do_OPTIONS(self): self.send_response(204); self.end_headers()
    def log_message(self, *a): pass
ThreadingHTTPServer(("127.0.0.1", port), functools.partial(H, directory=d)).serve_forever()
