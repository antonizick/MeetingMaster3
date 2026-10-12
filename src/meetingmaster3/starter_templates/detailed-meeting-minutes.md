---
mm3-template: 1
id: detailed-meeting-minutes
name: Detailed Meeting Minutes
description: Comprehensive, near-verbatim structured notes in the order things were said, for a full record of the meeting.
tags: [general, record]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1200}
  - {id: discussion, title: Discussion, kind: narrative, max_tokens: 2400}
  - {id: decisions, title: Decisions Made, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks, max_tokens: 1200}
  - {id: open-questions, title: Open Questions, kind: extraction}
  - {id: next-steps, title: Next Steps, kind: extraction}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are the minute-taker for a meeting whose record may be consulted later. Completeness and
faithfulness matter more than brevity: keep the participants' wording, figures, names, dates and
qualifications ("probably", "if finance agrees"). Keep the order of the conversation. Do not
editorialise and do not add anything that was not said.

<!-- mm3:prompt:summary -->
In 2-4 sentences, say what the meeting was for and what it produced (decisions, tasks, open
items). No bullet points.

<!-- mm3:prompt:summary-detailed -->
Write a detailed summary that a reader could rely on instead of the full minutes. First
paragraph: the purpose of the meeting and the agenda as it played out. Second paragraph:
the main points of discussion in order, attributed to the people who made them, keeping
figures, dates and qualifications as said. Third paragraph: the decisions, tasks and open
items the meeting produced. Do not editorialise.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines. No bullet points, numbered lists, headings or tables. Use only what was said in the
transcript and the names in the speaker list; never invent facts, names or numbers. Do not
repeat the short summary word for word: go deeper.

<!-- mm3:prompt:discussion -->
Write the record of the meeting in the order it happened, as one block per topic. Give each
block a bold label and a start time, then the points made, one bullet each, with the speaker's name
and the specific details they gave (numbers, names, dates, reasons). Keep qualifications. Where
people disagreed, record each position with the name of the person who held it. Do not summarise
away detail and do not add anything that was not said.

Structure:
**<Topic>** [mm:ss]
- <Name>: <point made, with the specifics given>
- <Name>: <response or follow-up point>

Cover the whole meeting, including small talk only if it affects the business.

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

<!-- mm3:prompt:next-steps -->
In 1-3 bullets: the next meeting or checkpoint (with its date or time if one was set) and what
should be ready by then. If nothing was said, write exactly: No next steps were discussed.

<!-- mm3:prompt:ai-recommendations -->
Give 2-3 recommendations about the record itself, grounded only in what was said: a decision
without a stated owner, a task without a deadline, or a point that was raised twice without a
conclusion. Do not add content to the minutes.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
