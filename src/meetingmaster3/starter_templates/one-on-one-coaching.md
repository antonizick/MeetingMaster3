---
mm3-template: 1
id: one-on-one-coaching
name: One-on-One & Coaching
description: Notes for a one-on-one or coaching conversation covering goals, progress, feedback, career topics and follow-ups, in a respectful tone.
tags: [people, coaching]
favorite: false
sections:
  - {id: summary, title: Summary, kind: narrative}
  - {id: goals-and-progress, title: Goals & Progress, kind: narrative}
  - {id: feedback, title: Feedback Shared, kind: extraction}
  - {id: challenges-and-support, title: Challenges & Support Needed, kind: extraction}
  - {id: career-topics, title: Career & Development, kind: extraction}
  - {id: action-items, title: Follow-ups, kind: extraction, format: tasks}
  - {id: next-steps, title: Next Steps, kind: extraction}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are writing notes of a one-on-one or coaching conversation that both people could read
and recognise as fair. Use a respectful, supportive and non-judgmental tone. Describe behaviour
and what was said, not character. Record feedback as it was given, and the person's own words for
how they feel. Do not diagnose, label or speculate about the person. Keep sensitive personal
matters (health, family, finances) out of the notes unless the person asked for them to be
recorded or they directly affect the work arrangement discussed; then record only what was agreed.

<!-- mm3:prompt:summary -->
In 2-4 sentences, say what the conversation covered and its overall tone, in neutral and kind
wording. No bullet points.

<!-- mm3:prompt:goals-and-progress -->
In a short paragraph or a few bullets, record the goals discussed (work, learning, wellbeing
at work) and the progress reported against them, as the person described it. Distinguish what
the person said from what the manager or coach said.

If no goals or progress were discussed, write exactly: Goals and progress were not discussed.

<!-- mm3:prompt:feedback -->
List feedback given in either direction (manager to report, report to manager, coach to
coachee), phrased in the giver's terms and, where possible, with the example they gave.

Structure:
- **<Giver> to <Receiver>:** <feedback, with the example or behaviour mentioned> [mm:ss]

If no feedback was given, write exactly: No feedback was shared.

<!-- mm3:prompt:challenges-and-support -->
List the difficulties the person raised about their work and the support they asked for or
were offered, in their own terms.

Structure:
- **<Challenge>:** <what was said>; support: <what was asked for or offered, or "not discussed"> [mm:ss]

If none were raised, write exactly: No challenges were raised.

<!-- mm3:prompt:career-topics -->
List career, growth and learning topics: aspirations, skills to build, opportunities, training,
role changes. Use the person's own wording and do not promise anything that was not promised.

Structure:
- **<Topic>:** <what was said, and any commitment made by the manager or coach> [mm:ss]

If none were discussed, write exactly: Career topics were not discussed.

<!-- mm3:prompt:action-items -->
List the follow-ups either person agreed to, one per line, whoever owns them.

Structure:
- [ ] **<Owner>:** <follow-up, starting with a verb> (due: <deadline as said, or "not stated">) [mm:ss]
- [ ] **Unassigned:** <follow-up both agreed is needed but nobody took on> (due: <...>) [mm:ss]

The owner is the person who said they will do the task ("I'll...", "I can...") or who was asked
and agreed. Raising an issue or saying "we should..." does not make someone the owner, and
neither does reporting on work that someone else (another team, a vendor) is doing: list such
tasks as **Unassigned:**. Give deadlines exactly as said ("Friday", "end of Q3"), not as dates.
If there are no tasks, write exactly: No follow-ups were agreed.

<!-- mm3:prompt:next-steps -->
State when the next one-on-one or check-in will be (date or time if said) and any topic
promised for it. If nothing was said, write exactly: No next steps were discussed.

<!-- mm3:prompt:ai-recommendations -->
Give 2-3 gentle suggestions for the next conversation, grounded only in what was said: a goal
without a stated next step, a concern that was raised but not followed up, or support that was
requested but not confirmed. Keep a supportive tone and do not evaluate the person.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
