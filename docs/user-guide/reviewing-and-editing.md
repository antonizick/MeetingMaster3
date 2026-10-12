# Reviewing and editing a note

The review workspace is where a draft becomes your final note. It shows the recording and its
transcript on the left and the note on the right. Open it with **Review & edit** when a meeting
finishes, from **Recent**, or from **Open a note**.

![The review workspace](../assets/06-review-workspace.png)

## Opening a note

- **After processing:** the job page's **Review & edit** button.
- **Open a note** (top menu): your recent notes, plus a browser of your vault. The browser lists only
  notes MeetingMaster3 wrote (files with an `mm3-id` property). Companion transcripts and archived
  versions are hidden, as are hidden folders such as `.obsidian`. You cannot browse outside the vault.
- A note that was not written by MeetingMaster3 opens as a read-only preview.

The address of the workspace is `/meetings/<mm3-id>`, so a bookmark keeps working after you rename or
move the note, as long as you have opened it once from its new place (or from **Open a note**).

## The recording and the transcript

| Action | How |
|---|---|
| Play / pause | ▶ button, or <kbd>Space</kbd> or <kbd>K</kbd> |
| Back / forward 5 seconds | −5 s / +5 s, or <kbd>J</kbd> / <kbd>L</kbd> |
| Speed | 0.75× to 2× |
| Jump to a moment | Click a timestamp or any word in the transcript |
| Jump from the note | In **Preview**, click a `[mm:ss]` reference; in the editor, <kbd>Ctrl</kbd>/<kbd>⌘</kbd>-click it |
| Find text | The search box; <kbd>Enter</kbd> / <kbd>Shift</kbd>+<kbd>Enter</kbd> for next / previous |

The keyboard shortcuts do nothing while you are typing in a field. The sentence being played is
highlighted and kept in view. Scrolling the transcript yourself turns **Follow** off; tick it to
follow the playback again. Drag the bar between the panes (or focus it and use the arrow keys) to
change their widths; on a narrow screen the panes stack.

If the recording was removed by the retention policy (see [configuration](configuration.md), `privacy.*`),
the player is replaced by a notice. The transcript still works.

## Editing the note

The note is shown in parts:

- **Properties:** the note's Obsidian properties (YAML), folded by default. Keep `mm3-id`: it links the
  note to its transcript and recording, and saving refuses a change to it.
- **Your own text** (dashed boxes): the title and header, and anything you write between or after
  the sections. MeetingMaster3 never rewrites this text.
- **Sections** (framed): the parts MeetingMaster3 generated, each between two marker lines such as
  `<!-- mm3:section:summary -->`. The markers are shown dimmed and cannot be edited here: they are
  how MeetingMaster3 finds a section again. Everything between them (the `## Heading` and the text)
  is yours to edit.

**Save to vault** (or <kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>S</kbd>) writes the note atomically. Only the parts
you changed differ from the file on disk; every other byte stays as it was, including Windows line
endings.

Your unsaved edits are kept as a draft in MeetingMaster3's data folder while you type. If you close
the tab without saving, the next time you open the note it offers **Restore my edits** or **Discard
them**.

**Preview** shows the note rendered (raw HTML is not rendered; images are not loaded).

### When the note changed elsewhere

If the file was changed after you opened it (in Obsidian, by a sync tool, or in another tab), saving
does not overwrite it. You see both versions side by side and choose:

- **Keep mine:** overwrite the vault file with your version.
- **Take theirs:** discard your edits and reload the note from the vault.
- **Keep editing:** copy what you need from the comparison into your version, then save and keep mine.

## Regenerating a section

Each section has **Regenerate…**. Add instructions if you like ("Make it shorter", "Focus on the
budget") and, under **Model**, pick another backend or model. A cloud backend asks for your consent
for this request. The new version is compared with the section as it is in the editor now (your
unsaved edits included). Switch between **Side by side** and **Unified** views, then:

- **Accept:** replace the section in the editor.
- **Accept & archive previous:** first save the current version of the section to the archive (below),
  then replace it.
- **Discard:** keep the section as it is.

![A regenerated section with its diff](../assets/07-review-regenerate.png)

Accepting changes only the editor; **Save to vault** to keep the result.

### Archives

Archived versions go to an `Archive` folder next to the note:

- One section: `Archive/2026-10-11 - Title.<section-id>.20261011-1530.md`
- A whole note (template switch): `Archive/2026-10-11 - Title.20261011-1530.md`

Archives carry an `mm3-archived` property, so they are not offered by **Open a note**.

## Switching the template

**Switch template…** writes the whole note again with another template (this takes as long as
writing the notes did the first time). You see the new note compared with the current one before
anything is written. Applying it archives the current note whole, then writes the new one. Anything
you wrote outside the sections is kept at the end of the new note under **Preserved notes**, and your
own properties (for example `aliases`) are kept. Save your edits first: switching works on the note as
saved in the vault.

## Renaming speakers

**Rename speakers…** lists the speakers of the transcript. Change a name, or empty it to go back to
"Speaker N", and preview the changes. Applying them updates:

- the companion transcript (the names on each turn and its `mm3-speakers` property);
- the note's `mm3-speakers` and `participants` (people you added to `participants` by hand are kept);
- the **Participants** line under the title, unless you edited that line;
- names inside the generated sections (whole words only).

Your own text outside the sections is not changed. Renaming does not teach voice recognition the new
name: the voice samples of a meeting are deleted when its speakers are first confirmed (see
[speakers](speakers.md)).

## When something is missing or damaged

| Situation | What you see | What you can do |
|---|---|---|
| The companion transcript is missing | The note opens with "Transcript not found"; regeneration, template switching and renaming are off | **Locate the transcript**: it is searched for in the whole vault. If it is next to the note under another name, **Link this transcript**; if it is elsewhere, move it next to the note. If the recording is still kept, **Transcribe the recording again** (this writes a new note). |
| A section's markers are damaged (for example a closing marker was deleted in Obsidian) | A warning naming the problem; the damaged text is shown as your own text and is never guessed at | **Append a fresh “…” section** writes a new copy of that section (as `<id>-2`) before AI Recommendations; delete the damaged text yourself when you are happy |
| The note has no MeetingMaster3 markers at all | A read-only view | Edit it in Obsidian |
| The recording was deleted by retention | A notice instead of the player | Everything else works |

If an edit in your own text adds, removes or changes a marker line (for example while repairing a damaged
section), saving asks you to confirm. A marker typed inside a section is refused.

See also: [getting started](getting-started.md), [templates](templates.md), [speakers](speakers.md).
