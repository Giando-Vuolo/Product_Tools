"""Horizontal step navigation shared by the multi-step tools (Sprint Review, Quarterly Planner, Release Notes)
and the Release Plan pages. Steps are drawn as blue-framed chevrons: boxes ending in an arrow (the last one square)."""
import streamlit as st

# Arrow depth of each chevron; the next step's notch has the same depth so they nest.
_ARROW = "14px"
# Blue frame drawn around each chevron (outer shape filled blue, inner shape inset by this much)
_FRAME = "2px"

# Each step is a frame (Streamlit's button / page-link wrapper, or .po-frame for the current step) clipped to
# the chevron and filled blue, holding the step itself clipped to the same shape. The shape depends on the
# column: first = flat left, last = flat right, others = notch on the left and arrow on the right.
_STEPPER_CSS = """
    <style>
        .st-key-{key} {{ margin: 0.5rem 0 1.25rem 0; }}
        .st-key-{key} [data-testid="stHorizontalBlock"] {{ gap: 6px !important; }}
        .st-key-{key} [data-testid="stColumn"] {{
            --po-clip: polygon(0 0, calc(100% - {arrow}) 0, 100% 50%, calc(100% - {arrow}) 100%, 0 100%, {arrow} 50%);
            --po-pad-left: calc({arrow} + 0.6rem); --po-pad-right: calc({arrow} + 0.6rem);
        }}
        .st-key-{key} [data-testid="stColumn"]:first-child {{
            --po-clip: polygon(0 0, calc(100% - {arrow}) 0, 100% 50%, calc(100% - {arrow}) 100%, 0 100%);
            --po-pad-left: 0.9rem;
        }}
        .st-key-{key} [data-testid="stColumn"]:last-child {{
            --po-clip: polygon(0 0, 100% 0, 100% 100%, 0 100%, {arrow} 50%);
            --po-pad-right: 0.9rem;
        }}
        .st-key-{key} [data-testid="stColumn"]:first-child:last-child {{
            --po-clip: none; --po-pad-left: 0.9rem; --po-pad-right: 0.9rem;
        }}
        .st-key-{key} :is([data-testid="stButton"], [data-testid="stPageLink"], .po-frame) {{
            width: 100%; box-sizing: border-box; padding: {frame};
            background: #60A5FA; clip-path: var(--po-clip);
        }}
        .st-key-{key} :is([data-testid="stPageLink"] > div) {{ width: 100%; }}
        /* Page links add the page's own icon: the step label already says what the step is */
        .st-key-{key} [data-testid="stPageLink"] a [data-testid="stIconEmoji"] {{ display: none; }}
        .st-key-{key} :is(.po-step, button, [data-testid="stPageLink"] a) {{
            display: flex; align-items: center; justify-content: center; gap: 0.5rem;
            width: 100%; min-height: 2.5rem; margin: 0; box-sizing: border-box;
            padding: 0.4rem var(--po-pad-right) 0.4rem var(--po-pad-left) !important;
            border: none !important; border-radius: 0 !important;
            background: #2A2A33 !important; color: #CBD5E1 !important; font-weight: 600 !important;
            clip-path: var(--po-clip);
        }}
        .st-key-{key} :is(button, [data-testid="stPageLink"] a):hover {{
            background: #3A3A46 !important; color: #FFFFFF !important;
        }}
        .st-key-{key} .po-step.po-step-active {{ background: #60A5FA !important; color: #0F172A !important; }}
        .st-key-{key} .po-step-num {{
            display: inline-flex; align-items: center; justify-content: center;
            width: 1.5rem; height: 1.5rem; border-radius: 50%; flex: none;
            background: #0F172A; color: #60A5FA; font-size: 0.8rem;
        }}
    </style>
"""


def inject_stepper_css(key):
    """Styles for a stepper rendered inside st.container(key=key)."""
    st.markdown(_STEPPER_CSS.format(key=key, arrow=_ARROW, frame=_FRAME), unsafe_allow_html=True)


def active_step_html(number, label):
    """The current step: a highlighted, non-clickable chevron."""
    return (f'<div class="po-frame"><div class="po-step po-step-active">'
            f'<span class="po-step-num">{number}</span>{label}</div></div>')


def step_label(number, label, done):
    """Label of a clickable step: its number, its title and a check mark once the step is behind."""
    return f"{number}. {label} ✅" if done else f"{number}. {label}"


def render_stepper(steps, state_key, key):
    """Render `steps` ("<icon> <name>" labels) as a stepper bound to st.session_state[state_key].

    The current step is highlighted, previous steps are checked, and clicking another step
    sets st.session_state[state_key] to it. An unknown or missing value resets to the first step.
    """
    if st.session_state.get(state_key) not in steps:
        st.session_state[state_key] = steps[0]

    def _go_to(step):
        st.session_state[state_key] = step

    inject_stepper_css(key)
    current = steps.index(st.session_state[state_key])
    with st.container(key=key):
        for i, (col, step) in enumerate(zip(st.columns(len(steps)), steps)):
            with col:
                if i == current:
                    st.markdown(active_step_html(i + 1, step), unsafe_allow_html=True)
                else:
                    st.button(step_label(i + 1, step, done=i < current), key=f"{key}_{i}",
                              on_click=_go_to, args=(step,), use_container_width=True)
