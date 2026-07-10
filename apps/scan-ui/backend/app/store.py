"""Tiny in-memory store for recently completed scan results.

Lets the browser fetch the downloadable static HTML report after a scan
finishes streaming. Ephemeral by design: process memory only, bounded size,
cleared on restart -- there is no user data worth persisting across
deploys, and scan results may embed content from the target/attacker LLMs.
"""

from collections import OrderedDict

from giskard.checks import SuiteResult

_MAX_ENTRIES = 10

_results: "OrderedDict[str, SuiteResult]" = OrderedDict()


def put(scan_id: str, result: SuiteResult) -> None:
    _results[scan_id] = result
    _results.move_to_end(scan_id)
    while len(_results) > _MAX_ENTRIES:
        _results.popitem(last=False)


def get(scan_id: str) -> SuiteResult | None:
    return _results.get(scan_id)
