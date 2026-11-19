# Connect your YouTube channel (one time, ~5 min, free)
I can't do this for you: it needs your Google login.
1. Go to https://console.cloud.google.com/ -> create a project (any name).
2. APIs & Services > Library > enable **YouTube Data API v3**.
3. APIs & Services > OAuth consent screen: User type **External**, fill the app name + your email, add **yourself as a Test user**. (Leave in Testing.)
4. Credentials > Create credentials > **OAuth client ID** > Application type **Desktop app**. Download the JSON.
5. Save it as `youtube_client_secret.json` in the repo root (git-ignored; the token is saved next to it)
6. Run once and click Allow in the browser that opens (pick the channel's account):
   `.venv/bin/python scripts/youtube_upload.py --auth`
Notes
- API uploads from an unaudited ("Testing") project are forced to **private** by YouTube until the project passes Google's API audit. If your uploads show as private, either request the audit (form: "YouTube API Services - Audit and Quota Extension") or open them in Studio and set Public.
- Quota: ~6 uploads/day on the default 10,000 units.
- Never share youtube_client_secret.json / youtube_token.json.
