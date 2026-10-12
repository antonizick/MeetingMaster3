---
mm3-template: 1
id: project-team-sync
name: Project Team Sync
description: Multi-participant project sync with status by person or role, blockers, dependencies, milestones and tasks.
tags: [project, team]
favorite: false
sections:
  - {id: summary, title: Summary, kind: narrative}
  - {id: status-by-person, title: Status by Person, kind: extraction, max_tokens: 1500}
  - {id: milestones, title: Milestones & Dates, kind: extraction}
  - {id: blockers, title: Blockers & Dependencies, kind: extraction}
  - {id: decisions, title: Decisions Made, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks, max_tokens: 1200}
  - {id: next-steps, title: Next Steps, kind: extraction}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are a project manager recording a team sync with several contributors. Capture what each
person reported, in their own terms, and keep status honest: "in progress" is not "done", and a
hope is not a commitment. Never attribute work to someone who did not say they own it.

<!-- mm3:prompt:summary -->
In 2-4 sentences, give the overall state of the project as reported: what is on track, what is
at risk and what is blocked. No bullet points.

<!-- mm3:prompt:status-by-person -->
One block per contributor who gave an update, in the order they spoke. For each, record what
they have done, what they are working on or plan next, and anything they said is blocking them.
Use the contributor's name and, if they stated it, their role or area.

Structure:
**<Name>** (<role or area, if stated>)
- Done: <completed work>
- Next: <planned or in-progress work>
- Blocked by: <blocker, or "nothing stated">

Leave out a line only by writing "nothing stated". Do not merge contributors into a group, and
do not list people who said nothing about the project.

<!-- mm3:prompt:milestones -->
List the milestones, releases, deadlines and target dates that were mentioned, with their status
(on track, at risk, slipped, done) and any change of date, exactly as said.

Structure:
- **<Milestone>:** <date as said>; <status and reason if given> [mm:ss]

If none were mentioned, write exactly: No milestones were mentioned.

<!-- mm3:prompt:blockers -->
List what blocks or may delay the work: missing information, waiting on another person or
team, access, budget, approvals, or dependencies on other work. Say what it affects and who can
unblock it, if stated.

Structure:
- **<Blocker or dependency>:** affects <work or milestone>; <who can unblock it, or "not stated"> [mm:ss]

If none were mentioned, write exactly: No blockers or dependencies were mentioned.

<!-- mm3:prompt:decisions -->
List the decisions that were made, one short bullet each, with who made them. A proposal, a
preference or "let's think about it" is not a decision, and neither is a task assignment.

Structure:
- <Decision> (<Name>) [mm:ss]

If no decision was made, write exactly: No decisions were made.

<!-- mm3:prompt:action-items -->
List every task that was agreed, one per line.

Structure:
- [ ] **<Owner>:** <task, starting with a verb> (due: <deadline as said, or "not stated">) [mm:ss]
- [ ] **Unassigned:** <task the group said should be done but nobody took on> (due: <...>) [mm:ss]

The owner is the person who said they will do the task ("I'll...", "I can...") or who was asked
and agreed. Raising an issue or saying "we should..." does not make someone the owner, and
neither does reporting on work that someone else (another team, a vendor) is doing: list such
tasks as **Unassigned:**. Give deadlines exactly as said ("Friday", "end of Q3"), not as dates.
If there are no tasks, write exactly: No action items were agreed.

<!-- mm3:prompt:next-steps -->
In 1-3 bullets: the next meeting or checkpoint (with its date or time if one was set) and what
should be ready by then. If nothing was said, write exactly: No next steps were discussed.

<!-- mm3:prompt:ai-recommendations -->
Give 2-4 recommendations about delivery, grounded only in the updates: a milestone at risk
with an unresolved blocker, a person carrying much more work than others, a dependency with no
owner, or a task without a date. Do not invent tasks that nobody mentioned.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
