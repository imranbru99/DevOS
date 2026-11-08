#!/usr/bin/env python3
"""Count DevOS downloads from GitHub Release assets (no install telemetry).

GitHub tracks each release file's download_count. This tool reads that API and
writes a snapshot under stats/ so we can see totals and growth over time.

  python3 tools/download-stats.py              # print summary
  python3 tools/download-stats.py --write      # update stats/downloads.json + history
  python3 tools/download-stats.py --json       # print JSON to stdout

Requires network. Optional GITHUB_TOKEN / GH_TOKEN raises the API rate limit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = os.environ.get("DEVOS_GITHUB_REPO", "imranbru99/DevOS")
ROOT = Path(__file__).resolve().parents[1]
STATS_DIR = ROOT / "stats"
LATEST_PATH = STATS_DIR / "downloads.json"
HISTORY_PATH = STATS_DIR / "downloads-history.jsonl"

# Assets that represent "someone got DevOS" (ISO / image / update bundle).
# Anchored at end so checksums like *.iso.sha256 are not counted.
COUNT_NAME = re.compile(
    r"(?i)("
    r"\.iso$"
    r"|\.img(\.xz|\.gz|\.zst)?$"
    r"|devos-update\.tar\.gz$"
    r"|devos-install\.ping$"
    r")$"
)
# Prefer ISO counts as the headline "downloads"; update bundles are secondary.
ISO_NAME = re.compile(r"(?i)\.iso$")
INSTALL_PING_NAME = re.compile(r"(?i)devos-install\.ping$")


def _headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "DevOS-download-stats",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_releases(repo: str = REPO) -> List[Dict[str, Any]]:
    """All non-draft releases (paginated)."""
    out: List[Dict[str, Any]] = []
    page = 1
    while page <= 20:
        url = f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}"
        batch = _get_json(url)
        if not isinstance(batch, list) or not batch:
            break
        for rel in batch:
            if rel.get("draft"):
                continue
            out.append(rel)
        if len(batch) < 100:
            break
        page += 1
    return out


def summarize(releases: List[Dict[str, Any]], repo: str = REPO) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assets_out: List[Dict[str, Any]] = []
    by_tag: Dict[str, Dict[str, Any]] = {}
    total = 0
    iso_total = 0
    update_total = 0
    install_total = 0

    for rel in releases:
        tag = str(rel.get("tag_name") or "")
        tag_total = 0
        tag_iso = 0
        tag_installs = 0
        for asset in rel.get("assets") or []:
            name = str(asset.get("name") or "")
            count = int(asset.get("download_count") or 0)
            if not COUNT_NAME.search(name):
                continue
            entry = {
                "tag": tag,
                "name": name,
                "download_count": count,
                "size": int(asset.get("size") or 0),
                "content_type": asset.get("content_type"),
                "updated_at": asset.get("updated_at"),
                "browser_download_url": asset.get("browser_download_url"),
            }
            assets_out.append(entry)
            tag_total += count
            total += count
            if INSTALL_PING_NAME.search(name):
                install_total += count
                tag_installs += count
            elif ISO_NAME.search(name):
                iso_total += count
                tag_iso += count
            elif name.lower().startswith("devos-update"):
                update_total += count
        if tag_total:
            by_tag[tag] = {
                "tag": tag,
                "published_at": rel.get("published_at"),
                "downloads": tag_total,
                "iso_downloads": tag_iso,
                "installs": tag_installs,
                "prerelease": bool(rel.get("prerelease")),
            }

    tags = sorted(by_tag.values(), key=lambda t: t.get("published_at") or "", reverse=True)
    return {
        "repo": repo,
        "fetched_at": now,
        "note": (
            "GitHub Release asset download_count. This is downloads of published "
            "files (ISO / update bundle), not a phone-home install counter. "
            "DevOS does not send telemetry from installed PCs."
        ),
        "totals": {
            "all_counted_assets": total,
            "iso": iso_total,
            "update_bundle": update_total,
            "installs": install_total,
        },
        "releases": tags,
        "assets": sorted(assets_out, key=lambda a: (-a["download_count"], a["tag"], a["name"])),
    }


def write_snapshot(summary: Dict[str, Any]) -> None:
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LATEST_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, LATEST_PATH)

    # One compact history line per run (for charts / deltas).
    line = {
        "fetched_at": summary["fetched_at"],
        "totals": summary["totals"],
        "by_tag": {r["tag"]: r["downloads"] for r in summary.get("releases") or []},
    }
    with open(HISTORY_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def print_human(summary: Dict[str, Any]) -> None:
    totals = summary.get("totals") or {}
    print(f"DevOS downloads · {summary.get('repo')}")
    print(f"Fetched: {summary.get('fetched_at')}")
    print()
    print(f"  Installs (from ISO):     {totals.get('installs', 0)}")
    print(f"  ISO downloads:           {totals.get('iso', 0)}")
    print(f"  Update bundle downloads: {totals.get('update_bundle', 0)}")
    print(f"  All counted assets:      {totals.get('all_counted_assets', 0)}")
    print()
    releases = summary.get("releases") or []
    if not releases:
        print("  No counted release assets yet.")
        print("  Publish the ISO and run: bash tools/publish-install-ping.sh")
        return
    print("  By release:")
    for rel in releases[:20]:
        pre = " (pre)" if rel.get("prerelease") else ""
        print(
            f"    {rel['tag']:<16}  "
            f"installs={rel.get('installs', 0):<5}  "
            f"iso={rel.get('iso_downloads', 0):<6}  "
            f"all={rel.get('downloads', 0)}{pre}"
        )
    assets = summary.get("assets") or []
    if assets:
        print()
        print("  Top assets:")
        for asset in assets[:12]:
            print(f"    {asset['download_count']:>7}  {asset['tag']}  {asset['name']}")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="DevOS GitHub Release download counts")
    p.add_argument("--repo", default=REPO, help="owner/name (default: imranbru99/DevOS)")
    p.add_argument("--write", action="store_true", help="write stats/downloads.json + history")
    p.add_argument("--json", action="store_true", help="print full JSON")
    args = p.parse_args(argv)

    try:
        releases = fetch_releases(args.repo)
    except urllib.error.HTTPError as exc:
        print(f"GitHub API error: {exc.code} {exc.reason}", file=sys.stderr)
        body = exc.read().decode("utf-8", errors="replace")[:400]
        if body:
            print(body, file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"Failed to fetch releases: {exc}", file=sys.stderr)
        return 1

    summary = summarize(releases, args.repo)
    if args.write:
        write_snapshot(summary)
        print(f"Wrote {LATEST_PATH.relative_to(ROOT)}", file=sys.stderr)
        print(f"Appended {HISTORY_PATH.relative_to(ROOT)}", file=sys.stderr)
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print_human(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
