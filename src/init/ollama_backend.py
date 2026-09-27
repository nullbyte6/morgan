"""One Ollama service, with transports owned by their asyncio loops."""

import threading


class SharedOllamaBackend:
    def __init__(self, model_name=None, *, base_url="http://localhost:11434/v1"):
        if model_name is None:
            from .brain import MODEL_NAME
            model_name = MODEL_NAME
        self.model_name = model_name
        self.base_url = base_url
        self.settings = {"thinking": False, "openai_reasoning_effort": "none", "temperature": 0.2}
        self.profile = {"openai_chat_supports_multiple_system_messages": False,
                        "openai_chat_supports_max_completion_tokens": False,
                        "openai_supports_tool_choice_required": False}
        self._transports = {}
        self._lock = threading.RLock()

    def model(self, loop, name=None):
        from pydantic_ai.models.ollama import OllamaModel
        from pydantic_ai.providers.ollama import OllamaProvider
        from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT, get_user_agent
        from .task_trace import trace_provider_request
        import httpx2

        with self._lock:
            transport = self._transports.get(loop)
            if transport is None:
                client = httpx2.AsyncClient(
                    timeout=httpx2.Timeout(timeout=DEFAULT_HTTP_TIMEOUT, connect=5),
                    headers={"User-Agent": get_user_agent()},
                    event_hooks={"request": [trace_provider_request]})
                provider = OllamaProvider(base_url=self.base_url, http_client=client)
                transport = (client, provider, {})
                self._transports[loop] = transport
            client, provider, models = transport
            name = name or self.model_name
            if name not in models:
                models[name] = OllamaModel(name, provider=provider, profile=self.profile,
                                          settings=dict(self.settings))
            return models[name]

    async def close_transport(self, loop):
        with self._lock:
            transport = self._transports.pop(loop, None)
        if transport is not None:
            await transport[0].aclose()
