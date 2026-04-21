from __future__ import annotations

from pathlib import Path

import yaml


def test_daily_collect_audit_workflow_uses_admin_token_secret() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/daily-collect-audit.yml").read_text(encoding="utf-8"))

    assert "schedule" in workflow[True]
    job = workflow["jobs"]["collect-audit"]
    rendered = str(job)

    assert "PROMO_QUERY_BASE_URL" in rendered
    assert "ADMIN_TOKEN" in rendered
    assert "/admin/collect" in rendered
    assert "/admin/collect/status" in rendered
    assert "/admin/audit" in rendered
