"""Pure description of the 'Release Plan' menu group (order checked by tests)."""

# (order, file, title, url_path). url_path None = Streamlit default (derived from the file name).
RELEASE_PLAN_PAGES = (
    (0, "tools/release_plan/0_Overview.py", "0 · Overview", "release-plan-overview"),
    (1, "tools/release_plan/1_Scope.py", "1 · Scope", "release-plan-scope"),
    (2, "tools/release_plan/2_Approval.py", "2 · Approval", "release-plan-approval"),
    (3, "tools/release_plan/3_Documentation_Table.py", "3 · Documentation table", "release-plan-documentation-table"),
    (4, "tools/release_plan/4_Critical_Changes.py", "4 · Critical changes", "release-plan-critical-changes"),
    (5, "tools/release_plan/5_PRE_Testing.py", "5 · PRE testing", "release-plan-pre-testing"),
    (6, "tools/release_plan/6_Unassigned.py", "6 · Unassigned", "release-plan-unassigned"),
    (7, "tools/7_Release_Plan.py", "7 · Post-actions", None),
    (8, "tools/release_plan/8_Notifications.py", "8 · Notifications", "release-plan-notifications"),
)
