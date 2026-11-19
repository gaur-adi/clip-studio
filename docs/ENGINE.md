# Clip Studio edit engine (v2)

Live moments are now **planned** instead of rendered as a fixed 40 s window. Nothing here uploads or publishes anything.

## Flow
`moment (peak−28 … peak+12 s)` → full word transcript (`<id>.words.json`) → **planner** (`app/planner.py`, gemma4:12b via your Ollama host) → **validation** (`app/editplan.py`) →
optional **vision payoff check** (`app/visual_check.py`) → **duplicate claim** (`app/dedupe.py`, SQLite) → review (or auto-approve if enabled) → `scripts/make_short.py` render → **quality gate** (`app/qa.py`) → `final/` if ready, else `review/`.

| Module | Job |
|---|---|
| `config.py` | defaults + optional root `config.json` overrides (never overwritten except by the Settings API, whitelisted keys only) |
| `editplan.py` | pure functions: segment validation/repair, speech-safe snapping, filler trim + finish-sentence polish, caption remap, scores, gate, `tighten` |
| `planner.py` | prompt, model call, up to 3 attempts (the validation error is fed back to the model), heuristic unscored fallback |
| `visual_check.py` | 3×3 frame contact sheet → vision model: is the payoff visible, does the edit open on a menu. Can only add doubt, never raise a score |
| `dedupe.py` | atomic interval claims per source (`data/clip_registry.sqlite3`) |
| `qa.py` | ffprobe/blackdetect/silencedetect/volumedetect, caption bounds, layout/face overlap, duplicate |
| `metadata.py` | language, verified topic/creator, tags, title/description without invented claims |
| `pipeline_v2.py` | orchestration, metadata schema v2 (all old keys kept), `final/` vs `review/` |
| `analytics.py` | import YouTube Studio CSV exports, join to edit records |

## Rules the engine enforces
- Hook, clarity and payoff are gated **independently**; energy never compensates (`editorial_quality = min(mean(h,c,p), min(h,c,p)+2)`). Default 7/7/7, review margin 2 — **experimental starting values, not validated predictors**.
- Evidence quotes (opening and payoff) must be found in the transcript near the stated time, otherwise the plan goes to review.
- A payoff later than 14 s into the edit triggers one corrective retry, then an explicit, flagged auto-tighten (stays in review).
- Cuts never land inside a word; captions are remapped through the **same** segment map the renderer uses.
- No transcript, model down or invalid answers → `needs_review` with no scores (never silently approved, never a neutral default score).
- Game/topic is verified only from your setting or the stream title. Hashtags and description follow it; no "launch week", "permission" or commentary claims.
- Framing presets: `context` (full frame over blur), `gameplay` (large crop), `gameplay_facecam` (gameplay + reaction panel). Legacy names `blur/center/auto/stack` still work. Safe areas keep text clear of the phone UI; the banner shows only for the first 2.8 s.

## New endpoints (local only)
`GET /api/settings`, `POST /api/settings` (thresholds, edit limits, auto_approve, default framing), `POST /api/plan/update` (new start/end, speech-safe snapped), `POST /api/approve` (preset), `POST /api/reject`, `GET /api/analytics/report`.
Approving is your explicit decision; the quality gate still decides `final/` vs `review/`. The manual Render button and the old VOD analysis path are unchanged (min length now from config, 8 s).

## Analytics
Export a content table from YouTube Studio as CSV, then
```bash
.venv/bin/python app/analytics.py import studio_export.csv --label 48h
.venv/bin/python app/analytics.py report
```
Compares average view duration with the edited length, time-to-payoff, scores and framing per clip. Reading the YouTube Analytics API directly would need a separate read-only authorisation from you and is not included.

## Tests
```bash
cd tests && ../.venv/bin/python -m unittest discover -p "test_*.py"
```
Covers plan parsing and malformed answers, speech-safe boundaries, multi-segment caption remap, planner retry/fallback, duplicate intervals (including a concurrent race), language/topic propagation, metadata claims, settings validation and the analytics importer. Real renders are checked separately (see the upgrade report); passing tests alone do not establish that a clip is good.

## Licences
Ideas studied from four public repos (one AGPL, three MIT) were re-implemented here; no code was copied.
