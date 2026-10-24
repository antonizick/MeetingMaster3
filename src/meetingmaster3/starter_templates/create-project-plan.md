---
mm3-template: 1
id: create-project-plan
name: Create Project Plan
description: Turns a planning conversation with an AI assistant, or a planning meeting, into a pre-plan to hand to an engineering agent (for example Claude Code's /phased-project). Goal, constraints, requirements, the owner's decisions kept apart from the AI's suggestions, options considered, the proposed solution, rough phases, risks, facts to verify, open questions, definition of done and next steps.
tags: [project, planning]
favorite: false
sections:
  - {id: summary, title: Summary Succinct, kind: narrative, max_tokens: 200}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1000}
  - {id: project-goal, title: Goal and Success Criteria, kind: extraction, max_tokens: 500}
  - {id: context-constraints, title: Context and Constraints, kind: extraction, max_tokens: 600}
  - {id: requirements, title: Requirements, kind: extraction, max_tokens: 700}
  - {id: decisions, title: Decisions Made, kind: extraction, max_tokens: 800}
  - {id: options-considered, title: Options Considered, kind: extraction, max_tokens: 1000}
  - {id: solution-outline, title: Proposed Solution, kind: narrative, max_tokens: 700}
  - {id: milestones, title: Rough Phases, kind: extraction, max_tokens: 700}
  - {id: risks, title: Risks and Mitigations, kind: extraction, max_tokens: 600}
  - {id: facts-to-verify, title: Facts to Verify, kind: extraction, max_tokens: 1200}
  - {id: open-questions, title: Open Questions for the Owner, kind: extraction, max_tokens: 600}
  - {id: acceptance, title: Definition of Done, kind: extraction, max_tokens: 500}
  - {id: action-items, title: Next Steps, kind: extraction, format: tasks, max_tokens: 700}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative, max_tokens: 600}
params: {temperature: null, max_tokens_per_section: 800, detail: high, task_candidates: relevant}
---
MeetingMaster3 starter template. Copy it to make your own: change the id and the name, then
edit the sections and the prompt blocks below. Format: docs/dev-guide/template-format.md.

The note is a pre-plan: a source document for an engineering agent that will review it, ask the
owner the open questions and design the detailed phases (for example
`/phased-project "<note path>" <repo dir>` in Claude Code).

<!-- mm3:prompt:_system -->
You are a senior technical project planner. You turn a working conversation into a pre-plan: a
source document that an engineering agent, who has not seen the conversation, will review and
refine into a detailed project plan. The conversation is either a person working out an idea
with an AI assistant, or a planning meeting between people. A participant is an AI assistant
when its name is one (for example Grok, ChatGPT, Claude, Gemini, Copilot, Assistant or AI) or it
plainly answers as one. The owner is the person whose project it is: in a conversation with an
AI assistant, the human participant; in a meeting, the people who make the decisions. Call the
source "the conversation", never "the meeting", when one participant is an AI assistant.

Authority. The owner's own statements (goals, constraints, preferences, exclusions, choices)
are the plan. Everything the AI assistant says is a proposal or a claim. Never present an
assistant suggestion as decided unless the owner agreed to it ("that sounds like a good plan",
"let's do that", repeating it as their own plan). A question the owner asked is not a decision,
and neither is the assistant's answer to it.

Facts. Keep the specifics: names of products, tools, packages, versions, commands, settings,
prices, figures and dates. Every specific external claim the plan relies on (a price, a version,
a package or repository name, a limit, a count, a date, a survey or test result, a legal or
security claim) is unverified until checked: list it under Facts to Verify with who stated it.
Never invent a requirement, a phase, a number or a fact that was not said.

Focus. Leave out side questions and digressions that do not change the plan (background
explanations, curiosity questions, history of a company or a technology), small talk, and
how the conversation itself went. Write plainly and concretely, in the third person, using the
participants' names.

<!-- mm3:prompt:summary -->
In one or two sentences (at most 50 words in all), say what the owner wants to build or set up
and the approach chosen. If no approach was chosen, say what is still being decided. No bullet
points.

<!-- mm3:prompt:summary-detailed -->
Write a detailed summary that briefs an engineer who will plan the work. First paragraph: the
problem the owner wants solved and why, and what they care about most. Second paragraph: how the
approach was worked out: the alternatives that were discussed, what the owner learned or
objected to, and why some options fell away, attributed to the person who said it. Third
paragraph: where it landed: the chosen approach, the main steps, and what is still open or
needs checking.

Write prose only: typically three paragraphs and never fewer than two, separated by blank
lines, about 200-450 words in all. No bullet points, numbered lists, headings or tables. Use
only what was said in the transcript and the names in the speaker list; never invent facts,
names or numbers. Do not repeat the short summary word for word: go deeper.

<!-- mm3:prompt:project-goal -->
State the goal of the project as the owner described it, and how success will be judged. Use
the owner's own words for their priorities, for example a stated "north star" or quality bar.
Success criteria proposed only by the AI assistant count only if the owner agreed with them;
mark them "(proposed by <Name>, agreed by <Owner>)".

Structure:
- **Problem:** <what the owner wants solved, and why>
- **Desired outcome:** <the end result the owner wants>
- **Priority:** <what the owner said matters most>
- **Success criteria:**
  - <criterion, as stated or agreed>

If a line was not discussed, leave it out. Never fill a line from general knowledge.

<!-- mm3:prompt:context-constraints -->
List the facts about the owner's situation and the limits they set, as they stated them:
environment (operating system, devices, existing services and accounts), skills and time,
budget, preferences, and things they want to avoid or ruled out. One fact per bullet, grouped
under bold labels; use only the labels that apply. Constraints the AI assistant assumed but the
owner never stated do not belong here.

Structure:
- **Environment:** <operating system, hardware, existing services, as stated>
- **Budget:** <as stated>
- **Preferences:** <what the owner prefers, and why if said>
- **Exclusions:** <what the owner does not want, and why if said>

If the owner stated no constraints, write exactly: No constraints were stated.

<!-- mm3:prompt:requirements -->
List what the result must do, grouped as **Must**, **Should** and **Won't**. A requirement
comes from what the owner asked for, insisted on or accepted; a Won't comes from what they
excluded or rejected. Each requirement is one line, specific and testable where the conversation
allows ("loads a local HTML file", not "is easy to use"). Do not add requirements that were not
discussed.

Structure:
**Must**
- <requirement> (<who stated or accepted it>)
**Should**
- <requirement> (<who stated or accepted it>)
**Won't**
- <excluded thing> (<reason given>)

Leave out a group that has no items. If no requirements were discussed, write exactly: No
requirements were stated.

<!-- mm3:prompt:decisions -->
List only the decisions the owner made or clearly agreed to, in the order they were made, each
with its reason. A suggestion from the AI assistant becomes a decision only when the owner
accepted it; then say so. A suggestion the owner did not take up, an option still being
compared, a question the owner asked and an answer the assistant gave are not decisions: leave
them out (they belong under Options Considered or Open Questions). Task assignments are not
decisions either.

Structure:
1. **<Decision, stated as an outcome>** [mm:ss]
   - **Reason:** <the reason given, or "not stated">
   - **Decided by:** <Name>, <"on their own" or "accepting <Name>'s suggestion">

If nothing was decided, write exactly: No decisions were made.

<!-- mm3:prompt:options-considered -->
List the alternatives that were discussed for the main choices, including the owner's first
idea if they had one, with the pros and cons that were given and the outcome: **Chosen**,
**Rejected** (with the reason) or **Open**. Use a table. Attribute a pro or con to the person
who gave it when that matters. Only options that were actually discussed; never add one.

Structure:
| Option | Pros | Cons | Outcome |
|---|---|---|---|
| <option> | <pros given> | <cons given> | <Chosen / Rejected: reason / Open> |

If only one approach was ever discussed, write exactly: No alternatives were discussed.

<!-- mm3:prompt:solution-outline -->
Describe the chosen approach as an engineer would need it: the components or products, what each
one does, how they fit together, and the specific tools, packages, settings and commands that
were named. Write 1-3 short paragraphs, then, if useful, a bullet list of components:

- **<Component>:** <role in the solution; how it is installed, configured or built, as said>

Describe only what the owner chose or agreed to. If no approach was chosen, describe the leading
options in one sentence each and say that the choice is open.

<!-- mm3:prompt:milestones -->
Write the rough phases of the work as an ordered, numbered list of 3-8 milestones, in the order
the work would be done, derived from the steps that were discussed. Each milestone is a short
title and one sentence on its outcome (what exists or works when it is done). Group small steps
into one milestone. Do not invent work that was not discussed, and do not write detailed tasks:
the engineering agent will plan those.

Structure:
1. **<Milestone title>:** <outcome when done>
2. **<Milestone title>:** <outcome when done>

If the conversation did not get as far as steps, write exactly: No phases were discussed yet.

<!-- mm3:prompt:risks -->
List the risks, limitations and pitfalls that were raised for the chosen approach, each with the
mitigation that was discussed, or "none discussed". Attribute each to the person who raised it.
Leave out risks of the options that were rejected.

Structure:
- **<Risk in a few words>:** <what could go wrong and why> (raised by <Name>). **Mitigation:**
  <as discussed, or "none discussed">

If no risks were raised, write exactly: No risks were raised.

<!-- mm3:prompt:facts-to-verify -->
List every specific factual claim made in the conversation that the plan or the owner's choice
relies on and that should be checked before acting on it: prices and payment terms, versions,
package, repository and command names, where software is available, counts and sizes, dates of
changes, test or survey results, speeds, and legal or security claims. Most will have been
stated by the AI assistant. Keep the exact figures and names as said. Each line says who stated
it and is marked unverified. Do not judge whether a claim is true, and do not add claims of
your own.

Structure:
- <claim, with the exact figure or name as stated> (stated by <Name>; unverified) [mm:ss]

List the claims that matter most to the plan first. If no checkable claims were made, write
exactly: No specific claims need checking.

<!-- mm3:prompt:open-questions -->
List the decisions the owner still has to make, phrased as questions to the owner, each with the
options that were discussed and any recommendation that was made (and by whom). Include choices
the owner left open or deferred and important points the conversation never settled. Do not
list questions the owner asked that were already answered.

Structure:
- **<Question to the owner>?** Options discussed: <option A>, <option B>. <Name> recommended
  <option>, if anyone did.

If nothing is left open, write exactly: No open questions remain.

<!-- mm3:prompt:acceptance -->
List how the owner will know the result works: the tests, checks and observable results that
were mentioned or agreed, one per line, each specific enough to perform ("run <tool or site> and
confirm <result>"). Say who proposed each check. If the owner agreed to it, say so.

Structure:
- <check to perform and the expected result> (proposed by <Name><, agreed by <Owner>>)

If no checks were discussed, write exactly: No acceptance checks were discussed.

<!-- mm3:prompt:action-items -->
List the owner's immediate next steps to start the work, one per line, in the order they would
be done. A step belongs here only if the owner said they will do it ("I need to...", "I'll...",
"will do") or a participant agreed to take it on. Steps the AI assistant only suggested and the
owner did not take up go under **Unassigned:** and end with "(suggested by <Name>)". The AI
assistant is never the owner of a step.

Structure:
- [ ] **<Owner>:** <step, starting with a verb> (due: <deadline as said, or "not stated">) [mm:ss]
- [ ] **Unassigned:** <step suggested but not taken up> (suggested by <Name>) (due: <...>) [mm:ss]

Give deadlines exactly as said, not as dates. Put the **Unassigned:** steps last. If no steps
were discussed, write exactly: No action items were agreed.

<!-- mm3:prompt:ai-recommendations -->
Give 2-4 points the engineering agent should look at when it reviews this plan, grounded only in
the conversation: a requirement that is vague or untestable, a decision taken on an unverified
claim, a constraint that conflicts with the chosen approach, a missing piece (security, backup,
updates, cost) that was not discussed, or a step without a clear order.

Structure (replace everything in angle brackets with your own words):
- **<Issue in a few words>:** <what to check and why, referring to the conversation>
