# Importing a transcript or an AI conversation

A meeting doesn't have to start from a recording. MeetingMaster3 can start from a **text file**: a conversation with an AI assistant exported as Markdown, or a transcript made somewhere else. You check who said each turn, pick a template, and get an ordinary meeting: a note, a companion transcript and a readable transcript in your vault, an entry on the **Meetings** page, and full support for review, section regeneration, template switching, renaming, **Search** and **Ask-AI**. There is no audio, no transcription and no GPU step.

## How to import
1. Open **New meeting** and choose **Import a transcript or AI conversation** at the top.
2. Choose or drop the file (`.md`, `.txt`, `.vtt` or `.srt`, up to 10 MB; see `importing.max_mb`).
3. Optionally type a title. Left empty, the title comes from the file's first heading or its frontmatter `title:`, and otherwise from the file name. The date works the same way (the file's frontmatter `date:`, then a date in the file name, then today).
4. Put your name first under **Participants**. It names your side of an AI conversation (otherwise `importing.user_name`, by default "Me").
5. Pick the template, model and backend as for a recording. The same cloud consent applies: a cloud backend receives the imported text.
6. Choose **Accept settings & start**. A few seconds later the job pauses at **Who said what?** Choose **Check the speakers**.

From the command line:

```bash
mm3 import "privacy chat.md" --speaker user=Nick --speaker assistant=Grok --template default-notes --yes
mm3 import standup.vtt --title "Standup" --date 2026-10-20
```

`--speaker` takes `user=…` and `assistant=…` for AI conversations, or a label such as `SPEAKER_00=Alice`. `--yes` accepts the speakers as detected; without it, `mm3 import` asks on a terminal, and otherwise stops with a hint.

## Checking who said what
The check page lists every turn (the first 200, then **Show all**), with the speaker's name as a button:

- **Press the name** (or focus it and press Enter or Space) to give the turn to the other speaker. With three or more speakers, it moves to the next one.
- Turns marked **check** (highlighted) are the ones MeetingMaster3 guessed with low confidence. Look at those first.
- Type the speakers' names at the top. Every turn's button follows.
- Pick the template, then **Confirm & write notes**.

The server checks every change (an unknown speaker or turn is refused).

## Supported files

| What | Looks like | Speakers | Times |
|---|---|---|---|
| AI conversation, labelled | `## User` / `## Assistant`, `**You:**`, `User:` / `Grok:` / `ChatGPT:` / `Claude:` lines, ChatGPT's `You said:` / `ChatGPT said:`, or a person's `Name:` that repeats | From the labels | None |
| AI conversation, unlabelled (Grok voice mode) | Paragraphs separated by blank lines, nothing saying who spoke | Guessed (see below) | None |
| Timestamped transcript | `[00:01:02] Alice: text`, `**[00:01:02] Alice:** text`, `[01:02] text` | From the line | Kept |
| MeetingMaster3 `.txt` export, Otter or Plaud style | `00:04 Alice` (or `Alice 00:00:04`) on one line, the text below | From the line | Kept |
| MeetingMaster3 companion | `….transcript.md` written by MeetingMaster3 | Exact | Exact (with word timings) |
| WebVTT captions | `.vtt` with `<v Name>` voice tags or `Name:` prefixes | From the tags | Kept |
| SubRip subtitles | `.srt`, speaker from a `Name:` prefix | From the prefix, else none | Kept |

The format is recognised from the **content**, not from the file name. Markdown inside an AI answer (lists, code blocks, tables) is kept. Export chrome (Copy, Share, Regenerate, `2 / 2` counters) is dropped.

### Unlabelled conversations (Grok voice mode)
A voice-mode export has no speaker names and no times, and speech-to-text leaves **growing copies** of what you said (the same sentence two to five times, each copy longer). MeetingMaster3 keeps only the last, complete copy, ignoring punctuation and small recognition differences. Then it guesses each paragraph's speaker: fillers ("um", "uh"), repeated words, openings like "Okay, so…", "I…" and questions to the assistant point to you; em dashes, Markdown, long polished paragraphs, figures and "you/your" point to the assistant. A short "Checking current numbers." line joins the answer that follows it. The guess allows several assistant paragraphs in a row. On the synthetic test conversation, and on the real example it was built for, about 98 % of the paragraphs come out right before any fixes. Expect to fix a handful of turns on the check page.

## How to export a conversation
- **Grok:** export the conversation as Markdown, or copy it into a `.md` file. Voice-mode chats come out without speaker labels; that is fine. A Grok **share link** can be imported directly from Phase 15l on.
- **ChatGPT:** select the conversation and copy it into a `.md` file, or use a "save as Markdown" browser extension. The `You said:` / `ChatGPT said:` layout is recognised.
- **Claude:** copy the conversation (or use a Markdown export extension); `Human:` / `Claude:` and `## User` / `## Claude` headings both work.
- **Meeting tools:** download captions as `.vtt` or `.srt`, or a transcript as text with timestamps.

## What is and isn't kept
- **No invented times.** An AI conversation has no times, so the transcript is marked untimed: no clocks in the companion, the readable transcript, the review page or Search results, no "Length" line, and the notes carry no `[mm:ss]` references (they are removed even if the model writes one).
- **Times are kept** for timestamped transcripts, so clicking a line or a `[mm:ss]` in the note jumps to that moment in the transcript (there's no player).
- The note's frontmatter says where it came from: `mm3-source: import` and `mm3-source-format` (for example `chat-unlabelled`). The review page shows **Imported from …**.
- **No audio:** *Keep forever*, retention and *Transcribe the recording again* don't apply.
- The original file stays in the job's folder in the app data (`<data>/jobs/<id>/source.<ext>`) until you delete the job. It is never copied into the vault.
- Text you import goes to the language model like a transcript. A cloud backend needs your consent, as for recordings.

## Troubleshooting
| Message | What to do |
|---|---|
| `E_IMPORT_UNREADABLE` "That file is not text" | You chose a recording or a binary file. Use **Record or upload audio** for recordings. |
| `E_IMPORT_UNREADABLE` "not UTF-8 text" | Re-save the file as UTF-8. |
| `E_IMPORT_TOO_LARGE` | Split the conversation, or raise `importing.max_mb`. |
| `E_IMPORT_EMPTY` | The file has no conversation text. |
| Every turn has the same speaker | The file may be labelled in a way MeetingMaster3 does not recognise. Fix the turns on the check page, and open an issue with a synthetic example. |

See also: [`reviewing-and-editing.md`](reviewing-and-editing.md), [`search-and-ask.md`](search-and-ask.md), [`configuration.md`](configuration.md) (`importing.*`).
