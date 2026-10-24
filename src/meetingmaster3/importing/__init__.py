"""Import a transcript or an AI conversation from a text file (Phase 15k, spec R32).

:func:`detect_and_parse` turns the bytes of a file into an :class:`ImportedConversation`;
:func:`~meetingmaster3.importing.convert.to_transcript` turns that into the
:class:`~meetingmaster3.domain.transcript.Transcript` the rest of the pipeline uses. The ``import``
job runs ``import_parse`` → ``await_speaker_confirmation`` → ``generate`` → ``write``
(:mod:`meetingmaster3.importing.stages`). See ``docs/dev-guide/importing.md``.
"""

from meetingmaster3.importing.detect import PARSERS, decode, detect, detect_and_parse
from meetingmaster3.importing.model import (
    E_IMPORT_EMPTY,
    E_IMPORT_TOO_LARGE,
    E_IMPORT_UNREADABLE,
    FORMAT_NAMES,
    ImportedConversation,
    ImportedTurn,
    format_name,
)

__all__ = [
    "E_IMPORT_EMPTY",
    "E_IMPORT_TOO_LARGE",
    "E_IMPORT_UNREADABLE",
    "FORMAT_NAMES",
    "PARSERS",
    "ImportedConversation",
    "ImportedTurn",
    "decode",
    "detect",
    "detect_and_parse",
    "format_name",
]
