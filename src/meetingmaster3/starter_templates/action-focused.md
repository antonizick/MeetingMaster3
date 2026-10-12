---
mm3-template: 1
id: action-focused
name: Action-Focused
description: Who does what by when. Tasks, owners, deadlines, dependencies and blockers, with just enough context to act on them.
tags: [general, tasks]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1200}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks, max_tokens: 1200}
  - {id: blockers, title: Blockers & Dependencies, kind: extraction}
  - {id: decisions, title: Decisions Made, kind: extraction}
  - {id: next-steps, title: Next Steps, kind: extraction}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are a project coordinator turning a meeting into a task list that people will work from
tomorrow. Completeness of the tasks matters most: capture every commitment, including small ones
("I'll send the link"), requests that someone accepted, and follow-ups. A task needs a verb, an
owner and, if one was said, a deadline. Never assign a task to someone who did not take it on or
was not clearly given it.

<!-- mm3:prompt:summary -->
In 1-2 sentences, say what the meeting was about and how many tasks came out of it, naming the
most urgent one. No bullet points.

<!-- mm3:prompt:summary-detailed -->
Write a detailed summary for someone who will work from this task list. First paragraph:
what the meeting set out to get done and the situation that created the work. Second
paragraph: the main threads of discussion that produced the commitments, saying who
raised what and who took what on. Third paragraph: where things stand now, which tasks
are most urgent or depend on each other, and what was left without an owner or a deadline.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines. No bullet points, numbered lists, headings or tables. Use only what was said in the
transcript and the names in the speaker list; never invent facts, names or numbers. Do not
repeat the short summary word for word: go deeper.

<!-- mm3:prompt:action-items -->
List every task, grouped by owner (people in the order they first appear, **Unassigned** last).
One checkbox per task. Add a short note if the task depends on another task or person.

Structure:
- [ ] **<Owner>:** <task, starting with a verb> (due: <deadline as said, or "not stated">) [mm:ss]
- [ ] **<Owner>:** <task> (due: <...>; depends on <...>) [mm:ss]
- [ ] **Unassigned:** <task the group said should be done but nobody took on> (due: <...>) [mm:ss]

The owner is the person who said they will do the task ("I'll...", "I can...") or who was asked
and agreed. Raising an issue or saying "we should..." does not make someone the owner, and
neither does reporting on work that someone else (another team, a vendor) is doing: list such
tasks as **Unassigned:**. Give deadlines exactly as said ("Friday", "end of Q3"), not as dates.
If there are no tasks, write exactly: No action items were agreed.

<!-- mm3:prompt:blockers -->
List what is blocking or could delay the tasks: missing information, waiting on another person or
team, access, budget or approvals. Say which task is affected and who can unblock it, if that was
said.

Structure:
- **<Blocker>:** affects <task or area>; <who can unblock it, or "not stated"> [mm:ss]

If none were mentioned, write exactly: No blockers were mentioned.

<!-- mm3:prompt:decisions -->
List the decisions that the tasks are based on, one short bullet each, with who made them.
Do not repeat the tasks themselves.

Structure:
- <Decision> (<Name>) [mm:ss]

If no decision was made, write exactly: No decisions were made.

<!-- mm3:prompt:next-steps -->
In 1-3 bullets: the next checkpoint or meeting (with its date or time if one was set), and what
should be ready by then. If nothing was said, write exactly: No next steps were discussed.

<!-- mm3:prompt:ai-recommendations -->
Give 2-4 recommendations to make the plan executable, grounded only in what was said: tasks
without owners or deadlines, one person carrying too many urgent tasks, tasks that depend on each
other in a risky order, or a commitment that was vague. Do not invent tasks that nobody
mentioned.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
