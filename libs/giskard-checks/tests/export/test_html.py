from pathlib import Path

from giskard.checks import (
    CheckResult,
    CheckStatus,
    Interaction,
    Metric,
    ScenarioResult,
    SuiteResult,
    TestCaseResult,
    Trace,
)
from giskard.checks.export.html import to_html
from giskard.checks.scenarios.suite import Suite


def _sample_suite_result() -> SuiteResult:
    return SuiteResult(
        results=[
            ScenarioResult(
                scenario_name="scenario_pass",
                steps=[
                    TestCaseResult(
                        results=[
                            CheckResult(
                                status=CheckStatus.PASS,
                                message="grounded",
                                metrics=[Metric(name="score", value=0.95)],
                                details={"check_name": "Groundedness"},
                            ),
                        ],
                        duration_ms=100,
                    )
                ],
                duration_ms=100,
                final_trace=Trace(
                    interactions=[
                        Interaction(inputs="Hello", outputs="Hi there!"),
                    ]
                ),
                tags=["Category:Hallucination"],
            ),
            ScenarioResult(
                scenario_name="scenario_fail",
                steps=[
                    TestCaseResult(
                        results=[
                            CheckResult(
                                status=CheckStatus.FAIL,
                                message="answer is not grounded",
                                metrics=[Metric(name="confidence", value=0.2)],
                                details={"check_name": "Groundedness"},
                            ),
                        ],
                        duration_ms=120,
                    )
                ],
                duration_ms=120,
                final_trace=Trace(),
                tags=["Category:Hallucination"],
            ),
            ScenarioResult(
                scenario_name="scenario_error",
                steps=[
                    TestCaseResult(
                        results=[
                            CheckResult(
                                status=CheckStatus.ERROR,
                                message="judge crashed",
                                details={"check_name": "LLMJudge"},
                            )
                        ],
                        duration_ms=150,
                    )
                ],
                duration_ms=150,
                final_trace=Trace(),
            ),
            ScenarioResult(
                scenario_name="scenario_skip",
                steps=[
                    TestCaseResult(
                        results=[
                            CheckResult(
                                status=CheckStatus.SKIP,
                                message="no retrieved context",
                                details={"check_name": "ContextRelevance"},
                            )
                        ],
                        duration_ms=50,
                    )
                ],
                duration_ms=50,
                final_trace=Trace(),
            ),
        ],
        duration_ms=420,
        suite=Suite(name="test"),
        recommendation="Investigate the **grounding** failures first.",
    )


def test_to_html_is_well_formed_and_self_contained() -> None:
    html_doc = to_html(_sample_suite_result())

    assert html_doc.startswith("<!doctype html>")
    assert "<html" in html_doc and "</html>" in html_doc
    # No external network requests: no CDN links, no remote script/link tags.
    assert "http://" not in html_doc
    assert "https://" not in html_doc


def test_to_html_includes_summary_counts() -> None:
    html_doc = to_html(_sample_suite_result())

    assert ">4</span>" in html_doc  # total
    assert "33.3%" in html_doc  # pass rate: 1 passed / 3 non-skipped


def test_to_html_includes_all_scenario_names_and_statuses() -> None:
    html_doc = to_html(_sample_suite_result())

    for name in ("scenario_pass", "scenario_fail", "scenario_error", "scenario_skip"):
        assert name in html_doc

    assert 'data-status="pass"' in html_doc
    assert 'data-status="fail"' in html_doc
    assert 'data-status="error"' in html_doc
    assert 'data-status="skip"' in html_doc


def test_to_html_renders_check_messages_and_metrics() -> None:
    html_doc = to_html(_sample_suite_result())

    assert "grounded" in html_doc
    assert "answer is not grounded" in html_doc
    assert "score" in html_doc
    assert "0.95" in html_doc


def test_to_html_renders_interactions_from_trace() -> None:
    html_doc = to_html(_sample_suite_result())

    assert "Hello" in html_doc
    assert "Hi there!" in html_doc


def test_to_html_renders_recommendation() -> None:
    html_doc = to_html(_sample_suite_result())

    assert "Recommendation" in html_doc
    assert "grounding" in html_doc


def test_to_html_group_by_renders_group_table() -> None:
    html_doc = to_html(_sample_suite_result(), group_by="Category")

    assert "group-table" in html_doc
    assert "Hallucination" in html_doc
    assert "(untagged)" in html_doc


def test_to_html_escapes_untrusted_content() -> None:
    result = SuiteResult(
        results=[
            ScenarioResult(
                scenario_name="<script>alert(1)</script>",
                steps=[
                    TestCaseResult(
                        results=[
                            CheckResult(
                                status=CheckStatus.FAIL,
                                message="<img src=x onerror=alert(2)>",
                                details={"check_name": "XSS"},
                            )
                        ],
                        duration_ms=10,
                    )
                ],
                duration_ms=10,
                final_trace=Trace(),
            )
        ],
        duration_ms=10,
    )

    html_doc = to_html(result)

    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;" in html_doc
    assert "<img src=x onerror=alert(2)>" not in html_doc


def test_to_html_writes_file(tmp_path: Path) -> None:
    output_path = tmp_path / "report.html"

    html_doc = to_html(_sample_suite_result(), path=output_path)

    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == html_doc


def test_suite_result_convenience_method_matches_function() -> None:
    suite_result = _sample_suite_result()

    html_from_method = suite_result.to_html()
    html_from_function = to_html(suite_result)

    assert html_from_method == html_from_function
