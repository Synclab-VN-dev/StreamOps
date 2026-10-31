"""Hourly cleanup. Dry-run by default; no orphan/release/issue deletion."""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from gateway import (
    GitHub,
    REPO,
    TAG,
    Rejected,
    read_mapping,
    validate_release,
    verify_mapping,
)


def eligible(issue, now):
    if issue.get("state") != "closed" or not issue.get("closed_at"):
        return False
    try:
        return now > datetime.fromisoformat(
            issue["closed_at"].replace("Z", "+00:00")
        ) + timedelta(hours=24)
    except (ValueError, TypeError):
        return False


def cleanup(github, release_id, bot_id, now, dry_run=True):
    validate_release(github.release(release_id), release_id)
    audit = []
    # Enumerate issues with bot-owned mappings, not filename-derived ownership.
    for issue in github.issues():
        if "pull_request" in issue:
            continue
        for comment in github.comments(issue["number"]):
            m = read_mapping(comment, bot_id)
            if not m or m.get("releaseId") != release_id or m.get("releaseTag") != TAG:
                continue
            assets = github.assets(release_id)
            matches = [a for a in assets if a.get("id") == m.get("assetId")]
            if len(matches) != 1:
                continue
            a = matches[0]
            if (
                a.get("uploader", {}).get("id") != bot_id
                or not verify_mapping(m, issue, release_id, a)
                or not eligible(issue, now)
            ):
                continue
            # Refetch release, asset AND current mapping/state immediately before mutation.
            validate_release(github.release(release_id), release_id)
            fresh_assets = github.assets(release_id)
            fresh_comments = github.comments(issue["number"])
            fresh_issue = github.issue(issue["number"])
            fresh_maps = [read_mapping(c, bot_id) for c in fresh_comments]
            if m not in fresh_maps or any(
                x and x.get("reportId") == m["reportId"] and x != m for x in fresh_maps
            ):
                continue
            fresh = next((v for v in fresh_assets if v.get("id") == a["id"]), None)
            if (
                fresh != a
                or not eligible(fresh_issue, now)
                or fresh_issue.get("closed_at") != issue.get("closed_at")
                or not verify_mapping(m, fresh_issue, release_id, fresh)
            ):
                continue
            if not dry_run:
                try:
                    github.delete(a["id"])
                except Rejected as e:
                    if e.code != "GITHUB_404":
                        raise
            audit.append(
                {
                    "issueNumber": issue["number"],
                    "assetId": a["id"],
                    "action": "WOULD_DELETE" if dry_run else "DELETED",
                }
            )
    return audit


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    # Configuration must be explicitly provisioned. Never infer a release from a name search.
    gh = GitHub(lambda: os.environ["GITHUB_TOKEN"])
    try:
        result = cleanup(
            gh,
            int(os.environ["DIAGNOSTIC_RELEASE_ID"]),
            int(os.environ["DIAGNOSTIC_BOT_ID"]),
            datetime.now(timezone.utc),
            not a.execute,
        )
    except Exception:
        print(
            json.dumps({"status": "BLOCKED", "reason": "PREFLIGHT_OR_GITHUB_FAILURE"})
        )
        return 1
    print(json.dumps({"status": "OK", "audit": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
