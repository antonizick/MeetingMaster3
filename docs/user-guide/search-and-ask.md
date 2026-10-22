# Search and Ask

MeetingMaster3 keeps an index of every meeting in your vault so you can find what was discussed
**by meaning as well as by the words used**: "where did we spend more than planned?" finds the
meeting where someone said "the costs exceeded the forecast". The **Search** page and `mm3 search`
use it today; **Ask** (Phase 15j) will answer broad questions from the same index.

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
*Coming in Phase 15j:* broad questions ("how many times have we discussed X, who led those
discussions, and in which meetings?") answered from the meetings on file, with cited meetings and a
table of meetings, dates and attendees built from the files.
