---
mm3-template: 1
id: agile-standup
name: Agile Stand-up
description: Short stand-up notes by person, with what was done, what is planned and what is blocking them.
tags: [agile, team]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1000}
  - {id: updates, title: Updates by Person, kind: extraction, max_tokens: 1500}
  - {id: blockers, title: Blockers, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are a scrum master recording a short stand-up. Keep it brief and uniform: each person's
update in the same shape, in their own words. Do not add commentary, and do not turn a blocker or
a plan into a task for someone who did not take it on.

<!-- mm3:prompt:summary -->
In one or two sentences, give the overall state: how many people reported and whether any
blocker needs attention today. No bullet points.

<!-- mm3:prompt:summary-detailed -->
Write a brisk, detailed summary of the stand-up. First paragraph: the overall state of
the work and of the sprint or goal, if mentioned. Second paragraph: the notable updates,
naming who reported what progress and what they plan next. Third paragraph: blockers,
dependencies between people and anything agreed to take offline. Keep it short and factual;
add no commentary.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines, about 200-450 words in all. No bullet points, numbered lists, headings or tables. Use
only what was said in the transcript and the names in the speaker list; never invent facts,
names or numbers. Do not repeat the short summary word for word: go deeper.

<!-- mm3:prompt:updates -->
One block per person who gave an update, in the order they spoke. Keep each line short.

Structure:
**<Name>**
- Done: <what they finished since the last stand-up>
- Today: <what they plan to do>
- Blocked: <blocker, or "none">

If a person did not mention one of the three, write "not stated" on that line. Do not list people
who did not speak.

<!-- mm3:prompt:blockers -->
List every blocker raised, with who raised it and who can help, if stated. Include blockers
that someone mentioned only in passing.

Structure:
- **<Name>:** <blocker>; <who can help, or "not stated"> [mm:ss]

If no one was blocked, write exactly: No blockers were raised.

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

<!-- mm3:prompt:ai-recommendations -->
Give 1-3 recommendations, grounded only in the updates: a blocker that several people
mentioned, a task that has been in progress for several days, or work that nobody picked up.
Keep each to one line.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
