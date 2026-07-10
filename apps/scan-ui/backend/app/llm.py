"""Per-request LLM wiring.

giskard-llm's provider routing (``giskard.llm.configure``) and
giskard-checks' default-generator override (``set_default_generator``) are
both process-global state, not request-scoped. To keep concurrent requests'
credentials from clobbering each other, each role gets a uniquely-aliased
provider registration for the lifetime of one scan.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from giskard import llm as giskard_llm
from giskard.agents import BaseGenerator, Generator
from giskard.checks import Trace

from .config import LLMRoleConfig


def _provider_kwargs(cfg: LLMRoleConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"api_key": cfg.api_key}
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url
    if cfg.api_version and cfg.provider in ("azure", "azure_ai"):
        kwargs["api_version"] = cfg.api_version
    return kwargs


def make_generator(cfg: LLMRoleConfig) -> BaseGenerator:
    """Build a generator wired to this request's own credentials.

    Registers a uniquely-aliased provider config so this request's API key
    can't be read or overwritten by a concurrent request sharing the same
    provider type.
    """
    alias = f"{cfg.provider}-{uuid.uuid4().hex[:12]}"
    giskard_llm.configure(alias, provider=cfg.provider, **_provider_kwargs(cfg))
    return Generator(model=f"{alias}/{cfg.model}")


def build_target(
    target_generator: BaseGenerator, system_prompt: str
) -> Callable[[str, Trace[str, str]], Awaitable[str]]:
    """Wrap a generator + system prompt as a scan Target.

    Reconstructs the conversation from the scan's accumulated trace on every
    call, since the target LLM itself is stateless between turns.
    """

    async def target(inputs: str, trace: Trace[str, str]) -> str:
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for interaction in trace.interactions:
            messages.append({"role": "user", "content": str(interaction.inputs)})
            messages.append({"role": "assistant", "content": str(interaction.outputs)})
        messages.append({"role": "user", "content": inputs})

        response = await target_generator.complete(messages)
        return response.choices[0].message.text or ""

    return target
