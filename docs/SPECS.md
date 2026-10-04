## AI Model Requirements

Morgan uses two local models through Ollama: a light assistant model that stays
loaded for conversation, web search and PC actions, and a larger coding model
that the assistant hands real coding jobs to with the `delegate_coding` tool.
Voice input is transcribed locally with Whisper, so neither model needs audio
input.

### Models

| Role | Model | Size | Native context | Modalities |
| --- | --- | --- | --- | --- |
| Assistant | `qwen3.5:4b` | ~3.3 GB | 262,144 tokens | Text and image |
| Coding | `qwen3.5:9b` | ~6.6 GB | 262,144 tokens | Text and image |

Both models support tool calling. The assistant is kept loaded with the
`keep_alive` setting. The coding model uses Ollama's default lifetime, so it is
unloaded a few minutes after the last use.

There is no model selector: Morgan switches models by itself. A real coding job
is handed to the coding model with the `delegate_coding` tool. When a request
reaches four tool steps or two failed ones, or when the assistant calls the
`escalate` tool, the rest of the request continues on the coding model with the
same conversation, and the next request starts on the assistant again.

The `base_model_name` and `coding_model` entries of `dev/core.json` set the
models, and the `coding_model` setting of the user configuration overrides the
coding model; an empty `coding_model` falls back to the assistant model, which
also turns escalation off.

### Storage

- Minimum free disk space: ~15 GB for both models and their model data
- Recommended free disk space: 20+ GB to leave room for Ollama runtime data, updates and additional model data

### Memory

The models do not define fixed minimum CPU, RAM or VRAM requirements for running
through Ollama. Actual memory requirements depend on quantization, context
length, KV cache configuration, multimodal inputs and hardware acceleration.

#### Practical requirements for Morgan

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

The assistant and coding models occupy approximately 10 GB together, so a 16 GB
GPU can keep both loaded with Morgan's recommended 32,768-token context while
the coding model is in use. On a GPU with 8 to 12 GB of VRAM, Ollama swaps the
two models, which adds a few seconds to the first reply after a coding job.

Both models accept images, so Morgan does not require a separate
vision-language model. Morgan does not create derived Ollama
models; when it starts Ollama it sets `OLLAMA_CONTEXT_LENGTH` to the
`context_length` of the user configuration, which Settings edits (32,768 by
default). An Ollama service that was already running
keeps its own context length, and Morgan budgets against the context Ollama reports.