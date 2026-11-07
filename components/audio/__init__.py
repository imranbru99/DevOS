"""DevOS audio helpers — microphone discovery and durable system defaults."""
from .mic_defaults import (  # noqa: F401
    apply_preferred_source,
    ensure_source_ready,
    get_default_source,
    list_input_sources,
    load_preferences,
    prefer_source,
    probe_source_signal,
    save_preferences,
)
