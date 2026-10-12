---
description: Start or resume a MeetingMaster3 build phase (e.g. /phase 03, /phase 15a, /phase next, /phase status)
argument-hint: "[NN | NNa | next | status]"
---
You are executing a MeetingMaster3 build phase. Argument: `$ARGUMENTS` (empty means `next`).

Other agents may be running other phases at the same time. The Status column **on `main`** is how they know what is taken, so read it from `main` (`git show main:IMPLEMENTATION_PLAN.md`), not from a phase branch or worktree.

Phase IDs are two digits, optionally followed by a lower-case letter for an interim tuning round (ADR-0030): `15a` comes after `15` and before `16`. Wherever `NN` appears below, it means the full ID (`15a`), including in branch, worktree and `grep` patterns.

1. Read `CLAUDE.md`, `IMPLEMENTATION_PLAN.md` and `prompts/_shared-instructions.md`.
2. Pick the phase:
   - `status`: print a compact table of all phases (number, name, model, status icon, dependencies met?, and a **Live** column showing the phase's branch and worktree from `git branch --list 'phase-*'` and `git worktree list`). Flag drift with ⚠️: a `phase-NN-*` branch or worktree exists but the row on `main` is not `🔄 In progress` (an agent skipped the claim), or a row is `🔄 In progress` with no branch or worktree (a stale claim). Name the next eligible phase or phases, list any open owner questions, then stop.
   - `next` or empty: the lowest-numbered phase whose status is `⬜ Not started` and whose dependencies are all `✅ Complete`. If any phase is already `🔄 In progress`, list it (worktree, time of its last commit, number of uncommitted changes) and ask Nick whether to resume it or start the new one, because another session may still be working on it. If several phases are eligible in parallel, name them and ask which one to run.
   - `NN`: that phase. If any of its dependencies is not `✅ Complete`, say so and stop. If it is `🔄 In progress`, ask Nick to confirm that no other session is running it before you resume.
3. **Model check:** compare the phase's "AI Model to Use" with the model you are running as. If they differ, tell Nick the exact `/model` command for the listed model and ask whether to continue anyway before doing any work. (This replaces the generic session model-fit check for phase sessions.)
4. **Claim before work (mandatory):** for a `⬜ Not started` phase, follow the claim protocol in `prompts/_shared-instructions.md` §1a. Commit `🔄 In progress` to `main`, update the Obsidian note, then create the worktree `../MeetingMaster3-phase-NN`. Do not open the phase's Tasks or change any other file until `git show main:IMPLEMENTATION_PLAN.md | grep '^| NN '` shows `🔄 In progress`. If the claim cannot be made (the main checkout is not on `main`, or `IMPLEMENTATION_PLAN.md` has uncommitted changes there), stop and tell Nick.
5. **Resume:** if the phase is `🔄 In progress`, read its Phase Log entry, `git status` and `git log` in its worktree, and continue from where the work stopped instead of starting over. If a branch or worktree exists but the row on `main` still says `⬜ Not started` (a session that started before the claim rule existed), make the claim commit on `main` now (§1a steps 3, 4 and 6), then resume.
6. Check the plan's Owner questions table for questions needed by this phase. If one is still open, ask Nick before starting the affected work.
7. Open the phase's prompt file (linked in the table) and execute it fully **in the phase's worktree**, including the close-out checklist in `_shared-instructions.md`.
