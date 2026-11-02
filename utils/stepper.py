"""Horizontal step navigation shared by the multi-step tools (Sprint Review, Quarterly Planner)."""
import streamlit as st

_STEPPER_CSS = """
    <style>
        .st-key-{key} {{ margin: 0.5rem 0 1.25rem 0; }}
        .st-key-{key} [data-testid="stColumn"] {{ position: relative; }}
        .st-key-{key} [data-testid="stColumn"]:not(:last-child)::after {{
            content: ""; position: absolute; top: 50%; right: -1rem; width: 1rem;
            border-top: 2px solid #3E3E4A;
        }}
        .st-key-{key} .po-step {{
            display: flex; align-items: center; gap: 0.6rem;
            padding: 0.55rem 0.9rem; border-radius: 10px; min-height: 2.6rem;
            border: 1px solid #60A5FA; background: rgba(96, 165, 250, 0.12);
            color: #FFFFFF; font-weight: 600;
        }}
        .st-key-{key} .po-step-num {{
            display: inline-flex; align-items: center; justify-content: center;
            width: 1.6rem; height: 1.6rem; border-radius: 50%; flex: none;
            background: #60A5FA; color: #0F172A; font-size: 0.85rem;
        }}
        .st-key-{key} button {{
            min-height: 2.6rem;
            border: 1px solid #3E3E4A !important; border-radius: 10px !important;
            background: #18181D !important; color: #94A3B8 !important; font-weight: 600 !important;
        }}
        .st-key-{key} button:hover {{ border-color: #60A5FA !important; color: #FFFFFF !important; }}
    </style>
"""


def render_stepper(steps, state_key, key):
    """Render `steps` ("<icon> <name>" labels) as a stepper bound to st.session_state[state_key].

    The current step is highlighted, previous steps are checked, and clicking another step
    sets st.session_state[state_key] to it. An unknown or missing value resets to the first step.
    """
    if st.session_state.get(state_key) not in steps:
        st.session_state[state_key] = steps[0]

    def _go_to(step):
        st.session_state[state_key] = step

    st.markdown(_STEPPER_CSS.format(key=key), unsafe_allow_html=True)
    current = steps.index(st.session_state[state_key])
    with st.container(key=key):
        for i, (col, step) in enumerate(zip(st.columns(len(steps)), steps)):
            with col:
                if i == current:
                    st.markdown(f'<div class="po-step"><span class="po-step-num">{i + 1}</span>{step}</div>',
                                unsafe_allow_html=True)
                else:
                    marker = "✅" if i < current else f"{i + 1}."
                    st.button(f"{marker} {step}", key=f"{key}_{i}", on_click=_go_to, args=(step,),
                              use_container_width=True)
