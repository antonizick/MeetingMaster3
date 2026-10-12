---
mm3-template: 1
id: chronological-timeline
name: Chronological Timeline
description: Events, updates and decisions in the order they occurred, with timestamps, for a clear sequence of what happened and when.
tags: [general, timeline]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1000}
  - {id: timeline, title: Timeline, kind: extraction, max_tokens: 2400}
  - {id: decisions, title: Decisions Made, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are reconstructing the sequence of a conversation for someone who needs to see what
happened and in what order. Every entry carries the meeting timestamp where it occurred, and the
entries are in order of time. Keep each entry to one event, update or decision, and name who
said or did it. If the speakers describe past events with dates (for example, an incident
timeline), record those dates as said in the entry text, in addition to the meeting timestamp.
Do not reorder, merge distant events or invent events.

<!-- mm3:prompt:summary -->
In 2-3 sentences, give the arc of the meeting from start to finish. No bullet points.

<!-- mm3:prompt:summary-detailed -->
Write a detailed summary that follows the arc of the meeting in order. First paragraph:
how it opened and what it was for. Second paragraph: the main sequence of topics and
events, in the order they happened, with who drove each. Third paragraph: how it ended,
what was concluded and what remained open. Keep the order of events; never reorder them.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines, about 200-450 words in all. No bullet points, numbered lists, headings or tables. Use
only what was said in the transcript and the names in the speaker list; never invent facts,
names or numbers. Do not repeat the short summary word for word: go deeper.

<!-- mm3:prompt:timeline -->
List the events, topics, updates and turning points in the order they happened in the meeting,
one line each, starting with the timestamp. Include when topics changed, when decisions were made
and when tasks were assigned. If speakers discussed dated events, keep the dates as said.

Structure:
- [mm:ss] <Name>: <event, update or turning point>
- [mm:ss] <Name>: <event>

Cover the whole meeting, from the first minutes to the last, without gaps in the narrative.

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

<!-- mm3:prompt:ai-recommendations -->
Give 1-3 observations about the sequence, grounded only in what was said: a decision that came
before the information it depended on, a topic that returned later without resolution, or a gap
in a described incident timeline. Do not add events.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
