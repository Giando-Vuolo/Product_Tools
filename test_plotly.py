"""
Plotly Timeline Axis Test Suite

Unifies the testing of:
1. Categorical axis custom ordering via category_orders (test_plotly.py original scope).
2. Numeric axis positioning for custom vertical placement (test_plotly2.py original scope).
"""

import pandas as pd
import plotly.express as px

print("==========================================================")
print("🧪 Running Plotly Timeline Axis Verification Suite")
print("==========================================================\n")

# ---------------------------------------------------------
# Test Case 1: Categorical Axis Custom Ordering
# ---------------------------------------------------------
print("--- TEST CASE 1: Categorical Axis (category_orders) ---")
rows_cat = []
y_axis_order = []

# Append dummy Cluster Header
rows_cat.append({
    'Start Date': '2023-01-01',
    'Due Date': '2023-01-30',
    'Y_Axis_Label': 'C_0'
})
y_axis_order.append('C_0')

# Append dummy Epics/Items
for i in range(10):
    rows_cat.append({
        'Start Date': '2023-01-05',
        'Due Date': '2023-01-10',
        'Y_Axis_Label': f'E_{i}'
    })
    y_axis_order.append(f'E_{i}')

df_cat = pd.DataFrame(rows_cat)

fig_cat = px.timeline(
    df_cat,
    x_start="Start Date",
    x_end="Due Date",
    y="Y_Axis_Label",
    category_orders={"Y_Axis_Label": y_axis_order}
)

print(f"✔️ Dataframe rows created: {len(df_cat)}")
print(f"✔️ Y-Axis trace elements: {len(fig_cat.data[0].y)}")
print(f"✔️ Categories array inside Plotly layout: {fig_cat.layout.yaxis.categoryarray}\n")

# ---------------------------------------------------------
# Test Case 2: Numeric Y-Index Placement
# ---------------------------------------------------------
print("--- TEST CASE 2: Numeric Y-Axis Placement (Y_Index) ---")
rows_num = []
for i in range(5):
    rows_num.append({
        'Start Date': f'2023-01-0{i+1}',
        'Due Date': f'2023-01-1{i}',
        'Y_Index': i
    })

df_num = pd.DataFrame(rows_num)

fig_num = px.timeline(
    df_num,
    x_start="Start Date",
    x_end="Due Date",
    y="Y_Index"
)

print(f"✔️ Axis type computed by Plotly: {fig_num.layout.yaxis.type}")
print(f"✔️ Axis range determined: {fig_num.layout.yaxis.range}")
print("==========================================================")
