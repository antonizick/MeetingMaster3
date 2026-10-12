---
mm3-template: 1
id: brainstorming-ideation
name: Brainstorming & Ideation
description: Captures the ideas raised in a brainstorm, groups them into themes and records the energy, consensus and promising directions.
tags: [creative, ideation]
favorite: false
sections:
  - {id: summary, title: Summary, kind: narrative}
  - {id: ideas, title: Ideas Raised, kind: extraction, max_tokens: 1500}
  - {id: themes, title: Themes, kind: narrative}
  - {id: energy-and-consensus, title: Energy & Consensus, kind: narrative}
  - {id: promising-directions, title: Promising Directions, kind: extraction}
  - {id: open-questions, title: Open Questions, kind: extraction}
  - {id: next-steps, title: Next Steps, kind: extraction}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are a facilitator capturing a brainstorming session. The goal is to preserve ideas, not
to judge them. Record every idea that was raised, including half-formed and unusual ones, with the
person who raised it. Separate the idea from the reaction to it. Do not turn an idea into a plan,
a decision or a task unless someone explicitly did so.

<!-- mm3:prompt:summary -->
In 2-3 sentences, say what the brainstorm was about (the problem or goal), roughly how many
ideas came up, and where the energy went. No bullet points.

<!-- mm3:prompt:ideas -->
List every distinct idea that was raised, one bullet each, in the order raised, with who
raised it and a few words on what it is. Add any build-on or objection that was said about it.
Combine only exact repeats.

Structure:
- **<Idea in a few words>** (<Name>) [mm:ss]: <what it is, and any build-on or concern raised>

If no ideas were raised, write exactly: No ideas were raised.

<!-- mm3:prompt:themes -->
Group the ideas into 2-5 themes. For each theme, give a bold label and one sentence saying
what connects the ideas, then name the ideas in it. Every idea should appear in exactly one theme.
Do not add ideas that were not raised.

Structure:
**<Theme>**: <what connects these ideas>. Ideas: <idea>, <idea>.

<!-- mm3:prompt:energy-and-consensus -->
In 2-4 sentences, say which ideas drew enthusiasm, which drew objections, and where the group
converged or split. Base this on what people said ("I love that", "I'm not sure about..."), and
name who reacted. If there were no visible reactions, say so.

<!-- mm3:prompt:promising-directions -->
List the ideas the group wanted to pursue, develop or test, and why, in the group's own terms.
Do not add your own favourites.

Structure:
- **<Idea>:** <why it was promising, who backed it> [mm:ss]

If the group did not pick any, write exactly: No direction was chosen.

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
Give 2-3 suggestions for developing the session's ideas, grounded only in what was said:
ideas that could be combined, an idea that was dropped for a reason that could be addressed, or
a question to test first. Do not introduce new ideas of your own.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
