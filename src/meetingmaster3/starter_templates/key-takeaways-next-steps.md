---
mm3-template: 1
id: key-takeaways-next-steps
name: Key Takeaways & Next Steps
description: Only the key insights and the immediate actions, for a quick read.
tags: [general, brief]
favorite: false
sections:
  - {id: key-points, title: Key Takeaways, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are writing the shortest useful note: the few things that mattered and what happens
next. Choose the points a reader would regret missing. Each is one short sentence. Leave out
background, pleasantries and detail that does not change what anyone does.

<!-- mm3:prompt:key-points -->
List the 3-6 most important insights, conclusions or decisions, one sentence each, most
important first. Mark a decision as such only if it was decided.

Structure:
- <Takeaway, in one sentence> [mm:ss]

If nothing of substance was discussed, write exactly: No key takeaways were identified.

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
Give 1-2 one-line suggestions, grounded only in the meeting: the one thing most worth doing
first, or a follow-up that is missing an owner. Do not add new content.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
