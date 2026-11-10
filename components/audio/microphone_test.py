"""Sample the current microphone locally for the Sound window."""

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assistant"))
from voice import FRAME_BYTES, level_0_1, record_command, rms


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else None
    command = record_command(device=source or None)
    if not command:
        return 1
    try:
        result = subprocess.run(["timeout", "3s", *command], capture_output=True)
    except OSError:
        return 1
    if result.returncode not in (0, 124) or not result.stdout:
        return 1
    peak = max(rms(result.stdout[i:i + FRAME_BYTES])
               for i in range(0, len(result.stdout), FRAME_BYTES))
    print(round(level_0_1(peak) * 100))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
