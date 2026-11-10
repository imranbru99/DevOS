"""DevOS audio/video helpers — mic, speaker, and camera discovery."""
from .camera_defaults import (  # noqa: F401
    camera_summary,
    has_camera,
    list_cameras,
)
from .mic_defaults import (  # noqa: F401
    apply_preferred_devices,
    apply_preferred_sink,
    apply_preferred_source,
    ensure_sink_ready,
    ensure_source_ready,
    get_default_sink,
    get_default_source,
    list_input_sources,
    list_output_sinks,
    load_preferences,
    prefer_sink,
    prefer_source,
    probe_source_signal,
    save_preferences,
)
