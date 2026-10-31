# Roadmap

What is **not** in 0.1.0, and what is likely next. Nothing here is a promise or a date. If one of these
matters to you, open an issue and say so: that is how the order gets decided.

Items come from the specification (§12), the decisions log and the follow-ups recorded while building
0.1.0 (see [`MM3_IMPLEMENTATION_PLAN.md`](../MM3_IMPLEMENTATION_PLAN.md)). The product's limits today are also
listed under "Known limitations" in the [README](../README.md).

## Verification still wanted
- **Firefox and Safari.** The browser tests run in Chromium only; a click-through in other browsers, and a
  screen-reader pass, have not been done.
- **More hardware.** Only an 8 GB laptop GPU was measured. The 16 GB, 24 GB and CPU-only rows of the hardware
  table are estimates, and `generation.max_context` values above 16k are untested.
- **More recordings.** The voiceprint match threshold (0.6) was tuned on two recordings; it needs more and
  noisier audio.
- **Sleep and resume.** Suspending the machine in the middle of a job has not been tested.

## Likely next
- **Undo last rename.** One click to reverse *Title & date…* (the journal and backups already exist).
- **Cache map-reduce notes.** Regenerating one section of a long meeting repeats the whole map step; caching
  the map output would make it fast.
- **Auto-resume interrupted jobs.** Today you resume them yourself.
- **Better long-meeting recall.** Roughly one action item in sixteen and some questions are missed in
  3-hour meetings; segmented processing for very long recordings is part of this.
- **Reasoning-only and picky cloud models.** DeepSeek R1 and gpt-oss need their own request parameters;
  Mistral 7B and Mixtral on Bedrock reject system prompts; Fable 5.1 on Bedrock needs a data-retention setting
  the app does not send yet.
- **A "kept forever" marker** on rows in Meetings, and per-meeting retention periods.
- **Imported conversations** filtered apart from meetings in lists, and an optional LLM pass to assign roles
  in unlabelled chats.
- **Notifications** when a job finishes, and a favicon made from the logo.

## Later
- **Multi-language support:** templates and task-owner cues are English today; language detection looks at the
  first 30 seconds only.
- **Better speaker re-identification** and an enrolment UI; enrolling voiceprints after a rename; showing merged
  speaker labels as one turn.
- **Partial transcript editing and re-alignment.**
- **An Obsidian plugin** for tighter integration.
- **A feedback loop** that uses the collected ratings to improve templates.
- **Windows packaging** and a simple installer.
- **Additional backends:** native Anthropic and Google adapters (the OpenAI-compatible adapter already covers
  many servers).
- **Search at scale:** a vector extension or numpy once a vault passes about 20,000 passages (brute force takes
  about 340 ms at that size); indexing notes that MeetingMaster3 did not write; section anchors that open a
  search hit at its section.
- **Ask-AI:** a relevance check that resists decoy matches, and parallel reads for cloud backends.
- **Importing** ChatGPT or Claude share links (only Grok share links are supported).
- **Smaller engineering items:** build `JobRunner.describe()` without rebuilding the pipeline on every poll,
  bind `::1` as well as `127.0.0.1`, a lighter property-testing profile for CI, drop the
  `httpx` deprecation warning once Starlette's test client moves on, and a deterministic de-duplication of
  repeated list lines produced by small models.
