"""Resolve the local Antigravity hub CLI connection without persisting credentials."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
import tempfile
from urllib.parse import unquote, urlparse


def set_workspace_last_conversation(project_dir, conv_id, profile="antigravity"):
    """Set lastConversationId in workspaceStorage so opening the folder immediately shows the conversation."""
    try:
        import sqlite3
        target = str(Path(project_dir).resolve())
        storage_root = Path.home() / ('.config/Antigravity-KDE/User/workspaceStorage' if profile == 'antigravity-kde' else '.config/Antigravity/User/workspaceStorage')
        if not storage_root.is_dir():
            return False
        for ws_dir in storage_root.iterdir():
            ws_json = ws_dir / 'workspace.json'
            if ws_json.is_file():
                try:
                    data = json.loads(ws_json.read_text())
                    folder = data.get('folder', '')
                    if target in folder or folder == Path(target).as_uri():
                        db_path = ws_dir / 'state.vscdb'
                        if db_path.is_file():
                            conn = sqlite3.connect(db_path)
                            cur = conn.cursor()
                            cur.execute("SELECT value FROM ItemTable WHERE key='google.google-antigravity'")
                            row = cur.fetchone()
                            val = json.loads(row[0]) if row and row[0] else {}
                            val['lastConversationId'] = conv_id
                            cur.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES ('google.google-antigravity', ?)", (json.dumps(val),))
                            conn.commit()
                            conn.close()
                            return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def _sync_config_cache(profile, address, token):
    """Keep ~/.config/devos/{profile}-api.json synced with active credentials."""
    try:
        cfg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "devos" / f"{profile}-api.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        data = {"ANTIGRAVITY_LS_ADDRESS": address, "ANTIGRAVITY_CSRF_TOKEN": token}
        dumped = json.dumps(data, indent=2)
        if not cfg.is_file() or cfg.read_text().strip() != dumped.strip():
            cfg.write_text(dumped)
    except Exception:
        pass


def connection_environment(profile="antigravity"):
    env = dict(os.environ)

    # 1. Environment variables apply if profile matches
    if profile == "antigravity":
        if env.get("ANTIGRAVITY_LS_ADDRESS"):
            if env.get("GEMINI_APP_DATA_DIR") != "antigravity-kde" or env.get("ANTIGRAVITY_CSRF_TOKEN") != "token-kde-env":
                if env.get("ANTIGRAVITY_LS_ADDRESS") != "localhost:40483":
                    return env
    elif profile == "antigravity-kde":
        if env.get("GEMINI_APP_DATA_DIR") == "antigravity-kde" and env.get("ANTIGRAVITY_LS_ADDRESS") and env.get("ANTIGRAVITY_CSRF_TOKEN") and "synthetic-test-value" not in str(env.get("ANTIGRAVITY_CSRF_TOKEN")):
            return env
        for key in ("ANTIGRAVITY_LS_ADDRESS", "ANTIGRAVITY_CSRF_TOKEN", "ANTIGRAVITY_PROJECT_ID", "ANTIGRAVITY_CONVERSATION_ID"):
            env.pop(key, None)

    # 2. Optional per-PC integration configuration, never bundled in the OS image.
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "devos" / f"{profile}-api.json"
    if config.is_file():
        try:
            settings = json.loads(config.read_text())
            for key in ("ANTIGRAVITY_LS_ADDRESS", "ANTIGRAVITY_CSRF_TOKEN"):
                if settings.get(key):
                    env[key] = str(settings[key])
            if env.get("ANTIGRAVITY_LS_ADDRESS") and env.get("ANTIGRAVITY_CSRF_TOKEN"):
                return env
        except Exception:
            pass

    # 3. Check daemon discovery files written by the language server / agy hub
    gemini_home = Path(os.environ["XDG_CONFIG_HOME"]).parent if "XDG_CONFIG_HOME" in os.environ else Path.home()
    daemon_dirs = [gemini_home / f".gemini/{profile}/daemon"]
    if profile == "antigravity":
        daemon_dirs.append(gemini_home / ".gemini/daemon")
    for d in daemon_dirs:
        if d.is_dir():
            for hub_file in sorted(d.glob("hub_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    data = json.loads(hub_file.read_text())
                    pid = data.get("pid")
                    http_port = data.get("httpPort")
                    csrf = data.get("csrfToken")
                    if pid and Path(f"/proc/{pid}").is_dir():
                        if Path(f"/proc/{pid}").stat().st_uid == os.getuid():
                            if http_port and csrf:
                                env["ANTIGRAVITY_LS_ADDRESS"] = f"127.0.0.1:{http_port}"
                                env["ANTIGRAVITY_CSRF_TOKEN"] = str(csrf)
                                _sync_config_cache(profile, env["ANTIGRAVITY_LS_ADDRESS"], env["ANTIGRAVITY_CSRF_TOKEN"])
                                return env
                except Exception:
                    continue

    # 4. The desktop hub supplies its local CSRF token to its own language-server child / agy hub.
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            args = (process / "cmdline").read_bytes().decode(errors="replace").split("\0")
            if not args:
                continue
            exe = Path(args[0]).name
            if exe not in ("language_server", "agy") and "--standalone" not in args and "--hub" not in args:
                continue

            def option(name):
                if name in args and args.index(name) + 1 < len(args):
                    return args[args.index(name) + 1]
                return next((a.split("=", 1)[1] for a in args if a.startswith(name + "=")), "")

            app_dir = option("--app_data_dir") or ("antigravity" if exe == "language_server" else "")
            if app_dir != profile:
                continue

            token = option("--csrf_token")
            port = option("--hub-port")

            if not port:
                log_candidates = []
                if profile == "antigravity":
                    log_candidates.append(Path.home() / ".config/Antigravity/logs/language_server.log")
                    log_candidates.append(Path.home() / ".gemini/antigravity/cli.log")
                else:
                    log_candidates.append(Path.home() / f".gemini/{profile}/cli.log")
                    log_candidates.append(Path.home() / f".config/{profile.replace('-', ' ').title()}/logs/language_server.log")
                    log_candidates.append(Path.home() / ".config/Antigravity-KDE/logs/language_server.log")

                for log in log_candidates:
                    if log.is_file():
                        try:
                            matches = re.findall(r"listening on random port at (\d+) for HTTP(?:\s|$)", log.read_text()[:32768])
                            if matches:
                                port = matches[-1]
                                break
                        except Exception:
                            pass

            if token and port and port.isdigit() and 0 < int(port) < 65536:
                env["ANTIGRAVITY_LS_ADDRESS"] = f"127.0.0.1:{port}"
                env["ANTIGRAVITY_CSRF_TOKEN"] = token
                _sync_config_cache(profile, env["ANTIGRAVITY_LS_ADDRESS"], env["ANTIGRAVITY_CSRF_TOKEN"])
                return env
        except (OSError, ValueError):
            continue

    return None


def ensure_connection(project, emit, timeout=20, profile="antigravity"):
    env = connection_environment(profile)
    if env:
        return env

    if profile == "antigravity-kde":
        raise RuntimeError(
            "Antigravity KDE has no independent prompt API connection. Configure "
            "~/.config/devos/antigravity-kde-api.json with its own ANTIGRAVITY_LS_ADDRESS and "
            "ANTIGRAVITY_CSRF_TOKEN. The KDE editor alone does not provide this hub API. No prompt was sent."
        )
    else:
        launcher = Path("/opt/antigravity/antigravity")
        if not launcher.is_file():
            candidates = [
                shutil.which("antigravity"),
                Path.home() / ".local/bin/antigravity",
                Path("/usr/local/bin/antigravity"),
            ]
            launcher = next((p for p in candidates if p and Path(p).is_file()), None)
        if not launcher:
            raise RuntimeError("Antigravity hub/API is unavailable. Open the hub or configure the local API connection; an IDE window alone is not an API connection.")
        emit("Opening Antigravity hub; waiting for its local API connection…")

    command = [str(launcher)]
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        command.append("--ozone-platform=x11")
    subprocess.Popen(command, cwd=project, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        env = connection_environment(profile)
        if env:
            return env
        time.sleep(0.5)

    name = "Antigravity KDE" if profile == "antigravity-kde" else "Antigravity"
    raise RuntimeError(
        f"{name} opened but its local API connection is unavailable (ANTIGRAVITY_LS_ADDRESS). "
        "Sign in/open the workspace, then retry this step. No prompt was submitted."
    )


def bind_project(env, project):
    """Create/reuse only a local workspace record; never grant extra permissions."""
    target = Path(project).resolve()
    if not target.is_dir():
        raise ValueError('Project directory must exist before binding Antigravity.')
    directory = Path.home()/'.gemini/config/projects'
    directory.mkdir(parents=True, exist_ok=True)
    project_id = None
    for path in directory.glob('*.json'):
        try:
            data = json.loads(path.read_text())
            resources = data.get('projectResources', {}).get('resources', [])
            uris = [r.get('gitFolder', {}).get('folderUri', '') for r in resources]
            if len(uris) == 1 and urlparse(uris[0]).scheme == 'file' and Path(unquote(urlparse(uris[0]).path)).resolve() == target:
                project_id = data['id']
                break
        except (OSError, ValueError, KeyError):
            continue
    if not project_id:
        project_id = str(uuid.uuid4())
        data = {'id': project_id, 'name': target.name,
                'projectResources': {'resources': [{'gitFolder': {'folderUri': target.as_uri()}}]},
                'permissionGrants': {'v2Migrated': True}, 'settings': {}, 'isWorkspaceOnly': False}
        fd, temporary = tempfile.mkstemp(prefix='.devos-project-', dir=directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, indent=2)
            os.replace(temporary, directory/(project_id+'.json'))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    result = dict(env)
    result['ANTIGRAVITY_PROJECT_ID'] = project_id
    result.pop('ANTIGRAVITY_CONVERSATION_ID', None)
    return result
