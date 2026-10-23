"""Streamlit chat UI. Talks to the FastAPI backend over HTTP only (never imports app.*)."""

import json
import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
START_HINT = "Start it with: `uv run uvicorn app.api.main:app --reload`"
EXAMPLES = [
    "Which hubs in the Midwest are most exposed to winter disruption?",
    "Compare Miami and Houston in terms of hurricane and flood exposure.",
    "What percentage of days in Denver last year had snowfall?",
    "Why is the Dallas hub's weather disruption risk high?",
]


SIDEBAR_CSS = """
<style>
section[data-testid="stSidebar"] { width: 600px !important; min-width: 600px !important; }
</style>
"""
ROW_PX = 35  # st.dataframe row height; header counts as one row


def api(method: str, path: str, **kwargs) -> tuple[dict | list | None, str | None]:
    """(data, error message)."""
    try:
        response = httpx.request(method, f"{API_URL}{path}", timeout=90, **kwargs)
    except httpx.HTTPError:
        return None, f"The agent API is not reachable at {API_URL}. {START_HINT}"
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        return None, f"API error {response.status_code}: {detail}"
    return response.json(), None


def render_result(result: dict) -> None:
    kind = result["kind"]
    if kind == "rank":
        st.dataframe(
            [
                {
                    "#": r["rank"],
                    "hub": r["name"],
                    "score": round(r["score"], 1),
                    "label": r["label"],
                    "top drivers": ", ".join(r["top_drivers"]),
                }
                for r in result["rows"]
            ],
            hide_index=True,
        )
    elif kind == "compare":
        rows = [
            {
                "hazard": hz,
                **{h["name"]: round(h["hazards"][hz]["score"], 1) for h in result["hubs"]},
            }
            for hz in result["hazards"]
        ]
        rows.append(
            {"hazard": "overall", **{h["name"]: round(h["composite"], 1) for h in result["hubs"]}}
        )
        st.dataframe(rows, hide_index=True)
    elif kind == "explain":
        hub = result["hub"]
        st.metric(
            hub["name"],
            f"{hub['composite']:.1f} ({hub['label']})",
            f"rank {hub['overall_rank']} of {result['total_hubs']}",
            delta_color="off",
        )
        st.dataframe(
            [
                {
                    "hazard": h["hazard"],
                    "score": round(h["score"], 1),
                    "contribution": round(h["contribution"], 1),
                    "observed": None
                    if h["observed_score"] is None
                    else round(h["observed_score"], 1),
                    "NRI": round(h["nri_score"], 1),
                }
                for h in hub["hazards"].values()
            ],
            hide_index=True,
        )
    elif kind == "stat":
        st.metric(
            f"{result['hub_name']} · {result['metric']} · {result['period_label']}",
            result["value"],
            f"{result['matched_days']} of {result['days_with_data']} days",
            delta_color="off",
        )


def render_message(i: int, msg: dict, latest: bool) -> None:
    with st.chat_message(msg["role"]):
        if msg.get("error"):
            st.error(msg["content"])
            return
        st.markdown(msg["content"])
        payload = msg.get("payload")
        if not payload:
            return
        for caveat in payload["answer"]["caveats"]:
            st.caption(f"⚠️ {caveat}")
        if payload.get("result") or payload.get("plan"):
            with st.expander("How I got this"):
                if payload.get("result"):
                    render_result(payload["result"])
                st.code(json.dumps(payload.get("plan"), indent=2), language="json")
                if payload.get("result"):
                    st.json(payload["result"], expanded=False)
        for j, q in enumerate(payload["answer"]["suggested_followups"] if latest else []):
            st.button(q, key=f"fu-{i}-{j}", on_click=ask, args=(q,), disabled=busy())


def busy() -> bool:
    return st.session_state.busy


def ask(question: str) -> None:
    """Queue a question; the next run shows it, locks the input and calls the API."""
    if busy() or not question or not question.strip():
        return
    st.session_state.messages.append({"role": "user", "content": question})
    st.session_state.pending = question
    st.session_state.busy = True


def send(question: str) -> None:
    body = {"message": question, "session_id": st.session_state.session_id}
    payload, error = api("POST", "/chat", json=body)
    if payload:
        st.session_state.session_id = payload["session_id"]
        msg = {"role": "assistant", "content": payload["answer"]["text"], "payload": payload}
    else:
        msg = {"role": "assistant", "content": error, "error": True}
    st.session_state.messages.append(msg)


def sidebar() -> None:
    with st.sidebar:
        st.header("Hub Multi-Hazard risk ranking")
        health, error = api("GET", "/health")
        if error:
            st.error(error)
        if health:
            st.caption(
                f"Model {health['llm_model']} · scoring v{health['scoring_version']} · "
                f"data {health['dataset']['window_start'][:4]}–"
                f"{health['dataset']['window_end'][:4]}"
            )
        hubs, _ = api("GET", "/hubs") if health else (None, None)
        if hubs:
            st.dataframe(
                [
                    {
                        "#": h["overall_rank"],
                        "hub": h["name"],
                        "region": h["region"],
                        "Overall Risk": round(h["composite"], 1),
                        "label": h["label"],
                        "Dominant Hazard": h["peak_hazard"].replace("_", " "),
                    }
                    for h in hubs
                ],
                hide_index=True,
                height=ROW_PX * (len(hubs) + 1) + 3,  # every hub visible, no inner scroll
                column_config={  # pixel widths sum to < sidebar width, so no column is cut
                    "#": st.column_config.NumberColumn(width=34),
                    "hub": st.column_config.TextColumn(width=140),
                    "region": st.column_config.TextColumn(width=80),
                    "Overall Risk": st.column_config.NumberColumn(format="%.1f", width=92),
                    "label": st.column_config.TextColumn(width=64),
                    "Dominant Hazard": st.column_config.TextColumn(width=125),
                },
            )
        st.subheader("Try")
        for k, q in enumerate(EXAMPLES):
            st.button(q, key=f"ex-{k}", on_click=ask, args=(q,), disabled=busy())
        if st.button("New conversation", type="primary", disabled=busy()):
            st.session_state.messages, st.session_state.session_id = [], None


st.set_page_config(
    page_title="Weather Risk Agent", page_icon="🌩️", layout="wide", initial_sidebar_state="expanded"
)
st.markdown(SIDEBAR_CSS, unsafe_allow_html=True)
for key, default in {"messages": [], "session_id": None, "pending": None, "busy": False}.items():
    st.session_state.setdefault(key, default)

st.title("Weather Risk Intelligence Agent")
st.caption(
    "Ranks, compares and explains weather-disruption exposure for 15 US hubs "
    "(2021–2025 Open-Meteo history + FEMA National Risk Index)."
)
sidebar()

st.chat_input(
    "Thinking…" if busy() else "Ask about hub weather risk…",
    key="chat_box",
    max_chars=1000,
    disabled=busy(),
    submit_mode="disable",  # locks client-side immediately on submit
    on_submit=lambda: ask(st.session_state.chat_box),
)

messages = st.session_state.messages
for i, msg in enumerate(messages):
    render_message(i, msg, latest=i == len(messages) - 1 and not busy())

if st.session_state.pending:
    with st.chat_message("assistant"), st.spinner("Thinking…"):
        send(st.session_state.pending)
    st.session_state.pending, st.session_state.busy = None, False
    st.rerun()  # re-render with the input and buttons enabled again
