#!/usr/bin/env python3
"""Premium DevOS AI Pipeline layer — modes, blueprints, handoff, gates, watchdog, scorecard.

Designed to sit beside TaskPipeline without replacing the scheduler. Every feature is
opt-in via context flags so existing queues keep working.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MODES = {
    "balanced": {
        "label": "Balanced",
        "hint": "Reliable parallel run with handoff memory and stall alerts.",
        "parallel_limit": 4,
        "handoff": True,
        "quality_gate": False,
        "watchdog_minutes": 25,
        "auto_failover": False,
        "strict_completion": True,
    },
    "quality": {
        "label": "Quality",
        "hint": "Strict gates: handoff + verify scripts before the next step advances.",
        "parallel_limit": 2,
        "handoff": True,
        "quality_gate": True,
        "watchdog_minutes": 20,
        "auto_failover": False,
        "strict_completion": True,
    },
    "overnight": {
        "label": "Overnight",
        "hint": "Max throughput: auto-failover on quota, longer stall patience, more parallel.",
        "parallel_limit": 6,
        "handoff": True,
        "quality_gate": False,
        "watchdog_minutes": 45,
        "auto_failover": True,
        "strict_completion": True,
    },
    "speed": {
        "label": "Speed",
        "hint": "Fastest dispatch; lighter gates. Best when agents are healthy.",
        "parallel_limit": 8,
        "handoff": False,
        "quality_gate": False,
        "watchdog_minutes": 15,
        "auto_failover": True,
        "strict_completion": False,
    },
}

# Curated blueprints — structured multi-step recipes (no personal prompts).
BLUEPRINTS: Dict[str, Dict[str, Any]] = {
    "saas-laravel": {
        "title": "Premium SaaS (Laravel)",
        "summary": "Multi-tenant SaaS with auth, billing hooks, admin, API, tests, deploy.",
        "steps": [
            (
                "PHASE 1 — Foundation\n"
                "Scaffold a production Laravel app in {project_dir}. Configure .env.example, "
                "database, multi-tenancy (or team/org model), auth (register/login/verify), "
                "roles/permissions, and a clean domain layout (app/Domain). Write docs/ARCHITECTURE.md "
                "and docs/DECISIONS.md. Seed a demo tenant. Run migrations and feature tests for auth."
            ),
            (
                "PHASE 2 — Core product\n"
                "Build the primary business modules for this product with CRUD, policies, "
                "validation, API resources, and Vue/Blade UI. Every module must be feature-flaggable. "
                "Add factories, seeders, and Pest/PHPUnit coverage for the happy path + authz failures."
            ),
            (
                "PHASE 3 — Billing, admin, ops\n"
                "Add admin dashboard, audit log, notification center, health endpoint, queue workers, "
                "and a Stripe-ready billing stub (or local fake gateway). Document env vars and "
                "runbooks in docs/OPS.md. Ensure `php artisan test` is green."
            ),
            (
                "PHASE 4 — Ship\n"
                "Add Dockerfile, docker-compose, CI workflow, README with setup/demo credentials, "
                "and a one-command smoke script. Tag a v0.1.0-ready state. Commit with a clear message."
            ),
        ],
    },
    "api-service": {
        "title": "Premium API Service",
        "summary": "Versioned REST/JSON API with auth, OpenAPI, tests, and container deploy.",
        "steps": [
            (
                "PHASE 1 — API skeleton\n"
                "Create the service in {project_dir} with versioned routes (/api/v1), JWT or "
                "token auth, request validation, structured errors, OpenAPI/Swagger, and healthz. "
                "Document architecture and run `tests` for auth + health."
            ),
            (
                "PHASE 2 — Domain endpoints\n"
                "Implement the core resources with pagination, filtering, idempotency keys where "
                "relevant, and rate-limit headers. Full test coverage for success and 4xx paths."
            ),
            (
                "PHASE 3 — Production pack\n"
                "Dockerfile, compose, CI, README, migrate/seed scripts, and a smoke client script. "
                "All tests green; commit."
            ),
        ],
    },
    "landing-dashboard": {
        "title": "Landing + App Dashboard",
        "summary": "Marketing site + authenticated dashboard with settings and dark UI.",
        "steps": [
            (
                "PHASE 1 — Brand landing\n"
                "Build a polished landing page in {project_dir} (hero, features, pricing, FAQ, CTA) "
                "with responsive layout and accessible markup. No placeholder lorem."
            ),
            (
                "PHASE 2 — App shell\n"
                "Add auth and an authenticated dashboard with navigation, settings, and empty states. "
                "Persist user preferences. Cover critical flows with tests."
            ),
            (
                "PHASE 3 — Polish & ship\n"
                "Performance pass, SEO meta, Dockerfile/CI/README, and a short demo script. Commit."
            ),
        ],
    },
    "qa-hardening": {
        "title": "QA Hardening Pass",
        "summary": "Audit an existing project: tests, security, perf, docs, release checklist.",
        "steps": [
            (
                "PHASE 1 — Audit\n"
                "Inspect {project_dir}. Produce docs/AUDIT.md covering architecture risks, missing "
                "tests, security issues, and a prioritized fix list. Do not invent files that already exist."
            ),
            (
                "PHASE 2 — Fix & prove\n"
                "Implement the top fixes. Add/repair tests. Run the full suite. Update README and "
                "docs/RELEASE_CHECKLIST.md. Commit with a clear summary of risk reduced."
            ),
        ],
    },
}


def get_mode(context: Dict[str, Any]) -> str:
    mode = (context.get("premium_mode") or "balanced").lower().strip()
    return mode if mode in MODES else "balanced"


def mode_settings(context: Dict[str, Any]) -> Dict[str, Any]:
    return dict(MODES[get_mode(context)])


def set_mode(context: Dict[str, Any], mode: str) -> Dict[str, Any]:
    mode = (mode or "balanced").lower().strip()
    if mode not in MODES:
        raise ValueError(f"Unknown mode '{mode}'. Choose: {', '.join(MODES)}")
    context["premium_mode"] = mode
    context["premium_mode_set_at"] = datetime.datetime.now().isoformat()
    return mode_settings(context)


def list_blueprints() -> List[Dict[str, str]]:
    return [
        {"id": key, "title": meta["title"], "summary": meta["summary"], "steps": str(len(meta["steps"]))}
        for key, meta in BLUEPRINTS.items()
    ]


def expand_blueprint(blueprint_id: str, project_dir: str = "{project_dir}") -> List[str]:
    meta = BLUEPRINTS.get(blueprint_id)
    if not meta:
        raise ValueError(f"Unknown blueprint '{blueprint_id}'")
    return [step.replace("{project_dir}", project_dir) for step in meta["steps"]]


def previous_step_summary(queue: List[Dict[str, Any]], task: Dict[str, Any]) -> Optional[str]:
    """Find the latest completed sibling step in the same project for handoff memory."""
    project = str(Path(task.get("project") or "").expanduser())
    slug = task.get("project_slug")
    best = None
    for other in queue:
        if other.get("id") == task.get("id"):
            continue
        if other.get("status") != "COMPLETED":
            continue
        same = False
        if project and str(Path(other.get("project") or "").expanduser()) == project:
            same = True
        elif slug and other.get("project_slug") == slug:
            same = True
        if not same:
            continue
        finished = other.get("completed_at") or other.get("started_at") or other.get("created_at") or ""
        if best is None or finished >= (best.get("completed_at") or best.get("started_at") or ""):
            best = other
    if not best:
        return None
    summary = (best.get("completion_summary") or best.get("status_message") or best.get("output") or "").strip()
    summary = summary[:1800]
    if not summary:
        summary = f"Step {best.get('id')} completed successfully (no written summary)."
    return (
        f"\n\n================================================================================\n"
        f"[PIPELINE HANDOFF — previous step context]\n"
        f"Previous step id: {best.get('id')}\n"
        f"Agent: {best.get('agent')}\n"
        f"Summary / notes for continuity (do not redo finished work; build on it):\n"
        f"{summary}\n"
        f"================================================================================\n"
    )


def apply_handoff(queue: List[Dict[str, Any]], task: Dict[str, Any], resolved_prompt: str,
                  context: Dict[str, Any]) -> str:
    if not mode_settings(context).get("handoff"):
        return resolved_prompt
    if task.get("premium_handoff_applied"):
        return resolved_prompt
    brief = previous_step_summary(queue, task)
    if not brief:
        return resolved_prompt
    task["premium_handoff_applied"] = True
    return resolved_prompt + brief


def record_completion(context: Dict[str, Any], task: Dict[str, Any], success: bool) -> None:
    score = context.setdefault("scorecard", {
        "completed": 0, "failed": 0, "total_seconds": 0.0, "by_agent": {},
    })
    agent = (task.get("agent") or "unknown").lower()
    by = score.setdefault("by_agent", {}).setdefault(agent, {"completed": 0, "failed": 0})
    started = task.get("started_at")
    elapsed = 0.0
    if started:
        try:
            elapsed = max(0.0, (datetime.datetime.now() - datetime.datetime.fromisoformat(started)).total_seconds())
        except ValueError:
            elapsed = 0.0
    task["completed_at"] = datetime.datetime.now().isoformat()
    task["duration_seconds"] = round(elapsed, 1)
    score["total_seconds"] = float(score.get("total_seconds") or 0) + elapsed
    if success:
        score["completed"] = int(score.get("completed") or 0) + 1
        by["completed"] = int(by.get("completed") or 0) + 1
        # Prefer completion report summary when present
        report_path = task.get("completion_report")
        if report_path and Path(report_path).is_file():
            try:
                data = json.loads(Path(report_path).read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("summary"), str):
                    task["completion_summary"] = data["summary"][:2000]
            except (OSError, ValueError, TypeError):
                pass
        if not task.get("completion_summary"):
            task["completion_summary"] = (task.get("status_message") or "")[:2000]
    else:
        score["failed"] = int(score.get("failed") or 0) + 1
        by["failed"] = int(by.get("failed") or 0) + 1
    score["updated_at"] = datetime.datetime.now().isoformat()


def scorecard_view(context: Dict[str, Any], queue: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    score = dict(context.get("scorecard") or {})
    completed = int(score.get("completed") or 0)
    failed = int(score.get("failed") or 0)
    total = completed + failed
    avg = (float(score.get("total_seconds") or 0) / completed) if completed else 0.0
    live = {}
    if queue is not None:
        live = {
            "queued": sum(1 for t in queue if t.get("status") == "QUEUED"),
            "running": sum(1 for t in queue if t.get("status") == "RUNNING"),
            "submitted": sum(1 for t in queue if t.get("status") == "SUBMITTED"),
            "rate_limited": sum(1 for t in queue if t.get("status") == "RATE_LIMITED"),
        }
    return {
        "mode": get_mode(context),
        "mode_label": MODES[get_mode(context)]["label"],
        "completed": completed,
        "failed": failed,
        "success_rate": round((completed / total) * 100, 1) if total else 0.0,
        "avg_seconds": round(avg, 1),
        "by_agent": score.get("by_agent") or {},
        "live": live,
    }


def run_quality_gate(task: Dict[str, Any], context: Dict[str, Any]) -> Tuple[bool, str]:
    """Optional post-complete verification before the queue treats the step as done."""
    if not mode_settings(context).get("quality_gate"):
        return True, "quality gate off"
    project = Path(task.get("project") or "").expanduser()
    if not project.is_dir():
        return False, "quality gate: project directory missing"
    # Prefer project-local gate script when present
    script = project / ".devos" / "pipeline" / "quality-gate.sh"
    if script.is_file() and os.access(script, os.X_OK):
        try:
            proc = subprocess.run(
                [str(script)], cwd=str(project), capture_output=True, text=True, timeout=600
            )
            out = ((proc.stdout or "") + (proc.stderr or ""))[-4000:]
            if proc.returncode != 0:
                return False, f"quality-gate.sh failed ({proc.returncode}): {out[:500]}"
            return True, out[:500] or "quality-gate.sh passed"
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"quality-gate.sh error: {exc}"

    # Lightweight defaults: discover common test entrypoints
    checks: List[List[str]] = []
    if (project / "vendor/bin/pest").is_file():
        checks.append(["php", "vendor/bin/pest", "--parallel"])
    elif (project / "vendor/bin/phpunit").is_file():
        checks.append(["php", "vendor/bin/phpunit"])
    elif (project / "package.json").is_file():
        try:
            pkg = json.loads((project / "package.json").read_text(encoding="utf-8"))
            scripts = pkg.get("scripts") or {}
            if "test" in scripts:
                checks.append(["npm", "test", "--silent"])
        except (OSError, ValueError):
            pass
    elif (project / "pytest.ini").is_file() or (project / "pyproject.toml").is_file():
        checks.append(["pytest", "-q"])

    if not checks:
        return True, "quality gate: no standard test runner found (skipped)"

    logs = []
    for cmd in checks:
        try:
            proc = subprocess.run(cmd, cwd=str(project), capture_output=True, text=True, timeout=900)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"quality gate failed running {' '.join(cmd)}: {exc}"
        logs.append(f"$ {' '.join(cmd)}\n{(proc.stdout or '')[-1500:]}")
        if proc.returncode != 0:
            return False, f"quality gate failed ({' '.join(cmd)}): {(proc.stderr or proc.stdout or '')[:500]}"
    return True, "quality gate passed\n" + "\n".join(logs)[:1500]


def detect_stalls(queue: List[Dict[str, Any]], context: Dict[str, Any],
                  now: Optional[datetime.datetime] = None) -> List[Dict[str, Any]]:
    """Return RUNNING/SUBMITTED tasks with no progress beyond the mode's watchdog window."""
    settings = mode_settings(context)
    minutes = int(settings.get("watchdog_minutes") or 0)
    if minutes <= 0:
        return []
    now = now or datetime.datetime.now()
    stalled = []
    for task in queue:
        if task.get("status") not in ("RUNNING", "SUBMITTED"):
            continue
        marker = task.get("last_progress_at") or task.get("started_at") or task.get("created_at")
        if not marker:
            continue
        try:
            started = datetime.datetime.fromisoformat(marker)
        except ValueError:
            continue
        age_min = (now - started).total_seconds() / 60.0
        if age_min >= minutes:
            stalled.append({
                "id": task.get("id"),
                "agent": task.get("agent"),
                "status": task.get("status"),
                "project_slug": task.get("project_slug"),
                "idle_minutes": int(age_min),
                "watchdog_minutes": minutes,
            })
    return stalled


def mark_progress(task: Dict[str, Any]) -> None:
    task["last_progress_at"] = datetime.datetime.now().isoformat()


def overnight_failover_agent(task: Dict[str, Any], context: Dict[str, Any],
                             available: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """Pick a failover agent when Overnight/Speed mode hits quota."""
    if not mode_settings(context).get("auto_failover"):
        return None
    current = (task.get("agent") or "").lower()
    order = ["local", "cursor-agent", "codex", "antigravity-kde", "antigravity", "chatgpt"]
    for name in order:
        if name == current:
            continue
        if name in ("antigravity", "antigravity-kde") and current in ("antigravity", "antigravity-kde"):
            # Same Google quota family — skip sibling when cooling
            continue
        meta = available.get(name)
        if meta and meta.get("available"):
            return name
    return None


def export_recipe(queue: List[Dict[str, Any]], slug: str) -> Dict[str, Any]:
    steps = [t for t in queue if t.get("project_slug") == slug]
    return {
        "version": 1,
        "kind": "devos-pipeline-recipe",
        "project_title": (steps[0].get("project_title") if steps else slug),
        "project_slug": slug,
        "exported_at": datetime.datetime.now().isoformat(),
        "steps": [
            {"prompt": t.get("prompt"), "agent": t.get("agent"), "create_repo": bool(t.get("create_repo"))}
            for t in steps
        ],
    }


def import_recipe(recipe: Dict[str, Any]) -> Tuple[str, str, List[Tuple[str, str, bool]]]:
    if not isinstance(recipe, dict) or recipe.get("kind") != "devos-pipeline-recipe":
        raise ValueError("Not a DevOS pipeline recipe")
    title = str(recipe.get("project_title") or recipe.get("project_slug") or "Imported Project")
    slug = str(recipe.get("project_slug") or title)
    steps_out: List[Tuple[str, str, bool]] = []
    for step in recipe.get("steps") or []:
        if not isinstance(step, dict):
            continue
        prompt = (step.get("prompt") or "").strip()
        if not prompt:
            continue
        agent = (step.get("agent") or "antigravity").lower()
        steps_out.append((prompt, agent, bool(step.get("create_repo"))))
    if not steps_out:
        raise ValueError("Recipe has no steps")
    return title, slug, steps_out
