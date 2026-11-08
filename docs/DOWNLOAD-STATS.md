# Counting DevOS downloads & installs (GitHub)

DevOS does **not** send personal data. Counting uses **GitHub Release
`download_count`** only.

## How it works

1. Publish the ISO (and update bundle) as files on a
   [GitHub Release](https://github.com/imranbru99/DevOS/releases).
2. Every download of that file increments GitHub’s `download_count`.
3. After a Calamares install, `devos-install-ping` downloads a tiny
   `devos-install.ping` asset **once** (deferred until the PC is online).
   That asset’s `download_count` ≈ number of installs.
4. `tools/download-stats.py` reads the API and writes `stats/downloads.json`.
5. Refresh the snapshot locally when needed:
   `python3 tools/download-stats.py --write` (appends `stats/downloads-history.jsonl`).

| Counts | Does not count |
|--------|----------------|
| ISO / image / `devos-update.tar.gz` downloads from Releases | USB copies shared without a new download |
| `devos-install.ping` (one anonymous GET per install) | Machine-id, hostname, or user identity |
| Cumulative per asset (via API) | |

### One-time: publish the install-ping asset

```sh
bash tools/publish-install-ping.sh
```

This creates the `install-ping` release tag with `stats/devos-install.ping`.
The installer queues the ping even offline; `devos-install-ping.service`
retries quietly every 5 minutes until the network works, then disables itself.

## Commands

```sh
# Live summary from GitHub
python3 tools/download-stats.py

# Refresh files under stats/
python3 tools/download-stats.py --write

# Machine-readable
python3 tools/download-stats.py --json
```

Optional: set `GITHUB_TOKEN` or `GH_TOKEN` for a higher API rate limit.
`DEVOS_GITHUB_REPO=owner/name` overrides the default `imranbru99/DevOS`.

## Publishing an ISO so it is counted

CI builds may upload an ISO as a workflow **artifact** (temporary). Artifacts
are **not** counted. Attach the ISO to a release:

```sh
TAG=v26.04.1
gh release create "$TAG" --generate-notes \
  out/devos-26.04-amd64.iso \
  out/devos-26.04-amd64.iso.sha256
```

Or add the ISO to an existing tag:

```sh
gh release upload "$TAG" out/devos-26.04-amd64.iso out/devos-26.04-amd64.iso.sha256
```

The update-bundle workflow already uploads `devos-update.tar.gz*` on `v*` tags;
those downloads are counted as “update bundle” in the summary.

## Reading the numbers

- Latest snapshot: [`stats/downloads.json`](../stats/downloads.json)
- History (one JSON object per day): [`stats/downloads-history.jsonl`](../stats/downloads-history.jsonl)
- Manual Action run: **Actions → Download stats → Run workflow**
