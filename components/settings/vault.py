#!/usr/bin/env python3
"""
DevOS Vault: a password-encrypted folder after install.

Full-disk LUKS still has to be chosen in the installer. Vault creates a LUKS2
file, formats it, and mounts it at ~/Vault. The password is passed to
cryptsetup on its input and is not written to a config file.
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
from typing import Any, Callable, Dict, List, Optional


IMG = os.path.expanduser("~/.local/share/devos/vault.img")
MOUNT = os.path.expanduser("~/Vault")
MAPPER = "devos-vault"
MAPPER_DEV = f"/dev/mapper/{MAPPER}"


def _euid() -> int:
    fn = getattr(os, "geteuid", None)
    return fn() if fn else 0


def plan_create(size_mb: int, image: str = IMG, mount: str = MOUNT) -> List[List[str]]:
    return [
        ["dd", "if=/dev/zero", f"of={image}", "bs=1M", f"count={int(size_mb)}", "status=none"],
        ["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", image],
        ["cryptsetup", "open", image, MAPPER],
        ["mkfs.ext4", "-q", MAPPER_DEV],
        ["mkdir", "-p", mount],
        ["mount", MAPPER_DEV, mount],
    ]


class Vault:
    def __init__(self, runner: Optional[Callable] = None, euid: Optional[int] = None,
                 image: str = IMG, mount: str = MOUNT):
        self.runner = runner or self._default_run
        self._euid = _euid() if euid is None else euid
        self.image = image
        self.mount = mount

    @staticmethod
    def _default_run(argv: List[str], secret: str = "", timeout: int = 600):
        try:
            proc = subprocess.run(argv, input=secret, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)

    def status(self) -> Dict[str, Any]:
        mounted = os.path.ismount(self.mount)
        return {
            "image": self.image if os.path.isfile(self.image) else "",
            "mount": self.mount,
            "open": mounted,
            "full_disk": "Choose Encrypt system while installing DevOS. Vault protects one folder.",
        }

    def _root(self, action: str) -> Dict[str, Any]:
        return {
            "status": "NEEDS_ROOT",
            "message": "Opening an encrypted folder needs an administrator password.",
            "command": ["pkexec", sys.executable, os.path.abspath(__file__), action],
        }

    def create(self, size_mb: int, passphrase: str) -> Dict[str, Any]:
        if size_mb < 64:
            return {"status": "ERROR", "error": "Vault needs at least 64 MB."}
        if not passphrase or len(passphrase) < 8:
            return {"status": "ERROR", "error": "Use a password of at least 8 characters."}
        if os.path.exists(self.image):
            return {"status": "EXISTS", "message": "A vault already exists. Open it, or delete the image file yourself first."}
        if self._euid != 0:
            return self._root("create")
        if not shutil.which("cryptsetup"):
            return {"status": "NEEDS_PACKAGE", "packages": ["cryptsetup"],
                    "message": "cryptsetup is not installed."}
        os.makedirs(os.path.dirname(self.image), exist_ok=True)
        steps = plan_create(size_mb, self.image, self.mount)
        for cmd in steps:
            secret = passphrase if cmd[0] == "cryptsetup" else ""
            code, out, err = self.runner(cmd, secret)
            if code != 0:
                self.runner(["cryptsetup", "close", MAPPER], "")
                return {"status": "FAILED", "error": (err or out or "Vault setup stopped.").strip(), "step": cmd[0]}
        return {
            "status": "CREATED",
            "mount": self.mount,
            "message": f"Vault is open at {self.mount}. Files you put there stay encrypted when you close it.",
        }

    def open(self, passphrase: str) -> Dict[str, Any]:
        if self._euid != 0:
            return self._root("open")
        if not os.path.isfile(self.image):
            return {"status": "MISSING", "message": "No vault yet. Create one first."}
        if os.path.ismount(self.mount):
            return {"status": "OPEN", "mount": self.mount, "message": "Vault is already open."}
        code, out, err = self.runner(["cryptsetup", "open", self.image, MAPPER], passphrase)
        if code != 0:
            return {"status": "FAILED", "error": (err or out or "Could not unlock the vault. Check the password.").strip()}
        os.makedirs(self.mount, exist_ok=True)
        code, out, err = self.runner(["mount", MAPPER_DEV, self.mount], "")
        if code != 0:
            self.runner(["cryptsetup", "close", MAPPER], "")
            return {"status": "FAILED", "error": (err or out or "Unlocked, but the folder could not be mounted.").strip()}
        return {"status": "OPEN", "mount": self.mount, "message": f"Vault is open at {self.mount}."}

    def close(self) -> Dict[str, Any]:
        if self._euid != 0:
            return self._root("close")
        errors = []
        if os.path.ismount(self.mount):
            code, out, err = self.runner(["umount", self.mount], "")
            if code != 0:
                errors.append((err or out or "unmount failed").strip())
        if os.path.exists(MAPPER_DEV):
            code, out, err = self.runner(["cryptsetup", "close", MAPPER], "")
            if code != 0:
                errors.append((err or out or "cryptsetup close failed").strip())
        if errors:
            return {"status": "FAILED", "error": " ".join(errors)}
        return {"status": "CLOSED", "message": "Vault is closed. The files stay in the encrypted image."}


def _ask_secret(prompt: str) -> str:
    if shutil.which("kdialog"):
        box = subprocess.run(["kdialog", "--password", prompt], capture_output=True, text=True)
        if box.returncode != 0:
            return ""
        return box.stdout.rstrip("\n")
    import getpass
    return getpass.getpass(prompt + ": ")


def gui() -> int:
    vault = Vault()
    if vault._euid != 0 and shutil.which("pkexec"):
        os.execvp("pkexec", ["pkexec", sys.executable, os.path.abspath(__file__), "gui"])
    if not shutil.which("kdialog"):
        print(json.dumps(vault.status(), indent=2))
        return 0
    choice = subprocess.run(
        ["kdialog", "--menu", "DevOS Vault", "create", "Create encrypted folder",
         "open", "Open", "close", "Close", "status", "Status"],
        capture_output=True, text=True)
    if choice.returncode != 0:
        return 0
    action = choice.stdout.strip()
    if action == "status":
        info = vault.status()
        subprocess.run(["kdialog", "--msgbox", "Open: %s\nFolder: %s" % ("yes" if info["open"] else "no", info["mount"])])
        return 0
    if action == "close":
        result = vault.close()
    elif action == "create":
        size = subprocess.run(["kdialog", "--inputbox", "Size in MB (at least 64)", "2048"],
                              capture_output=True, text=True)
        if size.returncode != 0:
            return 0
        try:
            size_mb = int(size.stdout.strip())
        except ValueError:
            size_mb = 0
        secret = _ask_secret("Password for the vault")
        result = vault.create(size_mb, secret)
    else:
        secret = _ask_secret("Vault password")
        result = vault.open(secret)
    subprocess.run(["kdialog", "--msgbox", result.get("message") or result.get("error") or result.get("status")])
    return 0 if result.get("status") in ("CREATED", "OPEN", "CLOSED") else 1


def main():
    parser = argparse.ArgumentParser(description="DevOS Vault")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    sub.add_parser("gui")
    create_p = sub.add_parser("create")
    create_p.add_argument("--size-mb", type=int, default=2048)
    open_p = sub.add_parser("open")
    sub.add_parser("close")
    args = parser.parse_args()
    vault = Vault()
    if args.command == "gui":
        sys.exit(gui())
    if args.command == "create":
        if vault._euid != 0 and shutil.which("pkexec") and os.environ.get("DEVOS_NO_PKEXEC") != "1":
            os.execvp("pkexec", ["pkexec", sys.executable, os.path.abspath(__file__), "create", "--size-mb", str(args.size_mb)])
        secret = _ask_secret("New vault password")
        res = vault.create(args.size_mb, secret)
    elif args.command == "open":
        if vault._euid != 0 and shutil.which("pkexec") and os.environ.get("DEVOS_NO_PKEXEC") != "1":
            os.execvp("pkexec", ["pkexec", sys.executable, os.path.abspath(__file__), "open"])
        secret = _ask_secret("Vault password")
        res = vault.open(secret)
    elif args.command == "close":
        if vault._euid != 0 and shutil.which("pkexec") and os.environ.get("DEVOS_NO_PKEXEC") != "1":
            os.execvp("pkexec", ["pkexec", sys.executable, os.path.abspath(__file__), "close"])
        res = vault.close()
    else:
        res = vault.status()
    print(json.dumps({k: v for k, v in res.items() if k != "command"}, indent=2))
    sys.exit(0 if res.get("status", "OK") in ("CREATED", "OPEN", "CLOSED", "EXISTS", "MISSING") or "image" in res else 1)


if __name__ == "__main__":
    main()
