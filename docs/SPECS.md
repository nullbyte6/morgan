## AI Model Requirements
Arlo uses Qwen3.8-27B as its primary local multimodal model through Ollama.

### Model
- Model: Qwen3.8-27B
- Architecture: Dense multimodal model
- Parameters: 27.3B
- Quantization (Ollama default): Q4
- Model size: ~18 GB
- Native context: 262,144 tokens
- Modalities: Text and image
- Capabilities: Vision, tool calling, reasoning, coding and agentic workflows

### Storage
- Minimum free disk space: ~20 GB for Qwen3.8-27B alone
- Recommended free disk space: 30+ GB to leave room for model/runtime data and updates

### Memory
Qwen does not publish official minimum CPU, RAM or VRAM requirements.
Actual memory requirements depend on quantization, context length and Ollama configuration.

#### Practical requirements for Arlo
Minimum:
- RAM: 32 GB
- GPU VRAM: 16 GB
- CPU: Modern 64-bit x86 CPU
- GPU: Ollama-compatible GPU with hardware acceleration
- Context: Reduced context may be required to avoid excessive CPU/RAM offloading

Recommended:
- RAM: 32–64 GB
- GPU VRAM: 24 GB+
- CPU: Modern 8-core or better x86-64 CPU
- Storage: SSD/NVMe

Ideal:
- RAM: 64 GB+
- GPU VRAM: 32 GB+
- GPU: High-performance GPU supported by Ollama
- Storage: NVMe SSD

A 24 GB GPU provides substantially more headroom for the Q4 model and KV cache.
A 32 GB GPU is preferable for very large context windows.