"""
agents/classifier_agent.py
LangGraph-based agent that:
1. Classifies each email into a category
2. Decides what action to take
3. Generates reply drafts where needed
"""

import os
from typing import TypedDict, Annotated, Literal
from dotenv import load_dotenv

from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

load_dotenv()

# ── LLM Resilient Setup ───────────────────────────────────────────────────────
def get_resilient_llm():
    """Returns a model with fallback logic: Ollama -> Groq."""
    use_ollama = os.getenv("USE_OLLAMA", "false").lower() == "true"
    ollama_model = os.getenv("OLLAMA_MODEL", "claude-opus-4.6")
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    # 1. Try to prepare Ollama if requested
    if use_ollama:
        print(f"  Attempting to use Ollama: {ollama_model} at {ollama_base_url}...")
        try:
            import urllib.request
            req = urllib.request.Request(f"{ollama_base_url.rstrip('/')}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    return ChatOllama(model=ollama_model, base_url=ollama_base_url, temperature=0.1)
        except Exception as e:
            print("  ⚠️  Ollama connection failed. Falling back to Groq Cloud...")

    # 2. Fallback to Groq (Cloud)
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.1,
        groq_api_key=os.getenv("GROQ_API_KEY"),
    )

llm = get_resilient_llm()

# ── Agent State ───────────────────────────────────────────────────────────────
class EmailState(TypedDict):
    email: dict
    category: str
    action: str
    draft_subject: str
    draft_body: str
    reasoning: str


# ── Prompts ───────────────────────────────────────────────────────────────────
CLASSIFY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert email classifier for a job applicant.
Classify the email into EXACTLY one of these categories:

- REJECTION     : Company says no, not moving forward, application declined
- INTERVIEW     : Invitation for interview, screening call, assessment, or next steps
- HOLD          : Application on hold, will be revisited, waitlisted
- FOLLOW_UP     : Recruiter asking for documents, more info, or checking availability  
- APPLIED       : Auto-confirmation that an application was received
- IRRELEVANT    : Spam, promotions, non-job-related emails

Respond with ONLY the category label. Nothing else."""),
    ("human", "Subject: {subject}\nFrom: {sender}\nBody:\n{body}"),
])

ACTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are deciding what action to take for a job application email.

Given the category, decide the action:
- REJECTION  → DRAFT_FEEDBACK  (draft a polite feedback request reply)
- INTERVIEW  → DRAFT_CONFIRM   (draft a confirmation/availability reply)  
- HOLD       → LABEL_ONLY      (just label it, no reply needed)
- FOLLOW_UP  → DRAFT_RESPONSE  (draft a helpful response)
- APPLIED    → LABEL_ONLY      (just label it)
- IRRELEVANT → SKIP            (do nothing)

Respond with ONLY the action label. Nothing else."""),
    ("human", "Category: {category}\nSubject: {subject}"),
])

DRAFT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an experienced, high-level HR Manager and Career Strategist. 
Your goal is to draft professional, sophisticated, and impactful email replies for a job candidate.

PERSONA:
- Sophisticated, articulate, and demonstrates high emotional intelligence.
- Uses professional business vocabulary (e.g., 'appreciate the transparency', 'constructive insights', 'long-term alignment').
- Avoids generic clichés but maintains a warm, respectful tone.

CANDIDATE DETAILS:
- Name: {name}
- Phone: {phone}
- Email: {email}
- LinkedIn: {linkedin}

DRAFTING STRATEGIES:
- REJECTIONS (DRAFT_FEEDBACK): Acknowledge the decision with grace and express genuine gratitude for the interviewers' time. Respectfully request 1-2 brief insights into your candidacy—specifically whether the focus for growth should be on technical depth, particular toolsets, or cultural nuances. Frame this as vital data for your professional evolution. Reiterate your high regard for the organization and suggest keeping your profile active for future strategic alignment.
- INTERVIEW INVITES (DRAFT_CONFIRM): Express clear enthusiasm. Reiterate interest in the specific role. Provide your availability clearly and ask if there are specific materials or topics you should prepare to make the most of the conversation.
- FOLLOW-UPS (DRAFT_RESPONSE): Be helpful and prompt.

RULES FOR STRUCTURE & FORMATTING:
- Length & Flow: 150-200 words. MUST be multi-paragraph. Do NOT send a single block of text.
- Paragraph 1: Professional opening, expressing gratitude, acknowledging the context.
- Paragraph 2: Core message (asking for feedback, confirming details, or answering query). Use substantial, articulate sentences. 
- Paragraph 3: Forward-looking professional sign-off and call to action. 
- Tone: Highly respectful, concise but substantive, emotionally intelligent. 
- Signature: Include the candidate's full name and contact links provided.
- Prohibited: No placeholders like [Company Name], no generic "I hope this email finds you well"."""),
    ("human", """Action: {action}
Original Subject: {subject}
From: {sender}
Original Email Body:
{body}

Write the reply email body ONLY. No subject line."""),
])


# ── Invocation Wrapper with Fallback ──────────────────────────────────────────
_fallback_llm = None

def get_fallback_model():
    global _fallback_llm
    if _fallback_llm is None:
        _fallback_llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            groq_api_key=os.getenv("GROQ_API_KEY"),
        )
    return _fallback_llm

def safe_invoke(chain_or_llm, input_data):
    """Invoke and fallback to Groq if the primary LLM fails."""
    global llm
    try:
        return chain_or_llm.invoke(input_data)
    except Exception as e:
        # If Ollama is failing (missing model, etc.), switch to cloud
        if isinstance(llm, ChatOllama):
            print(f"\n  ⚠️  Primary model (Ollama) failed: {e}")
            print("  🔄  Switching to Groq Cloud fallback for the next retry...")
            llm = get_fallback_model()
            # We don't try to invoke here because input_data might be a dict 
            # while the raw 'llm' expects messages/prompts. 
            # Re-raise so the 'main.py' retry loop can start fresh with the new global 'llm'.
        raise e

# ── Agent Nodes ───────────────────────────────────────────────────────────────
def classify_node(state: EmailState) -> EmailState:
    """Classify the email category."""
    email = state["email"]
    chain = CLASSIFY_PROMPT | llm
    result = safe_invoke(chain, {
        "subject": email["subject"],
        "sender": email["sender"],
        "body": email["body"],
    })
    category = result.content.strip().upper()

    # Validate — default to IRRELEVANT if unrecognised
    valid = {"REJECTION", "INTERVIEW", "HOLD", "FOLLOW_UP", "APPLIED", "IRRELEVANT"}
    if category not in valid:
        category = "IRRELEVANT"

    return {**state, "category": category}


def decide_action_node(state: EmailState) -> EmailState:
    """Decide what action to take."""
    sender = state["email"]["sender"].lower()
    category = state["category"]
    
    # Check for "do-not-reply" patterns
    is_noreply = any(pattern in sender for pattern in ["noreply", "no-reply", "donotreply", "do-not-reply"])

    chain = ACTION_PROMPT | llm
    result = safe_invoke(chain, {
        "category": category,
        "subject": state["email"]["subject"],
    })
    action = result.content.strip().upper()

    valid_actions = {"DRAFT_FEEDBACK", "DRAFT_CONFIRM", "DRAFT_RESPONSE", "LABEL_ONLY", "SKIP"}
    if action not in valid_actions:
        action = "LABEL_ONLY"

    # Override: Do NOT draft if it's a no-reply address
    if is_noreply and action.startswith("DRAFT_"):
        action = "LABEL_ONLY"

    return {**state, "action": action}


def draft_reply_node(state: EmailState) -> EmailState:
    """Generate a reply draft."""
    email = state["email"]
    chain = DRAFT_PROMPT | llm
    result = safe_invoke(chain, {
        "name": os.getenv("YOUR_NAME", "Your Name"),
        "phone": os.getenv("YOUR_PHONE", ""),
        "email": os.getenv("YOUR_EMAIL", ""),
        "linkedin": os.getenv("YOUR_LINKEDIN", ""),
        "action": state["action"],
        "subject": email["subject"],
        "sender": email["sender"],
        "body": email["body"],
    })

    # Build reply subject
    original_subject = email["subject"]
    if not original_subject.lower().startswith("re:"):
        reply_subject = f"Re: {original_subject}"
    else:
        reply_subject = original_subject

    return {
        **state,
        "draft_subject": reply_subject,
        "draft_body": result.content.strip(),
    }


def skip_node(state: EmailState) -> EmailState:
    """No action needed."""
    return {**state, "action": "SKIP", "draft_body": "", "draft_subject": ""}


# ── Routing Logic ─────────────────────────────────────────────────────────────
def route_action(state: EmailState) -> Literal["draft_reply", "skip"]:
    if state["action"] in {"DRAFT_FEEDBACK", "DRAFT_CONFIRM", "DRAFT_RESPONSE"}:
        return "draft_reply"
    return "skip"


# ── Build LangGraph ───────────────────────────────────────────────────────────
def build_classifier_graph():
    graph = StateGraph(EmailState)

    graph.add_node("classify", classify_node)
    graph.add_node("decide_action", decide_action_node)
    graph.add_node("draft_reply", draft_reply_node)
    graph.add_node("skip", skip_node)

    graph.set_entry_point("classify")
    graph.add_edge("classify", "decide_action")
    graph.add_conditional_edges(
        "decide_action",
        route_action,
        {"draft_reply": "draft_reply", "skip": "skip"},
    )
    graph.add_edge("draft_reply", END)
    graph.add_edge("skip", END)

    return graph.compile()


# Singleton — compile once
classifier = build_classifier_graph()


def process_email(email: dict) -> EmailState:
    """Run a single email through the classifier agent."""
    initial_state: EmailState = {
        "email": email,
        "category": "",
        "action": "",
        "draft_subject": "",
        "draft_body": "",
        "reasoning": "",
    }
    return classifier.invoke(initial_state)
