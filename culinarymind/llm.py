"""LLMProviderAdapter: one interface, two real providers (OpenAI-compatible and Anthropic).
Keys come from .env via config; never hard-coded."""
import json, urllib.request, urllib.error
from abc import ABC, abstractmethod
from . import config

class LLMError(RuntimeError): pass

class LLMProviderAdapter(ABC):
    @abstractmethod
    def generate(self, messages, tools=None, system=None) -> dict:
        """Return {'text': str, 'tool_calls': [{'name','arguments'(dict)}]}."""

def _post(url, headers, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e: raise LLMError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e: raise LLMError(f"Network error: {e.reason}")
    except OSError as e: raise LLMError(f"Connection error: {e}")
    try: return json.loads(raw)
    except ValueError: raise LLMError(f"Provider returned a non-JSON response (check LLM_BASE_URL and LLM_MODEL in .env): {raw[:200]!r}")

class OpenAICompatAdapter(LLMProviderAdapter):
    def __init__(self, key=None, model=None, base_url=None):
        self.key = key or config.LLM_API_KEY; self.model = model or config.LLM_MODEL
        self.base = (base_url or config.LLM_BASE_URL).rstrip("/")
    def generate(self, messages, tools=None, system=None):
        if not self.key: raise LLMError("LLM_API_KEY not set (see .env.example)")
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        body = {"model": self.model, "messages": msgs}
        if tools: body["tools"] = [{"type": "function", "function": t} for t in tools]
        data = _post(f"{self.base}/chat/completions", {"Authorization": f"Bearer {self.key}"}, body)
        try:
            msg = data["choices"][0]["message"]
            calls = [{"name": c["function"]["name"], "arguments": json.loads(c["function"]["arguments"] or "{}")}
                     for c in msg.get("tool_calls") or []]
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise LLMError(f"Unexpected response format from provider: {str(data)[:300]}")
        return {"text": msg.get("content") or "", "tool_calls": calls}

class AnthropicAdapter(LLMProviderAdapter):
    def __init__(self, key=None, model=None):
        self.key = key or config.LLM_API_KEY; self.model = model or config.LLM_MODEL
    def generate(self, messages, tools=None, system=None):
        if not self.key: raise LLMError("LLM_API_KEY not set (see .env.example)")
        body = {"model": self.model, "max_tokens": 1500, "messages": messages}
        if system: body["system"] = system
        if tools: body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
        data = _post("https://api.anthropic.com/v1/messages",
                     {"x-api-key": self.key, "anthropic-version": "2023-06-01"}, body)
        text = "".join(b.get("text", "") for b in data["content"] if b["type"] == "text")
        calls = [{"name": b["name"], "arguments": b["input"]} for b in data["content"] if b["type"] == "tool_use"]
        return {"text": text, "tool_calls": calls}

def get_adapter() -> LLMProviderAdapter:
    return AnthropicAdapter() if config.LLM_PROVIDER == "anthropic" else OpenAICompatAdapter()
