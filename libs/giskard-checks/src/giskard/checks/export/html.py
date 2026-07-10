"""Self-contained static HTML report export for SuiteResult.

Produces a single HTML file with inline CSS/JS (no external requests, no
server) that can be opened directly in a browser to visually inspect a
suite run: summary counts, optional per-tag pass-rate breakdown, and
collapsible per-scenario detail (steps, checks, metrics, and final trace).
"""

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from ..core.result import (
    STATUS_MAPPING,
    CheckResult,
    ScenarioResult,
    SuiteResult,
    TestCaseResult,
)

_STATUS_CLASS = {
    "pass": "pass",
    "fail": "fail",
    "error": "error",
    "skip": "skip",
}

_STATUS_LABEL = {
    "pass": "PASSED",
    "fail": "FAILED",
    "error": "ERROR",
    "skip": "SKIPPED",
}


def _json_block(value: Any) -> str:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json", fallback=str)
    else:
        payload = value
    return escape(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _check_label(check: CheckResult, fallback: str) -> str:
    if isinstance(check.details, dict):
        return str(
            check.details.get("check_name")
            or check.details.get("check_kind")
            or check.details.get("name")
            or fallback
        )
    return fallback


def _render_metrics(check: CheckResult) -> str:
    if not check.metrics:
        return ""
    items = "".join(
        f'<span class="metric"><span class="metric-name">{escape(m.name)}</span>'
        f'<span class="metric-value">{m.value:g}</span></span>'
        for m in check.metrics
    )
    return f'<div class="metrics">{items}</div>'


def _render_check(check: CheckResult, check_idx: int) -> str:
    status = check.status.value
    label = escape(_check_label(check, f"check_{check_idx}"))
    message = escape(check.message) if check.message else ""
    details_html = (
        f'<details class="raw"><summary>details</summary><pre>{_json_block(check.details)}</pre></details>'
        if check.details
        else ""
    )
    return f"""
    <div class="check {_STATUS_CLASS[status]}">
      <div class="check-head">
        <span class="badge {_STATUS_CLASS[status]}">{_STATUS_LABEL[status]}</span>
        <span class="check-name">{label}</span>
      </div>
      {f'<div class="check-message">{message}</div>' if message else ""}
      {_render_metrics(check)}
      {details_html}
    </div>"""


def _render_step(step: TestCaseResult, step_idx: int) -> str:
    checks_html = "".join(
        _render_check(check, check_idx)
        for check_idx, check in enumerate(step.results, start=1)
    )
    return f"""
    <div class="step {_STATUS_CLASS[step.status.value]}">
      <div class="step-head">Step {step_idx} &middot; {step.duration_ms}ms</div>
      {checks_html}
    </div>"""


def _render_trace(trace: Any) -> str:
    interactions = getattr(trace, "interactions", None)
    if not isinstance(interactions, list) or not interactions:
        payload = (
            _json_block(trace) if hasattr(trace, "model_dump") else escape(repr(trace))
        )
        return f'<details class="raw"><summary>trace (raw)</summary><pre>{payload}</pre></details>'

    rows = []
    for idx, interaction in enumerate(interactions, start=1):
        inputs = escape(repr(getattr(interaction, "inputs", None)))
        outputs = escape(repr(getattr(interaction, "outputs", None)))
        rows.append(f"""
        <div class="interaction">
          <div class="interaction-idx">#{idx}</div>
          <div class="interaction-body">
            <div><span class="io-label">in</span><pre>{inputs}</pre></div>
            <div><span class="io-label">out</span><pre>{outputs}</pre></div>
          </div>
        </div>""")
    return "".join(rows)


def _render_scenario(scenario: ScenarioResult[Any]) -> str:
    status = scenario.status.value
    steps_html = "".join(
        _render_step(step, idx) for idx, step in enumerate(scenario.steps, start=1)
    )
    trace_html = _render_trace(scenario.final_trace)
    tags_html = "".join(f'<span class="tag">{escape(t)}</span>' for t in scenario.tags)
    runs = (
        f'<span class="runs">runs: {scenario.runs_executed}/{scenario.multiple_runs}</span>'
        if scenario.multiple_runs != 1
        else ""
    )

    return f"""
    <details class="scenario {_STATUS_CLASS[status]}" data-status="{status}"
              data-name="{escape(scenario.scenario_name.lower())}">
      <summary>
        <span class="badge {_STATUS_CLASS[status]}">{_STATUS_LABEL[status]}</span>
        <span class="scenario-name">{escape(scenario.scenario_name)}</span>
        <span class="scenario-meta">{scenario.duration_ms}ms {runs}</span>
        <span class="tags">{tags_html}</span>
      </summary>
      <div class="scenario-body">
        <div class="steps">{steps_html}</div>
        <div class="trace">
          <h4>Final trace</h4>
          {trace_html}
        </div>
      </div>
    </details>"""


def _render_group_table(result: SuiteResult, group_by: str) -> str:
    grouped = result.group_by(group_by)
    rows = []
    for group_value, stats in grouped.groups.items():
        if group_value is None:
            name = "(untagged)"
        elif group_value == "":
            name = "true"
        else:
            name = group_value
        rate = (
            f"{stats.passed} / {stats.non_skipped}"
            if stats.pass_rate is not None
            else "—"
        )
        pct = f"{stats.pass_rate:.0%}" if stats.pass_rate is not None else ""
        rows.append(f"""
        <tr>
          <td>{escape(name)}</td>
          <td>{escape(rate)}</td>
          <td>{escape(pct)}</td>
        </tr>""")

    return f"""
    <table class="group-table">
      <thead><tr><th>{escape(group_by)}</th><th>Pass rate</th><th></th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""


def _render_recommendation(recommendation: str | None) -> str:
    if not recommendation or not recommendation.strip():
        return ""
    return f"""
    <div class="recommendation">
      <h3>Recommendation</h3>
      <pre>{escape(recommendation)}</pre>
    </div>"""


_CSS = """
:root {
  color-scheme: light dark;
  --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280; --border: #e5e7eb;
  --card: #f9fafb; --pass: #16a34a; --fail: #dc2626; --error: #d97706; --skip: #6b7280;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af; --border: #2a2e37; --card: #171a21; }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem; background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 14px; line-height: 1.5;
}
h1 { font-size: 1.4rem; margin: 0 0 0.25rem; }
h3, h4 { margin: 0.5rem 0; }
.subtitle { color: var(--muted); margin-bottom: 1.5rem; }
.summary { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
.stat {
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 0.6rem 1rem; min-width: 90px;
}
.stat .n { font-size: 1.3rem; font-weight: 600; display: block; }
.stat .l { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.03em; }
.stat.pass .n { color: var(--pass); }
.stat.fail .n { color: var(--fail); }
.stat.error .n { color: var(--error); }
.stat.skip .n { color: var(--skip); }
.toolbar { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }
.toolbar input[type=search] {
  flex: 1; min-width: 200px; padding: 0.4rem 0.7rem; border-radius: 6px;
  border: 1px solid var(--border); background: var(--bg); color: var(--fg);
}
.filter-btn {
  padding: 0.35rem 0.8rem; border-radius: 6px; border: 1px solid var(--border);
  background: var(--card); color: var(--fg); cursor: pointer; font-size: 0.85rem;
}
.filter-btn.active { border-color: var(--fg); font-weight: 600; }
.badge {
  display: inline-block; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.7rem;
  font-weight: 700; letter-spacing: 0.02em; color: #fff;
}
.badge.pass { background: var(--pass); }
.badge.fail { background: var(--fail); }
.badge.error { background: var(--error); }
.badge.skip { background: var(--skip); }
.group-table { border-collapse: collapse; margin-bottom: 1.5rem; width: 100%; max-width: 480px; }
.group-table th, .group-table td {
  text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid var(--border);
}
.recommendation {
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 0.75rem 1rem; margin-bottom: 1.5rem;
}
.recommendation pre { white-space: pre-wrap; margin: 0; font-family: inherit; }
.scenario {
  border: 1px solid var(--border); border-radius: 8px; margin-bottom: 0.6rem;
  background: var(--card); overflow: hidden;
}
.scenario summary {
  cursor: pointer; padding: 0.6rem 0.9rem; display: flex; align-items: center;
  gap: 0.6rem; list-style: none;
}
.scenario summary::-webkit-details-marker { display: none; }
.scenario summary::before { content: "\\25b8"; color: var(--muted); }
.scenario[open] summary::before { content: "\\25be"; }
.scenario-name { font-weight: 600; }
.scenario-meta { color: var(--muted); font-size: 0.8rem; margin-left: auto; }
.tags { display: flex; gap: 0.3rem; }
.tag {
  background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
  padding: 0.05rem 0.4rem; font-size: 0.7rem; color: var(--muted);
}
.scenario-body { padding: 0 0.9rem 0.9rem; border-top: 1px solid var(--border); }
.step { margin-top: 0.6rem; }
.step-head { color: var(--muted); font-size: 0.75rem; margin-bottom: 0.3rem; }
.check {
  border-left: 3px solid var(--border); padding: 0.3rem 0.6rem; margin-bottom: 0.3rem;
  background: var(--bg); border-radius: 0 4px 4px 0;
}
.check.pass { border-left-color: var(--pass); }
.check.fail { border-left-color: var(--fail); }
.check.error { border-left-color: var(--error); }
.check.skip { border-left-color: var(--skip); }
.check-head { display: flex; align-items: center; gap: 0.5rem; }
.check-name { font-weight: 600; }
.check-message { color: var(--muted); margin-top: 0.15rem; }
.metrics { margin-top: 0.3rem; display: flex; gap: 0.5rem; flex-wrap: wrap; }
.metric {
  font-size: 0.75rem; background: var(--card); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.05rem 0.4rem;
}
.metric-name { color: var(--muted); margin-right: 0.3rem; }
details.raw { margin-top: 0.3rem; }
details.raw summary { cursor: pointer; color: var(--muted); font-size: 0.75rem; }
pre {
  background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
  padding: 0.5rem; overflow-x: auto; font-size: 0.75rem; margin: 0.3rem 0 0;
}
.trace { margin-top: 0.8rem; }
.interaction { display: flex; gap: 0.6rem; margin-bottom: 0.4rem; }
.interaction-idx { color: var(--muted); font-size: 0.75rem; padding-top: 0.2rem; }
.interaction-body { flex: 1; }
.io-label {
  display: inline-block; color: var(--muted); font-size: 0.7rem; text-transform: uppercase;
  margin-bottom: 0.1rem;
}
.hidden { display: none !important; }
"""

_JS = """
(function () {
  var search = document.getElementById('scenario-search');
  var buttons = document.querySelectorAll('.filter-btn');
  var scenarios = document.querySelectorAll('.scenario');
  var activeStatus = 'all';

  function applyFilters() {
    var term = (search.value || '').toLowerCase();
    scenarios.forEach(function (el) {
      var matchesStatus = activeStatus === 'all' || el.dataset.status === activeStatus;
      var matchesTerm = !term || el.dataset.name.indexOf(term) !== -1;
      el.classList.toggle('hidden', !(matchesStatus && matchesTerm));
    });
  }

  buttons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      buttons.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      activeStatus = btn.dataset.status;
      applyFilters();
    });
  });

  search.addEventListener('input', applyFilters);
})();
"""


def to_html(
    result: SuiteResult,
    path: str | Path | None = None,
    *,
    group_by: str | None = None,
    title: str = "Giskard Suite Report",
) -> str:
    """Render a suite result as a self-contained static HTML report.

    The report has no external dependencies (inline CSS/JS only) and can be
    opened directly in a browser. It includes summary counts, an optional
    per-tag pass-rate table, and collapsible per-scenario detail with steps,
    checks, metrics, and the final trace.

    Parameters
    ----------
    result : SuiteResult
        The suite result to render.
    path : str | Path | None
        If given, the HTML is also written to this path (parent directories
        are created as needed).
    group_by : str | None
        Tag key to group by (e.g. ``"Category"``). When set, a per-group
        pass-rate table is included after the summary.
    title : str
        Report title shown in the page header and ``<title>``.

    Returns
    -------
    str
        The rendered HTML document.
    """
    generated_at = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )

    stats = [
        ("total", len(result.results)),
        ("pass", result.passed_count),
        ("fail", result.failed_count),
        ("error", result.errored_count),
        ("skip", result.skipped_count),
    ]
    stats_html = "".join(
        f'<div class="stat {_STATUS_CLASS.get(key, "")}"><span class="n">{count}</span>'
        f'<span class="l">{STATUS_MAPPING[key]["title"] if key != "total" else "Total"}</span></div>'
        for key, count in stats
    )

    group_table_html = _render_group_table(result, group_by) if group_by else ""
    scenarios_html = "".join(_render_scenario(s) for s in result.results)
    recommendation_html = _render_recommendation(result.recommendation)

    filter_buttons = "".join(
        f'<button class="filter-btn{" active" if status == "all" else ""}" data-status="{status}">{label}</button>'
        for status, label in (
            ("all", "All"),
            ("pass", "Passed"),
            ("fail", "Failed"),
            ("error", "Errored"),
            ("skip", "Skipped"),
        )
    )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <div class="subtitle">
    Generated {generated_at} &middot; Pass rate {result.pass_rate:.1%}
    &middot; Duration {result.duration_ms}ms
  </div>

  <div class="summary">{stats_html}</div>

  {group_table_html}
  {recommendation_html}

  <div class="toolbar">
    {filter_buttons}
    <input type="search" id="scenario-search" placeholder="Filter scenarios by name&hellip;">
  </div>

  <div class="scenarios">{scenarios_html}</div>

  <script>{_JS}</script>
</body>
</html>"""

    if path is not None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_doc, encoding="utf-8")

    return html_doc
