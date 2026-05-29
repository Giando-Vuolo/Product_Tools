# 🎯 Product Owner Tools (PO Tools)

PO Tools is an intuitive, visual application designed specifically for **Product Owners, Product Managers, and Project Leaders** to visualize, manage, and analyze product backlogs and release roadmap datasets beautifully. 

You can connect directly to your corporate **Jira Server / Cloud** to automatically extract delivered capabilities and upcoming features, customize branding theme colors, edit ticket roadmaps interactively in a high-fidelity workspace workbook, and export stunning presentation-grade **Release Notes PDFs** and **Sprint Review slide decks**.

---

## 🚀 Key Features

* **🔌 Dual Jira Backlog Ingestion**: Securely connect to your company Jira server using secure tokens to fetch live sprint roadmaps (or drag-and-drop local CSV files).
* **✍️ Commercial Workspace Workbook**: Refine technical Jira summaries into elegant commercial feature descriptions, schedule live product demos with presenters, and toggle report targets.
* **🎨 Visual Branding**: Customize document primary theme colors with premium corporate presets, upload corporate logos, and add custom welcome intros.
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
5. Edit the values to insert your actual company URLs and JIRA API token, then **save and close the file**.
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
1. Open your **Terminal** app (press `Cmd + Space`, type "Terminal", and press Enter).
2. Drag and drop the `run.sh` file from your project folder directly into the Terminal window.
3. Press **Enter**.
4. *Tip for the very first launch:* If you get a permission error on your Mac, copy-paste this line into the Terminal first, press Enter, and then drag-and-drop the file again:
   ```bash
   chmod +x run.sh
   ```
5. Once loaded, it will automatically launch the app in your default web browser at `http://localhost:8501`.

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
   pip install streamlit pandas plotly
   ```
4. **Launch Streamlit**:
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
*Built with ❤️ to empower Product Teams.*
