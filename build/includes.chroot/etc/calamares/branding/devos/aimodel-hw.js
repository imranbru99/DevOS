.pragma library
// Default for a 4 GB laptop; devos-ai-hwprobe rewrites it at live boot.
var hw = {
 "ram_gb": 4.0,
 "threads": 2,
 "cpu": "",
 "gpu": "",
 "disk_gb": 0.0,
 "recommended": "small",
 "recommended_extras": [
  "vision"
 ],
 "models": [
  {
   "id": "tiny",
   "name": "Tiny",
   "params": "0.5B",
   "file": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
   "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
   "size_mb": 490,
   "min_ram_gb": 2,
   "min_threads": 1,
   "built_in": true,
   "about": "Built in. Quick answers and PC help on any computer.",
   "fits": true
  },
  {
   "id": "small",
   "name": "Small",
   "params": "1.5B",
   "file": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
   "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
   "size_mb": 1120,
   "min_ram_gb": 4,
   "min_threads": 2,
   "about": "Better answers and summaries. Good for most laptops.",
   "fits": true
  },
  {
   "id": "medium",
   "name": "Medium",
   "params": "3B",
   "file": "qwen2.5-3b-instruct-q4_k_m.gguf",
   "url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
   "size_mb": 2100,
   "min_ram_gb": 8,
   "min_threads": 4,
   "about": "Writes, explains code and reads long PDFs well.",
   "fits": false
  },
  {
   "id": "large",
   "name": "Large",
   "params": "7B",
   "file": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
   "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
   "size_mb": 4680,
   "min_ram_gb": 16,
   "min_threads": 6,
   "about": "Near cloud-assistant quality. Needs a strong PC.",
   "fits": false
  },
  {
   "id": "xl",
   "name": "Extra large",
   "params": "14B",
   "file": "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
   "url": "https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf",
   "size_mb": 8990,
   "min_ram_gb": 32,
   "min_threads": 8,
   "never_recommend": true,
   "about": "Best quality, slow on most PCs. For workstations.",
   "fits": false
  }
 ],
 "extras": [
  {
   "id": "vision",
   "name": "Photo understanding",
   "size_mb": 520,
   "min_ram_gb": 4,
   "about": "Describe photos and screenshots. Text in images and PDFs is read without it.",
   "fits": true
  },
  {
   "id": "coder",
   "name": "Coding model",
   "size_mb": 1120,
   "min_ram_gb": 8,
   "about": "A second model tuned for code, used by DevOS Code and the API (model \"devos-ai-code\").",
   "fits": false
  }
 ],
 "built_in_skills": "Reading PDFs and text in images (Bangla + English) and voice commands work with every choice."
};
