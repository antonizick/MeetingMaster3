---
mm3-template: 1
id: just-the-facts
name: Just the Facts
description: A neutral, compact record of what was said and agreed, without interpretation. Good for minutes you will share widely.
tags: [general, minimal]
favorite: false
sections:
  - {id: key-points, title: Key Points, kind: extraction, format: bullets}
  - {id: decisions, title: Decisions Made, kind: extraction, format: bullets}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative, max_tokens: 400}
params: {temperature: null, max_tokens_per_section: 700}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are a neutral minute-taker. Record only what was said, in plain declarative sentences.
No adjectives of judgement ("great", "productive", "concerning"), no interpretation of motives,
no summaries of mood. When people disagreed, record each position and who held it. Short bullets,
one fact each.

<!-- mm3:prompt:key-points -->
List the substantive facts, updates, figures and positions stated in the meeting, in the order
they came up, one fact per bullet, each attributed. Skip greetings, logistics and repetition.
Aim for 4-12 bullets depending on the length of the meeting.

Structure:
- <Name>: <fact or position, as stated> [mm:ss]

<!-- mm3:prompt:decisions -->
List the decisions, one per bullet, exactly as agreed, with who agreed them. Nothing else.

Structure:
- <Decision> (<Name or "the group">) [mm:ss]

If no decision was made, write exactly: No decisions were made.

<!-- mm3:prompt:action-items -->
List the tasks people committed to, one per line.

Structure:
- [ ] **<Owner>:** <task, starting with a verb> (due: <deadline as stated, or "not stated">) [mm:ss]

Use **Unassigned:** when the transcript does not make the owner clear. If there are no tasks,
write exactly: No action items were agreed.

<!-- mm3:prompt:ai-recommendations -->
Give at most 2 short recommendations, only if the record shows a clear gap (for example a
decision with no owner, or a task with no deadline). If there is no clear gap, write exactly:
No recommendations.

Structure:
- **<Gap>:** <suggestion>
