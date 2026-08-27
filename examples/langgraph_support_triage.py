"""A real LangGraph pipeline instrumented with Kredisco.

Four agents process a support ticket. They use different models and
different prompt quality, so their scores separate for real reasons.

    triage      Haiku    -> tight prompt, should score well
    extract     Haiku    -> strict JSON parsing, punished when it drifts
    draft       Sonnet   -> should score well
    review      Haiku    -> strict validator, mixed

Run:
    pip install langgraph langchain-anthropic python-dotenv
    python pipeline.py
"""

import json
import os
import sys
from typing import TypedDict

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.graph import END, START, StateGraph

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kredisco import Kredisco

load_dotenv()

MODEL_FAST = "claude-haiku-4-5-20251001"
MODEL_SMART = "claude-sonnet-5"

# Sonnet 5 rejects `temperature`; Haiku still accepts it.
fast = ChatAnthropic(model=MODEL_FAST, max_tokens=700, temperature=0)
smart = ChatAnthropic(model=MODEL_SMART, max_tokens=700)

kd = Kredisco(
    api_key=os.environ["KREDISCO_API_KEY"],
    workflow_id="support-triage",
    server=os.environ.get("KREDISCO_SERVER", "http://127.0.0.1:8000"),
)

triage_agent = kd.agent("triage-haiku", specialty="classify")
extract_agent = kd.agent("extractor-haiku", specialty="extract")
draft_agent = kd.agent("drafter-sonnet", specialty="draft")
review_agent = kd.agent("reviewer-haiku", specialty="review")


class State(TypedDict):
    ticket: str
    category: str
    fields: dict
    reply: str
    verdict: str


# ---------- helpers ----------

CATEGORIES = {"billing", "technical", "account", "other"}


def strip_fences(text: str) -> str:
    """Models wrap JSON in ```json blocks even when told not to."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    return text.strip()


# ---------- the work ----------

def do_triage(ticket: str) -> str:
    prompt = (
        "Classify this support ticket as exactly one of: "
        "billing, technical, account, other.\n"
        "Reply with that single word only.\n\n" + ticket
    )
    return fast.invoke(prompt).content.strip().lower()


def do_extract(ticket: str) -> dict:
    prompt = (
        "Extract fields from this support ticket as JSON with keys: "
        "issue, order_id (or null), urgency (low/medium/high). "
        "Return only the JSON object.\n\n" + ticket
    )
    try:
        return json.loads(strip_fences(fast.invoke(prompt).content))
    except Exception as exc:
        print("   extract failed:", exc)
        raise


def do_draft(ticket: str, category: str) -> str:
    prompt = (
        f"Write a reply to this {category} support ticket. "
        "Two or three sentences, professional, no placeholder names, "
        "no subject line.\n\n" + ticket
    )
    try:
        content = smart.invoke(prompt).content
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            )
        return content.strip()
    except Exception as exc:
        print("   draft failed:", exc)
        raise


def do_review(reply: str) -> str:
    prompt = (
        "Does this support reply commit to a specific action? "
        "Answer PASS or FAIL and nothing else.\n\n" + reply
    )
    return fast.invoke(prompt).content.strip().upper()


# ---------- what "done correctly" means ----------

def triage_ok(r) -> bool:
    return isinstance(r, str) and r in CATEGORIES


def fields_ok(r) -> bool:
    return isinstance(r, dict) and len(r) > 0


def reply_ok(r) -> bool:
    return isinstance(r, str) and 40 < len(r) < 1200


def verdict_ok(r) -> bool:
    return r in {"PASS", "FAIL"}


# ---------- graph nodes ----------

def triage_node(state: State) -> dict:
    return {"category": kd.track(
        triage_agent, "classify", do_triage, state["ticket"],
        validate=triage_ok, retries=1, default="other",
    )}


def extract_node(state: State) -> dict:
    return {"fields": kd.track(
        extract_agent, "extract", do_extract, state["ticket"],
        validate=fields_ok, retries=1, default={},
    )}


def draft_node(state: State) -> dict:
    return {"reply": kd.track(
        draft_agent, "draft", do_draft, state["ticket"], state["category"],
        validate=reply_ok, retries=1, default="",
    )}


def review_node(state: State) -> dict:
    if not state.get("reply"):
        return {"verdict": "SKIPPED"}
    return {"verdict": kd.track(
        review_agent, "review", do_review, state["reply"],
        validate=verdict_ok, retries=1, default="UNKNOWN",
    )}


graph = StateGraph(State)
graph.add_node("triage", triage_node)
graph.add_node("extract", extract_node)
graph.add_node("draft", draft_node)
graph.add_node("review", review_node)
graph.add_edge(START, "triage")
graph.add_edge("triage", "extract")
graph.add_edge("extract", "draft")
graph.add_edge("draft", "review")
graph.add_edge("review", END)
app = graph.compile()


TICKETS = [
    "I was charged twice for my March subscription. Order #4471. Please refund the duplicate.",
    "The export button does nothing on Firefox. Console shows a 500 from /api/export.",
    "I need to change the email on my account from old@corp.com to new@corp.com.",
    "Your pricing page says $29 but I was billed $39. Which is correct?",
    "App crashes on launch after the latest update. Pixel 8, Android 15.",
    "Can I transfer my licence to a colleague taking over the project?",
    "Invoice INV-2231 has the wrong VAT number. We need a corrected copy.",
    "Two-factor codes are being rejected even though my clock is synced.",
]


def main():
    for i, ticket in enumerate(TICKETS, 1):
        print(f"\n--- ticket {i}/{len(TICKETS)} ---")
        try:
            out = app.invoke({"ticket": ticket})
            print("category:", out.get("category"))
            print("fields:  ", "ok" if out.get("fields") else "FAILED")
            print("reply:   ", (out.get("reply") or "(none)")[:64], "...")
            print("review:  ", out.get("verdict"))
        except Exception as exc:
            print("pipeline error:", exc)

    print("\n--- scores ---")
    for agent in (triage_agent, extract_agent, draft_agent, review_agent):
        try:
            print(f"{agent.name:18} {kd.score(agent.pubkey)}")
        except Exception as exc:
            print(f"{agent.name:18} unavailable ({exc})")

    print("\nopen http://127.0.0.1:8000/app")


if __name__ == "__main__":
    main()