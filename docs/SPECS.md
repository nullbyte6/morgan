## AI Model Requirements
Arlo uses Ministral 3 14B as its primary local multimodal model through Ollama.

### Model
- Model: Ministral 3 14B
- Architecture: Dense multimodal Transformer
- Parameters: ~14B
- Quantization (Ollama default): Q4_K_M
- Model size: ~9.1 GB
- Native context: 262,144 tokens
- Modalities: Text and image
- Capabilities: Vision, tool calling, reasoning, coding, multilingual interaction and agentic workflows

### Storage
- Minimum free disk space: ~12 GB for Ministral 3 14B and its model data
- Recommended free disk space: 20+ GB to leave room for Ollama runtime data, updates and additional model data

### Memory
Mistral does not define fixed minimum CPU, RAM or VRAM requirements for running
Ministral 3 14B through Ollama. Actual memory requirements depend on quantization,
context length, KV cache configuration and hardware acceleration.

#### Practical requirements for Arlo

Minimum:
- RAM: 16 GB
- GPU VRAM: 8 GB
- CPU: Modern 64-bit x86 CPU
- GPU: Ollama-compatible GPU with hardware acceleration
- Context: Reduced context may be required on lower-memory systems

Recommended:
- RAM: 32 GB
- GPU VRAM: 16 GB
- CPU: Modern 8-core or better x86-64 CPU
- GPU: Ollama-compatible GPU with 16 GB VRAM
- Storage: SSD/NVMe
- Context: 32,768 tokens

Ideal:
- RAM: 32–64 GB
- GPU VRAM: 24 GB+
- CPU: Modern high-performance 8-core or better x86-64 CPU
- GPU: High-performance GPU supported by Ollama
- Storage: NVMe SSD

A 16 GB GPU provides sufficient headroom to run the Q4_K_M model with a
substantial KV cache while keeping most or all model computation GPU-accelerated.
Higher VRAM capacities provide additional headroom for larger context windows.