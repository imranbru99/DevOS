#!/usr/bin/env python3
"""Durable microphone and speaker defaults for DevOS (recorder, calls, every app).

PipeWire/WirePlumber already remembers the last default node, but USB mics and
speakers often reappear under a new node name after unplug/replug or profile
changes. DevOS stores a stable identity (USB serial / bus-id / description) and
re-applies `pactl set-default-source` / `set-default-sink` / `wpctl set-default`
whenever that device returns so Chrome calls, voice typing, playback, and the
screen recorder all stay on the same devices.
"""
from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PREFS_PATH = Path.home() / ".config" / "DevOS" / "audio-defaults.json"
SYSTEM_PREFS = Path("/etc/devos/audio-defaults.json")


def _whicht(cmd: str) -> bool:
    from shutil import which
    return which(cmd) is not None


def _run(cmd: List[str], timeout: float = 4.0) -> Tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout)
        return 0, out
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        text = ""
        if isinstance(exc, subprocess.CalledProcessError) and exc.output:
            text = exc.output if isinstance(exc.output, str) else ""
        return 1, text


def load_preferences() -> Dict[str, Any]:
    for path in (PREFS_PATH, SYSTEM_PREFS):
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return {}


def save_preferences(prefs: Dict[str, Any]) -> Path:
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    prefs = dict(prefs)
    prefs["updated_at"] = int(time.time())
    PREFS_PATH.write_text(json.dumps(prefs, indent=2) + "\n", encoding="utf-8")
    return PREFS_PATH


def _parse_sources(text: str) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("Source #"):
            if current:
                sources.append(current)
            current = {"props": {}}
            continue
        if current is None:
            continue
        if line.startswith("\tName:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("\tDescription:"):
            current["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("\tMute:"):
            current["mute"] = line.split(":", 1)[1].strip().lower() == "yes"
        elif line.startswith("\tVolume:"):
            current["volume_line"] = line.split(":", 1)[1].strip()
        elif " = " in line and line.strip().startswith(("alsa.", "device.", "node.", "api.")):
            key, _, val = line.strip().partition(" = ")
            current["props"][key] = val.strip().strip('"')
    if current:
        sources.append(current)

    real: List[Dict[str, Any]] = []
    for src in sources:
        name = src.get("name") or ""
        props = src.get("props") or {}
        if not name or name.endswith(".monitor") or props.get("device.class") == "monitor":
            continue
        src["bus"] = props.get("device.bus") or ""
        src["serial"] = props.get("device.serial") or ""
        src["product"] = props.get("device.product.name") or props.get("node.nick") or src.get("description") or name
        src["card"] = props.get("alsa.card_name") or props.get("device.product.name") or ""
        src["form_factor"] = props.get("device.form_factor") or ""
        src["is_usb"] = (src["bus"] == "usb") or name.startswith("alsa_input.usb-")
        # Prefer dedicated mics over HDMI/monitor-ish names
        score = 10
        if src["is_usb"] or src["form_factor"] == "microphone":
            score += 100
        if "hdmi" in name.lower() or "monitor" in (src.get("description") or "").lower():
            score -= 50
        if "headphone" in (src.get("description") or "").lower():
            score += 20
        src["score"] = score
        real.append(src)
    real.sort(key=lambda s: (-s["score"], s.get("description") or s["name"]))
    return real


def list_input_sources() -> List[Dict[str, Any]]:
    if not _whicht("pactl"):
        return []
    rc, out = _run(["pactl", "list", "sources"])
    if rc != 0:
        return []
    return _parse_sources(out)


def _parse_sinks(text: str) -> List[Dict[str, Any]]:
    sinks: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("Sink #"):
            if current:
                sinks.append(current)
            current = {"props": {}}
            continue
        if current is None:
            continue
        if line.startswith("\tName:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("\tDescription:"):
            current["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("\tMute:"):
            current["mute"] = line.split(":", 1)[1].strip().lower() == "yes"
        elif line.startswith("\tVolume:"):
            current["volume_line"] = line.split(":", 1)[1].strip()
        elif " = " in line and line.strip().startswith(("alsa.", "device.", "node.", "api.")):
            key, _, val = line.strip().partition(" = ")
            current["props"][key] = val.strip().strip('"')
    if current:
        sinks.append(current)

    real: List[Dict[str, Any]] = []
    for sink in sinks:
        name = sink.get("name") or ""
        props = sink.get("props") or {}
        if not name:
            continue
        sink["bus"] = props.get("device.bus") or ""
        sink["serial"] = props.get("device.serial") or ""
        sink["product"] = props.get("device.product.name") or props.get("node.nick") or sink.get("description") or name
        sink["card"] = props.get("alsa.card_name") or props.get("device.product.name") or ""
        sink["form_factor"] = props.get("device.form_factor") or ""
        sink["is_usb"] = (sink["bus"] == "usb") or name.startswith("alsa_output.usb-")
        score = 10
        if sink["is_usb"] or sink["form_factor"] in ("speaker", "headset", "headphone"):
            score += 100
        desc = (sink.get("description") or "").lower()
        if "hdmi" in name.lower() or "displayport" in name.lower() or "hdmi" in desc or "displayport" in desc:
            score -= 80
        if "headphone" in desc or "headset" in desc:
            score += 20
        sink["score"] = score
        real.append(sink)
    real.sort(key=lambda s: (-s["score"], s.get("description") or s["name"]))
    return real


def list_output_sinks() -> List[Dict[str, Any]]:
    if not _whicht("pactl"):
        return []
    rc, out = _run(["pactl", "list", "sinks"])
    if rc != 0:
        return []
    return _parse_sinks(out)


def get_default_source() -> Optional[str]:
    if not _whicht("pactl"):
        return None
    rc, out = _run(["pactl", "get-default-source"])
    name = out.strip() if rc == 0 else ""
    return name or None


def get_default_sink() -> Optional[str]:
    if not _whicht("pactl"):
        return None
    rc, out = _run(["pactl", "get-default-sink"])
    name = out.strip() if rc == 0 else ""
    return name or None


def get_default_mic_label() -> str:
    name = get_default_source()
    if not name:
        return "No microphone"
    for src in list_input_sources():
        if src["name"] == name:
            return src.get("description") or src.get("product") or name
    return name


def get_default_speaker_label() -> str:
    name = get_default_sink()
    if not name:
        return "No speakers"
    for sink in list_output_sinks():
        if sink["name"] == name:
            return sink.get("description") or sink.get("product") or name
    return name


def _wpctl_id_for_name(node_name: str) -> Optional[str]:
    if not _whicht("wpctl"):
        return None
    rc, out = _run(["wpctl", "status"])
    if rc != 0:
        return None
    # Lines like: " *   57. USB Microphone Mono"
    # Better: inspect via pactl + wpctl inspect is heavy; use `pw-cli` if needed.
    rc2, dump = _run(["pw-cli", "list-objects"], timeout=6)
    if rc2 != 0:
        return None
    current_id = None
    for line in dump.splitlines():
        m = re.match(r"\s*id (\d+),", line)
        if m:
            current_id = m.group(1)
            continue
        if current_id and f'node.name = "{node_name}"' in line:
            return current_id
    return None


def set_default_source(name: str) -> bool:
    ok = False
    if _whicht("pactl"):
        rc, _ = _run(["pactl", "set-default-source", name])
        ok = rc == 0 or ok
    node_id = _wpctl_id_for_name(name)
    if node_id and _whicht("wpctl"):
        rc, _ = _run(["wpctl", "set-default", node_id])
        ok = rc == 0 or ok
    return ok or (get_default_source() == name)


def prefer_source(name: str, make_system_default: bool = True) -> Dict[str, Any]:
    """Remember this mic and optionally make it the PipeWire default for all apps."""
    match = next((s for s in list_input_sources() if s["name"] == name), None)
    prefs = load_preferences()
    prefs["preferred_source_name"] = name
    if match:
        prefs["preferred_serial"] = match.get("serial") or ""
        prefs["preferred_product"] = match.get("product") or match.get("description") or ""
        prefs["preferred_description"] = match.get("description") or ""
        prefs["preferred_is_usb"] = bool(match.get("is_usb"))
    path = save_preferences(prefs)
    applied = False
    if make_system_default:
        applied = set_default_source(name)
        ensure_source_ready(name)
    return {"ok": True, "prefs": path, "applied": applied, "source": name}


def find_preferred_source(sources: Optional[List[Dict[str, Any]]] = None, *,
                          allow_fallback: bool = True) -> Optional[Dict[str, Any]]:
    sources = sources if sources is not None else list_input_sources()
    if not sources:
        return None
    prefs = load_preferences()
    serial = (prefs.get("preferred_serial") or "").strip()
    product = (prefs.get("preferred_product") or "").strip().lower()
    desc = (prefs.get("preferred_description") or "").strip().lower()
    name = (prefs.get("preferred_source_name") or "").strip()

    if name:
        for s in sources:
            if s["name"] == name:
                return s
    if serial:
        for s in sources:
            if (s.get("serial") or "") == serial:
                return s
    if product:
        for s in sources:
            if product in (s.get("product") or "").lower() or product in (s.get("description") or "").lower():
                return s
    if desc:
        for s in sources:
            if desc in (s.get("description") or "").lower():
                return s
    # Auto-pick: USB / form-factor microphone first
    return sources[0] if allow_fallback else None


def restore_input() -> None:
    """Restore the chosen mic on reconnect without touching mute or gain."""
    sources = list_input_sources()
    chosen = find_preferred_source(sources, allow_fallback=False)
    if chosen is None and not load_preferences().get("preferred_source_name"):
        chosen = next((source for source in sources if source["is_usb"]), None)
    if chosen and chosen["name"] != get_default_source():
        set_default_source(chosen["name"])


def usb_input_status(sys_root: Path = Path("/sys")) -> str:
    """Describe how far a connected USB audio input got through the stack."""
    rc, output = _run(["pactl", "list", "sources"])
    if any(source["is_usb"] for source in _parse_sources(output)):
        return "A USB input is ready. Select it above, then test the microphone."
    for pcm in (sys_root / "class/sound").glob("pcmC*D*c"):
        if any((parent / "idVendor").is_file() for parent in pcm.resolve().parents):
            if rc:
                return "Linux detected a USB recording input, but the sound service is unavailable."
            return ("Linux detected a USB recording input. Open More volume settings → "
                    "Configuration and choose a USB profile with an input.")
    for interface in (sys_root / "bus/usb/devices").glob("*:*/bInterfaceClass"):
        try:
            if interface.read_text().strip().lower() == "01":
                return ("A USB audio device is connected, but Linux found no USB recording input. "
                        "Reconnect the microphone directly to another USB port.")
        except OSError:
            continue  # The device may have been unplugged during the check.
    return "No USB audio device detected. Check the cable and plug the microphone directly into another USB port."


def apply_preferred_source(auto_pick_usb: bool = True) -> Dict[str, Any]:
    """Re-apply saved (or best USB) mic as the system default. Safe to run on plug-in."""
    sources = list_input_sources()
    if not sources:
        return {"ok": False, "error": "no_input_sources"}
    prefs = load_preferences()
    chosen = find_preferred_source(sources)
    if chosen is None and auto_pick_usb:
        chosen = sources[0]
    if chosen is None:
        return {"ok": False, "error": "no_match"}
    # Persist identity when auto-picking a dedicated mic the first time
    if not prefs.get("preferred_serial") and not prefs.get("preferred_source_name"):
        if chosen.get("is_usb") or chosen.get("form_factor") == "microphone":
            prefer_source(chosen["name"], make_system_default=False)
    applied = set_default_source(chosen["name"])
    heal = ensure_source_ready(chosen["name"])
    return {
        "ok": applied,
        "source": chosen["name"],
        "description": chosen.get("description"),
        "heal": heal,
    }


def set_default_sink(name: str) -> bool:
    ok = False
    if _whicht("pactl"):
        rc, _ = _run(["pactl", "set-default-sink", name])
        ok = rc == 0 or ok
    node_id = _wpctl_id_for_name(name)
    if node_id and _whicht("wpctl"):
        rc, _ = _run(["wpctl", "set-default", node_id])
        ok = rc == 0 or ok
    return ok or (get_default_sink() == name)


def prefer_sink(name: str, make_system_default: bool = True) -> Dict[str, Any]:
    """Remember this speaker/headset and optionally make it the PipeWire default."""
    match = next((s for s in list_output_sinks() if s["name"] == name), None)
    prefs = load_preferences()
    prefs["preferred_sink_name"] = name
    if match:
        prefs["preferred_sink_serial"] = match.get("serial") or ""
        prefs["preferred_sink_product"] = match.get("product") or match.get("description") or ""
        prefs["preferred_sink_description"] = match.get("description") or ""
        prefs["preferred_sink_is_usb"] = bool(match.get("is_usb"))
    path = save_preferences(prefs)
    applied = False
    if make_system_default:
        applied = set_default_sink(name)
        ensure_sink_ready(name)
    return {"ok": True, "prefs": path, "applied": applied, "sink": name}


def find_preferred_sink(sinks: Optional[List[Dict[str, Any]]] = None, *,
                        allow_fallback: bool = True) -> Optional[Dict[str, Any]]:
    sinks = sinks if sinks is not None else list_output_sinks()
    if not sinks:
        return None
    prefs = load_preferences()
    serial = (prefs.get("preferred_sink_serial") or "").strip()
    product = (prefs.get("preferred_sink_product") or "").strip().lower()
    desc = (prefs.get("preferred_sink_description") or "").strip().lower()
    name = (prefs.get("preferred_sink_name") or "").strip()

    if name:
        for s in sinks:
            if s["name"] == name:
                return s
    if serial:
        for s in sinks:
            if (s.get("serial") or "") == serial:
                return s
    if product:
        for s in sinks:
            if product in (s.get("product") or "").lower() or product in (s.get("description") or "").lower():
                return s
    if desc:
        for s in sinks:
            if desc in (s.get("description") or "").lower():
                return s
    return sinks[0] if allow_fallback else None


def restore_output() -> None:
    """Return to a saved speaker when available, preserving volume and mute."""
    chosen = find_preferred_sink(allow_fallback=False)
    if chosen and chosen["name"] != get_default_sink():
        set_default_sink(chosen["name"])


def apply_preferred_sink(auto_pick_usb: bool = True) -> Dict[str, Any]:
    """Re-apply saved (or best USB/analog) speaker as the system default."""
    sinks = list_output_sinks()
    if not sinks:
        return {"ok": False, "error": "no_output_sinks"}
    prefs = load_preferences()
    chosen = find_preferred_sink(sinks)
    if chosen is None and auto_pick_usb:
        chosen = sinks[0]
    if chosen is None:
        return {"ok": False, "error": "no_match"}
    if not prefs.get("preferred_sink_serial") and not prefs.get("preferred_sink_name"):
        if chosen.get("is_usb") or chosen.get("form_factor") in ("speaker", "headset", "headphone"):
            prefer_sink(chosen["name"], make_system_default=False)
    applied = set_default_sink(chosen["name"])
    heal = ensure_sink_ready(chosen["name"])
    return {
        "ok": applied,
        "sink": chosen["name"],
        "description": chosen.get("description"),
        "heal": heal,
    }


def apply_preferred_devices(auto_pick_usb: bool = True) -> Dict[str, Any]:
    """Apply preferred mic and speakers together (login / USB sound hotplug)."""
    return {
        "source": apply_preferred_source(auto_pick_usb=auto_pick_usb),
        "sink": apply_preferred_sink(auto_pick_usb=auto_pick_usb),
    }


def ensure_sink_ready(name: Optional[str] = None) -> Dict[str, Any]:
    """Unmute and raise soft volume on the given sink."""
    name = name or get_default_sink()
    result = {"sink": name, "unmuted": False, "volume": False}
    if not name or not _whicht("pactl"):
        return result
    rc, _ = _run(["pactl", "set-sink-mute", name, "0"])
    result["unmuted"] = rc == 0
    rc, _ = _run(["pactl", "set-sink-volume", name, "100%"])
    result["volume"] = rc == 0
    node_id = _wpctl_id_for_name(name)
    if node_id and _whicht("wpctl"):
        _run(["wpctl", "set-mute", node_id, "0"])
        _run(["wpctl", "set-volume", node_id, "1.0"])
    return result


def ensure_source_ready(name: Optional[str] = None) -> Dict[str, Any]:
    """Unmute, raise soft volume, and poke ALSA capture for the given source."""
    name = name or get_default_source()
    result = {"source": name, "unmuted": False, "volume": False, "alsa": False}
    if not name or not _whicht("pactl"):
        return result
    rc, _ = _run(["pactl", "set-source-mute", name, "0"])
    result["unmuted"] = rc == 0
    # 100% soft volume; hardware gain stays with ALSA/WirePlumber routes
    rc, _ = _run(["pactl", "set-source-volume", name, "100%"])
    result["volume"] = rc == 0
    # ALSA card index from name when possible
    sources = {s["name"]: s for s in list_input_sources()}
    src = sources.get(name) or {}
    card = (src.get("props") or {}).get("alsa.card")
    if card is None:
        # Fall back to USB card 0 / first capture card from arecord -l is overkill;
        # parse "hw:N" from api.alsa.path when present.
        path = (src.get("props") or {}).get("api.alsa.path") or ""
        m = re.search(r"hw:(\d+)", path)
        if m:
            card = m.group(1)
    if card is not None and _whicht("amixer"):
        for control in ("Mic Capture", "Capture", "Mic", "PGA", "Digital", "ADC"):
            # Quote-free argv keeps spaces in control names intact
            rc1, _ = _run(["amixer", "-c", str(card), "-q", "sset", control, "unmute", "cap"], timeout=2)
            rc2, _ = _run(["amixer", "-c", str(card), "-q", "sset", control, "100%"], timeout=2)
            if rc1 == 0 or rc2 == 0:
                result["alsa"] = True
                break
        _run(["amixer", "-c", str(card), "-q", "sset", "Auto Gain Control", "on"], timeout=2)
    # Keep WirePlumber route unmuted if wpctl knows the node
    node_id = _wpctl_id_for_name(name)
    if node_id and _whicht("wpctl"):
        _run(["wpctl", "set-mute", node_id, "0"])
        _run(["wpctl", "set-volume", node_id, "1.0"])
    return result


def probe_source_signal(name: Optional[str] = None, seconds: float = 1.2) -> Dict[str, Any]:
    """Record a short clip from the source and return peak amplitude (0…32767)."""
    name = name or get_default_source()
    if not name:
        return {"ok": False, "error": "no_source", "peak": 0}
    fd, path = tempfile.mkstemp(prefix="devos-mic-probe-", suffix=".wav")
    os.close(fd)
    try:
        cmd: List[str]
        if _whicht("parecord"):
            cmd = ["parecord", "--device=" + name, "--channels=1", "--rate=48000",
                   "--file-format=wav", path]
        elif _whicht("pw-record"):
            cmd = ["pw-record", "--target=" + name, "--channels=1", "--rate=48000", path]
        else:
            return {"ok": False, "error": "no_recorder", "peak": 0}
        import signal as _signal
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(max(0.4, seconds))
        try:
            proc.send_signal(_signal.SIGINT)
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                proc.kill()
        peak = 0
        frames = 0
        if os.path.isfile(path) and os.path.getsize(path) > 1000:
            with wave.open(path, "rb") as wf:
                data = wf.readframes(wf.getnframes())
                frames = wf.getnframes()
                if data:
                    samples = struct.unpack("<" + "h" * (len(data) // 2), data)
                    peak = max((abs(s) for s in samples), default=0)
        return {"ok": True, "source": name, "peak": peak, "frames": frames, "path": path}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def format_source_choice(src: Dict[str, Any]) -> str:
    label = src.get("description") or src.get("product") or src["name"]
    tags = []
    if src.get("is_usb"):
        tags.append("USB")
    if src.get("form_factor") == "microphone":
        tags.append("Mic")
    if tags:
        return f"{label} ({', '.join(tags)})"
    return label


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="devos-audio-defaults",
                                     description="Manage DevOS default microphone and speakers for all apps")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list", help="list capture sources and output sinks")
    sub.add_parser("status", help="show default + saved preference")
    sub.add_parser("apply", help="apply saved/preferred mic and speakers as system defaults")
    sub.add_parser("restore-devices", help="restore preferred audio devices after reconnecting")
    sub.add_parser("check-usb-input", help="check USB microphone detection")
    p = sub.add_parser("prefer", help="remember a mic source and set it as system default")
    p.add_argument("source", nargs="?", help="PipeWire/Pulse source name (default: current)")
    ps = sub.add_parser("prefer-sink", help="remember a speaker sink and set it as system default")
    ps.add_argument("sink", nargs="?", help="PipeWire/Pulse sink name (default: current)")
    sub.add_parser("heal", help="unmute + raise gain on the default mic and speakers")
    probe = sub.add_parser("probe", help="measure a short peak from the mic")
    probe.add_argument("--seconds", type=float, default=1.2)
    args = parser.parse_args(argv)

    if args.cmd == "restore-devices":
        restore_input()
        restore_output()
        return 0
    if args.cmd == "check-usb-input":
        print(usb_input_status())
        return 0

    if args.cmd in (None, "status"):
        prefs = load_preferences()
        print(json.dumps({
            "default_source": get_default_source(),
            "default_label": get_default_mic_label(),
            "default_sink": get_default_sink(),
            "default_speaker_label": get_default_speaker_label(),
            "preferences": prefs,
            "sources": [{"name": s["name"], "description": s.get("description"),
                         "usb": s.get("is_usb"), "serial": s.get("serial")}
                        for s in list_input_sources()],
            "sinks": [{"name": s["name"], "description": s.get("description"),
                       "usb": s.get("is_usb"), "serial": s.get("serial")}
                      for s in list_output_sinks()],
        }, indent=2))
        return 0
    if args.cmd == "list":
        print("Sources:")
        for s in list_input_sources():
            mark = "*" if s["name"] == get_default_source() else " "
            print(f"{mark} {s['name']}\t{format_source_choice(s)}")
        print("Sinks:")
        for s in list_output_sinks():
            mark = "*" if s["name"] == get_default_sink() else " "
            print(f"{mark} {s['name']}\t{format_source_choice(s)}")
        return 0
    if args.cmd == "apply":
        print(json.dumps(apply_preferred_devices(), indent=2))
        return 0
    if args.cmd == "prefer":
        name = args.source or get_default_source()
        if not name:
            print("No source available", flush=True)
            return 1
        print(json.dumps(prefer_source(name), indent=2))
        return 0
    if args.cmd == "prefer-sink":
        name = args.sink or get_default_sink()
        if not name:
            print("No sink available", flush=True)
            return 1
        print(json.dumps(prefer_sink(name), indent=2))
        return 0
    if args.cmd == "heal":
        print(json.dumps({
            "source": ensure_source_ready(),
            "sink": ensure_sink_ready(),
        }, indent=2))
        return 0
    if args.cmd == "probe":
        ensure_source_ready()
        print(json.dumps(probe_source_signal(seconds=args.seconds), indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    # Fix signal import used in probe
    import signal as _signal  # noqa: F401
    raise SystemExit(main())
