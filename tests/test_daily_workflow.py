from __future__ import annotations

from pathlib import Path

import yaml


def test_daily_workflow_uses_weekday_dst_crons_not_runner_start_hour_gate():
    repo_root = Path(__file__).resolve().parents[1]
    workflow_path = repo_root / ".github" / "workflows" / "daily-teams-report.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    crons = [entry["cron"] for entry in workflow["on"]["schedule"]]
    dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]

    assert crons == ["37 23 * * 0-4", "37 0 * * 1-5"]
    assert dispatch_inputs["report_date"]["type"] == "string"
    assert "github.event.schedule" in workflow_text
    assert 'EXPECTED_SCHEDULE="37 0 * * 1-5"' in workflow_text
    assert 'EXPECTED_SCHEDULE="37 23 * * 0-4"' in workflow_text
    assert "DISPATCH_REPORT_DATE" in workflow_text
    assert 'REPORT_DATE_OPTION="--as-of"' in workflow_text
    assert 'REPORT_DATE_OPTION="--report-date"' in workflow_text
    assert "LOCAL_HOUR" not in workflow_text
    assert "date +%H" not in workflow_text

