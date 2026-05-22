# Product Owner Tools (PO Tools)

PO Tools is a Streamlit-based application designed to help Product Owners and Project Managers visualize, manage, and analyze Jira Epic and Task data interactively. 

The application reads exports from Jira (or any standardized CSV) and transforms them into an intuitive, powerful dashboard featuring dynamic KPIs, Sprint Velocity tracking, and an advanced hierarchical Gantt chart.

## 🚀 Key Features

### 1. Advanced Interactive Gantt Chart
A meticulously designed Gantt chart powered by Plotly that allows you to see the big picture without losing the details:
- **Three Viewing Modes**:
  - `Clusters`: High-level view showing only the summarized grouping layers.
  - `Items`: Flat view showing all Epics individually without group headers.
  - `All`: Full hierarchical tree view with Epics properly indented under their respective Clusters.
- **Hierarchical Layout**: Clean left-aligned tree structure mimicking native desktop applications, showing the Jira Key, Epic Name, Cluster grouping, and the total item count.
- **Milestone Support**: Automatically formats and visually distinguishes 0-day milestones on the timeline.
- **Interactive Details**: Clicking any bar on the timeline automatically updates the "Epic Details" panel below to show full Jira context, descriptions, and metadata.

### 2. Comprehensive Filtering
Easily slice and dice your product backlog:
- Filter by Quarters and Sprints.
- Filter by Epics, Specific Jira Statuses, or Assignees.
- Dynamic KPIs update in real-time based on your active filters.

### 3. Sprint Velocity & Forecasting
Visualize team performance over time with automated Sprint bar charts that contrast:
- Completed Story Points
- Incomplete / Rollover Points
- Blocked items

## 🛠️ Installation & Usage

1. **Prerequisites**: Ensure you have Python 3.9+ installed along with `pip`.
2. **Setup Virtual Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
3. **Install Dependencies**:
   Ensure you have installed the required libraries (Streamlit, Pandas, Plotly):
   ```bash
   pip install streamlit pandas plotly
   ```
4. **Run the Application**:
   ```bash
   streamlit run app.py
   ```

## 📁 Data Format Requirements (`jira_mock.csv`)

To get the most out of the Gantt chart and features, your CSV should ideally contain the following columns (as seen in the provided `jira_mock.csv`):

- `Key`: The Jira ticket ID (e.g., PROJ-123).
- `Epic Name` (or `Summary`): The title of the epic/ticket.
- `Status`: Current state (To Do, In Progress, Done, Blocked).
- `Sprint` / `Quarter`: For timeline filtering.
- `Start Date` & `Due Date`: (Format YYYY-MM-DD) Required to plot the length of the Gantt bars.
- `Cluster`: The overarching group, theme, or initiative.
- `Cluster Name`: (Optional) A descriptive subtitle for the cluster.
- `Milestone`: (Optional) `TRUE` or `FALSE`. If TRUE, the item is rendered as a diamond milestone marker on the Gantt chart.

---
*Built with ❤️ using Streamlit and Plotly.*
