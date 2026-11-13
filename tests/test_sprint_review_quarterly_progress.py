import pandas as pd
import pytest
from reportlab.graphics.shapes import Drawing, Circle, Wedge
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from utils.pdf_helpers import build_custom_extra_table_pdf_block
from utils.quarterly_planner_helpers import PROGRESS_COUNTS_COLUMN, quarterly_progress_table_view


def test_quarterly_rendering_is_scoped_to_epic_table():
    df = pd.DataFrame([{"Key": "EPIC-1", "Completion": "67%", "To Do": 3,
                        "In progress": 5, "Closed / Resolved": 12}])
    original = df.copy(deep=True)
    for quarterly in (False, True):
        table = build_custom_extra_table_pdf_block(
            df, colors.HexColor("#123456"), getSampleStyleSheet(),
            is_landscape=True, quarterly_progress=quarterly,
        )[0]
        headers = [cell.getPlainText() for cell in table._cellvalues[0]]
        drawing = next(cell for cell in table._cellvalues[1] if isinstance(cell, Drawing))
        assert any(isinstance(shape, Circle) for shape in drawing.contents) == quarterly
        if quarterly:
            assert PROGRESS_COUNTS_COLUMN in headers
            assert not any(column in headers for column in ("To Do", "In progress", "Closed / Resolved"))
            assert table._cellvalues[1][headers.index(PROGRESS_COUNTS_COLUMN)].getPlainText() == "3 / 5 / 12"
            assert any(isinstance(shape, Wedge) for shape in drawing.contents)
            assert table._colWidths[headers.index(PROGRESS_COUNTS_COLUMN)] == 90
            assert table._colWidths[headers.index("Key")] == 110
        else:
            assert "To Do" in headers
    pd.testing.assert_frame_equal(df, original)


def test_compact_view_preserves_index_and_handles_hidden_counts():
    df = pd.DataFrame({"Key": ["EPIC-1"], "To Do": [3], "Closed / Resolved": [12]}, index=[4])
    view = quarterly_progress_table_view(df)
    assert view.index.tolist() == [4]
    assert view[PROGRESS_COUNTS_COLUMN].tolist() == ["3 / - / 12"]
    assert view.columns.tolist() == ["Key", PROGRESS_COUNTS_COLUMN]


@pytest.mark.parametrize("position", ["Before Demo Table", "After Demo Table"])
def test_sprint_pdf_routes_quarterly_table_to_shared_rendering(position, monkeypatch):
    from utils import sprint_review_helpers, pdf_helpers

    class State(dict):
        def __getattr__(self, name):
            return self.get(name)

    monkeypatch.setattr(pdf_helpers.st, "session_state", State(primary_color="#123456", project_name="Test"))
    calls = []
    original = sprint_review_helpers.build_custom_extra_table_pdf_block

    def capture(*args, **kwargs):
        calls.append(kwargs.get("quarterly_progress", False))
        return original(*args, **kwargs)

    monkeypatch.setattr(sprint_review_helpers, "build_custom_extra_table_pdf_block", capture)
    config = {
        "project_name": "Test", "primary_color": "#123456", "next_release_df": None,
        "custom_tables": [{"title": "Epics Q4 - Current Progress", "position": position,
                           "table_type": "quarterly_epic_progress",
                           "df": pd.DataFrame([{"Key": "EPIC-1", "Completion": "67%", "To Do": 3,
                                                "In progress": 5, "Closed / Resolved": 12}])}],
    }
    from pypdf import PdfReader
    pdf = sprint_review_helpers.build_sprint_review_pdf(pd.DataFrame(), pd.DataFrame(), config)
    text = "\n".join(page.extract_text() for page in PdfReader(pdf).pages)
    assert calls == [True]
    assert "3 / 5 / 12" in text
    assert "67%" in text
