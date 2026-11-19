#!/usr/bin/env python3
"""Upload a Short to YOUR YouTube channel via the official YouTube Data API (free quota; ~100 units/day-limit: an upload costs 1600 units of the 10,000 daily).
One-time setup: docs/YOUTUBE_SETUP.md. Then:
  youtube_upload.py --auth                       (opens a browser once: you click Allow)
  youtube_upload.py FILE --title T --description D [--tags a,b] [--privacy public|unlisted|private]
Prints the Shorts URL on success."""
import argparse, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YT_DIR = os.environ.get("YT_DIR", ROOT)
SECRET = os.path.join(YT_DIR, "youtube_client_secret.json"); TOKEN = os.path.join(YT_DIR, "youtube_token.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def creds(interactive=False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    c = Credentials.from_authorized_user_file(TOKEN, SCOPES) if os.path.exists(TOKEN) else None
    if c and c.expired and c.refresh_token: c.refresh(Request())
    if not c or not c.valid:
        if not interactive: raise SystemExit("YouTube not connected: run  scripts/youtube_upload.py --auth  (see docs/YOUTUBE_SETUP.md)")
        from google_auth_oauthlib.flow import InstalledAppFlow
        c = InstalledAppFlow.from_client_secrets_file(SECRET, SCOPES).run_local_server(port=0)
    open(TOKEN, "w").write(c.to_json()); os.chmod(TOKEN, 0o600)
    return c

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("file", nargs="?"); ap.add_argument("--auth", action="store_true"); ap.add_argument("--meta", help="final/<name>.json written by the app: uploads its video with its title/description/tags")
    ap.add_argument("--title"); ap.add_argument("--description", default=""); ap.add_argument("--tags", default="")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    a = ap.parse_args()
    if a.auth:
        if not os.path.exists(SECRET): sys.exit(f"missing {SECRET} - see docs/YOUTUBE_SETUP.md")
        creds(True); print("connected"); sys.exit(0)
    meta = None
    if a.meta:
        import json
        meta = json.load(open(a.meta)); a.file = os.path.join(os.path.dirname(os.path.abspath(a.meta)), meta["video_file"])
        a.title = meta["title"]; a.description = meta["description"]; a.tags = ",".join(meta.get("tags", []))
        if "--privacy" not in sys.argv: a.privacy = meta.get("privacy_suggested", "public")
    if not a.file or not a.title: sys.exit("need FILE and --title (or --meta final/x.json)")
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    yt = build("youtube", "v3", credentials=creds())
    body = {"snippet": {"title": a.title[:100], "description": a.description[:4900], "tags": [t for t in a.tags.split(",") if t][:15], "categoryId": "20"},
            "status": {"privacyStatus": a.privacy, "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(a.file, mimetype="video/mp4", resumable=True))
    resp = None
    while resp is None: _, resp = req.next_chunk()
    url = "https://www.youtube.com/shorts/" + resp["id"]
    if meta:
        import time; meta.update(status="uploaded", youtube_url=url, uploaded=time.strftime("%Y-%m-%d %H:%M:%S"), privacy_used=a.privacy); json.dump(meta, open(a.meta, "w"), indent=2, ensure_ascii=False)
    print(url)
