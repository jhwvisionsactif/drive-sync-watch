# drive-sync-watch

Polls a set of Google Drive folders every 10 minutes and dispatches a sync
workflow in a target repo when their contents actually change.

Why: scheduled Actions jobs in private repos bill a 1-minute minimum per run
even when there is nothing to do. This repo is public, where standard-runner
minutes are free — so the cheap polling lives here, and the private repo's
sync only runs when Drive really changed (plus a daily safety-net schedule).

All identifying configuration (folder IDs, target repo, credentials) lives in
Actions secrets/variables, not in code:

| Name | Kind | Purpose |
|------|------|---------|
| `GCP_SA_KEY` | secret | service-account JSON, read access to the folders |
| `DISPATCH_PAT` | secret | PAT (repo+workflow) able to dispatch the target workflow |
| `FOLDER_IDS` | variable | comma-separated Drive folder IDs |
| `TARGET_REPO` | variable | `owner/name` of the repo to dispatch |
| `WORKFLOW_FILE` | variable | workflow file name to dispatch |

`state/fingerprint.txt` is the last-seen fingerprint (sha256 over file id +
content md5 + name for every image in every watched folder), committed back by
the workflow after each successful dispatch.
