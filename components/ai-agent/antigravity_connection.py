"""Resolve the local Antigravity hub CLI connection without persisting credentials."""
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
import tempfile
from urllib.parse import unquote, urlparse


def connection_environment():
    env = dict(os.environ)
    if env.get('ANTIGRAVITY_LS_ADDRESS'):
        return env
    # Optional per-PC integration configuration, never bundled in the OS image.
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'devos/antigravity-api.json'
    if config.is_file():
        settings = json.loads(config.read_text())
        for key in ('ANTIGRAVITY_LS_ADDRESS', 'ANTIGRAVITY_CSRF_TOKEN'):
            if settings.get(key):
                env[key] = str(settings[key])
        if env.get('ANTIGRAVITY_LS_ADDRESS'):
            return env
    # The desktop hub supplies its local CSRF token to its own language-server child.
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            args = (process/'cmdline').read_bytes().decode(errors='replace').split('\0')
            if not args or Path(args[0]).name != 'language_server' or '--standalone' not in args:
                continue
            def option(name):
                if name in args and args.index(name)+1 < len(args):
                    return args[args.index(name)+1]
                return next((a.split('=',1)[1] for a in args if a.startswith(name+'=')), '')
            if option('--app_data_dir') != 'antigravity':
                continue
            token = option('--csrf_token')
            log = Path.home()/'.config/Antigravity/logs/language_server.log'
            matches = re.findall(r'listening on random port at (\d+) for HTTP(?:\s|$)', log.read_text()[:32768])
            port = matches[-1] if matches else ''
            if token and port.isdigit() and 0 < int(port) < 65536:
                env['ANTIGRAVITY_LS_ADDRESS'] = f'127.0.0.1:{port}'
                env['ANTIGRAVITY_CSRF_TOKEN'] = token
                return env
        except (OSError, ValueError):
            continue
    return None


def ensure_connection(project, emit, timeout=20):
    env = connection_environment()
    if env:
        return env
    launcher = Path('/opt/antigravity/antigravity')
    if not launcher.is_file():
        raise RuntimeError('Antigravity hub/API is unavailable. Open the hub or configure the local API connection; an IDE window alone is not an API connection.')
    emit('Opening Antigravity hub; waiting for its local API connection…')
    subprocess.Popen([str(launcher)], cwd=project, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        env = connection_environment()
        if env:
            return env
        time.sleep(.5)
    raise RuntimeError('Antigravity opened but its local API connection is unavailable (ANTIGRAVITY_LS_ADDRESS). Sign in/open the hub, then retry this step. No prompt was submitted.')


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
