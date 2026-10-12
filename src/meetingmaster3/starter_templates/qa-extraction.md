---
mm3-template: 1
id: qa-extraction
name: Q&A Extraction
description: Extracts the questions asked and the answers given as a clean FAQ, and lists the questions left unanswered.
tags: [faq, reference]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1000}
  - {id: questions-and-answers, title: Questions & Answers, kind: extraction, max_tokens: 2400}
  - {id: unanswered, title: Unanswered Questions, kind: extraction}
  - {id: next-steps, title: Next Steps, kind: extraction}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

<!-- mm3:prompt:_system -->
You are turning a conversation into a clean FAQ that people can search later. Each entry has a
question stated clearly on its own (rewritten so it makes sense without the conversation) and the
answer actually given. Do not answer questions yourself, add outside knowledge, or merge distinct
questions. If an answer was partial, uncertain or contradicted, say so. Credit who asked and who
answered.

<!-- mm3:prompt:summary -->
In 1-3 sentences, say what the Q&A covered and how many questions were answered or left open.
No bullet points.

<!-- mm3:prompt:summary-detailed -->
Write a detailed summary of the question-and-answer session. First paragraph: what the
session covered, who was asking and who was answering. Second paragraph: the main themes
of the questions and the substance of the answers given, attributed to who gave them.
Third paragraph: the questions that were answered only partly, contradicted or left open.
Never answer a question yourself or add outside knowledge.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines, about 200-450 words in all. No bullet points, numbered lists, headings or tables. Use
only what was said in the transcript and the names in the speaker list; never invent facts,
names or numbers. Do not repeat the short summary word for word: go deeper.

<!-- mm3:prompt:questions-and-answers -->
List each question that was asked and answered, in the order asked. Rewrite the question so it
stands on its own. Give the answer in the answerer's terms, in 1-4 sentences, including figures,
names and conditions they gave. If the answer was uncertain, say so.

Structure:
**Q: <Question, standalone>** (<Name>) [mm:ss]
**A:** <Answer as given> (<Name>)

Keep the questions separate. Do not include questions that were answered only with "I don't know";
list those under Unanswered Questions.

If no questions were asked and answered, write exactly: No questions were answered.

<!-- mm3:prompt:unanswered -->
List the questions that were asked but not answered, or answered with "I don't know" or a
promise to follow up, with who is expected to answer if said.

Structure:
- **Q:** <Question, standalone> (<Name>) [mm:ss]; follow-up: <who, or "not stated">

If none, write exactly: No questions were left unanswered.

<!-- mm3:prompt:next-steps -->
List the follow-ups promised to answer open questions or to share material, with who owns
each and any date given. If none, write exactly: No next steps were discussed.

<!-- mm3:prompt:ai-recommendations -->
Give 2-3 suggestions, grounded only in the Q&A: questions that came up repeatedly and
deserve documentation, answers that were uncertain and need confirming, or unanswered questions
that block something.

Structure:
- **<Issue in a few words>:** <suggestion and why, referring to the discussion>
