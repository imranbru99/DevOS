# AI workflow verification

## Premium pipeline (DevOS)

The scheduler now includes an opt-in **premium layer** (`pipeline_premium.py`):

| Mode | Behavior |
| --- | --- |
| **Balanced** | Handoff memory between steps, stall watchdog (~25m), parallel 4 |
| **Quality** | Same + **quality gate** (project `quality-gate.sh` or Pest/PHPUnit/npm/pytest) before the next step |
| **Overnight** | Higher parallel, longer stall patience, **auto-failover** to another agent on quota |
| **Speed** | Max parallel, lighter gates |

**Blueprints** (one-click multi-phase projects): `saas-laravel`, `api-service`, `landing-dashboard`, `qa-hardening`.

**Handoff memory** appends the previous step’s completion summary into the next prompt so agents do not redo finished work.

**Scorecard** tracks success rate, average step duration, and per-agent stats (GUI KPIs + `devos-ai-pipeline scorecard`).

**Recipes**: `export-recipe` / `import-recipe` share a project’s step list as JSON.

CLI: `mode`, `scorecard`, `blueprints`, `blueprint <id>`, `export-recipe`, `import-recipe`.

---

The pipeline executes queued commands in order. A delayed, busy, rate-limited,
failed or unverified submitted task blocks dependent commands. Provider calls run
on a GUI worker thread. Pausing stops subsequent tasks; it does not cancel an
already running external command. Queue files use atomic, flushed replacement
and a shared advisory lock, so concurrent add/run operations cannot overwrite
one another. Each saved provider response is limited to its last 64 KiB.

Codex automation requires an installed, signed-in Codex CLI. Success requires a
successful CLI exit; an absent CLI is an error. The pipeline does not type into
arbitrary desktop windows or treat an idle desktop as proof of task success.
Antigravity's `new-conversation` acknowledges submission, not completion. Each
new attempt includes a unique local result-file contract. The agent must write a
matching completed report with named successful checks before the queue advances.
This is an agent-reported result, not an independent correctness guarantee. Failed
reports block dependent work; blocked reports await input. Missing or malformed
reports never count as success. Older conversations without this contract still
require inspection and **Confirm completed**. Transcript activity is only progress.

Local AI tasks invoke the actual coding engine in the selected directory, with
project edits and commands enabled by starting the pipeline. Its subprocess streams
progress and returns failure for errors, step limits, unfinished brief phases,
failed commands, or a run with no file/command work. A plain chat response cannot
complete a coding task. The coding backend reports unavailable models as errors.
If system Python was upgraded, the server can use an installed isolated runtime at
`~/.local/share/devos/ai-runtime` or `/opt/devos/ai-runtime`.

Other CLI providers require their installed, authenticated command-line tools;
editor-only launchers cannot submit work. CLI success still needs project-specific
validation. `pipeline_gui.py --run` explicitly starts/resumes the queue; a normal
launch only observes existing conversations until **Run Pipeline** is selected.


GitHub creation requires authenticated GitHub CLI. Opening a browser form is
not reported as successful creation. Repository creation/push must succeed for a
repository-creating pipeline task to be complete. New Git commits check both
effective author and committer identities before committing.

Tests use mocks and temporary queue files. They do not send prompts to real
accounts, publish repositories or consume provider credits.

Antigravity hub startup resolves its local HTTP API connection and binds each
conversation to the queued project directory before submitting the first prompt.
The directory is created from the normalized project slug first. The IDE-only
launcher cannot submit prompts and reports an actionable error instead of success.
Conversation IDs are persisted, and transcript activity is displayed without
automatically answering agent questions or treating inactivity as completion.

Recent runner events are stored beside the local queue and restored at startup.
The visible log receives progress while the worker is running. Events rotate at
1 MiB; private state stays in the user profile.

Steps 2–5 have no bundled default instructions. Personal templates are read only
from `~/.config/devos/pipeline_steps_25.md` and saved with owner-only permissions.
Do not copy personal templates, queue files, or connection credentials into the
source tree or OS image. Tests use synthetic instructions.

Validation on 2026-11-04: a two-step live Antigravity sample created `greeting.txt`,
verified it, automatically dispatched the second step, and created/verified
`result.txt`. A separate live Local AI pipeline sample wrote `hello.py`, executed
it successfully, and completed. These checks used temporary sample workspaces,
not personal queue prompts. They validate dispatch and handoff, not the correctness
of an arbitrary generated application. Claude/Aider require separate installed,
authenticated CLIs; their live execution was not tested on this PC.

Drafting a project: paste one full prompt and click **Add Prompt**. Repeat for
additional prompts. The draft list shows the first five words of each prompt;
select a row to move it up/down, edit it, or remove it. **Add Project to Pipeline**
is the final submission and queues every draft prompt under one project. Any
text still in the editor is included as one final prompt. Markdown `---` inside
a draft is preserved, not interpreted as a project or step separator. The
optional local Auto-add **step groups** (`~/.config/devos/pipeline_step_pack.json`).
Each named group holds 1–6 prompts (paste several in one editor separated by `---`).
**Auto-add group** picks a group and stages every step in that group in order after
Step 1. Edit groups with ⚙.

The queue displays one project per page; Previous/Next changes only the view,
not execution order. **Clear Logs** clears current and rotated activity history
without removing projects or their execution state. **Clear Queue** is separate.

Parallel projects (desktop pipeline): the runner reserves work from different
project directories and different agent *slots*. Within each project, only its
first unfinished prompt can run. A failed, scheduled, or unverified prompt
blocks that project's successors without blocking unrelated projects.
Codex/ChatGPT aliases share one slot. Google Antigravity and Antigravity KDE
are **separate execution slots** — one project can run on Antigravity while
another runs on Antigravity KDE. When an agent finishes, it picks up the next
queued project assigned to that same agent. They still bill one Google consumer
OAuth quota (`~/.gemini/jetski-standalone-oauth-token`); a *current*
`RESOURCE_EXHAUSTED` / Individual quota response cools both Antigravity apps
until the reported reset time. Stale quota text left in older transcript lines
must not pause a conversation that is still actively working in the IDE.
Dispatch runs outside the queue lock and completion merges only the reserved
task under the lock, so concurrent workers cannot overwrite one another's results.
Pausing stops new reservations; it does not cancel already submitted agent work.
Active/unverified tasks cannot be deleted to bypass the reservation.

Antigravity KDE is a second local IDE/client (isolated user-data and hub port).
Its prompt API is discovered through its language server daemon
(`~/.gemini/antigravity-kde/daemon/hub_*.json`) or live process inspection
(`--hub-port` and `--csrf_token`). A custom endpoint can be set in
`~/.config/devos/antigravity-kde-api.json`. Stale cached ports are discarded
when the hub is not listening. KDE never reuses the primary Antigravity hub
address.
