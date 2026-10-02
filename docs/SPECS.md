## AI Model Requirements

Arlo uses Gemma 4 E4B as its single local multimodal model through Ollama. It
is both the main model and the audio model, so only one model is loaded.

### Model

- Model: Gemma 4 E4B (`gemma4:e4b`)
- Architecture: Gemma 4
- Parameters: ~7.5B
- Quantization (Ollama default): Q4_K_M
- Model size: ~6.6 GB
- Native context: 131,072 tokens
- Modalities: Text, image and audio
- Capabilities: Vision, audio input, tool calling, reasoning and agentic workflows

### Storage

- Minimum free disk space: ~10 GB for Gemma 4 E4B and its model data
- Recommended free disk space: 15+ GB to leave room for Ollama runtime data, updates and additional model data

### Memory

Gemma does not define fixed minimum CPU, RAM or VRAM requirements for running
Gemma 4 E4B through Ollama. Actual memory requirements depend on quantization,
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
other runtime allocations. A 16 GB GPU can therefore run Gemma 4 E4B fully
GPU-accelerated with Arlo's recommended 32,768-token context on supported
hardware.

Gemma 4 E4B provides native text, image and audio processing, so Arlo does not
require a separate vision-language or audio model when multimodal input is
routed directly to the primary model. Arlo does not create derived Ollama
models; when it starts Ollama it sets `OLLAMA_CONTEXT_LENGTH` to the
`context_length` of the user configuration, which Settings edits (32,768 by
default). An Ollama service that was already running
keeps its own context length, and Arlo budgets against the context Ollama reports.