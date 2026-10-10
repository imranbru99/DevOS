"""
DevOS Local AI Core (ai-core)
Hardware Tier Detector & Engine Configuration
Detects system RAM, CPU capabilities, and GPU VRAM (NVIDIA CUDA, AMD ROCm, Intel Vulkan)
to assign the optimal local AI model tier. Zero external dependencies required.
"""

import os
import sys
import shutil
import subprocess
from typing import Dict, Any


class HardwareDetector:
    """Detects system hardware to configure the appropriate offline AI tier."""

    TIER_LITE = "Lite"          # <= 8 GB RAM, CPU or basic GPU -> Qwen2.5 1.5B/3B Q4
    TIER_STANDARD = "Standard"  # 16 GB RAM or 6-8 GB VRAM -> Qwen2.5 7B Q4_K_M
    TIER_PRO = "Pro"            # 32 GB+ RAM or 12-24 GB VRAM -> Qwen2.5 14B-32B Q4

    MODEL_CATALOG = {
        "Lite": {
            "chat_model": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
            "chat_file": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            "code_model": "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
            "code_file": "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
            "embed_model": "nomic-ai/nomic-embed-text-v1.5-GGUF",
            "embed_file": "nomic-embed-text-v1.5.Q4_K_M.gguf",
            "context_window": 4096,
            "gpu_layers": 0,
            "max_ram_mb": 2500,
        },
        "Standard": {
            "chat_model": "Qwen/Qwen2.5-7B-Instruct-GGUF",
            "chat_file": "qwen2.5-7b-instruct-q4_k_m.gguf",
            "code_model": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
            "code_file": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
            "embed_model": "nomic-ai/nomic-embed-text-v1.5-GGUF",
            "embed_file": "nomic-embed-text-v1.5.Q4_K_M.gguf",
            "context_window": 8192,
            "gpu_layers": 33,
            "max_ram_mb": 6500,
        },
        "Pro": {
            "chat_model": "Qwen/Qwen2.5-14B-Instruct-GGUF",
            "chat_file": "qwen2.5-14b-instruct-q4_k_m.gguf",
            "code_model": "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF",
            "code_file": "qwen2.5-coder-14b-instruct-q4_k_m.gguf",
            "embed_model": "BAAI/bge-m3-GGUF",
            "embed_file": "bge-m3-q4_k_m.gguf",
            "context_window": 16384,
            "gpu_layers": 48,
            "max_ram_mb": 14000,
        },
    }

    @staticmethod
    def get_system_ram_gb() -> float:
        """Returns total physical RAM in Gigabytes using OS-native methods."""
        # 1. Linux /proc/meminfo
        if os.path.exists("/proc/meminfo"):
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            parts = line.split()
                            kb = float(parts[1])
                            return round(kb / (1024 * 1024), 2)
            except Exception:
                pass

        # 2. Windows ctypes GlobalMemoryStatusEx
        if sys.platform == "win32":
            try:
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                return round(stat.ullTotalPhys / (1024 ** 3), 2)
            except Exception:
                pass

        # 3. Fallback to os.sysconf
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return round((pages * page_size) / (1024 ** 3), 2)
        except Exception:
            return 8.0

    @staticmethod
    def detect_gpu() -> Dict[str, Any]:
        """Detects presence of NVIDIA (CUDA), AMD (ROCm), or Intel (Vulkan/SYCL) GPU."""
        gpu_info = {
            "vendor": "none",
            "vram_gb": 0.0,
            "device_name": "CPU fallback",
            "backend": "cpu"
        }

        # 1. Check NVIDIA via nvidia-smi
        if shutil.which("nvidia-smi"):
            try:
                cmd = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
                output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
                if output:
                    name, mem = output.splitlines()[0].split(",")
                    gpu_info["vendor"] = "nvidia"
                    gpu_info["device_name"] = name.strip()
                    gpu_info["vram_gb"] = round(float(mem.strip()) / 1024, 2)
                    gpu_info["backend"] = "cuda"
                    return gpu_info
            except Exception:
                pass

        # 2. Check AMD ROCm / Vulkan
        if shutil.which("rocm-smi"):
            try:
                gpu_info["vendor"] = "amd"
                gpu_info["device_name"] = "AMD Radeon GPU (ROCm)"
                gpu_info["backend"] = "rocm"
                return gpu_info
            except Exception:
                pass

        # 3. Check lspci for Linux environments
        if shutil.which("lspci"):
            try:
                lspci_out = subprocess.check_output(["lspci"], text=True, stderr=subprocess.DEVNULL)
                if "NVIDIA" in lspci_out:
                    gpu_info["vendor"] = "nvidia"
                    gpu_info["backend"] = "cuda"
                elif "AMD" in lspci_out or "Radeon" in lspci_out:
                    gpu_info["vendor"] = "amd"
                    gpu_info["backend"] = "vulkan"
                elif "Intel" in lspci_out and "Graphics" in lspci_out:
                    gpu_info["vendor"] = "intel"
                    gpu_info["backend"] = "vulkan"
            except Exception:
                pass

        return gpu_info

    @classmethod
    def evaluate_tier(cls) -> Dict[str, Any]:
        """Evaluates hardware specs and assigns model tier with full configuration."""
        ram_gb = cls.get_system_ram_gb()
        gpu = cls.detect_gpu()
        vram_gb = gpu.get("vram_gb", 0.0)

        # Tier decision logic
        if ram_gb >= 30.0 or vram_gb >= 12.0:
            assigned_tier = cls.TIER_PRO
        elif ram_gb >= 14.0 or vram_gb >= 6.0:
            assigned_tier = cls.TIER_STANDARD
        else:
            assigned_tier = cls.TIER_LITE

        catalog = cls.MODEL_CATALOG[assigned_tier]

        return {
            "tier": assigned_tier,
            "ram_gb": ram_gb,
            "gpu": gpu,
            "models": catalog,
            "storage_dir": os.environ.get("DEVOS_MODELS_DIR", "/var/lib/DevOS/models"),
            "api_endpoint": "http://127.0.0.1:11434/v1",
        }


if __name__ == "__main__":
    result = HardwareDetector.evaluate_tier()
    print("DevOS Hardware AI Tier Evaluation:")
    for k, v in result.items():
        print(f"  {k}: {v}")
