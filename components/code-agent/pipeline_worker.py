"""Noninteractive coding-engine entry point for an explicitly started pipeline."""
import argparse
import json
import sys
from pathlib import Path

import code_agent as core


def run_task(prompt, project, emit=print, max_steps=35):
    agent = core.CodeAgent(
        core.Workspace(project), core.LocalLLM(), lambda action: False,
        core.ApprovalPolicy(auto_reads=True, auto_edits=True, auto_commands=True),
        max_steps=max_steps,
        on_event=lambda kind, value: emit(json.dumps({'event': kind, 'detail': value}, default=str))
        if kind in ('thinking_status', 'change_status', 'output', 'report') else None,
    )
    try:
        answer = agent.run(prompt)
        if agent._outcome == 'done' and agent.changed and not agent._commands_log:
            answer += "\n" + agent.run(
                "Validate the files you just changed. You MUST execute relevant tests or syntax checks "
                "with the run_command tool now, inspect their exit codes, and fix failures. "
                "Do not merely suggest commands for the user to run. Then summarize actual results."
            )
        # A saved multi-phase brief can initially return an acknowledgement only.
        # Do not silently run its later phases; those may be separate queue steps.
        state = core.brief.BriefState.load(agent.ws.root)
        pending = state is not None and not state.finished
        commands = dict(agent._commands_log)  # latest result of a retried command
        ok = (not agent.cancelled and agent._outcome == 'done' and not pending
              and all(code == 0 for code in commands.values())
              and bool(commands))
        result = {'status': 'completed' if ok else 'incomplete', 'summary': answer,
                  'outcome': agent._outcome, 'files': agent.changed,
                  'pending_phases': pending, 'commands': commands}
    except Exception as exc:
        result = {'status': 'failed', 'summary': str(exc)}
    emit(json.dumps({'result': result}))
    return 0 if result['status'] == 'completed' else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--max-steps', type=int, default=35)
    args = parser.parse_args()
    return run_task(sys.stdin.read(), args.project, max_steps=args.max_steps)


if __name__ == '__main__':
    raise SystemExit(main())
