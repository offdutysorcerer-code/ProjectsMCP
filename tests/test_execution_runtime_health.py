from __future__ import annotations

import unittest

from services.execution_runtime_health import ExecutionRuntimeHealthAggregator


class ExecutionRuntimeHealthAggregatorTests(unittest.TestCase):
    def test_aggregates_retained_command_runtime_results(self) -> None:
        health = ExecutionRuntimeHealthAggregator.aggregate([
            {
                "tool": "run_powershell",
                "status": "completed",
                "resultSummary": {
                    "ok": True,
                    "shell": "powershell",
                    "classification": {"code": "success"},
                    "recovery": {"attempted": False, "retry_count": 0},
                    "known_issues": {
                        "prevented": [
                            {"rule_id": "ps-cmd-cd-d-to-set-location-v1"},
                        ]
                    },
                },
            },
            {
                "tool": "run_powershell",
                "status": "completed",
                "resultSummary": {
                    "ok": False,
                    "shell": "powershell",
                    "timed_out": True,
                    "process_tree_terminated": True,
                    "classification": {"code": "timeout"},
                    "recovery": {"attempted": False, "retry_count": 0},
                    "known_issues": {"prevented": []},
                },
            },
            {
                "tool": "run_cmd",
                "status": "completed",
                "resultSummary": {
                    "ok": True,
                    "shell": "cmd",
                    "classification": {"code": "success_with_stderr"},
                    "recovery": {"attempted": True, "retry_count": 1},
                    "known_issues": {"prevented": []},
                },
            },
            {"tool": "git_status", "status": "completed", "resultSummary": {"ok": True}},
            {"tool": "run_command", "status": "running", "parameters": {"shell": "cmd"}},
        ])

        self.assertEqual(health["total"], 3)
        self.assertEqual(health["running"], 1)
        self.assertEqual(health["success"], 2)
        self.assertEqual(health["failed"], 1)
        self.assertEqual(health["successRate"], 0.6667)
        self.assertEqual(health["timeouts"], 1)
        self.assertEqual(health["processTreesTerminated"], 1)
        self.assertEqual(health["recoveries"], 1)
        self.assertEqual(health["retries"], 1)
        self.assertEqual(health["knownIssuesPrevented"], 1)
        self.assertEqual(health["byShell"]["powershell"]["total"], 2)
        self.assertEqual(health["byShell"]["cmd"]["total"], 1)
        self.assertEqual(health["classifications"][0], {"code": "success", "count": 1})
        self.assertEqual(
            health["knownIssueRules"],
            [{"ruleId": "ps-cmd-cd-d-to-set-location-v1", "count": 1}],
        )

    def test_empty_window_has_no_fake_success_rate(self) -> None:
        health = ExecutionRuntimeHealthAggregator.aggregate([])
        self.assertEqual(health["total"], 0)
        self.assertIsNone(health["successRate"])
        self.assertEqual(health["classifications"], [])


if __name__ == "__main__":
    unittest.main()
