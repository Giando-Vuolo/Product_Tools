from __future__ import annotations
import requests
import json
import io
import re
import os
from typing import Optional, List, Dict, Any
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

DEFAULT_ISSUE_STRUCTURES = {
    "default_preset_by_type": {
        "User Story": "Standard Agile (BDD / Gherkin)",
        "Story": "Standard Agile (BDD / Gherkin)",
        "Epic": "Commercial & Demo-Ready (PO Focus)",
        "Bug": "Bug & Root-Cause Report",
        "Technical Task": "Deep Technical Spec",
        "Task": "Lightweight Checklist",
        "Improvement": "Standard Agile (BDD / Gherkin)",
        "Risk": "Security / Quality Remediation"
    },
    "presets": {
        "Standard Agile (BDD / Gherkin)": [
            "User Story (As a / I want / So that)",
            "Business Context & Value",
            "Acceptance Criteria (Given / When / Then)",
            "Out of Scope",
            "Definition of Done"
        ],
        "Commercial & Demo-Ready (PO Focus)": [
            "Commercial Feature Summary",
            "Target Persona & Business Impact",
            "Key Capabilities (In Scope)",
            "Live Demo Flow & Acceptance Criteria",
            "Success Metrics / KPIs"
        ],
        "Deep Technical Spec": [
            "Technical Context & Objective",
            "Architecture & Implementation Details",
            "API / Data Model Changes",
            "Non-Functional Requirements (Performance / Security)",
            "Test & Verification Plan"
        ],
        "Bug & Root-Cause Report": [
            "Issue Description & Impact",
            "Steps to Reproduce",
            "Expected vs. Actual Behavior",
            "Environment & Logs / Screenshots",
            "Root Cause & Proposed Fix"
        ],
        "Security / Quality Remediation": [
            "Finding / Vulnerability Overview",
            "Affected Components & Severity",
            "Remediation Steps & Dependency Updates",
            "Verification & Regression Checklist"
        ],
        "Lightweight Checklist": [
            "Objective (1-2 Sentences)",
            "Implementation Checklist",
            "Acceptance Criteria"
        ]
    },
    "extra_sections": [
        "UI / UX Design Notes",
        "Dependencies & Risks",
        "Rollout & Rollback Plan",
        "QA Test Cases",
        "Analytics & Tracking"
    ]
}


class IssueStructuresDict(dict):
    """Dictionary holding issue structures with an optional warning message attribute."""
    def __init__(self, data=None, warning=None):
        super().__init__(data or {})
        self.warning = warning


def load_issue_structures(filepath: str = "ai_issue_structures.json", return_warning: bool = False):
    """
    Load and return the JSON configuration from filepath.
    Includes a safe fallback dictionary matching the schema if missing or malformed.
    """
    resolved_path = filepath
    if not os.path.exists(resolved_path):
        alt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), filepath)
        if os.path.exists(alt_path):
            resolved_path = alt_path

    warning_msg = None
    if not os.path.exists(resolved_path):
        warning_msg = f"Structure file '{filepath}' not found. Using fallback defaults."
        data = json.loads(json.dumps(DEFAULT_ISSUE_STRUCTURES))
    else:
        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                warning_msg = f"Structure file '{filepath}' is not a valid JSON object. Using fallback defaults."
                data = json.loads(json.dumps(DEFAULT_ISSUE_STRUCTURES))
            else:
                data = {
                    "default_preset_by_type": loaded.get("default_preset_by_type", DEFAULT_ISSUE_STRUCTURES["default_preset_by_type"]),
                    "presets": loaded.get("presets", DEFAULT_ISSUE_STRUCTURES["presets"]),
                    "extra_sections": loaded.get("extra_sections", DEFAULT_ISSUE_STRUCTURES["extra_sections"])
                }
        except Exception as e:
            warning_msg = f"Error reading '{filepath}': {e}. Using fallback defaults."
            data = json.loads(json.dumps(DEFAULT_ISSUE_STRUCTURES))

    if warning_msg:
        print(f"[AI Helpers] Warning: {warning_msg}")

    result = IssueStructuresDict(data, warning=warning_msg)
    if return_warning:
        return result, warning_msg
    return result


def extract_text_from_pdf(file_bytes):
    if not PdfReader:
        return "[PDF extraction not available. 'pypdf' is missing.]"
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        return f"[Error extracting PDF text: {str(e)}]"

def get_ollama_models(base_url="http://localhost:11434"):
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            return [model["name"] for model in models]
        return []
    except Exception as e:
        print(f"[AI Helpers] Error fetching Ollama models: {e}")
        return []

LEGACY_ISSUE_SYSTEM_PROMPT = """## Role & Objective
You are an expert Technical Product Manager and Agile Business Analyst. Your role is to convert raw product ideas, requirements, bugs, or technical debt notes into structured, production-ready Jira tickets.

## Strict Rules
1. **Language:** The output must ALWAYS be exclusively in English, regardless of the language used in the input prompt.
2. **Deterministic Formatting:** Strictly adhere to the standard templates defined below. Do not omit mandatory sections.
3. **Clarity & Actionability:** Avoid vague language. Write clear, unambiguous, testable, and concise items.
4. **Issue Classification:** If the user specifies the issue type, follow that template. If not specified, automatically classify the input into the most appropriate type.

---

## Output Templates

### 1. Epic
Issue Type: Epic
Summary: [Domain/Component] - Short descriptive title

Goal & Vision:
- [1-2 sentences explaining the high-level business problem or market opportunity being addressed]

Business Value & Metrics:
- [Primary KPIs, business outcomes, or measurable success metrics]

In-Scope:
- [Key capability / module 1]
- [Key capability / module 2]

Out-of-Scope:
- [Explicit boundary / what will NOT be delivered in this Epic]

### 2. User Story
Issue Type: User Story
Summary: [Module/Feature] - [Short user-centric summary]

User Narrative:
- As a [target user persona]
- I want [action or capability]
- So that [business value, benefit, or outcome]

Acceptance Criteria (Gherkin format):
Scenario 1: [Successful / Happy path description]
- Given [initial precondition or system state]
- When [action performed by user or system]
- Then [expected observable outcome]

Scenario 2: [Edge case or error handling description]
- Given [initial precondition or edge state]
- When [action performed]
- Then [expected fallback or validation message]

Additional Requirements & Constraints:
- [Non-functional requirements, permissions, security, or platform-specific rules]

### 3. Task
Issue Type: Task
Summary: [Team/Area] - Actionable summary of the task

Context:
- [Brief background explaining why this operational or project task is necessary]

Action Items:
- [ ] [Step 1: Specific action item]
- [ ] [Step 2: Specific action item]
- [ ] [Step 3: Specific action item]

Definition of Done (DoD) / Deliverables:
- [Tangible deliverable or verification criteria required to close this task]

### 4. Bug
Issue Type: Bug
Summary: [Module/Screen] - [Concise description of the failure]

Severity / Priority: [Critical | High | Medium | Low]

Preconditions:
- [User state, feature flags, permissions, or seeded data required before starting]

Steps to Reproduce:
1. [First navigation/action step]
2. [Second action step]
3. [Trigger step where the error occurs]

Expected Result:
- [Exact expected behavior according to requirements/design]

Actual Result:
- [Observed faulty behavior, unexpected error codes, UI breakages, or logs]

Environment:
- [OS, Browser/Device version, App version, or Environment: Staging / Production]

### 5. Improvement
Issue Type: Improvement
Summary: [Module/Feature] - Enhancement description

Current State:
- [Description of how the system currently works and the friction/bottleneck it creates]

Proposed Enhancement:
- [Specific modification, optimization, or feature refinement requested]

Expected Benefit:
- [Measurable improvement in UX, latency, operational overhead, or conversion]

Validation Criteria:
- [Clear checkpoint to confirm the enhancement has been successfully achieved]

### 6. Risk
Issue Type: Risk
Summary: [Risk Category: Technical/Business/Security/Delivery] - [Risk Statement]

Risk Statement:
- If [trigger condition or uncertain event occurs], then [adverse impact on delivery, scope, cost, security, or quality].

Likelihood: [High | Medium | Low]
Impact: [High | Medium | Low]

Mitigation Plan (Preventive):
- [Actionable proactive steps to decrease likelihood before it happens]

Contingency Plan (Reactive):
- [Fallback action plan if the risk materializes]

### 7. Technical Task
Issue Type: Technical Task
Summary: [Service/Architecture/Infra] - [Technical summary]

Technical Context:
- [Description of affected services, database tables, background jobs, or pipelines]

Proposed Solution & Architecture:
- [Implementation strategy, architecture patterns, API contracts, or schemas]

Implementation Steps:
- [ ] [Technical step 1]
- [ ] [Technical step 2]
- [ ] [Technical step 3]

Verification & Testing:
- [Unit/Integration test coverage requirements, observability/metrics, and rollback plan]

Instructions for Output Generation
Always format the response in clean Markdown.
Ensure every field is filled out with concrete details derived from the user input (avoid leaving placeholder text like [insert detail here]). If details are missing, make sensible, realistic industry-standard assumptions or flag them under constraints.
If some field is not needed you can skip it.
Do not include conversational introductory or concluding remarks. Just output the issue content."""


def generate_issue_with_ollama(
    model: str = "",
    issue_type: str = "",
    prompt_input: str = "",
    ollama_url: str = "http://localhost:11434",
    sections: list[str] | None = None,
    custom_instructions: str = "",
    preset_name: str = "",
    **kwargs
) -> str:
    # Support backward-compatible keyword arguments
    model_name = model or kwargs.get("model_name", "")
    input_text = prompt_input or kwargs.get("input_text", "")
    base_url = kwargs.get("base_url") if "base_url" in kwargs else ollama_url
    if not sections and "sections" in kwargs:
        sections = kwargs["sections"]
    if not custom_instructions and "custom_instructions" in kwargs:
        custom_instructions = kwargs["custom_instructions"]
    if not preset_name and "preset_name" in kwargs:
        preset_name = kwargs["preset_name"]

    has_custom_instructions = bool(custom_instructions and custom_instructions.strip())
    has_sections = bool(sections and len(sections) > 0)

    if has_sections or has_custom_instructions:
        prompt_parts = [
            "## Role & Objective",
            "You are an expert Technical Product Manager and Agile Business Analyst. Your role is to convert raw product ideas, requirements, bugs, or technical debt notes into structured, production-ready Jira tickets.",
            "",
            "## Core Rules",
            "1. **Language:** Output in English by default, unless explicitly requested otherwise in custom instructions.",
            "2. **Clarity & Actionability:** Avoid vague language. Write clear, unambiguous, testable, and concise items with concrete details derived from the user input (avoid placeholder text like [insert detail here]).",
            "3. **Deterministic Formatting:** Strictly adhere to the requested section headings and order. Do not invent extra top-level sections.",
            "4. **No Conversational Filler:** Do not include conversational greetings or concluding remarks. Output only the issue content in clean Markdown."
        ]

        if preset_name:
            prompt_parts.extend(["", f"**Structure Preset:** {preset_name}"])

        if has_sections:
            prompt_parts.extend([
                "",
                "## Required Output Sections (Strict Markdown Headings)",
                "You must structure the response strictly using the following exact Markdown headings (###) in this exact order. Do not omit any section, and do not invent additional top-level sections:"
            ])
            for idx, sec in enumerate(sections, 1):
                prompt_parts.append(f"{idx}. ### {sec}")

            formatting_rules = []
            if any("given / when / then" in s.lower() or "bdd" in s.lower() for s in sections):
                formatting_rules.append(
                    "- **BDD / Acceptance Criteria:** For the section relating to Acceptance Criteria or BDD, write concrete Gherkin scenarios with Scenario title, Given, When, and Then."
                )
            if any("as a / i want / so that" in s.lower() for s in sections):
                formatting_rules.append(
                    "- **Agile User Story Narrative:** Enforce the standard Agile template:\n  - As a [target user persona]\n  - I want [action or capability]\n  - So that [business value, benefit, or outcome]"
                )
            if any("checklist" in s.lower() for s in sections):
                formatting_rules.append(
                    "- **Checklist Format:** Format checklist items as actionable Markdown checkboxes (- [ ])."
                )

            if formatting_rules:
                prompt_parts.extend([
                    "",
                    "## Section-Level Formatting Rules",
                    *formatting_rules
                ])

        if has_custom_instructions:
            prompt_parts.extend([
                "",
                "## Custom Formatting & Structural Instructions",
                "Strictly follow these custom constraints and formatting instructions:",
                custom_instructions.strip()
            ])

        prompt_parts.extend([
            "",
            "Instructions for Output Generation:",
            "Always format the response in clean Markdown.",
            "Ensure every section is filled out with concrete details derived from the user input or sensible, realistic industry-standard assumptions.",
            "Do not include conversational introductory or concluding remarks. Just output the issue content."
        ])

        system_prompt = "\n".join(prompt_parts)
    else:
        system_prompt = LEGACY_ISSUE_SYSTEM_PROMPT

    user_prompt = f"Target Issue Type: {issue_type}\n\nInput Idea/Requirement:\n{input_text}"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False
    }

    try:
        response = requests.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=300)
        if response.status_code == 200:
            return response.json().get("message", {}).get("content", "").strip()
        else:
            return f"Error from Ollama: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Exception calling Ollama: {e}"


def generate_release_purpose_with_ollama(model_name, issues, base_url="http://localhost:11434"):
    """Summarise release scope from Epic-linked Tasks and User Stories only."""
    if issues is None or issues.empty:
        return ""

    relevant = issues.copy()
    epic_values = relevant.get("Epic", "-").fillna("-").astype(str).str.strip()
    relevant = relevant[
        relevant.get("Type", "").astype(str).str.strip().str.lower().isin({"task", "user story"})
        & epic_values.ne("-")
        & ~epic_values.str.contains(r"\bimprovements?\b", case=False, na=False)
    ]
    if relevant.empty:
        return ""

    lines = []
    for epic, epic_issues in relevant.groupby("Epic", sort=True):
        epic_title = re.sub(r"^[A-Z][A-Z0-9]+-\d+\s*-\s*", "", str(epic)).strip()
        lines.append(f"Epic title: {epic_title}")
        for _, issue in epic_issues.iterrows():
            description = str(issue.get("Description", "")).strip().replace("\n", " ")
            if len(description) > 420:
                description = description[:420] + "…"
            detail = f" | Description: {description}" if description else ""
            lines.append(f"- {issue.get('Type', 'Issue')}: {issue.get('Summary', '')}{detail}")

    prompt = "\n".join(lines)
    system_prompt = """You write the "Delivered functionality by Epic" portion of customer-facing software release notes.
Use only the supplied Epic-linked Tasks and User Stories. Improvement issues and Improvement Epics are handled separately, so do not include them.
Write in English. Return exactly one short bullet per supplied Epic, in the form "- Epic title: delivered value or capability".
Use the Epic title in every bullet. Combine the supplied issue summaries/descriptions into a clear, high-level statement of what is delivered in this release.
Do not invent details. Never mention Jira ticket or Epic identifiers. Do not add headings, an introduction, or a conclusion."""
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=180,
        )
        if response.status_code == 200:
            return response.json().get("message", {}).get("content", "").strip()
    except Exception as error:
        print(f"[AI Helpers] Release purpose generation failed: {error}")
    return ""
