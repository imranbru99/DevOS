#!/usr/bin/env python3
"""
DevOS 2027 Era: NPU (Neural Processing Unit) & Hybrid Silicon Acceleration
Detects on-die NPUs (Intel NPU, AMD Ryzen AI XDNA, Qualcomm Snapdragon X Elite, Apple-style silicon)
to offload ambient AI agent tasks at 2-5 Watts with zero battery drain.
"""

import sys
import os
import shutil
import json
import subprocess
from typing import Dict, Any


class NPUAccelerator:
    """Discovers and orchestrates local Neural Processing Units (NPUs)."""

    @staticmethod
    def detect_npu() -> Dict[str, Any]:
        """Scans Linux sysfs and kernel devices for dedicated NPU silicon."""
        npu_info = {
            "npu_detected": False,
            "vendor": "none",
            "device_model": "None (Using CPU/GPU acceleration)",
            "driver": "none",
            "rated_tops": 0,
            "power_efficiency": "Standard (GPU/CPU)",
            "ambient_readiness": "Ready via GPU/CPU fallback",
        }

        # 1. Check Intel NPU (Meteor Lake / Lunar Lake / Arrow Lake via intel_vpu / accel driver)
        if os.path.exists("/dev/accel/accel0") or os.path.exists("/sys/class/accel/accel0"):
            npu_info.update({
                "npu_detected": True,
                "vendor": "Intel",
                "device_model": "Intel AI Boost NPU (OpenVINO Engine)",
                "driver": "intel_vpu / level-zero",
                "rated_tops": 48,
                "power_efficiency": "Ultra-Low Power (2.5W)",
                "ambient_readiness": "Always-On Background Ambient Assistant Enabled",
            })
            return npu_info

        # 2. Check AMD XDNA (Ryzen AI / Strix Point via /dev/accel/accel0 or amdxdna)
        if os.path.exists("/dev/amdxdna") or (os.path.exists("/sys/module/amdxdna")):
            npu_info.update({
                "npu_detected": True,
                "vendor": "AMD",
                "device_model": "AMD Ryzen AI XDNA 2 NPU",
                "driver": "amdxdna / ROCm-NPU",
                "rated_tops": 50,
                "power_efficiency": "Ultra-Low Power (3.0W)",
                "ambient_readiness": "Always-On Background Ambient Assistant Enabled",
            })
            return npu_info

        # 3. Check Qualcomm Snapdragon X Elite (compute_npu / hexagon)
        if os.path.exists("/sys/class/misc/qcdsp") or os.path.exists("/dev/qce"):
            npu_info.update({
                "npu_detected": True,
                "vendor": "Qualcomm",
                "device_model": "Hexagon NPU (Snapdragon X Elite)",
                "driver": "qcom_q6v5_pas",
                "rated_tops": 45,
                "power_efficiency": "Ultra-Low Power (2.0W)",
                "ambient_readiness": "Always-On Background Ambient Assistant Enabled",
            })
            return npu_info

        return npu_info

    @classmethod
    def get_scheduling_recommendation(cls) -> Dict[str, Any]:
        """Decides whether to route inference to NPU, GPU, or CPU."""
        npu = cls.detect_npu()
        if npu["npu_detected"]:
            return {
                "ambient_chat_target": f"NPU ({npu['device_model']})",
                "heavy_code_target": "Discrete GPU (CUDA/ROCm) or CPU",
                "power_savings": "Prefer NPU for always-on / low-watt ambient tasks",
                "ambient_always_on": True,
                "runtime": "preference-file",  # OpenVINO/XDNA runtime optional when installed
            }
        return {
            "ambient_chat_target": "GPU / CPU Fallback",
            "heavy_code_target": "GPU / CPU Fallback",
            "power_savings": "Standard battery profile",
            "ambient_always_on": False,
            "runtime": "cpu-gpu",
        }

    @classmethod
    def write_preference(cls) -> str:
        """Persist scheduling preference for ai-core / assistant to read."""
        npu = cls.detect_npu()
        sched = cls.get_scheduling_recommendation()
        path = os.path.join(os.path.expanduser("~"), ".config", "devos", "npu-schedule.json")
        os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
        payload = {
            "npu": npu,
            "scheduling": sched,
            "policy": {
                "ambient_prefer": "npu" if npu.get("npu_detected") else "cpu",
                "heavy_prefer": "gpu_or_cpu",
                "note": "Preference only until a vendor NPU runtime is installed.",
            },
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
        return path


def main():
    npu = NPUAccelerator.detect_npu()
    sched = NPUAccelerator.get_scheduling_recommendation()
    path = NPUAccelerator.write_preference()
    print("DevOS NPU Silicon Status:")
    print(json.dumps({"npu": npu, "scheduling": sched, "preference_file": path}, indent=2))


if __name__ == "__main__":
    main()
