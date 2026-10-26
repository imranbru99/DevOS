# AI workflow verification

The pipeline executes queued commands in order. A delayed, busy, rate-limited,
failed or unverified submitted task blocks dependent commands. Provider calls run
on a GUI worker thread. Pausing stops subsequent tasks; it does not cancel an
already running external command. Queue files use atomic, flushed replacement
and a shared advisory lock, so concurrent add/run operations cannot overwrite
one another. Each saved provider response is limited to its last 64 KiB.

Codex automation requires an installed, signed-in Codex CLI. Success requires a
successful CLI exit; an absent CLI is an error. The pipeline does not type into
arbitrary desktop windows or treat an idle desktop as proof of task success.
Antigravity's `new-conversation` command acknowledges submission, not completion:
these tasks stay SUBMITTED, and the user must inspect the result and choose
**Confirm completed** before continuing. Verified automatic completion for this
provider requires a supported per-conversation result API; the current process
and transcript activity checks are only busy hints.

Local AI produces a model response; it does not independently prove that the
response's proposed code was installed, tested or deployed. Claude/Aider/custom
agents report their command exit status. A successful process exit also cannot
prove arbitrary task correctness; project-specific tests remain necessary.

GitHub creation requires authenticated GitHub CLI. Opening a browser form is
not reported as successful creation. Repository creation/push must succeed for a
repository-creating pipeline task to be complete. New Git commits check both
effective author and committer identities before committing.

Tests use mocks and temporary queue files. They do not send prompts to real
accounts, publish repositories or consume provider credits.
