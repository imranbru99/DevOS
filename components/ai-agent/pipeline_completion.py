"""Per-attempt agent completion reports. Activity/idle time is never success."""
import json
from pathlib import Path
import uuid


def prepare(task):
    token = uuid.uuid4().hex
    task['completion_token'] = token
    # Use an attempt-specific basename so old reports cannot complete a retry.
    path = Path(task['project']) / '.devos/pipeline' / (token + '.json')
    task['completion_report'] = str(path)
    example = {'attempt': token, 'status': 'completed', 'summary': 'What was delivered',
               'checks': [{'name': 'Relevant test or validation', 'passed': True}]}
    return ("\n\nPIPELINE RESULT CONTRACT:\nAfter completing this step and running relevant checks, "
            f"write a JSON result to {path}. Create its parent directory if needed.\n"
            f"Schema: {json.dumps(example)}\n"
            "Report actual results: never claim checks passed without running them. "
            "Use status failed for errors or blocked when user input/authorization is needed. "
            "Do not report completed while work remains or checks fail. "
            "This result allows the next queued step to start. Do not execute later steps yourself.\n")


def read(task):
    token = task.get('completion_token')
    if not token or not isinstance(token, str) or len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        return None
    root = Path(task['project']).resolve()
    path = root / '.devos/pipeline' / (token + '.json')
    try:
        if not path.resolve().is_relative_to(root) or path.is_symlink() or path.stat().st_size > 65536:
            return None
        report = json.loads(path.read_text())
        if not isinstance(report, dict) or report.get('attempt') != token:
            return None
        status = report.get('status')
        if status not in ('completed', 'failed', 'blocked') or not isinstance(report.get('summary'), str):
            return None
        if status == 'completed':
            checks = report.get('checks')
            if not isinstance(checks, list) or not checks or not all(
                isinstance(c, dict) and isinstance(c.get('name'), str) and c['name'].strip()
                and c.get('passed') is True for c in checks
            ):
                return None
        return report
    except (OSError, ValueError, TypeError):
        return None
