#!/usr/bin/env python3
"""
Mindforge - one-time YouTube OAuth bootstrap (run LOCALLY, not in CI!)
======================================================================
Authorizes YOUR channel once and prints a refresh token for the
YOUTUBE_REFRESH_TOKEN GitHub secret. After that, GitHub Actions can refresh
access tokens unattended forever.

Usage (on your own computer, with a normal browser):
  pip install google-auth-oauthlib google-auth
  set YOUTUBE_CLIENT_ID=...xxx.apps.googleusercontent.com
  set YOUTUBE_CLIENT_SECRET=...
  python youtube_auth.py

  (or: python youtube_auth.py --client-secret client_secret.json
       using the JSON file downloaded from Google Cloud Console - keep that
       file local, it is gitignored)

A browser window opens -> sign in with the YouTube channel's Google account
-> Google may show "unverified app" warning -> click Advanced > Go to app.
The refresh token is printed ONCE to this terminal.

  NEVER paste the token into chat, files, commits or screenshots - only into
  GitHub: Settings > Secrets and variables > Actions > New repository secret
  Name: YOUTUBE_REFRESH_TOKEN

The token is NOT saved to disk by this script. Tokens never touch the repo.
"""

import json
import os
import sys

SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def main(argv):
    opts = {}
    for a in argv[1:]:
        if a.startswith("--") and "=" in a:
            key, value = a.split("=", 1)
            opts[key.lstrip("-")] = value.strip('"')

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    secret_file = opts.get("client-secret")

    if secret_file:
        with open(secret_file, encoding="utf-8") as f:
            data = json.load(f)
        if "installed" in data:            # Desktop-app client secret file
            client_id = data["installed"]["client_id"]
            client_secret = data["installed"]["client_secret"]
        else:
            print("[error] expected a Desktop-app client secret JSON "
                  "('installed' section)", file=sys.stderr)
            return 1
    if not (client_id and client_secret):
        print("Usage: set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET "
              "environment variables (or pass --client-secret=FILE), "
              "then run: python youtube_auth.py", file=sys.stderr)
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        {"installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }}, scopes=[SCOPE])

    print("[auth] opening browser - sign in with the Google account that "
          "owns your YouTube channel...")
    creds = flow.run_local_server(
        port=0,
        access_type="offline",      # request a refresh token
        prompt="consent",           # force refresh-token issuance every time
    )

    if not creds.refresh_token:
        print("[error] no refresh token returned - rerun with prompt=consent "
              "(this script already does; make sure you completed consent)",
              file=sys.stderr)
        return 1

    print()
    print("=" * 64)
    print("Your YOUTUBE_REFRESH_TOKEN (copy it into GitHub Secrets):")
    print("=" * 64)
    print(creds.refresh_token)
    print("=" * 64)
    print("GitHub > Settings > Secrets and variables > Actions > "
          "New repository secret")
    print("  Name:  YOUTUBE_REFRESH_TOKEN")
    print("  Value: the token above")
    print()
    print("Also add:  YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET")
    print("Do NOT paste the token into chat, files or commits.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
