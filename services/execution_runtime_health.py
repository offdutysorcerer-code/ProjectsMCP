from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


_COMMAND_TOOLS = {"run_command", "run_cmd", "run_powershell"}
_SUCCESS_CLASSIFICATIONS = {"success", "success_with_stderr"}


class ExecutionRuntimeHealthAggregator:
    """Build a UI-neutral health summary from retained command tool telemetry."""

    @staticmethod
    def aggregate(tool_executions: Iterable[dict[str, Any]]) -> dict[str, Any]:
        items = [item for item in tool_executions if str(item.get("tool") or "") in _COMMAND_TOOLS]
        terminal = [item for item in items if str(item.get("status") or "") != "running"]
        classification_counts: Counter[str] = Counter()
        rule_counts: Counter[str] = Counter()
        shell_counts: dict[str, Counter[str]] = {}
        successes = failures = timeouts = terminated = recoveries = retries = prevented = 0

        for item in terminal:
            summary = item.get("resultSummary") if isinstance(item.get("resultSummary"), dict) else {}
            classification = summary.get("classification") if isinstance(summary.get("classification"), dict) else {}
            code = str(classification.get("code") or "unknown")
            classification_counts[code] += 1

            shell = str(summary.get("shell") or item.get("parameters", {}).get("shell") or "")
            if not shell:
                tool = str(item.get("tool") or "")
                shell = "powershell" if tool == "run_powershell" else "cmd" if tool == "run_cmd" else "unknown"
            bucket = shell_counts.setdefault(shell, Counter())
            bucket["total"] += 1

            is_success = bool(summary.get("ok")) or code in _SUCCESS_CLASSIFICATIONS
            if is_success:
                successes += 1
                bucket["success"] += 1
            else:
                failures += 1
                bucket["failed"] += 1

            if bool(summary.get("timed_out")) or code == "timeout":
                timeouts += 1
                bucket["timeouts"] += 1
            if bool(summary.get("process_tree_terminated")):
                terminated += 1

            recovery = summary.get("recovery") if isinstance(summary.get("recovery"), dict) else {}
            if bool(recovery.get("attempted")):
                recoveries += 1
            retries += int(recovery.get("retry_count") or 0)

            known_issues = summary.get("known_issues") if isinstance(summary.get("known_issues"), dict) else {}
            prevented_rules = known_issues.get("prevented") if isinstance(known_issues.get("prevented"), list) else []
            prevented += len(prevented_rules)
            for hit in prevented_rules:
                if isinstance(hit, dict):
                    rule_id = str(hit.get("rule_id") or hit.get("ruleId") or "unknown")
                    rule_counts[rule_id] += 1

        total = len(terminal)
        return {
            "scope": "retained_command_tool_executions",
            "retainedLimitNote": "Computed from retained RuntimeTelemetry toolExecutions, not lifetime history.",
            "total": total,
            "running": len(items) - total,
            "success": successes,
            "failed": failures,
            "successRate": round(successes / total, 4) if total else None,
            "timeouts": timeouts,
            "processTreesTerminated": terminated,
            "recoveries": recoveries,
            "retries": retries,
            "knownIssuesPrevented": prevented,
            "byShell": {
                shell: {
                    "total": counts["total"],
                    "success": counts["success"],
                    "failed": counts["failed"],
                    "timeouts": counts["timeouts"],
                }
                for shell, counts in sorted(shell_counts.items())
            },
            "classifications": [
                {"code": code, "count": count}
                for code, count in classification_counts.most_common()
            ],
            "knownIssueRules": [
                {"ruleId": rule_id, "count": count}
                for rule_id, count in rule_counts.most_common()
            ],
        }
