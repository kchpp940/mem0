"""Core internal modules for the mem0 CLI engineering layers.

Modules:
    errors     — CLI exception hierarchy + HTTP/API error → user-friendly mapper
    options    — Option parsing, type coercion, and stdin/file reading helpers
    requests   — Backend request builders (turn CLI options into Backend kwargs)
    renderers  — Output renderers (text / table / json / quiet / agent-envelope)
    wrapper    — Unified CommandContext + execute() wrapper around all the above
"""
