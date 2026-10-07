# 🎯 Product Owner Tools (PO Tools)

PO Tools is an intuitive, visual application designed specifically for **Product Owners, Product Managers, and Project Leaders** to visualize, manage, and analyze product backlogs and release roadmap datasets beautifully. 

You can connect directly to your corporate **Jira Server / Cloud** to automatically extract delivered capabilities and upcoming features, customize branding theme colors, edit ticket roadmaps interactively in a high-fidelity workspace workbook, and export stunning presentation-grade **Release Notes PDFs** and **Sprint Review slide decks**.

---

## 🚀 Key Features

* **🔌 Dual Jira Backlog Ingestion**: Securely connect to your company Jira server using secure tokens to fetch live sprint roadmaps (or drag-and-drop local CSV files).
* **🤖 AI Agent Hub (Ollama)**: Automatically translate informal notes into Jira tickets, compute sprint KPIs, and query Confluence/Jira knowledge bases using natural language. Powered by local LLMs via Ollama. *(Note: The AI Agent is currently hidden from the main sidebar for development, but is accessible via `http://localhost:8501/AI_Agent`).*
* **⚡ FastAPI Backend**: A standalone backend server providing internal API endpoints defined in `openapi_copilot.json`. It bridges the LLM with your live Jira and Confluence data.
* **🤝 Live Collaboration**: Automatically spins up a secure, free Cloudflare tunnel on startup, displaying a shareable public link in the sidebar so team members can view and edit the roadmap together in real time.
* **✍️ Commercial Workspace Workbook**: Refine technical Jira summaries into elegant commercial feature descriptions, schedule live product demos with presenters, and toggle report targets.
* **🎨 Visual Branding**: Customize document primary theme colors with premium corporate presets, upload corporate logos, and add custom welcome intros.
* **📈 Jira Quarterly Epic Progress**: Load and calculate progress stats for committed Epics (filtered by committed label + quarter label) directly inside both the Quarterly Planner and the Sprint Review modules.
* **💾 Export Presentation Slide Decks & PDFs**: Export compact, high-density, beautifully styled landscape slide presentation decks and portrait documents.
* **📊 Interactive Gantt Chart & Velocity Reports**: Track delivery speed, complete/rollover story points, and visualize hierarchical timelines at a glance.


---

## 🛠️ Easiest Setup & Launch (Zero Dev Knowledge Required)

You do **not** need any coding skills or terminal experience to run PO Tools. Just follow these simple steps:

### 1️⃣ Step 1: Install Python (If you don't have it)
PO Tools requires Python to run. Installing it is quick and free:
* **Windows**: Download the installer from the [official website](https://www.python.org/downloads/). 
  > [!IMPORTANT]
  > When installing on Windows, **make sure to check the box that says "Add Python.exe to PATH"** at the bottom of the installer window!
* **macOS**: Python is usually pre-installed. If not, download and run the installer from the [official website](https://www.python.org/downloads/).

### 2️⃣ Step 2: Configure Your Connection Settings (`.env`)
Before launching, configure your corporate server details:
1. Open the project folder on your computer.
2. Find the file named `.env.example`.
3. Make a copy of that file and rename the copy to `.env` (just `.env` with a dot at the beginning).
4. Open the new `.env` file with any text editor (like **Notepad** on Windows or **TextEdit** on Mac).
5. Edit the values to insert your actual company URLs, JIRA API token, and custom report configurations, then **save and close the file**.
   * `COMMITTED_LABEL`: The Jira label used to identify committed epics (defaults to `RC2_committed`).
   * `QUARTER_LABEL`: The label identifying the current quarter (defaults to `RC2_FB_18`).
   * `QUARTER_STATUS_TABLE_TITLE`: The title of the Epic progress status table.
   * `JIRA_VERSION_LINK_BASE`: The base project URL for version links in Release Notes.
   * **Release Notes:** Set `RELEASE_NOTES_DOCUMENT_TITLE` for the default cover and page-header title. It can also be changed in Release Notes Ingestion for the current document.
   * **Release Notes history:** Set `RELEASE_HISTORY_URL` to the full Confluence URL of the page containing your release-history table. Configure the five `RELEASE_HISTORY_*_COLUMN` values to match its headers: version, deployment date, SCS, service-change number and the column where the Release Note PDF link is written.
   * **Residual anomalies:** Set `RESIDUAL_ANOMALIES_JQL` to the Jira query that identifies known residual bugs. Use `{{PROJECT_KEY}}` to scope it to the project in the release link, `{{RELEASE_FIX_VERSION}}` to exclude that Jira Fix Version (or `{{RELEASE_VERSION}}` when it is only numeric). It can be overridden in Release Notes Ingestion for the current document, with a final safety check excluding bugs from the current release.
   * **Sprint KPIs Configs:** Set `JIRA_STORY_POINTS_FIELD`, `JIRA_SEVERITY_A_LABEL`, and `JIRA_STATUS_IN_PROGRESS` to match your Jira workflows. 
   * **Confluence Publisher:** Configure `CONFLUENCE_SPACE`, `CONFLUENCE_PAGE` (for Sprint Reviews), and `CONFLUENCE_KPI_PAGE` (for KPIs) to automate wiki exports.
   * **SonarQube KPIs (optional):** Set `SONAR_SERVER`, `SONAR_TOKEN` (a user token with Browse permission) and `SONAR_COMPONENT` (a project, application or portfolio key) to add Code Smells, Security Issues and Coverage % to Sprint KPIs. Values are taken from Sonar's history on the sprint end date. On the next publish, three columns are appended to the existing Confluence KPI table (older rows stay empty) together with a Code Quality chart. Leave any of the three empty to turn this off.
   * **SBOM Inventory KPI (optional):** Set `SBOM_SERVER`, `SBOM_API_KEY` and `SBOM_API_SECRET` (created in [Service Board](https://service-board.vwapps.run/)), `SBOM_NAMESPACE_ID` and `SBOM_APP_ID` to add Dependencies Findings (CVEs in dependencies across dev and prod, as shown on the SBOM Inventory app card). The API has no history, so the value is the one at calculation time. It is appended as one more column to the Confluence KPI table and to the Code Quality chart.
   * **Vanguard KPI (optional):** Set `VANGUARD_PROJECT_ID`, `VANGUARD_CLIENT_ID` and `VANGUARD_CLIENT_SECRET` in your local `.env`. Create and activate credentials in One.Cloud **Project > Access Management > API Credentials**, not the account's OAuth2 Clients page. Each **Calculate KPIs** retrieves all pages of current open findings (`state=open`, `preview=false`) and displays **Security findings, platform** with its capture time in UTC. This is a current snapshot, even for a past sprint. The existing publisher and charts include the column; older rows stay empty. Failed or incomplete queries show N/A, never zero or a partial count. Requests are restricted to the fixed OAuth token endpoint and GET project findings, with redirects disabled; no Vanguard resources are changed. See the [Customer API](https://docs.api.vwapps.cloud/) and [OpenAPI schema](https://docs.api.vwapps.cloud/content/api.yaml). Leave any of the three settings empty to disable.
   > [!NOTE]
   > The `.env` file is secure and ignored by Git so that your passwords and personal tokens are never saved publicly.


### 3️⃣ Step 3: Run the Application!

Choose the simple launch instructions below depending on your operating system:

#### 🪟 If you are on Windows
1. Locate the file named `run.bat` in the project folder.
2. **Double-click** on `run.bat` to launch the application!
3. A terminal window will open and automatically handle setting up the environment, installing dependencies, and launching the application.
4. Once loaded, it will automatically open your web browser to the application page at `http://localhost:8501`.

#### 🍏 If you are on macOS

You can run the app using the terminal, or create a convenient **one-click desktop app shortcut**:

##### 🌟 Option A: One-Click Desktop App (Recommended)
1. Open your **Terminal** app (press `Cmd + Space`, type "Terminal", and press Enter).
2. Drag and drop the [create_mac_shortcut.sh](file:///Users/fc0kewc/Desktop/PO_Tools/create_mac_shortcut.sh) file from your project folder directly into the Terminal window and press **Enter**.
3. This will create a native **`PO_Tools`** application on your Desktop with a custom analytics chart icon. 
4. From now on, you can simply **double-click** the icon on your Desktop to launch the app!

##### 💻 Option B: Run via Terminal
1. Open your **Terminal** app.
2. Drag and drop the [run.sh](file:///Users/fc0kewc/Desktop/PO_Tools/run.sh) file from your project folder directly into the Terminal window and press **Enter**.
3. *Tip for the very first launch:* If you get a permission error on your Mac, copy-paste this line into the Terminal first, press Enter, and then drag-and-drop the file again:
   ```bash
   chmod +x run.sh
   ```
4. Once loaded, it will automatically launch the app in your default web browser at `http://localhost:8501`.

---

## ⚙️ Manual/Advanced Installation

If you are a developer and prefer to configure the virtual environment and run the application manually from the CLI:

1. **Clone/Navigate** to your project directory.
2. **Create and Activate a Virtual Environment**:
   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate

   # macOS/Linux
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. **Install Dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install pypdf # For AI PDF extraction
   ```
4. **Launch the FastAPI Server** (Required for the AI Agent):
   ```bash
   uvicorn api:app --host 0.0.0.0 --port 8000 &
   ```
5. **Launch Streamlit**:
   ```bash
   streamlit run app.py
   ```

---

## 📁 Local Data Format Requirements (`jira_mock.csv`)

If you don't connect to a live Jira server and want to use the offline sandbox, you can drag and drop any local CSV backlog. For full visualization capability, ensure your CSV contains the following standard headers:

* `Key`: The Jira ticket reference ID (e.g., `PROJ-123`).
* `Epic Name` (or `Summary`): The title of the epic/task.
* `Status`: Current state (e.g., `To Do`, `In Progress`, `Done`, `Blocked`).
* `Sprint` / `Quarter`: For timeline/velocity filtering.
* `Start Date` & `Due Date`: Required to plot timelines (`YYYY-MM-DD`).
* `Cluster`: The overarching group theme or initiative.
* `Milestone`: Set to `TRUE` to render a timeline milestone diamond.

---
*Built with ❤️ by the Recall2 Team*
