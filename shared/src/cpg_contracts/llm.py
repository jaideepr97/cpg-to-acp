"""Shared LLM client factory with retry and timeout configuration."""

from langchain_openai import ChatOpenAI

LLM_MAX_RETRIES = 5
LLM_REQUEST_TIMEOUT = 120


def get_llm(state: dict) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=f"{state.get('litellm_url', 'http://localhost:4000')}/v1",
        api_key=state.get("llm_api_key", "sk-change-me"),
        model=state.get("llm_model", "default"),
        max_retries=LLM_MAX_RETRIES,
        request_timeout=LLM_REQUEST_TIMEOUT,
    )
