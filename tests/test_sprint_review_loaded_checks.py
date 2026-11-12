"""Sprint Review Ingestion: a green check stays under every loader while its data is loaded."""
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

PAGE = str(Path(__file__).resolve().parents[1] / "tools" / "2_Sprint_Review.py")


def _checks(at):
    return [m.value for m in at.markdown if "✅" in m.value]


def test_no_checks_when_nothing_is_loaded():
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    assert not at.exception
    assert _checks(at) == []


def test_checks_for_every_loaded_dataset():
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["overview_df"] = pd.DataFrame({"Key": ["P-1", "P-2"]})
    at.session_state["outlook_df"] = pd.DataFrame({"Key": ["P-3"]})
    at.session_state["custom_tables"] = [
        {"title": "Epics Q4", "table_type": "quarterly_epic_progress", "df": pd.DataFrame({"Key": ["E-1"] * 3})},
        {"title": "Special Project Metrics", "df": pd.DataFrame({"Key": ["X-1"] * 4})},
    ]
    at.session_state["current_sprint_metrics"] = {"sprint_name": "Sprint 42", "dates": "2026-10-05 to 2026-10-16"}
    at.run()

    assert not at.exception
    checks = " | ".join(_checks(at))
    assert "2 Overview tickets loaded" in checks
    assert "1 Outlook tickets loaded" in checks
    assert "3 committed Epics loaded" in checks
    assert "KPIs calculated for Sprint 42" in checks
    assert "Custom table 'Special Project Metrics' loaded (4 rows)" in checks
