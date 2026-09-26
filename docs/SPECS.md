## AI Model Requirements

Arlo uses Qwen3.5 9B as its primary local multimodal model through Ollama.

### Model

- Model: Qwen3.5 9B
- Architecture: Hybrid multimodal Transformer
- Parameters: ~9B
- Quantization (Ollama default): Q4_K_M
- Model size: ~6.6 GB
- Native context: 262,144 tokens
- Modalities: Text and image
- Capabilities: Vision, tool calling, reasoning, coding, multilingual interaction and agentic workflows

### Storage

- Minimum free disk space: ~10 GB for Qwen3.5 9B and its model data
- Recommended free disk space: 15+ GB to leave room for Ollama runtime data, updates and additional model data

### Memory

Qwen does not define fixed minimum CPU, RAM or VRAM requirements for running
Qwen3.5 9B through Ollama. Actual memory requirements depend on quantization,
context length, KV cache configuration, multimodal inputs and hardware acceleration.

#### Practical requirements for Arlo

Minimum:
- RAM: 16 GB
- GPU VRAM: 8 GB
- CPU: Modern 64-bit x86 CPU
- GPU: Ollama-compatible GPU with hardware acceleration
- Context: Reduced context may be required on lower-memory systems

Recommended:
- RAM: 32 GB
- GPU VRAM: 12–16 GB
- CPU: Modern 8-core or better x86-64 CPU
- GPU: Ollama-compatible GPU with 12+ GB VRAM
- Storage: SSD/NVMe
- Context: 32,768 tokens

Ideal:
- RAM: 32–64 GB
- GPU VRAM: 16 GB+
- CPU: Modern high-performance 8-core or better x86-64 CPU
- GPU: High-performance GPU supported by Ollama
- Storage: NVMe SSD

The Q4_K_M model occupies approximately 6.6 GB, leaving substantial VRAM
headroom on a 16 GB GPU for the context cache, multimodal processing and
other runtime allocations. A 16 GB GPU can therefore run Qwen3.5 9B fully
GPU-accelerated with Arlo's recommended 32,768-token context on supported
hardware.

Qwen3.5 9B provides native text and image processing, so Arlo does not
require a separate vision-language model for image understanding when
multimodal input is routed directly to the primary model.