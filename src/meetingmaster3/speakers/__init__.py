"""Speaker naming: embeddings, the opt-in voiceprint store, matching and the name cascade.

Nothing here imports an ML library at module level. :mod:`.embeddings` loads pyannote lazily;
:mod:`.vectors`, :mod:`.match`, :mod:`.store` and :mod:`.cascade` are pure Python (no numpy), so
the app and the unit tests run without the ``ml`` extra.
"""
