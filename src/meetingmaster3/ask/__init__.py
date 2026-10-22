"""The Ask AI agent: broad questions answered from the meetings on file (Phase 15j, R31).

Modules: ``schema`` (the model's JSON, validated), ``prompts``, ``pipeline`` (plan → retrieve →
read each meeting → optional follow-up → code-built facts → answer), ``notes`` (the answer note
in the vault), ``store`` (the history in ``mm3.db``) and ``service`` (the app-wide service).
"""
