---
mm3-template: 1
id: executive-summary
name: Executive Summary
description: A short, high-level brief on outcomes, key decisions and their implications, for readers who were not in the room.
tags: [general, leadership]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1200}
  - {id: decisions, title: Decisions Made, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks}
  - {id: open-questions, title: Open Questions, kind: extraction}
  - {id: next-steps, title: Next Steps, kind: extraction}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are briefing a busy executive who was not in the meeting and will spend one minute reading
the note. Lead with outcomes, not with the order of discussion. Prefer one precise sentence over
three general ones. Name who decided or committed to what. Leave out greetings, small talk,
logistics and anything that did not change an outcome.

<!-- mm3:prompt:summary -->
Write 2-4 sentences, as one paragraph, that answer: what was this meeting for, what was
concluded, and what does it mean for the business (impact, risk, cost or timing)? Mention the
single most important decision or result first. No bullet points. Do not list the participants.

<!-- mm3:prompt:summary-detailed -->
Write a detailed summary for an executive who has five minutes rather than one. First
paragraph: why the meeting was held and the business context. Second paragraph: the main
lines of discussion and the trade-offs, naming who argued for what. Third paragraph: what
was decided, what it means for the business (impact, risk, cost or timing) and what is
still unresolved. Lead with outcomes, not with the order of discussion.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines. No bullet points, numbered lists, headings or tables. Use only what was said in the
transcript and the names in the speaker list; never invent facts, names or numbers. Do not
repeat the short summary word for word: go deeper.

<!-- mm3:prompt:decisions -->
List every decision that was actually made in the meeting, one bullet each, most important
first. A decision is something the group agreed to do, approve, stop or choose. Proposals,
opinions and things that were only discussed are not decisions, and neither are individual
task assignments ("Tom will email Northwind"): those belong in Action Items.

Structure:
- **<Decision, stated as an outcome>.** <Why, in a few words, if a reason was given.> (<who decided or proposed it>) [mm:ss]

If no decision was made, write exactly: No decisions were made.

<!-- mm3:prompt:action-items -->
List every concrete task that someone agreed to do or was asked to do, one per line.

Structure:
- [ ] **<Owner>:** <task, starting with a verb> (due: <deadline as said, or "not stated">) [mm:ss]
- [ ] **Unassigned:** <task the group said should be done but nobody took on> (due: <...>) [mm:ss]

The owner is the person who said they will do the task ("I'll...", "I can...") or who was asked
and agreed. Raising an issue or saying "we should..." does not make someone the owner, and
neither does reporting on work that someone else (another team, a vendor) is doing: list such
tasks as **Unassigned:**. Give deadlines exactly as said ("Friday", "end of Q3"), not as dates.
If there are no tasks, write exactly: No action items were agreed.

<!-- mm3:prompt:open-questions -->
List the questions and issues that were raised but not resolved, one bullet each, with who
raised them. Include disagreements that were left open. Do not include questions that were
answered in the meeting.

Structure:
- <Question or unresolved issue> (raised by <Name>) [mm:ss]

If nothing was left open, write exactly: No open questions.

<!-- mm3:prompt:next-steps -->
In 1-4 bullets, say what happens next at the level of the whole group: the next meeting or
checkpoint, the milestone being worked towards, or who is waiting on whom. Do not repeat the
individual action items. If nothing was said about next steps, write exactly: No next steps
were discussed.

<!-- mm3:prompt:ai-recommendations -->
Give 2-4 recommendations to the meeting owner, grounded only in what was said. Good
recommendations point at a decision that lacks an owner or a deadline, a risk that was mentioned
but not addressed, a dependency between tasks, or a question that blocks progress. Each bullet
names the issue and a concrete, proportionate suggestion. Do not invent facts, people or numbers.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
