# Importing a transcript or an AI conversation

A meeting doesn't have to start from a recording. MeetingMaster3 can start from a **text file**: a conversation with an AI assistant exported as Markdown, or a transcript made somewhere else. You check who said each turn, pick a template, and get an ordinary meeting: a note, a companion transcript and a readable transcript in your vault, an entry on the **Meetings** page, and full support for review, section regeneration, template switching, renaming, **Search** and **Ask-AI**. There is no audio, no transcription and no GPU step.

## How to import
1. Open **New meeting** and choose **Import a transcript or AI conversation** at the top.
2. Choose or drop the file (`.md`, `.txt`, `.vtt` or `.srt`, up to 10 MB; see `importing.max_mb`).
3. Optionally type a title. Left empty, the title comes from the file's first heading or its frontmatter `title:`, and otherwise from the file name. The date works the same way (the file's frontmatter `date:`, then a date in the file name, then today).
4. Put your name first under **Participants**. It names your side of an AI conversation (otherwise `importing.user_name`, by default "Me").
5. Pick the template, model and backend as for a recording. The same cloud consent applies: a cloud backend receives the imported text.
6. Choose **Accept settings & start**. A few seconds later the job pauses at **Who said what?** Choose **Check the speakers**.

### From a Grok share link
Instead of a file, you can paste the **share link** Grok gives you. In Grok, open the conversation, choose **Share** and copy the link (it looks like `https://x.com/i/grok/share/…` or `https://grok.com/share/…`). On New meeting, choose **Import a transcript or AI conversation** and paste it into **Or paste a Grok share link** (leave the file empty). A share link is the better choice when you have one: every message says who sent it and when, so the speakers are exact (nothing to fix) and the notes' `[mm:ss]` references point at the real moments of the conversation. Long voice-mode messages that Grok stored as growing copies are merged, as for a Markdown export.

**What is downloaded:** when you press **Accept settings & start**, MeetingMaster3 makes one HTTPS request to `grok.com` for that one shared conversation (the same thing your browser does when it opens the link). It sends the share's id, your IP address and a `MeetingMaster3` user agent; nothing from your vault, no cookies, no login. The conversation is saved in the job's folder as `source.json`, so resuming the job never downloads it again. Title, date and start time come from the conversation unless you typed them. Only Grok links are accepted; for ChatGPT, Claude and others, export the conversation to Markdown and upload the file.

From the command line:

```bash
mm3 import "privacy chat.md" --speaker user=Nick --speaker assistant=Grok --template default-notes --yes
mm3 import standup.vtt --title "Standup" --date 2026-10-20
mm3 import "https://x.com/i/grok/share/…" --speaker user=Nick --yes
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
| Grok share link (pasted, not a file) | `https://x.com/i/grok/share/…`, `https://grok.com/share/…` | Exact (from Grok) | Real (from each message) |
| WebVTT captions | `.vtt` with `<v Name>` voice tags or `Name:` prefixes | From the tags | Kept |
| SubRip subtitles | `.srt`, speaker from a `Name:` prefix | From the prefix, else none | Kept |

The format is recognised from the **content**, not from the file name. Markdown inside an AI answer (lists, code blocks, tables) is kept. Export chrome (Copy, Share, Regenerate, `2 / 2` counters) is dropped.

### Unlabelled conversations (Grok voice mode)
A voice-mode export has no speaker names and no times, and speech-to-text leaves **growing copies** of what you said (the same sentence two to five times, each copy longer). MeetingMaster3 keeps only the last, complete copy, ignoring punctuation and small recognition differences. Then it guesses each paragraph's speaker: fillers ("um", "uh"), repeated words, openings like "Okay, so…", "I…" and questions to the assistant point to you; em dashes, Markdown, long polished paragraphs, figures and "you/your" point to the assistant. A short "Checking current numbers." line joins the answer that follows it. The guess allows several assistant paragraphs in a row. On the synthetic test conversation, and on the real example it was built for, about 98 % of the paragraphs come out right before any fixes. Expect to fix a handful of turns on the check page.

## How to export a conversation
- **Grok:** export the conversation as Markdown, or copy it into a `.md` file. Voice-mode chats come out without speaker labels; that is fine. Or paste the conversation's **share link** instead (above): it gives exact speakers and times.
- **ChatGPT:** select the conversation and copy it into a `.md` file, or use a "save as Markdown" browser extension. The `You said:` / `ChatGPT said:` layout is recognised.
- **Claude:** copy the conversation (or use a Markdown export extension); `Human:` / `Claude:` and `## User` / `## Claude` headings both work.
- **Meeting tools:** download captions as `.vtt` or `.srt`, or a transcript as text with timestamps.

## From an AI conversation to a Claude Code project
If you worked out a project idea in a conversation with an AI assistant (or in a planning
meeting), MeetingMaster3 can turn it into a plan an engineering agent can start from:
1. Import the conversation (a Markdown export or a Grok share link, above) and check the speakers.
2. Pick the **Create Project Plan** template (or switch an existing note to it on the review page).
3. Hand the note to Claude Code: `/phased-project "<path to the note in your vault>" <repo dir>`.
   The phased-project skill reads it as its source document, reviews it, asks you the open
   questions and designs the phases.

The note keeps **your decisions** apart from what the AI only suggested, shows the options that
were discussed and why they were rejected, and lists every price, version, package name and other
figure the AI stated under **Facts to Verify**, marked unverified. Check those before you rely on
them: an AI assistant can be wrong, and the template does not check facts. Side questions that
don't change the plan are left out. MeetingMaster3's section markers and header do not get in the
agent's way; the note reads as plain Markdown.

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
| `E_IMPORT_URL_UNSUPPORTED` | Only Grok share links can be pasted (`https://x.com/i/grok/share/…`, `https://grok.com/share/…`, https only). For other links, export the conversation to Markdown and upload the file. |
| `E_IMPORT_SHARE_NOT_FOUND` "not shared publicly, or it was deleted" | Open the link in a private browser window. If it doesn't open there, share the conversation again in Grok (or export it to Markdown). |
| `E_IMPORT_SHARE_UNAVAILABLE` | Grok answered with something MeetingMaster3 cannot read; the share-link format is not documented by Grok and may have changed. Export the conversation to Markdown and upload the file, and please open an issue. |
| `E_IMPORT_OFFLINE` "Cannot reach grok.com" | Check the internet connection (and `HTTPS_PROXY` if you use a proxy; in Docker the container needs outbound HTTPS). File imports keep working offline. |
