from __future__ import annotations

from pathlib import Path

import yaml


def test_daily_workflow_uses_dst_crons_not_runner_start_hour_gate():
    repo_root = Path(__file__).resolve().parents[1]
    workflow_path = repo_root / ".github" / "workflows" / "daily-teams-report.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    crons = [entry["cron"] for entry in workflow["on"]["schedule"]]

    assert crons == ["37 23 * * *", "37 0 * * *"]
    assert "github.event.schedule" in workflow_text
    assert "LOCAL_HOUR" not in workflow_text
    assert "date +%H" not in workflow_text

