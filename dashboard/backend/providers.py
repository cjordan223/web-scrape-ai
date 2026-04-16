"""Static registry of supported LLM providers."""

PROVIDERS: dict[str, dict] = {
    "ollama": {
        "label": "Ollama (Local)",
        "base_url": "http://localhost:11434",
        "auth": None,
        "notes": "Local inference via Ollama. No API key required.",
    },
    "mlx": {
        "label": "MLX (Apple Silicon)",
        "base_url": "http://localhost:8080",
        "auth": None,
        "notes": "Local inference via mlx-lm server. 2x faster on Apple Silicon.",
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "auth": "bearer",
        "notes": "Free tier: 15 RPM, 1M tokens/day.",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "auth": "bearer",
        "notes": "Free tier: 30 RPM, generous daily limits.",
    },
    "mistral": {
        "label": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "auth": "bearer",
        "notes": "Free models available (e.g., mistral-small).",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "auth": "bearer",
        "notes": "Aggregator. Many free models available.",
    },
    "together": {
        "label": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "auth": "bearer",
        "notes": "Free credits on signup.",
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)",
        "base_url": "",
        "auth": "bearer",
        "notes": "Any OpenAI-compatible endpoint.",
    },
}
