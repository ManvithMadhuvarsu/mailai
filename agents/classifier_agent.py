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
CLASSIFY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert email classifier for a job applicant named {candidate_name}.

Classify the following email into EXACTLY ONE of these categories:

REJECTION   — Company explicitly states they are not moving forward, application declined, not selected
INTERVIEW   — Invitation for interview, screening call, technical test, assignment, or "next steps"
HOLD        — Application under review, waitlisted, will be revisited, no decision yet
FOLLOW_UP   — Recruiter asking for documents, references, salary expectations, or availability
APPLIED     — Auto-confirmation/acknowledgement that an application was received
IRRELEVANT  — Spam, promotions, newsletters, OTPs, bank notifications, non-job emails

Classification Rules:
- If you see "we regret", "unfortunately", "not moving forward", "not selected" → REJECTION
- If you see "interview", "schedule", "next round", "test", "assessment" → INTERVIEW
- If you see "under review", "shortlisting", "will get back" → HOLD
- If the email asks for something from the candidate (documents, info) → FOLLOW_UP
- If the sender is "noreply@" with just a confirmation number → APPLIED
- When in doubt, lean towards IRRELEVANT rather than misclassifying

Respond with ONLY the category label. No explanation, no punctuation."""),
    ("human", "Subject: {subject}\nFrom: {sender}\n\nEmail Body:\n{body}"),
])

ACTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Based on the email category, determine the exact action to take.

Category → Action mapping:
REJECTION  → DRAFT_FEEDBACK   (draft a polite, professional feedback request reply)
INTERVIEW  → DRAFT_CONFIRM    (draft a confirmation and availability reply)
HOLD       → LABEL_ONLY       (just label it, no reply needed)
FOLLOW_UP  → DRAFT_RESPONSE   (draft a helpful, complete response)
APPLIED    → LABEL_ONLY       (just label it, auto-confirmations don't need replies)
IRRELEVANT → SKIP             (ignore completely)

Respond with ONLY the action label. No explanation."""),
    ("human", "Category: {category}\nSubject: {subject}\nFrom: {sender}"),
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


# ── Agent Nodes ───────────────────────────────────────────────────────────────
def classify_node(state: EmailState) -> EmailState:
    """Classify the email into a category."""
    email = state["email"]
    response = safe_invoke(CLASSIFY_PROMPT, {
        "candidate_name": os.getenv("YOUR_NAME", "the candidate"),
        "subject": email["subject"],
        "sender":  email["sender"],
        "body":    email["body"],
    })

    # Validate — default to IRRELEVANT if unrecognised
    valid = {"REJECTION", "INTERVIEW", "HOLD", "FOLLOW_UP", "APPLIED", "IRRELEVANT"}
    category = response.upper().strip().split()[0] if response else "IRRELEVANT"  # take first word only
    if category not in valid:
        logger.warning(f"Unexpected category '{response}' → defaulting to IRRELEVANT")
        category = "IRRELEVANT"

    logger.info(f"Classified '{email['subject'][:50]}' → {category}")
    return {**state, "category": category}


def decide_action_node(state: EmailState) -> EmailState:
    """Decide what action to take for this email."""
    email    = state["email"]
    category = state["category"]

    response = safe_invoke(ACTION_PROMPT, {
        "category": category,
        "subject":  email["subject"],
        "sender":   email["sender"],
    })

    valid_actions = {"DRAFT_FEEDBACK", "DRAFT_CONFIRM", "DRAFT_RESPONSE", "LABEL_ONLY", "SKIP"}
    action = response.upper().strip().split()[0] if response else "LABEL_ONLY"
    if action not in valid_actions:
        action = "LABEL_ONLY"

    logger.info(f"Action decided: {action}")
    return {**state, "action": action}


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
        "body":     email["body"],
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
    if state["action"] in {"DRAFT_FEEDBACK", "DRAFT_CONFIRM", "DRAFT_RESPONSE"}:
        return "draft_reply"
    return "skip"


# ── Build LangGraph ───────────────────────────────────────────────────────────
def build_classifier_graph():
    graph = StateGraph(EmailState)

    graph.add_node("classify",      classify_node)
    graph.add_node("decide_action", decide_action_node)
    graph.add_node("draft_reply",   draft_reply_node)
    graph.add_node("skip",          skip_node)

    graph.set_entry_point("classify")
    graph.add_edge("classify", "decide_action")
    graph.add_conditional_edges(
        "decide_action",
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
