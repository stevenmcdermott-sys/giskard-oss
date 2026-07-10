"""Request/response models for the scan API.

API keys are part of these models only in transit (request body, validated
and used for the duration of one scan); they are never persisted to disk or
a database. See app/llm.py for how they're wired into per-request provider
instances.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Provider = Literal["openai", "google", "anthropic", "azure", "azure_ai"]

PROVIDER_LABELS: dict[Provider, str] = {
    "openai": "OpenAI",
    "google": "Google (Gemini)",
    "anthropic": "Anthropic",
    "azure": "Azure OpenAI",
    "azure_ai": "Azure AI Foundry",
}


class LLMRoleConfig(BaseModel):
    provider: Provider
    model: str = Field(..., min_length=1)
    api_key: str = Field(..., min_length=1)
    base_url: str | None = None
    api_version: str | None = None

    @field_validator("model", "api_key")
    @classmethod
    def _strip_and_require(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ScanRequest(BaseModel):
    attacker: LLMRoleConfig
    judge: LLMRoleConfig
    target: LLMRoleConfig
    target_system_prompt: str = Field(..., min_length=1)

    description: str = Field(..., min_length=1)
    languages: list[str] = Field(..., min_length=1)
    target_mode: Literal["multiturn", "singleturn"] = "multiturn"

    max_scenarios: int | None = Field(default=None, ge=1)
    seed: int = 42
    group_by: str | None = "threat-type"
    commercial_use: bool = False
    include_dataset_generators: bool = False
    parallel: bool = True
    max_concurrency: int | None = Field(default=None, ge=1)

    @field_validator("languages")
    @classmethod
    def _clean_languages(cls, value: list[str]) -> list[str]:
        cleaned = [v.strip() for v in value if v.strip()]
        if not cleaned:
            raise ValueError("at least one language is required")
        return cleaned
