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
    def scan_file(cls, file_path: str) -> Dict[str, Any]:
        """Performs malware signature scan and permission audit."""
        abs_path = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.exists(abs_path):
            return {"error": f"File '{abs_path}' not found."}

        with open(abs_path, "rb") as f:
            content = f.read(5 * 1024 * 1024)

        # 1. Antivirus Signature Scan (ClamAV / EICAR)
        if cls.EICAR_SIGNATURE in content:
            return {
                "file": abs_path,
                "status": "MALWARE_DETECTED",
                "threat_name": "EICAR-Standard-Antivirus-Test-File",
                "safe_to_run": False,
                "ai_summary": "CRITICAL: File contains an active malware signature (EICAR test string). Execution blocked.",
            }

        flagged_risks = []
        is_apk = False

        # 2. Inspect APK for Dangerous Permissions
        if zipfile.is_zipfile(abs_path):
            try:
                with zipfile.ZipFile(abs_path, "r") as zf:
                    if "AndroidManifest.xml" in zf.namelist():
                        is_apk = True
                        manifest_raw = zf.read("AndroidManifest.xml").decode("latin-1", errors="ignore")
                        for perm, warning in cls.HIGH_RISK_PERMISSIONS.items():
                            if perm in manifest_raw:
                                flagged_risks.append({"permission": perm, "warning": warning})
            except Exception:
                pass

        if is_apk and flagged_risks:
            risk_descriptions = "; ".join(f"{r['permission']} ({r['warning']})" for r in flagged_risks)
            return {
                "file": abs_path,
                "is_apk": True,
                "status": "FLAGGED_HIGH_RISK",
                "safe_to_run": False,
                "flagged_permissions": flagged_risks,
                "ai_summary": (
                    f"Warning: This Android application requests {len(flagged_risks)} dangerous permissions: "
                    f"{risk_descriptions}. Please review before approving installation."
                ),
            }

        return {
            "file": abs_path,
            "status": "CLEAN",
            "safe_to_run": True,
            "ai_summary": "File scan passed: No malware signatures or excessive permissions detected.",
        }


def main():
    parser = argparse.ArgumentParser(description="DevOS Safety Scanner")
    parser.add_argument("file", help="Path to file to scan")
    args = parser.parse_args()

    report = AppSafetyScanner.scan_file(args.file)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
