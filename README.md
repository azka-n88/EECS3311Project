# CulinaryMind AI (EECS3311 Stage 2)
AI meal-planning agent with GUI (Tkinter) and CLI sharing one `ServiceController`.

## Setup
1. Python 3.10+ (tkinter and sqlite3 ship with Python). `pip install -r requirements.txt` (pytest only).
2. `cp .env.example .env`, then put your key in `LLM_API_KEY` (never commit `.env`).
   - OpenAI-compatible (OpenAI, Gemini, Groq, OpenRouter, Ollama): set `LLM_PROVIDER=openai`, `LLM_BASE_URL`, `LLM_MODEL`.
   - Anthropic: `LLM_PROVIDER=anthropic`, `LLM_MODEL=<model name>`.

## Run
- CLI: `python -m culinarymind.cli pantry-add milk 1 l --expiry 2026-11-17`
- GUI: `python -m culinarymind.gui` (added in later commits)
- Tests: `pytest`

## CLI examples
    python -m culinarymind.cli pantry-add rice 2 cup
    python -m culinarymind.cli plan-set 1 dinner chicken_stirfry
    python -m culinarymind.cli grocery
    python -m culinarymind.cli export ics plan.ics
