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

To get PO Tools up and running on your desktop, you can use the automated quick-start scripts or run it manually.

### 🖥️ Desktop Quick Start (Recommended)

The easiest way to run the application is to use the provided automated startup scripts. These will automatically check for a local virtual environment (`.venv`), create it if missing, install/upgrade the required dependencies (`streamlit`, `pandas`, `plotly`), and launch the server.

> [!NOTE]
> Once the server starts, a browser window will automatically open at `http://localhost:8501`. If it does not, you can manually open that address in your browser.

#### 🍏 macOS & 🐧 Linux Desktop
1. Open your **Terminal** app.
2. Run the automated script:
   ```bash
   # Give execution permission to the script (only needed the first time)
   chmod +x run.sh
   
   # Run the script
   ./run.sh
   ```

#### 🪟 Windows Desktop
1. Open **Command Prompt** (`cmd`) or **PowerShell**.
2. Run the batch script:
   ```cmd
   run.bat
   ```
   *(Or simply double-click the `run.bat` file in your Windows File Explorer!)*

---

### ⚙️ Manual Installation & Launch (Advanced)

If you prefer to configure the environment step-by-step manually, use the following commands:

1. **Prerequisites**: Ensure you have Python 3.9+ and `pip` installed.
2. **Setup and Activate a Virtual Environment**:
   ```bash
   # Create the virtual environment
   python -m venv .venv
   
   # Activate on macOS/Linux
   source .venv/bin/activate
   
   # Activate on Windows
   .venv\Scripts\activate
   ```
3. **Install Dependencies**:
   ```bash
   pip install --upgrade pip
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
