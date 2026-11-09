#!/usr/bin/env python3
"""
DevOS App Hub Safety Scanner
Inspects downloaded binaries, Windows executables, and Android APKs before execution.
Includes ClamAV/EICAR malware signature detection, dangerous APK permission analysis,
and plain-language AI safety evaluation.
"""

import sys
import os
import zipfile
import json
import argparse
from typing import Dict, Any, List

# DevOS Security's ClamAV layer (components/security/av.py). Optional: when it
# is missing or ClamAV is not installed, Windows/Android apps get
# "needs_confirmation" so the caller asks before running them.
_SECURITY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "security"))


def _security_av():
    if _SECURITY_DIR not in sys.path:
        sys.path.insert(0, _SECURITY_DIR)
    try:
        import av  # noqa: WPS433 (lazy on purpose)
        return av
    except Exception:
        return None


class AppSafetyScanner:
    """Pre-execution safety and malware scanner."""

    # Standard EICAR Antivirus Test Signature
    EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

    # High-risk Android permissions
    HIGH_RISK_PERMISSIONS = {
        "android.permission.SEND_SMS": "Can send SMS text messages (potential billing charges)",
        "android.permission.RECEIVE_SMS": "Can intercept SMS text messages (security 2FA risk)",
        "android.permission.READ_SMS": "Can read SMS private communications",
        "android.permission.BIND_ACCESSIBILITY_SERVICE": "Can read and automate screen interactions (high spyware risk)",
        "android.permission.SYSTEM_ALERT_WINDOW": "Can display overlay windows (overlay/phishing risk)",
        "android.permission.BIND_DEVICE_ADMIN": "Requests device administrator control",
        "android.permission.RECORD_AUDIO": "Can record microphone audio",
        "android.permission.CAMERA": "Can access device camera",
    }

    @classmethod
    def _contains_eicar(cls, abs_path: str) -> bool:
        """Scan file for EICAR signature across entire file using sliding window."""
        sig = cls.EICAR_SIGNATURE
        sig_len = len(sig)
        chunk_size = 64 * 1024
        try:
            with open(abs_path, "rb") as f:
                prev = b""
                while chunk := f.read(chunk_size):
                    window = prev + chunk
                    if sig in window:
                        return True
                    prev = chunk[-sig_len:]
        except Exception:
            pass
        return False

    @classmethod
    def _extract_apk_manifest_strings(cls, manifest_bytes: bytes) -> str:
        """Extracts strings from both compiled binary XML (AXML) and plain text XML."""
        if manifest_bytes.startswith(b"<?xml") or b"<manifest" in manifest_bytes:
            return manifest_bytes.decode("utf-8", errors="ignore")
        strings = []
        try:
            strings.append(manifest_bytes.decode("utf-16le", errors="ignore"))
        except Exception:
            pass
        try:
            strings.append(manifest_bytes.decode("latin-1", errors="ignore"))
        except Exception:
            pass
        return " ".join(strings)

    @classmethod
    def scan_file(cls, file_path: str) -> Dict[str, Any]:
        """Performs malware signature scan and permission audit."""
        abs_path = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.exists(abs_path):
            return {"error": f"File '{abs_path}' not found."}

        av = _security_av()
        if av is not None and av.is_quarantine_path(abs_path):
            return {
                "file": abs_path,
                "status": "QUARANTINED",
                "safe_to_run": False,
                "blocked": True,
                "ai_summary": "This file is in DevOS Security's quarantine and cannot be run.",
            }

        # 1. Antivirus Signature Scan (ClamAV / EICAR streaming across entire file)
        if cls._contains_eicar(abs_path):
            return {
                "file": abs_path,
                "status": "MALWARE_DETECTED",
                "threat_name": "EICAR-Standard-Antivirus-Test-File",
                "safe_to_run": False,
                "ai_summary": "CRITICAL: File contains an active malware signature (EICAR test string). Execution blocked.",
            }

        # 2. ClamAV (DevOS Security) for Windows and Android apps.
        av_report = cls._av_check(av, abs_path)
        if av_report.get("av_infected"):
            return dict(av_report, **{
                "file": abs_path,
                "status": "MALWARE_DETECTED",
                "threat_name": av_report.get("av_threat"),
                "safe_to_run": False,
                "blocked": True,
                "ai_summary": (f"CRITICAL: ClamAV found {av_report.get('av_threat')} in this file. "
                               "It was moved to quarantine and will not run."),
            })

        flagged_risks = []
        is_apk = False

        # 3. Inspect APK for Dangerous Permissions (supporting binary AXML & plaintext)
        if zipfile.is_zipfile(abs_path):
            try:
                with zipfile.ZipFile(abs_path, "r") as zf:
                    if "AndroidManifest.xml" in zf.namelist():
                        is_apk = True
                        manifest_raw = cls._extract_apk_manifest_strings(zf.read("AndroidManifest.xml"))
                        for perm, warning in cls.HIGH_RISK_PERMISSIONS.items():
                            if perm in manifest_raw:
                                flagged_risks.append({"permission": perm, "warning": warning})
            except Exception:
                pass

        if is_apk and flagged_risks:
            risk_descriptions = "; ".join(f"{r['permission']} ({r['warning']})" for r in flagged_risks)
            return dict(av_report, **{
                "file": abs_path,
                "is_apk": True,
                "status": "FLAGGED_HIGH_RISK",
                "safe_to_run": False,
                "flagged_permissions": flagged_risks,
                "ai_summary": (
                    f"Warning: This Android application requests {len(flagged_risks)} dangerous permissions: "
                    f"{risk_descriptions}. Please review before approving installation."
                ),
            })

        summary = "File scan passed: No malware signatures or excessive permissions detected."
        if av_report.get("needs_confirmation"):
            summary = ("No known threat signature in this file, but the antivirus could not check it "
                       f"({av_report.get('av_note')}). Run it only if you trust where it came from.")
        return dict(av_report, **{
            "file": abs_path,
            "status": "CLEAN",
            "safe_to_run": True,
            "ai_summary": summary,
        })

    @staticmethod
    def _av_check(av, abs_path: str) -> Dict[str, Any]:
        """ClamAV result for .exe/.msi/.apk-type files; {} for other files."""
        lower = abs_path.lower()
        if not lower.endswith((".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".apk", ".xapk", ".apks")):
            return {}
        if av is None:
            return {"av_scanned": False, "needs_confirmation": True,
                    "av_note": "DevOS Security is not installed"}
        res = av.scan_for_launch(abs_path)
        if res.get("infected"):
            return {"av_scanned": True, "av_infected": True, "av_threat": res.get("threat"),
                    "av_engine": res.get("engine"), "quarantined": bool(res.get("quarantined"))}
        if res.get("av_scanned"):
            return {"av_scanned": True, "av_engine": res.get("engine")}
        return {"av_scanned": False, "needs_confirmation": True,
                "av_note": res.get("error") or "scan failed"}


def main():
    parser = argparse.ArgumentParser(description="DevOS Safety Scanner")
    parser.add_argument("file", help="Path to file to scan")
    args = parser.parse_args()

    report = AppSafetyScanner.scan_file(args.file)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
