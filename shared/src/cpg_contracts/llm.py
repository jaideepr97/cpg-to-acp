"""Shared LLM client factory with retry and timeout configuration."""

from langchain_openai import ChatOpenAI

LLM_MAX_RETRIES = 5
LLM_REQUEST_TIMEOUT = 120


def get_llm(state: dict) -> ChatOpenAI:
    """Build an LLM client from pipeline state.

    state['litellm_url'] must be the bare origin (e.g. 'http://localhost:4000')
    — this function appends '/v1'. Do not include '/v1' in the config value.
    """
    return ChatOpenAI(
        base_url=f"{state.get('litellm_url', 'http://localhost:4000')}/v1",
        api_key=state.get("llm_api_key", "sk-change-me"),
        model=state.get("llm_model", "default"),
        use_responses_api=True,
        max_retries=LLM_MAX_RETRIES,
        request_timeout=LLM_REQUEST_TIMEOUT,
    )
