"""
agents/classifier_agent.py
LangGraph-based agent that:
1. Classifies each email into a category
2. Decides what action to take
3. Generates structured, HR-quality reply drafts
"""

import os
import logging
from typing import TypedDict, Literal

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

load_dotenv()
logger = logging.getLogger(__name__)


# ── LLM Resilient Setup ───────────────────────────────────────────────────────
def get_resilient_llm():
    """Return an LLM: try Ollama first, fall back to Groq Cloud."""
    use_ollama    = os.getenv("USE_OLLAMA", "false").lower() == "true"
    require_ollama = os.getenv("REQUIRE_OLLAMA", "false").lower() == "true"
    ollama_model  = os.getenv("OLLAMA_MODEL", "llama3")
    ollama_url    = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    if use_ollama:
        logger.info(f"Attempting Ollama: {ollama_model} @ {ollama_url}")
        print(f"  Attempting Ollama: {ollama_model} @ {ollama_url}...")
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{ollama_url.rstrip('/')}/api/tags", method="GET"
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    logger.info("Ollama reachable. Using Ollama.")
                    return ChatOllama(model=ollama_model, base_url=ollama_url, temperature=0.1)
        except Exception as e:
            if require_ollama:
                raise RuntimeError(f"Ollama unreachable and REQUIRE_OLLAMA=true: {e}") from e
            logger.warning(f"Ollama unreachable ({e}). Falling back to Groq.")
            print("  ⚠️  Ollama unreachable. Falling back to Groq Cloud...")

    logger.info("Using Groq Cloud LLM.")
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.1,
        groq_api_key=os.getenv("GROQ_API_KEY"),
    )


_primary_llm  = None
_fallback_llm = None


def _get_primary() -> ChatGroq | ChatOllama:
    global _primary_llm
    if _primary_llm is None:
        _primary_llm = get_resilient_llm()
    return _primary_llm


def _get_fallback() -> ChatGroq:
    global _fallback_llm
    if _fallback_llm is None:
        _fallback_llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            groq_api_key=os.getenv("GROQ_API_KEY"),
        )
    return _fallback_llm


def safe_invoke(prompt: ChatPromptTemplate, inputs: dict) -> str:
    """
    Invoke the prompt with the primary LLM; fall back to Groq on any failure.
    Returns the response content as a stripped string.
    """
    global _primary_llm
    llm = _get_primary()
    chain = prompt | llm
    try:
        result = chain.invoke(inputs)
        return result.content.strip()
    except Exception as e:
        if os.getenv("REQUIRE_OLLAMA", "false").lower() == "true":
            raise
        logger.warning(f"Primary LLM failed: {e}. Trying Groq fallback...")
        print(f"\n  ⚠️  Primary model failed: {e}")
        print("  🔄  Switching to Groq fallback...")
        # Reset the primary so next call tries fresh
        _primary_llm = None
        fallback_chain = prompt | _get_fallback()
        result = fallback_chain.invoke(inputs)
        return result.content.strip()


# ── Agent State ───────────────────────────────────────────────────────────────
class EmailState(TypedDict):
    email:         dict
    category:      str
    action:        str
    draft_subject: str
    draft_body:    str
    reasoning:     str


# ── Prompts ───────────────────────────────────────────────────────────────────
CLASSIFY_AND_ACTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert email classifier for a job applicant named {candidate_name}.

Classify the email into EXACTLY ONE category and choose EXACTLY ONE action.

Categories:
- REJECTION
- INTERVIEW
- HOLD
- FOLLOW_UP
- APPLIED
- IRRELEVANT

Actions:
- DRAFT_FEEDBACK
- DRAFT_CONFIRM
- DRAFT_RESPONSE
- LABEL_ONLY
- SKIP

Required mapping:
- REJECTION  -> DRAFT_FEEDBACK
- INTERVIEW  -> DRAFT_CONFIRM
- HOLD       -> LABEL_ONLY
- FOLLOW_UP  -> DRAFT_RESPONSE
- APPLIED    -> LABEL_ONLY
- IRRELEVANT -> SKIP

Respond in this exact format, one line only:
CATEGORY|ACTION

No extra text."""),
    ("human", "Subject: {subject}\nFrom: {sender}\n\nEmail Body:\n{body}"),
])

DRAFT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a seasoned HR Manager and Career Strategist drafting a professional email reply for a job candidate.

CANDIDATE DETAILS:
Name:     {name}
Phone:    {phone}
Email:    {email}
LinkedIn: {linkedin}

CRITICAL INSTRUCTIONS:
1. READ the original email carefully. Extract the company name, role title, and recruiter's first name.
2. Address the recruiter by their FIRST NAME if visible (e.g., "Dear Sarah," not "Dear HR Team").
3. Reference the SPECIFIC role and company from their email — never use placeholders like [Company Name].
4. Your reply MUST be contextually accurate to the content of THIS specific email.

════════════════════════════════════════════════
TEMPLATE FOR REJECTION (DRAFT_FEEDBACK):
════════════════════════════════════════════════
Para 1 — Acknowledgment:
  Thank [Recruiter Name] for keeping them informed. Acknowledge the decision with grace. 
  Reference the specific role and the company name.

Para 2 — Feedback Request:
  Politely ask: "Could you share 1-2 areas where my candidacy could have been stronger — 
  whether in technical depth, specific domain experience, or cultural alignment? 
  This perspective would be genuinely invaluable for my professional growth."

Para 3 — Forward-Looking Close:
  Express continued admiration for the company's work. Request to be kept in mind for 
  future roles. Sign off warmly with full contact details.

════════════════════════════════════════════════
TEMPLATE FOR INTERVIEW (DRAFT_CONFIRM):
════════════════════════════════════════════════
Para 1 — Enthusiastic Acknowledgment:
  Express genuine excitement. Name the specific role and company. Thank them.

Para 2 — Confirmation & Preparation:
  Confirm availability (e.g., "I am available on weekdays between 9 AM – 6 PM IST").
  Ask: "Are there specific topics, case studies, or materials I should prepare 
  to make the most of our conversation?"

Para 3 — Professional Close:
  Reiterate excitement. Provide phone number for easy scheduling. Sign off.

════════════════════════════════════════════════
TEMPLATE FOR FOLLOW-UP (DRAFT_RESPONSE):
════════════════════════════════════════════════
Para 1 — Prompt Acknowledgment:
  Thank them for reaching out. Acknowledge what they asked for.

Para 2 — Direct Response:
  Address their specific request clearly and completely. If they asked for 
  documents/resume/details, confirm you will attach them promptly.

Para 3 — Close:
  Express continued interest. Sign off with contact details.

════════════════════════════════════════════════
ABSOLUTE RULES:
════════════════════════════════════════════════
- ALWAYS 3 paragraphs (2 for simple follow-ups). NEVER one block of text.
- 150–250 words total.
- Warm, professional, articulate. Use phrases like "appreciate the transparency",
  "constructive insights", "long-term alignment", "valuable perspective".
- BANNED: "I hope this email finds you well", "To Whom It May Concern", any [brackets].
- END with a proper signature:

  Best regards,
  {name}
  {phone}  |  {email}
  {linkedin}"""),
    ("human", """Action Type: {action}
Original Email Subject: {subject}
From: {sender}

Original Email Body (read this carefully to extract names, company, and role):
{body}

Write the complete reply email body below. Follow the exact paragraph template for this action type. No subject line needed."""),
])


# ── Lightweight heuristics to avoid expensive LLM calls ──────────────────────
def _max_classify_chars() -> int:
    return int(os.getenv("CLASSIFY_MAX_CHARS", "900"))


def _max_draft_chars() -> int:
    return int(os.getenv("DRAFT_CONTEXT_MAX_CHARS", "2200"))


def _body_excerpt(body: str, max_chars: int) -> str:
    if not body:
        return ""
    text = body.strip()
    return text if len(text) <= max_chars else text[:max_chars]


def _is_noreply(sender: str) -> bool:
    s = (sender or "").lower()
    return any(p in s for p in ["noreply", "no-reply", "donotreply", "do-not-reply", "notifications@", "mailer-daemon"])


def _heuristic_result(email: dict) -> tuple[str, str] | None:
    subject = (email.get("subject") or "").lower()
    sender = (email.get("sender") or "").lower()
    body = (email.get("body") or "").lower()
    merged = f"{subject} {sender} {body}"

    if "instahyre" in merged or "verify your email" in merged or "confirm your identity" in merged:
        return ("IRRELEVANT", "SKIP")
    if _is_noreply(sender) and any(x in merged for x in ["application received", "thank you for applying", "received your application", "candidate id", "application number"]):
        return ("APPLIED", "LABEL_ONLY")
    if any(x in merged for x in ["we regret", "unfortunately", "not moving forward", "not selected", "won't be moving forward"]):
        return ("REJECTION", "DRAFT_FEEDBACK")
    if any(x in merged for x in ["interview", "assessment", "next round", "schedule", "technical test"]):
        return ("INTERVIEW", "DRAFT_CONFIRM")
    if any(x in merged for x in ["under review", "on hold", "will get back", "shortlisted"]):
        return ("HOLD", "LABEL_ONLY")
    return None


# ── Agent Nodes ───────────────────────────────────────────────────────────────
def classify_and_action_node(state: EmailState) -> EmailState:
    """Single LLM pass for category + action (with heuristics first)."""
    email = state["email"]
    heuristic = _heuristic_result(email)
    if heuristic:
        category, action = heuristic
        logger.info(f"Heuristic classified '{email['subject'][:50]}' -> {category} ({action})")
        return {**state, "category": category, "action": action}

    response = safe_invoke(CLASSIFY_AND_ACTION_PROMPT, {
        "candidate_name": os.getenv("YOUR_NAME", "the candidate"),
        "subject": email["subject"],
        "sender": email["sender"],
        "body": _body_excerpt(email.get("body", ""), _max_classify_chars()),
    })

    valid = {"REJECTION", "INTERVIEW", "HOLD", "FOLLOW_UP", "APPLIED", "IRRELEVANT"}
    valid_actions = {"DRAFT_FEEDBACK", "DRAFT_CONFIRM", "DRAFT_RESPONSE", "LABEL_ONLY", "SKIP"}

    category = "IRRELEVANT"
    action = "SKIP"
    if response and "|" in response:
        left, right = response.strip().split("|", 1)
        category = left.strip().upper()
        action = right.strip().upper()
    elif response:
        # fallback for non-compliant output
        category = response.upper().strip().split()[0]

    if category not in valid:
        logger.warning(f"Unexpected category '{response}' → defaulting to IRRELEVANT")
        category = "IRRELEVANT"
    mapping = {
        "REJECTION": "DRAFT_FEEDBACK",
        "INTERVIEW": "DRAFT_CONFIRM",
        "HOLD": "LABEL_ONLY",
        "FOLLOW_UP": "DRAFT_RESPONSE",
        "APPLIED": "LABEL_ONLY",
        "IRRELEVANT": "SKIP",
    }
    if action not in valid_actions:
        action = mapping[category]
    # Hard safety: don't burn tokens drafting to no-reply senders.
    if _is_noreply(email.get("sender", "")) and action.startswith("DRAFT_"):
        action = "LABEL_ONLY" if category != "IRRELEVANT" else "SKIP"

    logger.info(f"Classified '{email['subject'][:50]}' -> {category}; action={action}")
    return {**state, "category": category, "action": action}


def draft_reply_node(state: EmailState) -> EmailState:
    """Generate a professional reply draft."""
    email = state["email"]

    body = safe_invoke(DRAFT_PROMPT, {
        "name":     os.getenv("YOUR_NAME",     "Your Name"),
        "phone":    os.getenv("YOUR_PHONE",    ""),
        "email":    os.getenv("YOUR_EMAIL",    ""),
        "linkedin": os.getenv("YOUR_LINKEDIN", ""),
        "action":   state["action"],
        "subject":  email["subject"],
        "sender":   email["sender"],
        "body":     _body_excerpt(email.get("body", ""), _max_draft_chars()),
    })

    original_subject = email["subject"]
    reply_subject = (
        original_subject if original_subject.lower().startswith("re:")
        else f"Re: {original_subject}"
    )

    return {
        **state,
        "draft_subject": reply_subject,
        "draft_body":    body,
    }


def skip_node(state: EmailState) -> EmailState:
    """No action needed for this email."""
    return {**state, "draft_body": "", "draft_subject": ""}


# ── Routing ───────────────────────────────────────────────────────────────────
def route_action(state: EmailState) -> Literal["draft_reply", "skip"]:
    if os.getenv("DISABLE_DRAFTS", "false").lower() == "true":
        return "skip"
    if state["action"] in {"DRAFT_FEEDBACK", "DRAFT_CONFIRM", "DRAFT_RESPONSE"}:
        return "draft_reply"
    return "skip"


# ── Build LangGraph ───────────────────────────────────────────────────────────
def build_classifier_graph():
    graph = StateGraph(EmailState)

    graph.add_node("classify_and_action", classify_and_action_node)
    graph.add_node("draft_reply",   draft_reply_node)
    graph.add_node("skip",          skip_node)

    graph.set_entry_point("classify_and_action")
    graph.add_conditional_edges(
        "classify_and_action",
        route_action,
        {"draft_reply": "draft_reply", "skip": "skip"},
    )
    graph.add_edge("draft_reply", END)
    graph.add_edge("skip",        END)

    return graph.compile()


# Compile once at import time
classifier = build_classifier_graph()


def process_email(email: dict) -> EmailState:
    """Run a single email through the full classifier→action→draft pipeline."""
    initial: EmailState = {
        "email":         email,
        "category":      "",
        "action":        "",
        "draft_subject": "",
        "draft_body":    "",
        "reasoning":     "",
    }
    return classifier.invoke(initial)
