---
mm3-template: 1
id: speaker-attributed-notes
name: Speaker-Attributed Notes
description: Notes organised by speaker, so you can see what each person said, argued for and committed to.
tags: [general, attribution]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1000}
  - {id: points-by-speaker, title: Points by Speaker, kind: extraction, max_tokens: 2400}
  - {id: decisions, title: Decisions Made, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks, max_tokens: 1200}
  - {id: open-questions, title: Open Questions, kind: extraction}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are writing notes in which who said what matters, for example to follow each person's
position. Group the points under the person who made them and keep their stance as they expressed
it. Use only the names in the speaker list; if a speaker is unnamed, use their label (for example
"Speaker 3") and do not guess who they are. Never attribute a point to a person who did not make it.

<!-- mm3:prompt:summary -->
In 2-4 sentences, say what the meeting was about and who the main contributors were. No bullet
points.

<!-- mm3:prompt:summary-detailed -->
Write a detailed summary in which it is always clear who said what. First paragraph: what
the meeting was about and who the main contributors were. Second paragraph: each main
contributor's position or contribution, attributed by name and kept as they expressed it.
Third paragraph: where the positions met or diverged, and what was concluded or left open.
Use only the names in the speaker list; never guess who an unnamed speaker is.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines, about 200-450 words in all. No bullet points, numbered lists, headings or tables. Use
only what was said in the transcript and the names in the speaker list; never invent facts,
names or numbers. Do not repeat the short summary word for word: go deeper.

<!-- mm3:prompt:points-by-speaker -->
One block per speaker, in the order they first spoke. List 2-6 of their most important points,
each as a short bullet: positions taken, facts reported, requests, concerns and commitments. Keep
each person's stance in their own terms. Skip filler and agreement noises.

Structure:
**<Name>**
- <Point, position or concern> [mm:ss]
- <Point> [mm:ss]

Include every person who made a substantive point, and nobody who did not.

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

<!-- mm3:prompt:open-questions -->
List the questions that were raised and left unanswered, and the points that were explicitly
left open, one bullet each, with who asked or who is expected to find out, if that was said.

Structure:
- <Question or open point> (<Name>) [mm:ss]

If nothing was left open, write exactly: No open questions were raised.

<!-- mm3:prompt:ai-recommendations -->
Give 2-3 observations about the participation, grounded only in what was said: someone whose
objection was never answered, two people holding conflicting positions, or a topic only one person
spoke on. Do not judge anyone's contribution.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
