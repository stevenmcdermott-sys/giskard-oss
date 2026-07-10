"""Runs a vulnerability scan scenario-by-scenario, yielding progress events.

``Suite.run()`` (giskard-checks) only offers an all-or-nothing await with an
internal terminal progress bar and no external hook. To stream per-scenario
updates to a browser, this reimplements the same run loop `Suite.run` uses
internally (see giskard.checks.scenarios.suite), calling
``scenario.run(target=...)`` directly and yielding an event after each one
completes, then assembling the same ``SuiteResult`` at the end.

Attacker/Judge LLM caveat: only ``AdversarialScenarioGenerator`` accepts an
explicit ``generator=`` override reachable from here. Crescendo and GOAT's
internal per-turn attacker calls, and every LLM-judge check the generated
scenarios attach, fall back to giskard-checks' single process-global default
generator (see giskard.checks.settings) whenever no explicit generator was
given -- there is no separate "attacker" vs "judge" knob in the underlying
library. This runner sets that shared default to the Judge config (judge
correctness matters most for reported pass/fail results) so the Attacker
config's distinct effect is limited to the Adversarial scenario category.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from giskard.checks import (
    Scenario,
    ScenarioResult,
    SuiteResult,
    settings as checks_settings,
)
from giskard.scan.catalog import generate_suite
from giskard.scan.generators.adversarial import AdversarialScenarioGenerator
from giskard.scan.generators.crescendo import CrescendoAttackScenarioGenerator
from giskard.scan.generators.gcg import GCGInjectionScenarioGenerator
from giskard.scan.generators.goat import GOATAttackScenarioGenerator
from giskard.scan.generators.huggingface import HuggingFaceDatasetScenarioGenerator
from giskard.scan.generators.prompt_injection import PromptInjectionScenarioGenerator
from giskard.scan.registry import SuiteGeneratorRegistry

from .config import ScanRequest
from .llm import build_target, make_generator


def _build_generators(req: ScanRequest, attacker_generator: Any) -> list[Any]:
    registry = SuiteGeneratorRegistry()
    registry.register(AdversarialScenarioGenerator(generator=attacker_generator))
    registry.register(CrescendoAttackScenarioGenerator)
    registry.register(GOATAttackScenarioGenerator)
    registry.register(PromptInjectionScenarioGenerator)

    if req.include_dataset_generators:
        registry.register(
            HuggingFaceDatasetScenarioGenerator(
                repo_id="giskardai/do-not-answer-scenarios",
                repo_allow_commercial_use=False,
            )
        )
        registry.register(
            HuggingFaceDatasetScenarioGenerator(
                repo_id="giskardai/harmbench-scenarios",
                repo_allow_commercial_use=True,
            )
        )
        registry.register(GCGInjectionScenarioGenerator())

    return registry.generators(commercial_use=req.commercial_use)


def _scenario_event(
    index: int,
    total: int,
    scenario: Scenario[Any, Any, Any],
    result: ScenarioResult[Any],
) -> dict[str, Any]:
    return {
        "type": "scenario",
        "index": index,
        "total": total,
        "name": scenario.name,
        "status": result.status.value,
        "duration_ms": result.duration_ms,
        "tags": list(result.tags),
    }


async def _run_streaming(
    scenarios: list[Scenario[Any, Any, Any]],
    target_fn: Any,
    *,
    parallel: bool,
    max_concurrency: int | None,
) -> AsyncIterator[dict[str, Any] | list[ScenarioResult[Any]]]:
    """Yield a ``scenario`` event per completed scenario, then the final results list."""
    total = len(scenarios)
    results: list[ScenarioResult[Any] | None] = [None] * total

    if not parallel:
        for index, scenario in enumerate(scenarios):
            result = await scenario.run(target=target_fn, return_exception=True)
            results[index] = result
            yield _scenario_event(index, total, scenario, result)
        yield [r for r in results if r is not None]
        return

    semaphore = asyncio.Semaphore(max_concurrency) if max_concurrency else None
    queue: asyncio.Queue[tuple[int, Scenario[Any, Any, Any], ScenarioResult[Any]]] = (
        asyncio.Queue()
    )

    async def run_one(index: int, scenario: Scenario[Any, Any, Any]) -> None:
        if semaphore is not None:
            async with semaphore:
                result = await scenario.run(target=target_fn, return_exception=True)
        else:
            result = await scenario.run(target=target_fn, return_exception=True)
        results[index] = result
        await queue.put((index, scenario, result))

    async with asyncio.TaskGroup() as task_group:
        for index, scenario in enumerate(scenarios):
            task_group.create_task(run_one(index, scenario))

        for _ in range(total):
            index, scenario, result = await queue.get()
            yield _scenario_event(index, total, scenario, result)

    yield [r for r in results if r is not None]


async def run_scan(req: ScanRequest) -> AsyncIterator[dict[str, Any]]:
    """Execute a scan, yielding JSON-ready progress events.

    Event types: ``generated`` (scenario count known), ``scenario`` (one
    finished), ``done`` (final ``SuiteResult``, keyed ``result``).
    """
    attacker_generator = make_generator(req.attacker)
    judge_generator = make_generator(req.judge)
    target_generator = make_generator(req.target)
    target_fn = build_target(target_generator, req.target_system_prompt)

    generators = _build_generators(req, attacker_generator)

    previous_default = checks_settings._default_generator
    checks_settings.set_default_generator(judge_generator)
    try:
        suite = await generate_suite(
            description=req.description,
            languages=req.languages,
            generators=generators,
            max_scenarios=req.max_scenarios,
            seed=req.seed,
            target_mode=req.target_mode,
        )

        yield {"type": "generated", "total": len(suite.scenarios)}

        start = time.perf_counter()
        results: list[ScenarioResult[Any]] = []
        async for item in _run_streaming(
            suite.scenarios,
            target_fn,
            parallel=req.parallel,
            max_concurrency=req.max_concurrency,
        ):
            if isinstance(item, list):
                results = item
            else:
                yield item
        duration_ms = int((time.perf_counter() - start) * 1000)

        suite_result = SuiteResult(
            results=results, duration_ms=duration_ms, suite=suite
        )
        yield {"type": "done", "result": suite_result}
    finally:
        checks_settings._default_generator = previous_default
