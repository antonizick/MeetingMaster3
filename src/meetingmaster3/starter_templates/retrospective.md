---
mm3-template: 1
id: retrospective
name: Retrospective & Lessons Learned
description: Retrospective or lessons-learned review covering what went well, what did not, root causes and improvements to try.
tags: [agile, review]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1200}
  - {id: went-well, title: What Went Well, kind: extraction}
  - {id: did-not-go-well, title: What Did Not Go Well, kind: extraction}
  - {id: root-causes, title: Root Causes, kind: extraction}
  - {id: improvements, title: Improvements to Try, kind: extraction}
  - {id: decisions, title: Decisions Made, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks, max_tokens: 1200}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are a facilitator recording a blameless retrospective. Describe what happened and what
people said, not who is at fault. Phrase problems about processes, tools and circumstances, not
individuals. Credit people for what went well when they were named. Keep what went well, what did
not, and root causes in separate sections: do not blur symptoms and causes. Only record a root
cause if the group named or clearly agreed on it.

<!-- mm3:prompt:summary -->
In 2-4 sentences, say what was reviewed (sprint, project, incident or period), the overall
mood, and the most important lesson. No bullet points.

<!-- mm3:prompt:summary-detailed -->
Write a detailed, blameless summary of the retrospective. First paragraph: what was
reviewed (sprint, project, incident or period) and the overall mood. Second paragraph: what
went well and what did not, crediting people for successes when they were named and
describing problems in terms of processes, tools and circumstances. Third paragraph: the
root causes the group named or agreed on, the improvements it chose, and what remains
unresolved. Never blame individuals.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines. No bullet points, numbered lists, headings or tables. Use only what was said in the
transcript and the names in the speaker list; never invent facts, names or numbers. Do not
repeat the short summary word for word: go deeper.

<!-- mm3:prompt:went-well -->
List what the participants said went well, one bullet each, crediting the people named.

Structure:
- <What went well> (<Name>) [mm:ss]

If nothing was mentioned, write exactly: No successes were mentioned.

<!-- mm3:prompt:did-not-go-well -->
List what did not go well, one bullet each: problems, delays, frustrations and mistakes.
Describe the situation, not the person. Do not list causes or fixes here.

Structure:
- <What went wrong, and its impact if stated> (<Name>) [mm:ss]

If nothing was mentioned, write exactly: No problems were mentioned.

<!-- mm3:prompt:root-causes -->
List the causes the group identified for the problems, linking each to the problem. Only
include causes that were stated or agreed; do not guess. Distinguish "agreed cause" from "one
person's theory".

Structure:
- **<Problem>:** <cause, and whether it was agreed or one person's view> [mm:ss]

If no causes were discussed, write exactly: No root causes were discussed.

<!-- mm3:prompt:improvements -->
List the improvements and experiments that were proposed, with who proposed them and whether
the group agreed.

Structure:
- **<Improvement>** (<Name>): <agreed, discussed, or only suggested> [mm:ss]

If none were proposed, write exactly: No improvements were proposed.

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
Give 2-4 recommendations, grounded only in the discussion: a problem that was raised but has
no proposed improvement, an improvement with no owner, a theme that appeared in several places,
or a lesson worth recording for future projects. Keep a blameless tone.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
