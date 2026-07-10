# Nightly Workflow — Semi-Autonomous Overnight Builds

A routine for building Loom incrementally: you write the intent each evening, Claude Code executes overnight, and you review results each morning. Each cycle advances one task from the milestone files.

---

## Philosophy

Each overnight session should:
- Target **one concrete step** from a milestone file (e.g. "Step 1 — SchemaUIConfig model")
- Be **verifiable by tests** — Claude writes the tests and they must pass before committing
- Leave the repo in a **clean, committable state** — no half-finished migrations, no broken imports
- Produce a **morning review file** summarising what was done and what needs human attention

A step that can't be finished in one night should be sub-scoped further. If Claude hits a blocker, the session should write a `BLOCKED.md` note and stop rather than guessing.

---

## File Structure

```
docs/roadmap/
  NIGHT_TASK.md         ← you write this each evening
  MORNING_REVIEW.md     ← Claude writes this each morning (overwritten each night)
  BLOCKED.md            ← Claude writes this if it hits a genuine blocker
```

---

## Evening Setup (5 minutes)

### 1. Pick the next step

Open the current milestone file (e.g. `docs/roadmap/v0.4.0-schema-admin.md`). Find the first uncompleted step. Copy its prompt block.

### 2. Write `docs/roadmap/NIGHT_TASK.md`

Replace the file contents with:

```markdown
# Tonight's Task — [Date]

## Milestone
[e.g. v0.4.0 Step 1 — SchemaUIConfig model]

## Prompt
[paste the step prompt block here]

## Constraints
- Run `pytest` after every file change; stop if tests regress
- Do not create migrations without running `python manage.py migrate` to verify
- Do not push to remote
- Commit with message: "[milestone] [step description]"
- If blocked for more than 3 attempts on the same issue, write the blocker to
  docs/roadmap/BLOCKED.md and stop
- Write a summary of changes to docs/roadmap/MORNING_REVIEW.md before stopping

## Out of Scope Tonight
[anything you explicitly do not want touched]
```

### 3. Create a feature branch

```powershell
git checkout -b night/v0.4.0-step1-schema-ui-config
```

This protects `main` from partially-completed overnight work.

---

## Running Claude Code Overnight

### Option A — Local (Windows Task Scheduler)

**One-time setup:**

Create `scripts\night_build.ps1`:

```powershell
# scripts\night_build.ps1
param([string]$RepoPath = "C:\Users\Tim Alamenciak\Documents\RacoonLab\repos\loom")

Set-Location $RepoPath

$date = Get-Date -Format "yyyy-MM-dd"
$logDir = "logs\nightly"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$task = Get-Content "docs\roadmap\NIGHT_TASK.md" -Raw

Write-Output "[$date] Starting nightly build..." | Tee-Object "$logDir\$date.log"

# Run Claude Code non-interactively with the task
# Adjust flags based on your Claude Code CLI version (run `claude --help` to verify)
claude -p $task 2>&1 | Tee-Object -Append "$logDir\$date.log"

# Capture test results and diff for morning review
$diff = git diff --stat
$testOutput = python -m pytest --tb=short -q 2>&1 | Select-Object -Last 20
$reviewContent = @"
# Morning Review — $date

## What Was Built
*(Claude should have written this above — check the log if this section is empty)*

## Git Diff
``````
$diff
``````

## Test Results
``````
$testOutput
``````

## Log
Full log at: logs\nightly\$date.log
"@

$reviewContent | Out-File "docs\roadmap\MORNING_REVIEW.md" -Encoding utf8

Write-Output "[$date] Done. Review docs\roadmap\MORNING_REVIEW.md" | Tee-Object -Append "$logDir\$date.log"
```

**Schedule in Windows Task Scheduler:**

```powershell
# Run once to register the task
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NonInteractive -File C:\Users\Tim Alamenciak\Documents\RacoonLab\repos\loom\scripts\night_build.ps1"

$trigger = New-ScheduledTaskTrigger -Daily -At "11:00PM"

Register-ScheduledTask -TaskName "Loom Nightly Build" `
    -Action $action -Trigger $trigger `
    -RunLevel Highest -Force
```

Check `claude --help` for the exact non-interactive flags for your installed version. Common patterns:
- `claude -p "prompt"` — single-turn non-interactive
- `claude --print "prompt"` — alias in some versions

### Option B — Claude Code Scheduled Agent (Cloud)

If you want the build to run on Claude Code's cloud infrastructure (requires a GitHub remote):

1. Push your feature branch to GitHub
2. Use `/schedule` in a Claude Code session to create a nightly agent:

```
/schedule "At 11pm every weekday: read docs/roadmap/NIGHT_TASK.md from the
loom repo, execute the task described, commit the changes to the current feature
branch, and write a summary to docs/roadmap/MORNING_REVIEW.md"
```

The cloud agent can push to the feature branch; you review and merge in the morning.

---

## Morning Review (10–15 minutes)

### 1. Read the summary

```powershell
code docs\roadmap\MORNING_REVIEW.md
```

### 2. Check for blockers

```powershell
Test-Path docs\roadmap\BLOCKED.md
# If True, read it and address the blocker before tonight
```

### 3. Review the diff

```powershell
git diff main..HEAD --stat
git diff main..HEAD
```

### 4. Run tests yourself

```powershell
python -m pytest --tb=short
```

### 5. If satisfied — merge to main

```powershell
git checkout main
git merge --no-ff night/v0.4.0-step1-schema-ui-config -m "feat: SchemaUIConfig model (v0.4.0 Step 1)"
```

Mark the step complete in the milestone file (`- [x]` in the acceptance criteria).

### 6. If not satisfied — iterate

Don't merge. Update `NIGHT_TASK.md` with a correction note and let it run again tonight, or fix it yourself in the daytime.

---

## Scoping Guide

**Right-sized for one night (likely to finish cleanly):**
- A single new model + migration + 3–5 unit tests
- A single new view + template + 2–3 tests
- A new management command + tests
- A new utility function + tests

**Too large for one night (split further):**
- Multiple new models with FK relationships
- A new interactive UI component (form builder, drag-and-drop)
- End-to-end tests that depend on multiple not-yet-built components
- Any step with "integration with X" that requires understanding X's internals

**Good signals the task is right-sized:**
- The prompt block in the milestone file fits in one screen
- The "Scope for one night" note in the milestone file says it's suitable
- There are 3–7 explicit tests listed

---

## Sample `NIGHT_TASK.md` (copy as template)

```markdown
# Tonight's Task — 2026-07-11

## Milestone
v0.4.0 Step 1 — SchemaUIConfig model

## Prompt
Add a SchemaUIConfig model to apps/schemas/models.py with FK to SchemaVersion
(CASCADE) and nullable FK to Project (CASCADE, null=True, blank=True). JSONFields:
layers (list), ontology_routing (dict), widget_overrides (dict),
globally_hidden_slots (list), slot_help_text (dict). Add Meta.unique_together =
[('schema_version', 'project')]. Add classmethod for_schema_version(cls, sv,
project=None) implementing the three-level fallback: (1) project-level DB record,
(2) schema-level DB record, (3) transient instance from parsing config/loom_ui.yaml
using apps/schemas/ui_config.py. Create the migration. Write
tests/schemas/test_ui_config_model.py with: test_fallback_to_yaml (no DB record →
parses loom_ui.yaml, layers not empty), test_schema_level_record (schema-level record
returned when no project record), test_project_override_shadows_schema (project-level
record returned when both exist).

## Constraints
- Run `pytest tests/schemas/` after completing each file; stop if existing tests regress
- Do not create the migration without verifying it applies cleanly with `python manage.py migrate`
- Do not modify apps/annotation/ or apps/export/ tonight
- Do not push to remote
- Commit with message: "feat(schemas): add SchemaUIConfig model with fallback chain (v0.4.0 step 1)"
- If blocked for more than 3 attempts on the same issue, write the blocker to
  docs/roadmap/BLOCKED.md and stop cleanly
- Write a summary to docs/roadmap/MORNING_REVIEW.md before stopping

## Out of Scope Tonight
- The schema upload view (Step 3)
- Patching schema_engine.py (Step 2) — that comes next
- Any template work
```

---

## Troubleshooting

**Claude ran but made no commits**
Check `logs/nightly/<date>.log` for the session output. Common causes: permission error on the branch, tests failed and Claude correctly stopped, or the session timed out.

**Tests regressed**
Read `MORNING_REVIEW.md` — Claude should have noted what broke. If the regression is in an area Claude shouldn't have touched, check if the scope constraint in `NIGHT_TASK.md` was specific enough.

**Claude went off-scope**
Tighten the "Out of Scope" section in `NIGHT_TASK.md`. The more explicit, the better.

**Migration conflict**
If a migration was created on the night branch that conflicts with main, resolve with:
```powershell
python manage.py migrate --run-syncdb
# or renumber the migration manually
```
