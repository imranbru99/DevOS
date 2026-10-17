#!/usr/bin/env python3
"""
devos-ai-models: choose, download and remove DevOS AI models, and switch the
local AI API between "this PC only" and "my network".

  devos-ai-models hw                 hardware + recommended model (JSON)
  devos-ai-models list               every model, whether it fits and is installed
  devos-ai-models status             current choice and download state (JSON)
  devos-ai-models choose medium [--vision] [--coder] [--no-download]
  devos-ai-models download           fetch what was chosen (prints [Downloading] lines)
  devos-ai-models user-extras        per-user pieces (photo understanding), run at sign-in
  devos-ai-models remove large       delete a downloaded model
  devos-ai-models api                show the API address, key and examples
  devos-ai-models api lan on|off     share the API with phones/PCs on this network
  devos-ai-models api new-key        replace the API key

The installer page writes the choice into the new system with "choose ...
--no-download"; devos-ai-models.service then downloads it once the PC is online.
"""

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import model_catalog as catalog  # noqa: E402

API_CONF = "/etc/devos/ai-api.conf"
API_PORT = 11434
SERVICE_LINK = "/etc/systemd/system/multi-user.target.wants/devos-ai-models.service"
SERVICE_UNIT = "/etc/systemd/system/devos-ai-models.service"


# ---------------------------------------------------------------- hardware

def ram_gb() -> float:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1048576, 1)
    except (OSError, ValueError, IndexError):
        pass
    return 4.0


def largest_disk_gb() -> float:
    """At install time the target disk is not chosen yet: use the biggest one."""
    try:
        out = subprocess.run(["lsblk", "-dbno", "SIZE,TYPE,RM"], capture_output=True, text=True,
                             timeout=5).stdout
        sizes = [int(p[0]) for p in (l.split() for l in out.splitlines())
                 if len(p) >= 3 and p[1] == "disk" and p[2] == "0"]
        if sizes:
            return round(max(sizes) / 1e9, 1)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0.0


def free_disk_gb(path: str = "/var/lib") -> float:
    try:
        return round(shutil.disk_usage(path).free / 1e9, 1)
    except OSError:
        return 0.0


def gpu_name() -> str:
    try:
        out = subprocess.run(["lspci", "-mm"], capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines():
            if ("VGA" in line or "3D" in line or "Display" in line) and line.count('"') >= 6:
                parts = line.split('"')
                return f"{parts[3]} {parts[5]}".strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def cpu_name() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return " ".join(line.split(":", 1)[1].split())
    except OSError:
        pass
    return ""


def hardware(installer: bool = False) -> dict:
    disk = largest_disk_gb() if installer else free_disk_gb()
    return hardware_info(ram_gb(), os.cpu_count() or 2, cpu_name(), gpu_name(), disk, installer)


def hardware_info(ram: float, threads: int, cpu: str, gpu: str, disk: float, installer: bool) -> dict:
    # Leave room for DevOS itself (~12 GB) on an empty target disk.
    disk_for_models = max(disk - 12, 0) if installer else disk
    return {
        "ram_gb": ram,
        "threads": threads,
        "cpu": cpu,
        "gpu": gpu,
        "disk_gb": disk,
        "recommended": catalog.recommend(ram, threads, disk_for_models or None),
        "recommended_extras": catalog.recommend_extras(ram),
        "models": [dict(m, fits=catalog.fits(m, ram, threads, disk_for_models or None))
                   for m in catalog.CHAT_MODELS],
        "extras": [dict(e, fits=ram + 0.5 >= e["min_ram_gb"]) for e in catalog.EXTRAS],
        "built_in_skills": catalog.BUILT_IN_SKILLS,
    }


# ---------------------------------------------------------------- choice

def wanted_files(choice: dict) -> list:
    """(file, url, size_mb) that the system-wide model folder must hold."""
    files = []
    chat = catalog.chat_model(choice["chat"])
    if chat and not chat.get("built_in"):
        files.append((chat["file"], chat["url"], chat["size_mb"]))
    if choice.get("coder"):
        coder = catalog.coder_for(choice["chat"])
        files.append((coder["file"], coder["url"], coder["size_mb"]))
    return files


def write_choice(choice: dict, path: str = catalog.CHOICE_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(catalog.format_choice(choice))
    os.chmod(path, 0o644)


def enable_download_service() -> None:
    """Start the download at every boot until it finishes. A plain link works in
    the installer's chroot, where systemctl cannot talk to systemd."""
    if os.path.exists(SERVICE_UNIT):
        os.makedirs(os.path.dirname(SERVICE_LINK), exist_ok=True)
        if not os.path.lexists(SERVICE_LINK):
            os.symlink(SERVICE_UNIT, SERVICE_LINK)


def disable_download_service() -> None:
    try:
        os.remove(SERVICE_LINK)
    except OSError:
        pass


# ---------------------------------------------------------------- download

def _gguf(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(4) == b"GGUF"
    except OSError:
        return False


def download_file(name: str, url: str, size_mb: int, dest_dir: str = catalog.MODELS_DIR,
                  opener=urllib.request.urlopen, out=sys.stdout) -> bool:
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    if catalog.installed_file(name, [dest_dir]):
        return True
    part = dest + ".partial"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if free_disk_gb(dest_dir) * 1024 < (size_mb - have / 1048576) + 1024:
        print(f"Not enough free space for {name} ({size_mb} MB).", file=sys.stderr)
        return False
    req = urllib.request.Request(url, headers={"User-Agent": "DevOS-AI/1.0"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    last = 0.0
    try:
        with opener(req, timeout=60) as resp:
            if have and getattr(resp, "status", 200) != 206:
                have = 0
            length = int(resp.headers.get("Content-Length") or 0)
            total = (have + length) if length else size_mb * 1048576
            with open(part, "ab" if have else "wb") as handle:
                done = have
                while True:
                    block = resp.read(1024 * 1024)
                    if not block:
                        break
                    handle.write(block)
                    done += len(block)
                    if time.time() - last >= 1:
                        last = time.time()
                        # Same format as devos-ai-upgrade: the AI window turns it into a bar.
                        print(f"[Downloading] {done / 1048576:.1f} MB/{total / 1048576:.1f} MB", file=out, flush=True)
    except OSError as exc:
        print(f"The download stopped ({getattr(exc, 'reason', exc)}). It continues next time.", file=sys.stderr)
        return False
    if os.path.getsize(part) < size_mb * 1048576 * 0.9 or not _gguf(part):
        print(f"{name} is incomplete; it continues next time.", file=sys.stderr)
        return False
    os.replace(part, dest)
    os.chmod(dest, 0o644)
    return True


def download_choice(choice: dict) -> bool:
    ok = True
    for name, url, size_mb in wanted_files(choice):
        print(f"Getting {name} ({size_mb} MB)…", flush=True)
        ok = download_file(name, url, size_mb) and ok
    return ok


def restart_ai() -> None:
    subprocess.run(["systemctl", "try-restart", "devos-ai-core.service"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- API settings

def read_api_conf(path: str = API_CONF) -> dict:
    conf = {"listen": "local", "key": ""}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.partition("=")
                if key.strip() in conf:
                    conf[key.strip()] = value.strip()
    except OSError:
        pass
    return conf


def write_api_conf(conf: dict, path: str = API_CONF) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# DevOS AI API. listen=local (this PC only) or lan (phones/PCs on this network).\n")
        handle.write(f"listen={conf['listen']}\nkey={conf['key']}\n")
    # The key is a secret: only root and the AI service read it; people see it
    # through "devos-ai-models api" (pkexec) or the copy in their home folder.
    os.chmod(path, 0o600)


def lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


def api_summary(conf: dict) -> str:
    lines = [
        "DevOS AI API (OpenAI-compatible)",
        f"  On this PC:  http://127.0.0.1:{API_PORT}/v1   (no key needed)",
    ]
    if conf["listen"] == "lan":
        ip = lan_ip() or "<this-pc-ip>"
        lines += [f"  On your network: http://{ip}:{API_PORT}/v1",
                  f"  API key:     {conf['key']}"]
    else:
        lines.append("  Network access is off. Turn it on with: devos-ai-models api lan on")
    lines += [
        "  Models:      devos-ai (chat), devos-ai-code (code), devos-ai-embed",
        f"  Docs:        http://127.0.0.1:{API_PORT}/docs",
        "  Automations: devos auto commit | review | explain | summarize | hook",
        "",
        "Example:",
        f"  curl http://127.0.0.1:{API_PORT}/v1/chat/completions -H 'Content-Type: application/json' \\",
        "    -d '{\"model\":\"devos-ai\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="devos-ai-models", description="DevOS AI models and API")
    sub = parser.add_subparsers(dest="cmd")
    hw = sub.add_parser("hw")
    hw.add_argument("--installer", action="store_true")
    sub.add_parser("list")
    sub.add_parser("status")
    choose = sub.add_parser("choose")
    choose.add_argument("chat", nargs="?", default="")
    choose.add_argument("--vision", action="store_true")
    choose.add_argument("--coder", action="store_true")
    choose.add_argument("--no-download", action="store_true")
    choose.add_argument("--value", default="", help="installer value, e.g. medium+vision")
    sub.add_parser("download")
    sub.add_parser("user-extras")
    remove = sub.add_parser("remove")
    remove.add_argument("model")
    api = sub.add_parser("api")
    api.add_argument("action", nargs="*")
    args = parser.parse_args(argv)

    if args.cmd == "hw":
        print(json.dumps(hardware(installer=args.installer), indent=2))
        return 0

    if args.cmd in (None, "list"):
        info = hardware()
        choice = catalog.read_choice()
        for model in info["models"]:
            mark = "*" if model["id"] == choice["chat"] else " "
            have = "installed" if (model.get("built_in") or catalog.installed_file(model["file"])) else "not downloaded"
            fit = "" if model["fits"] else "  (needs " + str(model["min_ram_gb"]) + " GB RAM)"
            rec = "  <- recommended for this PC" if model["id"] == info["recommended"] else ""
            print(f"{mark} {model['id']:7} {model['params']:5} {model['size_mb']:>5} MB  {have}{fit}{rec}")
        return 0

    if args.cmd == "status":
        choice = catalog.read_choice()
        missing = [f[0] for f in wanted_files(choice) if not catalog.installed_file(f[0])]
        print(json.dumps({"choice": choice, "missing": missing, "ready": not missing}, indent=2))
        return 0

    if args.cmd == "choose":
        choice = catalog.parse_choice(args.value) if args.value else {
            "chat": args.chat or "tiny", "vision": args.vision, "coder": args.coder}
        if not catalog.chat_model(choice["chat"]):
            print(f"Unknown model '{choice['chat']}'. Use: " + ", ".join(m["id"] for m in catalog.CHAT_MODELS),
                  file=sys.stderr)
            return 2
        write_choice(choice)
        if wanted_files(choice):
            enable_download_service()
        if args.no_download:
            print(f"DevOS AI: {choice['chat']} chosen; it downloads once the PC is online.")
            return 0
        ok = download_choice(choice)
        if ok:
            disable_download_service()
            restart_ai()
            print("DevOS AI is ready.")
        return 0 if ok else 1

    if args.cmd == "download":
        choice = catalog.read_choice()
        ok = download_choice(choice)
        if ok:
            disable_download_service()
            restart_ai()
        return 0 if ok else 1

    if args.cmd == "user-extras":
        choice = catalog.read_choice()
        if not choice.get("vision"):
            return 0
        sys.path.insert(0, os.path.join(HERE, "..", "assistant"))
        try:
            import vision
        except ImportError:
            return 0
        if vision.model_installed():
            return 0
        ok, message = vision.download_model()
        print(message)
        return 0 if ok else 1

    if args.cmd == "remove":
        chat = catalog.chat_model(args.model)
        if not chat or chat.get("built_in"):
            print("Only downloaded models can be removed.", file=sys.stderr)
            return 2
        for name in (chat["file"], chat["file"] + ".partial"):
            try:
                os.remove(os.path.join(catalog.MODELS_DIR, name))
            except OSError:
                pass
        choice = catalog.read_choice()
        if choice["chat"] == args.model:
            choice["chat"] = "tiny"
            write_choice(choice)
        restart_ai()
        print(f"Removed {chat['name']}.")
        return 0

    if args.cmd == "api":
        conf = read_api_conf()
        action = args.action
        if action[:1] == ["lan"] and action[1:2] in (["on"], ["off"]):
            conf["listen"] = "lan" if action[1] == "on" else "local"
            if conf["listen"] == "lan" and not conf["key"]:
                conf["key"] = "devos-" + secrets.token_urlsafe(24)
        elif action == ["new-key"]:
            conf["key"] = "devos-" + secrets.token_urlsafe(24)
        elif action:
            print("Use: devos-ai-models api [lan on|lan off|new-key]", file=sys.stderr)
            return 2
        if action:
            write_api_conf(conf)
            restart_ai()
        print(api_summary(conf))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
