from __future__ import annotations

import json
import unittest
from pathlib import Path


class KnownIssueSeedCoverageTests(unittest.TestCase):
    def test_historical_issue_backlog_is_seeded(self) -> None:
        path = Path(__file__).resolve().parents[1] / "known_issues.json"
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        codes = {str(item.get("issue_code")) for item in payload.get("rules", [])}
        required = {
            "execution_policy",
            "command_not_found",
            "path_environment_drift",
            "utf8_encoding",
            "unbalanced_double_quote",
            "missing_cwd",
            "powershell_version_incompatible",
            "timeout",
            "orphan_process",
            "module_not_found",
            "cmd_syntax_in_powershell",
            "shell_syntax_mismatch",
            "prefer_structured_file_edit",
        }
        self.assertTrue(required.issubset(codes), required - codes)

    def test_high_risk_issues_are_not_auto_rewrite_rules(self) -> None:
        path = Path(__file__).resolve().parents[1] / "known_issues.json"
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        by_code = {str(item.get("issue_code")): item for item in payload.get("rules", [])}
        for code in ("timeout", "orphan_process", "module_not_found", "unbalanced_double_quote"):
            self.assertNotEqual(by_code[code].get("mode"), "preventive")


if __name__ == "__main__":
    unittest.main()
