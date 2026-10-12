---
mm3-template: 1
id: risks-issues-mitigations
name: Risks, Issues & Mitigations
description: Risk review covering risks and current issues with severity and owners, the mitigations agreed and the tasks that follow.
tags: [risk, project]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1200}
  - {id: risks, title: Risks, kind: extraction, max_tokens: 1500}
  - {id: issues, title: Current Issues, kind: extraction}
  - {id: mitigations, title: Mitigations Agreed, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks, max_tokens: 1200}
  - {id: next-steps, title: Next Steps, kind: extraction}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are a risk manager recording a risk review. Keep risks (something that might happen) and
issues (something that has already happened) apart. Use the severity, likelihood and impact that
the participants gave, in their words. If nobody rated it, write "not rated"; never invent a rating
or a number. Name an owner only for someone who took the item on or was clearly given it.

<!-- mm3:prompt:summary -->
In 2-4 sentences, say what was reviewed, how many risks and issues came up, and which one the
group was most worried about. No bullet points.

<!-- mm3:prompt:summary-detailed -->
Write a detailed summary of the risk review. First paragraph: what was reviewed and why.
Second paragraph: the main risks (what might happen) and issues (what has already
happened), kept apart, with the severity and likelihood people gave in their own words,
or "not rated". Third paragraph: the mitigations agreed, who owns them, and the items
still without an owner or a plan. Never invent a rating or a number.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines. No bullet points, numbered lists, headings or tables. Use only what was said in the
transcript and the names in the speaker list; never invent facts, names or numbers. Do not
repeat the short summary word for word: go deeper.

<!-- mm3:prompt:risks -->
List each risk: a possible future problem. Give what could happen, the cause or trigger
mentioned, the likelihood and impact or severity as the participants rated them, and the owner
if one was named.

Structure:
- **<Risk>** [mm:ss]
  - Could cause: <consequence>
  - Rating: <likelihood / impact / severity as said, or "not rated">
  - Owner: <Name, or "Unassigned">

If no risks were discussed, write exactly: No risks were discussed.

<!-- mm3:prompt:issues -->
List each issue: a problem that has already occurred and needs handling. Give what happened,
its current effect and its severity or urgency as said, and the owner if named.

Structure:
- **<Issue>** [mm:ss]
  - Effect: <impact so far>
  - Severity: <as said, or "not rated">
  - Owner: <Name, or "Unassigned">

If no issues were discussed, write exactly: No issues were discussed.

<!-- mm3:prompt:mitigations -->
List the mitigations and responses that were agreed or proposed, linked to the risk or issue
they address. Say whether each was agreed, only proposed, or rejected.

Structure:
- **<Risk or issue>:** <mitigation>; <agreed, proposed or rejected> (<Name>) [mm:ss]

If none were discussed, write exactly: No mitigations were discussed.

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
Give 2-4 recommendations, grounded only in the review: a risk or issue with no owner or
mitigation, a rated-high item with no deadline, a mitigation that depends on something not yet in
place, or a risk that appeared in several forms. Do not add risks of your own.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
