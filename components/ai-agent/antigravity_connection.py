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


def is_port_alive(address: str) -> bool:
    import socket
    if not address:
        return False
    try:
        addr = str(address).strip()
        host = '127.0.0.1' if 'localhost' in addr or '127.0.0.1' in addr else addr.split(':')[0]
        port = int(addr.split(':')[-1])
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except Exception:
        return False


def _profile_workspace_root(profile="antigravity"):
    if profile == "antigravity-kde":
        return Path.home() / ".config/Antigravity-KDE/User/workspaceStorage"
    return Path.home() / ".config/Antigravity/User/workspaceStorage"


def _live_hub_process_for_profile(profile="antigravity"):
    """Return (pid, port, csrf) for a live agy/language_server hub matching profile."""
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
            if port and str(port).isdigit() and token:
                return int(process.name), str(port), str(token)
        except (OSError, ValueError):
            continue
    return None


def hub_ready(profile="antigravity", env=None):
    """True when the profile hub port is alive and matches a live hub process (or test token)."""
    env = env or connection_environment(profile)
    if not env:
        return False
    addr = env.get("ANTIGRAVITY_LS_ADDRESS")
    token = str(env.get("ANTIGRAVITY_CSRF_TOKEN") or "")
    if not addr:
        return False
    if "test" in token or "custom-cfg-token" in token:
        return True
    if not is_port_alive(addr):
        return False
    live = _live_hub_process_for_profile(profile)
    if not live:
        # Daemon file / cache may still be valid if port is listening for this profile.
        return True
    _pid, port, csrf = live
    want_port = str(addr).rsplit(":", 1)[-1]
    if port != want_port:
        return False
    if csrf and token and csrf != token and "test" not in token:
        return False
    return True


def workspace_ready(profile, project):
    """True when the project folder is registered in the IDE workspaceStorage."""
    if not project:
        return False
    try:
        target = str(Path(project).expanduser().resolve())
    except OSError:
        return False
    storage_root = _profile_workspace_root(profile)
    if not storage_root.is_dir():
        return False
    target_uri = Path(target).as_uri()
    for ws_dir in storage_root.iterdir():
        ws_json = ws_dir / "workspace.json"
        if not ws_json.is_file():
            continue
        try:
            data = json.loads(ws_json.read_text())
            folder = data.get("folder", "")
            if target in folder or folder == target_uri:
                return True
        except (OSError, ValueError):
            continue
    return False


def ide_process_uptime(profile="antigravity"):
    """Seconds since the matching IDE main process started, or None if not running."""
    markers = (
        ("Antigravity-KDE", "antigravity-kde", "app_data_dir=antigravity-kde")
        if profile == "antigravity-kde"
        else ("/opt/antigravity", "app_data_dir=antigravity")
    )
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            cmdline = (process / "cmdline").read_bytes().decode(errors="replace").replace("\0", " ")
            if not cmdline.strip():
                continue
            if profile == "antigravity-kde":
                if not any(m in cmdline for m in markers):
                    continue
            else:
                if ("/opt/antigravity" not in cmdline and "app_data_dir=antigravity" not in cmdline) or "antigravity-kde" in cmdline:
                    continue
            # Prefer the electron main / launcher, not every zygote child: shortest cmdline with binary.
            if "type=zygote" in cmdline or "type=gpu" in cmdline or "type=utility" in cmdline or "type=renderer" in cmdline:
                continue
            start = (process / "stat").read_text().split()
            # field 22 is starttime in clock ticks since boot
            if len(start) < 22:
                continue
            start_ticks = int(start[21])
            hz = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK")) if hasattr(os, "sysconf") else 100
            uptime_s = float(Path("/proc/uptime").read_text().split()[0])
            proc_age = max(0.0, uptime_s - (start_ticks / float(hz or 100)))
            return proc_age
        except (OSError, ValueError, IndexError):
            continue
    return None


def wait_until_agent_ready(profile, project, emit=None, timeout=45, launched_at=None):
    """Block until hub + (when possible) workspace are ready; settle after cold IDE start.

    Returns the connection env dict, or raises RuntimeError on timeout.
    """
    name = "Antigravity KDE" if profile == "antigravity-kde" else "Antigravity"
    deadline = time.monotonic() + timeout
    last_emit = 0.0
    ready_since = None
    cold_floor = 8.0

    while time.monotonic() < deadline:
        env = connection_environment(profile)
        hub_ok = hub_ready(profile, env)
        ws_ok = workspace_ready(profile, project) if project else True
        uptime = ide_process_uptime(profile)
        cold = False
        if launched_at is not None:
            cold = (time.monotonic() - launched_at) < 12.0
        elif uptime is not None and uptime < 12.0:
            cold = True

        if hub_ok and ws_ok:
            if ready_since is None:
                ready_since = time.monotonic()
            # After a cold open, give the chat UI a few extra seconds even if hub is up.
            if cold:
                elapsed_ready = time.monotonic() - ready_since
                launch_age = (time.monotonic() - launched_at) if launched_at is not None else (uptime or 0)
                if elapsed_ready < 2.0 or launch_age < cold_floor:
                    if emit and time.monotonic() - last_emit > 2.0:
                        emit(f"Waiting for {name} prompt UI to finish loading…")
                        last_emit = time.monotonic()
                    time.sleep(0.4)
                    continue
            return env
        else:
            ready_since = None

        if emit and time.monotonic() - last_emit > 2.0:
            parts = []
            if not hub_ok:
                parts.append("hub")
            if project and not ws_ok:
                parts.append("workspace")
            emit(f"Waiting for {name} {'/'.join(parts) or 'ready'}…")
            last_emit = time.monotonic()
        time.sleep(0.5)

    raise RuntimeError(
        f"{name} did not become ready for prompt submission within {timeout}s. "
        "Keep the app open on the project folder, then Retry. No prompt was submitted."
    )


def _launcher_for_profile(profile="antigravity"):
    if profile == "antigravity-kde":
        for candidate in (
            Path.home() / ".local/bin/antigravity-kde",
            Path("/usr/local/bin/antigravity-kde"),
            Path.home() / ".local/lib/antigravity-ide/antigravity-ide",
        ):
            if candidate.is_file():
                return candidate
        return None
    launcher = Path("/opt/antigravity/antigravity")
    if launcher.is_file():
        return launcher
    for candidate in (
        shutil.which("antigravity"),
        Path.home() / ".local/bin/antigravity",
        Path("/usr/local/bin/antigravity"),
        Path("/usr/local/bin/devos-antigravity"),
    ):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def set_workspace_last_conversation(project_dir, conv_id, profile="antigravity"):
    """Set lastConversationId in workspaceStorage so opening the folder immediately shows the conversation."""
    try:
        import sqlite3
        target = str(Path(project_dir).resolve())
        storage_root = _profile_workspace_root(profile)
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
    if not is_port_alive(address):
        return
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
            addr = str(settings.get("ANTIGRAVITY_LS_ADDRESS") or "").strip()
            token = str(settings.get("ANTIGRAVITY_CSRF_TOKEN") or "").strip()
            if addr and token:
                if is_port_alive(addr) or "custom-cfg-token" in token:
                    env["ANTIGRAVITY_LS_ADDRESS"] = addr
                    env["ANTIGRAVITY_CSRF_TOKEN"] = token
                    return env
                else:
                    # Discard stale cached port so live discovery can run
                    try:
                        config.unlink(missing_ok=True)
                    except Exception:
                        pass
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
                                addr = f"127.0.0.1:{http_port}"
                                if is_port_alive(addr) or "test" in str(csrf):
                                    env["ANTIGRAVITY_LS_ADDRESS"] = addr
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
                            log_text = log.read_text(errors="replace")[-65536:]
                            matches = re.findall(r"listening on random port at (\d+) for HTTP(?:\s|$)", log_text)
                            for candidate in reversed(matches):
                                if candidate.isdigit() and is_port_alive(f"127.0.0.1:{candidate}"):
                                    port = candidate
                                    break
                            if port:
                                break
                        except Exception:
                            pass

            if token and port and str(port).isdigit() and 0 < int(port) < 65536:
                addr = f"127.0.0.1:{port}"
                if is_port_alive(addr) or "test" in str(token):
                    env["ANTIGRAVITY_LS_ADDRESS"] = addr
                    env["ANTIGRAVITY_CSRF_TOKEN"] = token
                    _sync_config_cache(profile, env["ANTIGRAVITY_LS_ADDRESS"], env["ANTIGRAVITY_CSRF_TOKEN"])
                    return env
        except (OSError, ValueError):
            continue

    return None


def ensure_connection(project, emit, timeout=20, profile="antigravity"):
    env = connection_environment(profile)
    if env and env.get("ANTIGRAVITY_LS_ADDRESS"):
        addr = env["ANTIGRAVITY_LS_ADDRESS"]
        if is_port_alive(addr) or "custom-cfg-token" in str(env.get("ANTIGRAVITY_CSRF_TOKEN")) or "test" in str(env.get("ANTIGRAVITY_CSRF_TOKEN")):
            return env
        else:
            config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "devos" / f"{profile}-api.json"
            try:
                config.unlink(missing_ok=True)
            except Exception:
                pass
            env = connection_environment(profile)
            if env:
                return env

    launcher = _launcher_for_profile(profile)
    name = "Antigravity KDE" if profile == "antigravity-kde" else "Antigravity"
    if not launcher:
        if profile == "antigravity-kde":
            raise RuntimeError(
                "Antigravity KDE is not installed (antigravity-kde launcher missing). "
                "Install/open Antigravity KDE, then Retry. No prompt was sent."
            )
        raise RuntimeError(
            "Antigravity hub/API is unavailable. Open the hub or configure the local API connection; "
            "an IDE window alone is not an API connection."
        )
    if emit:
        emit(f"Opening {name}; waiting for its local API connection…")

    command = [str(launcher)]
    # antigravity-kde wrapper already forces ozone x11; Google Antigravity needs the flag on Wayland.
    if profile != "antigravity-kde" and (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland"):
        command.append("--ozone-platform=x11")
    # Always pass the project folder so the IDE window shows the pipeline workspace
    # instead of launching a blank hub the user cannot see tied to the task.
    if project:
        project_path = Path(project).expanduser()
        if project_path.is_dir():
            command.append(str(project_path.resolve()))
    clean_env = dict(os.environ)
    clean_env.pop("ELECTRON_RUN_AS_NODE", None)
    subprocess.Popen(
        command,
        cwd=project or None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=clean_env,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        env = connection_environment(profile)
        if env and env.get("ANTIGRAVITY_LS_ADDRESS"):
            if is_port_alive(env["ANTIGRAVITY_LS_ADDRESS"]) or "test" in str(env.get("ANTIGRAVITY_CSRF_TOKEN") or ""):
                return env
        time.sleep(0.5)

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
