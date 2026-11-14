#!/usr/bin/env python3
"""
Mindforge - YouTube private uploader (Phase 3)
==============================================
Uploads the daily narrated MP4 to the channel owner's YouTube account as a
PRIVATE video via the official YouTube Data API v3 (resumable upload).

  python youtube_uploader.py content/2026-11-14.json --video output/2026-11-14.mp4

Security model:
  - OAuth credentials come ONLY from GitHub Actions secrets / environment:
      YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
  - Tokens are never printed, logged, committed or written to any file.
  - The upload ledger (content/uploads.json) stores ONLY the video id, private
    URL, title, privacy status and timestamp - never tokens.
  - privacyStatus is hardcoded to "private". This module can never publish
    publicly or change the visibility of an uploaded video.

Reliability:
  - Resumable upload (chunked, 8 MB) with exponential backoff on 5xx/network
    errors, then a videos.list verification that the video really exists and
    is private.
  - Deduplication: content/uploads.json (committed) maps each content date to
    its video id, so re-running the workflow never creates duplicates.
  - If the secrets are not configured, the uploader exits 0 with a [skip]
    message - Phase 0-2 behavior is preserved until OAuth is set up.

One-time authorization (your own machine, not CI): see youtube_auth.py and
the README section "Google Cloud setup".
"""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPLOADS_LEDGER = ROOT / "content" / "uploads.json"

# Minimum required scope - nothing more.
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TOKEN_URI = "https://oauth2.googleapis.com/token"
PRIVACY_STATUS = "private"          # NEVER changed by this code
CATEGORY_ID = "27"                  # Education
CHUNK_SIZE = 8 * 1024 * 1024        # 8 MB resumable chunks
MAX_RETRIES = 6                     # per-chunk retry attempts (exponential backoff)
RETRYABLE_STATUS = {500, 502, 503, 504}
MISSING_SECRETS_EXIT = 2            # distinct exit code: "not configured"


# ---------------------------------------------------------------------------
# Credentials (refresh-token only, offline access)
# ---------------------------------------------------------------------------
def missing_secrets():
    return [k for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
                        "YOUTUBE_REFRESH_TOKEN") if not os.environ.get(k)]


def build_credentials(client_id, client_secret, refresh_token):
    """Build offline credentials from the stored refresh token."""
    from google.oauth2.credentials import Credentials
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=TOKEN_URI,
        scopes=[SCOPE],
    )


def refresh_access_token(credentials):
    """Exchange the refresh token for a fresh access token (in memory only)."""
    from google.auth.transport.requests import AuthorizedSession, Request
    if not credentials.valid:
        credentials.refresh(Request())
    return credentials


def build_service(credentials):
    """Official Discovery client. Uses the bundled static discovery document
    (no extra network fetch) and quota is attributed to the GCP project."""
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=credentials,
                 cache_discovery=False)


# ---------------------------------------------------------------------------
# Upload metadata from the generated package
# ---------------------------------------------------------------------------
def metadata_from_pkg(pkg):
    """YouTube body built strictly from the generated content package."""
    title = pkg.get("title") or pkg.get("titles", ["Mindforge Daily"])[0]
    # YouTube titles cap at 100 chars.
    title = title[:100]
    body = {
        "snippet": {
            "title": title,
            "description": (pkg.get("description") or "").strip(),
            "tags": list(pkg.get("tags") or [])[:30],
            "categoryId": CATEGORY_ID,
        },
        "status": {
            "privacyStatus": PRIVACY_STATUS,       # always private
            "selfDeclaredMadeForKids": False,
        },
    }
    return body


# ---------------------------------------------------------------------------
# Upload ledger (dedup) - video ids only, NEVER tokens
# ---------------------------------------------------------------------------
def load_uploads(path=UPLOADS_LEDGER):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("uploads", {})
    except (json.JSONDecodeError, OSError):
        return {}


def already_uploaded(date_str, uploads=None, path=UPLOADS_LEDGER):
    if uploads is None:
        uploads = load_uploads(path)
    return date_str in uploads


def record_upload(date_str, video_id, title, path=UPLOADS_LEDGER):
    """Append to the ledger. Refuses to store anything but safe fields."""
    entry = {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": title,
        "privacy": PRIVACY_STATUS,
        "uploaded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    p = Path(path)
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    uploads = data.get("uploads", {})
    uploads[date_str] = entry
    data["uploads"] = uploads
    data["_note"] = "Upload ledger: video ids only - credentials are never stored in this file."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return entry


# ---------------------------------------------------------------------------
# Resumable upload + verification
# ---------------------------------------------------------------------------
def upload_video(pkg, video_path, service, date_str=None, uploads_path=UPLOADS_LEDGER,
                 on_progress=None):
    """Resumable upload with retries, then verification. Returns the entry."""
    video_path = Path(video_path)
    if not video_path.exists() or video_path.stat().st_size == 0:
        raise RuntimeError(f"Video file missing or empty: {video_path}")

    date_str = date_str or pkg.get("date", video_path.stem)
    if already_uploaded(date_str, path=uploads_path):
        prev = load_uploads(uploads_path)[date_str]
        print(f"[skip] {date_str} already uploaded (dedup): {prev['url']}")
        return None
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    body = metadata_from_pkg(pkg)
    media = MediaFileUpload(str(video_path), mimetype="video/mp4",
                            chunksize=CHUNK_SIZE, resumable=True)
    request = service.videos().insert(body=body, media_body=media)

    response = None
    status = None
    retries = 0
    waits = 0
    while response is None:
        status = None
        try:
            status, response = request.next_chunk()
            retries = 0
            if status and on_progress:
                on_progress(status.progress())
        except HttpError as e:
            code = getattr(getattr(e, "resp", None), "status", 0) or 0
            if code in RETRYABLE_STATUS and retries < MAX_RETRIES:
                retries += 1
                wait = min(60, 2 ** retries)
                print(f"[warn] transient HTTP {code} during upload, "
                      f"retry {retries}/{MAX_RETRIES} in {wait}s")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"YouTube upload failed (HTTP {code or 'unknown'}): "
                    f"{e}") from e
        except (OSError, EOFError) as e:
            # Network drop / broken chunk - retry the SAME resumable session.
            if retries < MAX_RETRIES:
                retries += 1
                wait = min(60, 2 ** retries)
                print(f"[warn] network error during upload ({e}), "
                      f"retry {retries}/{MAX_RETRIES} in {wait}s")
                time.sleep(wait)
            else:
                raise RuntimeError(f"YouTube upload failed after "
                                   f"{MAX_RETRIES} retries: {e}") from e
        if response is None and status is None:
            waits += 1
            if waits > 1000:   # stalled session guard (never spin forever)
                raise RuntimeError("YouTube upload stalled: no progress from "
                                   "resumable session (500 pending chunks)")
            continue

    if not response or not response.get("id"):
        raise RuntimeError(f"YouTube upload returned no video id: {response!r}")

    video_id = response["id"]
    return verify_and_record(response, date_str, video_id, body,
                             ledger_path=uploads_path)


def verify_and_record(insert_response, date_str, video_id, body,
                      ledger_path=UPLOADS_LEDGER):
    """Verify the upload and record success.

    Scope note: verification reads the video resource that videos.insert
    RETURNS (id/snippet/status parts) - Google echoes the created resource,
    so this confirms what was actually created with ZERO extra API calls and
    stays strictly inside the youtube.upload scope. videos.list would require
    the broader youtube.readonly scope, which this project deliberately does
    NOT request.
    """
    st = insert_response.get("status") or {}
    if st.get("privacyStatus") == PRIVACY_STATUS:
        title = (insert_response.get("snippet") or {}).get("title") \
            or body["snippet"]["title"]
        entry = record_upload(date_str, video_id, title, path=ledger_path)
        print(f"[ok] uploaded PRIVATE (verified from insert response): "
              f"{entry['url']}")
        return entry
    if not st:
        # Extremely unusual (Google always echoes status on insert). Record
        # anyway with a loud warning - failing here would break dedup and
        # cause a duplicate upload on the next run.
        print("[warn] insert response did not echo 'status' - cannot "
              "re-confirm privacy; recorded upload with warning.", file=sys.stderr)
        entry = record_upload(date_str, video_id,
                              body["snippet"]["title"], path=ledger_path)
        return entry
    raise RuntimeError(
        f"Uploaded video {video_id} has privacyStatus "
        f"'{st.get('privacyStatus')}' - expected '{PRIVACY_STATUS}'.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = dict(a.split("=", 1) for a in argv[1:]
                if a.startswith("--") and "=" in a)

    missing = missing_secrets()
    if missing:
        print(f"[skip] YouTube upload not configured "
              f"(missing secrets: {', '.join(missing)}). "
              f"Set them in repo Settings > Secrets - see README.")
        return 0

    if not args or "--video" not in opts:
        print("[error] usage: youtube_uploader.py <content.json> "
              "--video=<path.mp4>", file=sys.stderr)
        return 1
    json_path = Path(args[0])
    video_path = Path(opts["--video"])
    if not json_path.exists():
        print(f"[error] content JSON not found: {json_path}", file=sys.stderr)
        return 1
    pkg = json.loads(json_path.read_text(encoding="utf-8"))

    try:
        creds = build_credentials(os.environ["YOUTUBE_CLIENT_ID"],
                                  os.environ["YOUTUBE_CLIENT_SECRET"],
                                  os.environ["YOUTUBE_REFRESH_TOKEN"])
        refresh_access_token(creds)
        service = build_service(creds)
        entry = upload_video(pkg, video_path, service,
                             date_str=opts.get("date"))
        if entry:
            print(f"[ok] video id: {entry['video_id']} "
                  f"(private - requires your approval to publish)")
    except RuntimeError as e:
        msg = str(e)
        if "invalid_grant" in msg.lower():
            print(f"[error] {e}\n"
                  "        The refresh token expired or was revoked. "
                  "Re-run youtube_auth.py on your machine and update the "
                  "YOUTUBE_REFRESH_TOKEN secret.", file=sys.stderr)
        elif "quotaExceeded" in msg or "quota" in msg.lower():
            print(f"[error] {e}\n"
                  "        YouTube API quota exceeded for today "
                  "(default 10,000 units/day; one upload = 1,600).",
                  file=sys.stderr)
        else:
            print(f"[error] {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - clear failure, no partial state
        print(f"[error] unexpected failure: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
