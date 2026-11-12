"""Sprint KPIs calculated from Sprint Review (Ingestion button) and shown in the Workbook step."""
from datetime import datetime
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import kpi_helpers as kh

PAGE = str(Path(__file__).resolve().parents[1] / "tools" / "2_Sprint_Review.py")


def _fake_result(**overrides):
    df = pd.DataFrame([
        {"Key": "P-1", "Story Points": 5.0, "Resolved": True, "Is Bug": False, "Cycle Time (Days)": 2.0},
        {"Key": "P-2", "Story Points": 3.0, "Resolved": False, "Is Bug": True, "Cycle Time (Days)": None},
        {"Key": "P-3", "Story Points": 2.0, "Resolved": True, "Is Bug": True, "Cycle Time (Days)": 4.0},
    ])
    res = {
        "df": df, "gh_added_keys": ["P-3"],
        "scope_counts": {kh.ITEMS_COMMITTED_KPI: 2, kh.ITEMS_ADDED_KPI: 1, kh.ITEMS_DELIVERED_KPI: 2},
        "sprint_start": datetime(2026, 10, 5), "sprint_end": datetime(2026, 10, 16),
        "sprint_name": "Sprint 42", "releases_count": 1, "global_open_bugs": 4, "global_critical_bugs": 1,
    }
    res.update(overrides)
    return res


def test_helper_computes_jira_metrics(monkeypatch):
    calls = {}

    def fake_fetch(server, token, auth_type, email, sprint_query, selected_types):
        calls.update(sprint=sprint_query, types=selected_types)
        return _fake_result()

    monkeypatch.setattr(kh, "fetch_sprint_kpi_data", fake_fetch)
    metrics, error, warnings = kh.calculate_current_sprint_metrics("s", "t", "a", "e", " 42 ", ["Bug"])

    assert error is None and warnings == []
    assert calls == {"sprint": "42", "types": ["Bug"]}
    assert metrics["sprint_name"] == "Sprint 42"
    assert metrics["dates"] == "2026-10-05 to 2026-10-16"
    assert metrics["total_sp"] == "8" and metrics["achieved_sp"] == "7"
    assert metrics["items"][kh.ITEMS_COMMITTED_KPI] == "2"
    assert metrics["open_bugs"] == "4" and metrics["crit_bugs"] == "1"
    assert metrics["quality"] == {}


def test_helper_reports_errors(monkeypatch):
    assert kh.calculate_current_sprint_metrics("s", "t", "a", "e", "  ", [])[1]
    monkeypatch.setattr(kh, "fetch_sprint_kpi_data", lambda *a: {"error": "401 Unauthorized"})
    assert kh.calculate_current_sprint_metrics("s", "t", "a", "e", "42", [])[:2] == (None, "401 Unauthorized")
    monkeypatch.setattr(kh, "fetch_sprint_kpi_data", lambda *a: _fake_result(df=pd.DataFrame()))
    metrics, error, _ = kh.calculate_current_sprint_metrics("s", "t", "a", "e", "42", [])
    assert metrics is None and "No issues" in error


def test_helper_blanks_jira_kpis_when_source_off(monkeypatch):
    monkeypatch.setattr(kh, "fetch_sprint_kpi_data", lambda *a: _fake_result())
    metrics, _, _ = kh.calculate_current_sprint_metrics("s", "t", "a", "e", "42", [], jira_enabled=False)
    assert metrics["total_sp"] == "" and metrics["dates"] == "2026-10-05 to 2026-10-16"
    assert metrics["sprint_name"] == "Sprint 42"


def test_ingestion_button_calculates_kpis(monkeypatch):
    monkeypatch.setattr(kh, "fetch_sprint_kpi_data", lambda *a: _fake_result())
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    at.text_input(key="sr_kpi_sprint_widget").set_value("42").run()
    at.button(key="btn_calc_sprint_kpis").click().run()

    assert not at.exception
    assert at.session_state["current_sprint_metrics"]["sprint_name"] == "Sprint 42"
    assert any("Sprint 42" in s.value for s in at.success)


def test_workbook_shows_calculated_kpis():
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["current_sprint_metrics"] = {
        "sprint_name": "Sprint 42", "dates": "2026-10-05 to 2026-10-16", "total_sp": "8",
        "items": {kh.ITEMS_COMMITTED_KPI: "2"}, "quality": {},
    }
    at.session_state["active_tab"] = "✍️ Workbook"
    at.run()

    assert not at.exception
    labels = {m.label: m.value for m in at.metric}
    assert labels.get("Committed SP (at Start)") == "8"
    assert labels.get("Committed") == "2"


def test_workbook_without_kpis_points_to_ingestion():
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["active_tab"] = "✍️ Workbook"
    at.run()
    assert not at.exception
    assert any("Calculate Sprint KPIs" in i.value for i in at.info)
