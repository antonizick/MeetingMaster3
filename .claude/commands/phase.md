---
description: Start or resume a MeetingMaster3 build phase (e.g. /phase 03, /phase next, /phase status)
argument-hint: "[NN | next | status]"
---
You are executing a MeetingMaster3 build phase. Argument: `$ARGUMENTS` (empty means `next`).

1. Read `CLAUDE.md`, `IMPLEMENTATION_PLAN.md` and `prompts/_shared-instructions.md`.
2. Pick the phase:
   - `status`: print a compact table of all phases (number, name, model, status icon, dependencies met?), name the next eligible phase or phases, list any open owner questions, then stop.
   - `next` or empty: the lowest-numbered phase whose status is `⬜ Not started` or `🔄 In progress` and whose dependencies are all `✅ Complete`. If several are eligible in parallel, name them and ask which one to run.
   - `NN`: that phase. If any of its dependencies is not `✅ Complete`, say so and stop.
3. **Model check:** compare the phase's "AI Model to Use" with the model you are running as. If they differ, tell Nick the exact `/model` command for the listed model and ask whether to continue anyway before doing any work. (This replaces the generic session model-fit check for phase sessions.)
4. If the phase is `🔄 In progress`, this is a resumed session: read its Phase Log entry, `git status` and `git log` on its branch, and continue from where the work stopped instead of starting over.
5. Check the plan's Owner questions table for questions needed by this phase. If one is still open, ask Nick before starting the affected work.
6. Open the phase's prompt file (linked in the table) and execute it fully, including the close-out checklist in `_shared-instructions.md`.
