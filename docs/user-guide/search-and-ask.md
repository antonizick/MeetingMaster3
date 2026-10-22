# Search and Ask

MeetingMaster3 keeps an index of every meeting in your vault so you can find what was discussed
**by meaning as well as by the words used**: "where did we spend more than planned?" finds the
meeting where someone said "the costs exceeded the forecast". The **Search** page and `mm3 search`
find passages; the **Ask** page and `mm3 ask` answer broad questions from the same index, with
the meetings cited and a table built from the files.

## What is indexed
- Every **meeting note** MeetingMaster3 wrote (files with an `mm3-id` property), section by
  section. The *AI Recommendations* section is left out: it is the model's advice, not what was said.
  Your own text outside the sections is indexed too.
- Every **companion transcript** (`.transcript.md`), in windows of about 350 tokens with the time and
  the speakers' names (as you named them in *Rename speakers*). Turn this off with
  *Index the transcripts too* in Settings → Search & Ask.
- Not indexed: readable transcripts (`(Transcript).md`), archived versions, Ask answers, notes
  MeetingMaster3 did not write, hidden folders (`.obsidian`, `.trash`) and anything a symbolic link
  points to outside the vault.

The index lives in the app's data folder, **not in your vault**: `~/.local/share/meetingmaster3/search.db`
(Docker: the `/data` volume). It is derived data: deleting it loses nothing, and *Update index*
builds it again from the vault.

## Keeping it current
You do not have to do anything. The index is updated:
- when the app starts (in the background; the app is usable at once),
- a few seconds after MeetingMaster3 writes or changes a meeting (a new note, a save, a template
  switch, a regenerated section, a rename or re-date, an upgrade),
- every 10 minutes, and when you search if the last check is more than a minute old, for notes you
  edit or delete in Obsidian (`search.rescan_minutes`).

An update reads only files that changed (unchanged files cost one look at their size and time). A
note that only moved keeps its index entry; editing one section re-embeds only that section.

**It never slows a transcription down.** With the local embedder, indexing uses the graphics card
only while no meeting is being processed, in batches of a fraction of a second, and the embedding
model unloads itself shortly after.

## The embedding model
Meaning search needs an *embedding model*, which turns each passage into a list of numbers that
captures what it is about. The default is **`nomic-embed-text`** in your local Ollama (Apache-2.0,
274 MB). Install it once:

```bash
ollama pull nomic-embed-text
```

With Docker and the bundled Ollama: `docker compose exec ollama ollama pull nomic-embed-text`.

Without it (or with Ollama stopped) search still works **by words only**, and the page says so.
`mm3 llm test` tells you whether the model is available.

Other embedders (Settings → Search & Ask → *Embedding backend* and *Embedding model*):

| Backend | Model | Notes |
|---|---|---|
| Ollama (local, default) | `nomic-embed-text` | Nothing leaves this computer. `bge-m3`, `mxbai-embed-large` and `qwen3-embedding` work too. |
| AWS Bedrock | `amazon.titan-embed-text-v2:0` (or `cohere.embed-english-v3`) | Enable access to the model in the Bedrock console; the IAM policy in [llm-backends.md](llm-backends.md) already allows `bedrock:InvokeModel`. |
| OpenRouter | e.g. `openai/text-embedding-3-small` | OpenRouter serves embeddings at `/embeddings` (checked in Phase 15i). |
| OpenAI-compatible servers | the server's embedding model | LM Studio, vLLM and OpenAI serve `/embeddings`; a server without it is reported as "does not offer embeddings". |

Changing the model re-embeds every passage at the next update (a few minutes for a large vault).
Vectors of two models are never mixed.

### Cloud embedders need their own permission
Indexing with a cloud embedder **sends the full text of every meeting** (notes and transcripts) to
that provider, and every search sends your query. That is much more than writing one meeting's
notes, so it has its own switch: Settings → Language models → edit the backend → *Allow search
indexing with this backend's embeddings*. Remembering consent for notes does not cover it. Without
the switch nothing is sent and search uses words only. *Revoke consent* turns both off.

## Searching
Open **Search** in the navigation, type a question or some words and press Enter.

- Results are grouped by **meeting** (best first), with up to four matching passages each and the
  matched words highlighted. The badge says how the search ran: *meaning + words*, *words only*
  (meaning search unavailable, with the reason) or *meaning only* (your words were all common ones).
  A second badge says where meaning search ran: *local* or *cloud: …*.
- Click a meeting to open it; click a **transcript passage** to open the meeting **at that moment**
  (the transcript scrolls to it and the player is set there).
- **Filters:** a date range and a person (a participant or a named speaker; part of a name is
  enough).
- Any text is safe to type: quotes, `*`, `-`, `NEAR` or `:` are searched as plain words.

### From the command line
```bash
mm3 search "where did we spend more than planned"        # grouped results
mm3 search "budget" --from 2026-09-01 --person Dana --json
mm3 search index            # update now (add --rebuild to start from scratch)
mm3 search status           # meetings, passages, model, last update
```

`mm3 search index` waits while the server is processing a meeting, like the server does.

## Settings → Search & Ask
Shows the embedder, how many meetings and passages are indexed (and how many have meaning
vectors), the file size, the last update and any problem (for example "the embedding model is not
installed"). Buttons:

- **Update index**: bring it up to date now.
- **Rebuild index**: start from scratch (after changing the passage size, or if something looks
  wrong).
- **Delete index**: remove `search.db` and turn indexing off. Your notes are not touched. *Update
  index* turns it back on.

## Privacy
The index holds copies of the text of your meeting notes and transcripts, with titles, dates,
participants and speaker names. It stays on this computer in the app's data folder (mode 0600).
Nothing is sent anywhere unless you choose a cloud embedder and allow it. See [PRIVACY.md](../PRIVACY.md).

## Ask
**Ask** (in the navigation, or `mm3 ask`) answers broad questions from the meetings on file, for
example:

> How many times have we discussed the vendor contract? Who was principally in those discussions
> and what was their role? Also make a table of all the meetings, their dates and the attendees.

### How it answers
1. **Plans searches.** The model turns your question into a few short searches (other words for
   the topic, names, projects). If you name a time ("since September", "last quarter") it may also
   limit the dates.
2. **Searches** the index by meaning and by words for each search, and collects the matching
   meetings (at most *Most meetings read per question*, 25 by default; the answer says when more
   matched).
3. **Reads each meeting**: one model call per meeting with its title, date, participants and named
   speakers, its *Meeting Context* section when the note has one (people's stated roles), and the
   matching passages of the note and transcript with the passages around them. The model says
   whether the meeting discusses the topic (in depth, briefly or not at all), what it says, who took
   part and in what role, and quotes a few lines.
4. If fewer than two meetings turned out to be relevant, it **searches once more** with what it has
   learned (never more than once).
5. **Writes the answer** from those findings, citing meetings as links.

What you can trust: **which meetings, how many, their dates and attendees come from the files**,
not from the model. The table of meetings is built by MeetingMaster3; a person is listed only if
they appear in what the model read, a quote only if it is word for word in the meeting, and a link
to a meeting the model was not shown is removed (the answer's *How this was answered* section lists
any). The model decides which meetings are relevant and writes the narrative, so read the answer
like a colleague's summary and open the cited meetings for the detail.

### Asking good questions
- Name the topic in a few words, as people would have said it: "the vendor contract renewal",
  "hiring backend engineers", "the login outage".
- Say what you want: a count, the people and their roles, a table, a timeline, a short summary.
- Limit it when you can: the *Limit to dates or a person* fields always apply; a date in the
  question is used too.
- Follow up from an answer with **Ask a follow-up**: the earlier question and its findings are given
  to the new one. **Ask again** re-asks the same question against the current meetings.

### What is sent where
- **Local model** (Ollama, the default): nothing leaves this computer. Each meeting read is one
  call, about 10-40 s with `qwen3:8b` on an 8 GB GPU (see [PERFORMANCE.md](../PERFORMANCE.md)). Like
  indexing, Ask waits while a meeting is being transcribed and never runs a call next to one.
- **Cloud model** (Bedrock, OpenRouter, another OpenAI-compatible server): your question and the
  **excerpts of up to 25 meetings** (the matching passages, names, dates and Meeting Context) are
  sent to the provider. The Ask page says so before you send and shows an estimated cost when the
  model's price is known. You must tick **Send the excerpts to … for this question** each time,
  unless you turned on **Always allow Ask AI agent to send meeting excerpts to this backend** in
  Settings → Language models → edit the backend. Remembering consent for writing notes does **not**
  cover Ask, and Ask's switch does not cover notes. *Revoke consent* turns all of them off.
  `mm3 ask --allow-cloud` is the per-question consent on the command line.
- The question is also embedded for the meaning search, by the search embedder (local by default;
  a cloud embedder needs its own permission, see above).

### Where answers are kept
Every answer is saved automatically as a note in your vault, in **`MM3 Answers/`** (Settings →
Search & Ask → *Answers folder*), named `2026-10-22 1530 - How many times have we discussed….md`.
The note has the question, the answer, the table of meetings, a *People* table, *Sources* (one line
per meeting with why it was relevant and links to the moments in MeetingMaster3) and *How this
was answered* (the searches, the meetings read, the model, the time). Its properties are
`mm3-kind: answer`, `mm3-answer-id`, `question`, `asked`, `mm3-backend`, `mm3-model`,
`mm3-sources` (links to the meetings) and the tag `mm3/answer`.

- **In Obsidian**: the answers folder, the `#mm3/answer` tag, and each meeting's **backlinks** pane,
  which lists the answers that cite it. Meeting notes are never edited.
- **In MeetingMaster3**: the Ask page lists every answer, newest first; each answer opens in the
  app with its meeting links going to the meetings' review pages (*Open in Obsidian* opens the
  note). A meeting's review page lists **Answers that cite this meeting**.
- Renaming or re-dating a meeting (*Title & date…*) updates the links in answer notes too.
- Moving or renaming an answer note in Obsidian is fine: MeetingMaster3 finds it again by its
  `mm3-answer-id`. If it was deleted, the answer shows **File not found** with **Forget**.
- Turn off *Keep every answer* to have answers shown once and not saved anywhere.

### Deleting answers
Open the answer and choose **Delete… → Delete the answer**: the note is removed from the vault and
the answer from the list (it cannot be undone). Deleting the note in Obsidian and then choosing
**Forget** does the same. Answers are not indexed for search, so nothing else holds a copy.

### From the command line
```bash
mm3 ask "Who discussed the budget overrun, and in what role?"      # prints the answer and table
mm3 ask "What did we decide about the launch date?" --from 2026-09-01 --person Mei
mm3 ask "..." --backend bedrock --model us.anthropic.claude-haiku-5-5 --allow-cloud
mm3 ask "..." --no-save --json                                       # nothing saved; JSON output
```
