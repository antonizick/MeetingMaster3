---
description: Start or resume a MeetingMaster3 build phase (e.g. /phase 03, /phase 15a, /phase next, /phase status)
argument-hint: "[NN | NNa | next | status] [--auto]"
---
You are executing a MeetingMaster3 build phase. Argument: `$ARGUMENTS` (empty means `next`).

PHX-CONTRACT: 1

**Hands-off mode** is on if the argument contains `--auto` or `printenv PHX_AUTO` prints `1`; only PhaseHypervisor (`phx`) sets either. When it is off, skip the "Hands-off mode" section at the end and follow the steps below as written. When it is on, that section overrides the steps it names.

0. **PHX check** (hands-off mode off, every form): before anything else, run
   `f="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/phx/$(basename "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")").lock"; [ -e "$f" ] && ! flock -n -s "$f" true && echo "PHX-RUNNING $(cat "$f")"; printenv PHX_AUTO`.
   If it prints `PHX-RUNNING`, a PhaseHypervisor supervisor is running this plan: tell Nick (its PID, phase and start time from that line; `phx status` / `phx stop` if installed) and stop without claiming or changing anything. For `status`, show that notice above the table and continue.

Other agents may be running other phases at the same time. The Status column **on `main`** is how they know what is taken, so read it from `main` (`git show main:MM3_IMPLEMENTATION_PLAN.md`), not from a phase branch or worktree.

Phase IDs are two digits, optionally followed by a lower-case letter for a phase inserted later with `/phase-add` (ADR-0030, ADR-0034): `15a` comes after `15` and before `15b`, which comes before `16`; `09a` would sit between `09` and `10`. Wherever `NN` appears below, it means the full ID (`15a`), including in branch, worktree and `grep` patterns.

1. Read `CLAUDE.md`, `MM3_IMPLEMENTATION_PLAN.md` and `prompts/MM3_shared-instructions.md`.
2. Pick the phase:
   - `status`: print a compact table of all phases (number, name, model, status icon, dependencies met?, and a **Live** column showing the phase's branch and worktree from `git branch --list 'phase-*'` and `git worktree list`). Flag drift with ⚠️: a `phase-NN-*` branch or worktree exists but the row on `main` is not `🔄 In progress` (an agent skipped the claim), or a row is `🔄 In progress` with no branch or worktree (a stale claim). Name the next eligible phase or phases, list any open owner questions, then stop.
   - `next` or empty: the lowest-numbered phase whose status is `⬜ Not started` and whose dependencies are all `✅ Complete`. If any phase is already `🔄 In progress`, list it (worktree, time of its last commit, number of uncommitted changes) and ask Nick whether to resume it or start the new one, because another session may still be working on it. If several phases are eligible in parallel, name them and ask which one to run.
   - `NN`: that phase. If any of its dependencies is not `✅ Complete`, say so and stop. If it is `🔄 In progress`, ask Nick to confirm that no other session is running it before you resume.
3. **Model check:** compare the phase's "AI Model to Use" with the model you are running as. If they differ, tell Nick the exact `/model` command for the listed model and ask whether to continue anyway before doing any work. (This replaces the generic session model-fit check for phase sessions.)
4. **Claim before work (mandatory):** for a `⬜ Not started` phase, follow the claim protocol in `prompts/MM3_shared-instructions.md` §1a. Commit `🔄 In progress` to `main`, update the Obsidian note, then create the worktree `../MeetingMaster3-phase-NN`. Do not open the phase's Tasks or change any other file until `git show main:MM3_IMPLEMENTATION_PLAN.md | grep '^| NN '` shows `🔄 In progress`. If the claim cannot be made (the main checkout is not on `main`, or `MM3_IMPLEMENTATION_PLAN.md` has uncommitted changes there), stop and tell Nick.
5. **Resume:** if the phase is `🔄 In progress`, read its Phase Log entry, `git status` and `git log` in its worktree, and continue from where the work stopped instead of starting over. If a branch or worktree exists but the row on `main` still says `⬜ Not started` (a session that started before the claim rule existed), make the claim commit on `main` now (§1a steps 3, 4 and 6), then resume.
6. Check the plan's Owner questions table for questions needed by this phase. If one is still open, ask Nick before starting the affected work.
7. Open the phase's prompt file (linked in the table) and execute it fully **in the phase's worktree**, including the close-out checklist in `MM3_shared-instructions.md`.

## Hands-off mode (PhaseHypervisor, contract 1)
Applies only when hands-off mode is on. The full contract is `docs/PHX_AUTO_MODE_CONTRACT.md` in the PhaseHypervisor repo; these are the rules you need.
- **Never interactive.** Do not use AskUserQuestion, plan mode or anything that waits for Nick. Skip step 0 (the supervisor that started you holds the lock).
- **One named phase.** Strip `--auto` from the argument; what remains must be one phase ID. `status` works as usual. `next`, empty or anything else: change nothing and end with a `refused` result.
- **Refuse, changing nothing,** when: a dependency is not `✅ Complete`; the phase is `✅ Complete`; its Gate (the plan's `Gate` column, else `**Gate:**` in its prompt header) is `owner`; the ID is not in the table; the claim cannot be made (step 4); or it is `⛔ Blocked` and an owner question needed by it is still open.
- **Step 3:** skip the model check. In the Phase Log entry, put `- **Model:** ran as <your model ID> (auto mode; plan lists <listed model>)` right after the Timeline bullet.
- **Step 2 `NN` and step 5:** resume a `🔄 In progress` phase without asking. Resume a `⛔ Blocked` phase whose questions are all answered per shared instructions §1b ("Resuming").
- **Step 6, shared instructions §1 step 6, and the risk rule in `CLAUDE.md`:** wherever you would ask Nick, block the phase instead (block-with-question, shared instructions §1b) and end the session.
- **Close-out:** unchanged (merge and push without asking, per the git authority in `CLAUDE.md`). Write the final message as usual.
- **Result line.** The last line of your final message, in every outcome, is exactly one line, no code fence:
  `PHX-RESULT: {"contract":1,"phase":"NN","status":"complete","reason":"<one line, ≤ 200 chars>","merged":true,"pushed":true,"question_ids":[]}`
  `status` is `complete`, `blocked` (then `question_ids` lists the Owner question numbers as strings, never empty) or `refused` (nothing changed; `phase` is `null` if no valid ID was given). `merged` and `pushed` are true only if you did them in this session.
