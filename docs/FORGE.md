# Arlo Forge Mode
## Functionality
**Forge Mode** is an advanced capability of the Arlo agent designed for complex orchestration, persistent state management, and deep integration with specialized modules. This mode enables Arlo to:

- Execute multi-step workflows with long-term memory.
- Integrate voice models (CosyVoice) and real-time LLM processing.
- Manage application caches and safely close sessions.
- Use Pydantic backends for strict data validation.

## Usage
To activate Forge Mode: Click on the "Forge" button. That's it!

## Activation
Forge Mode is activated when:
- A request requiring advanced orchestration is detected through `orchestrator.py`.
- Access to voice models or LLMs is required, using modules under `src/cosyvoice/`.
- Strict Pydantic schema validation is required.
> **Note:** Forge Mode consumes additional resources and should only be used when necessary for complex tasks.