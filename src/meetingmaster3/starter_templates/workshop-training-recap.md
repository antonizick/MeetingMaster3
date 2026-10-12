---
mm3-template: 1
id: workshop-training-recap
name: Workshop & Training Recap
description: Recap of a workshop or training session covering the concepts taught, exercises, learnings, questions and how to apply them.
tags: [learning, training]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1000}
  - {id: concepts, title: Concepts Covered, kind: extraction, max_tokens: 1500}
  - {id: exercises, title: Exercises & Activities, kind: extraction}
  - {id: learnings, title: Key Learnings, kind: extraction}
  - {id: questions, title: Questions Raised, kind: extraction}
  - {id: applications, title: Applying It, kind: extraction}
  - {id: next-steps, title: Next Steps, kind: extraction}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are a participant writing a recap that a colleague who missed the session could learn
from. Explain the ideas as they were taught, in the trainer's terms and with the examples and
figures given. Keep the trainer's statements separate from participants' comments. Do not add
knowledge from outside the session and do not correct the trainer.

<!-- mm3:prompt:summary -->
In 3-4 sentences, say what the workshop or training was about, who ran it, and what participants
should now be able to do. No bullet points.

<!-- mm3:prompt:summary-detailed -->
Write a detailed recap that a colleague who missed the session could learn from. First
paragraph: the topic, who ran it and its aims. Second paragraph: the main ideas as they
were taught, in the trainer's terms, with the examples and figures given. Third paragraph:
the questions and comments from participants, what participants should now be able to do,
and any follow-up material or exercises mentioned. Do not add outside knowledge.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines, about 200-450 words in all. No bullet points, numbered lists, headings or tables. Use
only what was said in the transcript and the names in the speaker list; never invent facts,
names or numbers. Do not repeat the short summary word for word: go deeper.

<!-- mm3:prompt:concepts -->
List the concepts, techniques, rules or frameworks that were taught, in the order they were taught.
For each, give a bold name and 1-3 sentences explaining it as it was explained, with any example
the trainer used.

Structure:
- **<Concept>** [mm:ss]: <explanation as taught, with the trainer's example>

If nothing was taught, write exactly: No concepts were covered.

<!-- mm3:prompt:exercises -->
List the exercises, demos, discussions and breakout activities, with what participants did
and what came out of each, if said.

Structure:
- **<Activity>** [mm:ss]: <what participants did; outcome or debrief points>

If there were none, write exactly: No exercises were run.

<!-- mm3:prompt:learnings -->
List the main takeaways, as the trainer or participants put them: the points they stressed,
the mistakes to avoid and the rules of thumb. One bullet each, with who said it.

Structure:
- <Takeaway> (<Name>) [mm:ss]

If none were stated, write exactly: No key learnings were stated.

<!-- mm3:prompt:questions -->
List the questions participants asked and the answers given. If a question was not answered,
say so.

Structure:
- **Q:** <question> (<Name>) [mm:ss]
  **A:** <answer given, or "not answered">

If no questions were asked, write exactly: No questions were asked.

<!-- mm3:prompt:applications -->
List how participants said they would use what they learned, or how the trainer suggested
applying it, in their own terms. Do not invent applications.

Structure:
- <Application> (<Name>) [mm:ss]

If none were mentioned, write exactly: No applications were discussed.

<!-- mm3:prompt:next-steps -->
List follow-up material, practice, homework, further sessions or resources mentioned, and any
date given. If none were mentioned, write exactly: No next steps were discussed.

<!-- mm3:prompt:ai-recommendations -->
Give 2-3 suggestions for consolidating the learning, grounded only in the session: a
concept that drew many questions and may need revisiting, an exercise worth repeating, or a
practical application that was mentioned but not planned. Do not add new teaching content.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
