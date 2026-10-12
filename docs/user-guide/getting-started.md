# Getting started: from a recording to a note in your vault

Start the app and open <http://127.0.0.1:8765>:

```bash
uv sync --extra ml          # the transcription engine (see install-native.md)
uv run mm3 serve
```
Want to click through without models? `MM3_FAKE_PIPELINE=1 uv run mm3 serve` simulates every stage and writes a
real (placeholder) note into your vault.

## 1. Choose your vault (first run)
Type the folder of your Obsidian vault, the one that contains `.obsidian/`. The page checks it as you type: the
folder must exist and be writable (otherwise you get the reason and what to fix), and a missing `.obsidian/`
only shows a warning. The output folder accepts `{yyyy}`, `{mm}` and `{dd}`; the line below shows exactly where
the next note would go. *Save and continue* stores the choice in `config.yaml` and copies the starter templates
into the vault.

![Vault setup](../assets/01-setup.png)

## 2. New meeting
Pick or drop an audio or video file. The title, date and time are guessed from the file name and stay editable.
Then choose:
- **Template** (favourites first; invalid templates are listed but disabled, with the first problem).
- **Language model** and model. The badge says `local` or `cloud: <provider>`. Choosing a cloud backend opens a
  dialog explaining that the transcript text (not the audio) would be sent; *Use a local model* goes back.
- **Speakers**: separate speakers or not, and optionally the fewest and most speakers.
- **Hardware**: what was detected, the recommended Whisper model, and how long it should take for this file.
  *Advanced* lets you override the transcription model, compute type and batch size. Leave it alone to accept the
  recommendation, then press *Accept settings & start*.

![New meeting](../assets/02-new-meeting.png)

## 3. Progress
The job page lists every stage with a bar, message, time spent and an ETA, and updates by itself. You can reload
or close the tab; the page always shows the real state. *Cancel* stops the job (finished stages are kept and
*Resume* continues). If something fails you see what happened and what to do:
- **Retry**, or **Retry with smaller model** after a GPU out-of-memory error.
- "Transcription engine not installed" shows the install command.
- Warnings, such as speakers not separated because no Hugging Face token is set, appear in a yellow box.
- For a recording that does not sound like English you are asked whether to continue, treat it as English, or stop.

![Progress](../assets/03-progress.png)

## 4. Name the speakers
When the transcript is ready the job asks for names. Each speaker has a card with their talk time, up to three
audio samples to play, suggestions from remembered voices, a name field (with your known people offered as you
type), *Same person as…* to merge two voices, and, if voice recognition is enabled in the configuration, a
*Remember this voice* box (see [`speakers.md`](speakers.md) for what that stores). Leave a name empty to keep the
placeholder. You can still change the template here. *Confirm & write notes* resumes the job.

![Name speakers](../assets/04-name-speakers.png)

If the chosen backend is a cloud one and you did not agree in the dialog, the job pauses once more and asks
before anything is sent: *Allow*, *Use a local model instead* or *Don't send*.

## 5. Done
The completion box shows the note and transcript paths, an **Open in Obsidian** link and **Review & edit**, which
opens the review workspace: the recording and transcript side by side with the note, which you can edit,
regenerate section by section and save back to the vault. See [reviewing and editing](reviewing-and-editing.md).

![Done](../assets/05-done.png)

## Other pages
- **Recent** lists every job (resume interrupted ones, delete old ones) and the notes you wrote. A note that
  was deleted or moved, or that lies outside the vault you now use, is marked *File not found* or *Not in your
  vault*; **Remove from list** forgets one entry and the box above the list removes all such entries at once.
  Only the list entry goes: the app never deletes a note file from here, and an entry comes back when you open
  that note again.
- **Templates** shows the library and its editor; **Settings** covers the vault, models, backends, privacy and
  feedback.

## Troubleshooting
- *"The vault folder does not exist"*: mount the drive or fix the path on the setup page (`/setup`).
- *Upload rejected*: the limit is `audio.max_upload_mb` (default 2048).
- *The page does not update*: reload; if the server stopped, restart `mm3 serve` and resume the interrupted job
  from **Recent**.
