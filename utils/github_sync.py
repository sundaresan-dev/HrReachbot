"""
HRReach Bot - GitHub Sync Module
Auto-pushes database.json and resume.pdf to GitHub after changes,
so data persists across Render/Railway redeploys.
Uses [skip render] in commit messages to prevent redeploy loops.
"""

import os
import json
import base64
import logging
import threading
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

GITHUB_REPO = "sundaresan-dev/HrReachbot"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents"


def _get_token():
    """Get GitHub token from environment."""
    return os.getenv("GITHUB_TOKEN", "")


def _get_file_sha(filepath: str, token: str) -> str | None:
    """Get the current SHA of a file in the repo (needed for updates)."""
    try:
        req = urllib.request.Request(
            f"{GITHUB_API}/{filepath}?ref=main",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("sha")
    except Exception:
        return None


def _push_file(filepath: str, local_path: str, commit_msg: str):
    """Push a local file to GitHub repo via API."""
    token = _get_token()
    if not token:
        logger.debug("GITHUB_TOKEN not set — skipping sync")
        return

    try:
        # Read the local file
        with open(local_path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode()

        # Get current SHA (required for updating existing files)
        sha = _get_file_sha(filepath, token)

        # Build the API payload
        payload = {
            "message": f"{commit_msg} [skip render]",
            "content": content_b64,
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{GITHUB_API}/{filepath}",
            data=data,
            method="PUT",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            short_sha = result["commit"]["sha"][:8]
            logger.info(f"📤 Synced {filepath} → GitHub ({short_sha})")

    except Exception as e:
        logger.warning(f"GitHub sync failed for {filepath}: {e}")


def sync_database():
    """Push database.json to GitHub in a background thread."""
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database.json")
    thread = threading.Thread(
        target=_push_file,
        args=("database.json", db_path, "data: update database"),
        daemon=True,
    )
    thread.start()


def sync_resume():
    """Push resume.pdf to GitHub in a background thread."""
    resume_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resume.pdf")
    thread = threading.Thread(
        target=_push_file,
        args=("resume.pdf", resume_path, "data: update resume"),
        daemon=True,
    )
    thread.start()
