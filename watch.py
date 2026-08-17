#!/usr/bin/env python3
"""
Poll a set of Google Drive folders and dispatch a GitHub Actions workflow in a
target repo when their contents change.

Runs on a schedule in this repo (public → free Actions minutes). The target
repo's own scheduled sync can then run rarely (daily safety net) instead of
polling — scheduled jobs on private repos bill a 1-minute minimum per run even
when nothing changed.

Config (all via env — no identifying values live in this file):
  GCP_SA_KEY    service-account JSON with read access to the folders (secret)
  FOLDER_IDS    comma-separated Drive folder IDs to fingerprint (variable)
  DISPATCH_PAT  PAT with repo+workflow scope on the target repo (secret)
  TARGET_REPO   owner/name of the repo to dispatch (variable)
  WORKFLOW_FILE workflow file name in the target repo (variable)

State: state/fingerprint.txt, committed back to this repo by the workflow.
Fingerprint covers file id + content md5 + name per folder — the same signals
the downstream sync keys on, so a fingerprint change is exactly "a sync would
do work". Logs print counts only; this repo is public.
"""
import hashlib
import json
import os
import sys
import urllib.request

from google.oauth2 import service_account
from googleapiclient.discovery import build

STATE_PATH = os.path.join(os.path.dirname(__file__), "state", "fingerprint.txt")
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def drive_client():
    key_json = os.environ.get("GCP_SA_KEY")
    if not key_json:
        sys.exit("GCP_SA_KEY not set")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(key_json), scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def fingerprint(drive, folder_ids):
    entries = []
    total = 0
    for folder_id in folder_ids:
        query = (
            f"'{folder_id}' in parents and trashed=false "
            "and (mimeType='image/jpeg' or mimeType='image/png' or mimeType='image/webp')"
        )
        page_token = None
        while True:
            resp = drive.files().list(
                q=query,
                fields="nextPageToken, files(id,name,md5Checksum,modifiedTime)",
                pageSize=200,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                corpora="allDrives",
            ).execute()
            for f in resp.get("files", []):
                total += 1
                entries.append(
                    [folder_id, f["id"], f.get("md5Checksum") or f.get("modifiedTime"), f["name"]]
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    entries.sort()
    digest = hashlib.sha256(json.dumps(entries).encode()).hexdigest()
    return digest, total


def dispatch(target_repo, workflow_file, pat):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{target_repo}/actions/workflows/{workflow_file}/dispatches",
        data=json.dumps({"ref": "main"}).encode(),
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        if resp.status != 204:
            raise RuntimeError(f"dispatch returned HTTP {resp.status}")


def main():
    folder_ids = [x for x in os.environ.get("FOLDER_IDS", "").split(",") if x.strip()]
    if not folder_ids:
        sys.exit("FOLDER_IDS not set")
    target_repo = os.environ.get("TARGET_REPO") or sys.exit("TARGET_REPO not set")
    workflow_file = os.environ.get("WORKFLOW_FILE") or sys.exit("WORKFLOW_FILE not set")

    drive = drive_client()
    digest, total = fingerprint(drive, folder_ids)

    old = ""
    if os.path.exists(STATE_PATH):
        old = open(STATE_PATH).read().strip()

    if digest == old:
        print(f"no change ({total} files across {len(folder_ids)} folders)")
        return

    print(f"change detected ({total} files across {len(folder_ids)} folders) — dispatching sync")
    dispatch(target_repo, workflow_file, os.environ.get("DISPATCH_PAT"))
    # Only record the new fingerprint after a successful dispatch, so a failed
    # dispatch retries on the next tick instead of silently dropping the change.
    with open(STATE_PATH, "w") as fh:
        fh.write(digest + "\n")
    print("dispatched")


if __name__ == "__main__":
    main()
