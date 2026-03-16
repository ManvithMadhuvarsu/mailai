"""
main.py
Job Email Agent — Main Orchestrator

Run daily via:
  python main.py

Or schedule with cron:
  0 9 * * * cd /path/to/job_email_agent && python main.py >> data/agent.log 2>&1
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, Style, init

# Init
load_dotenv()
init(autoreset=True)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from tools.gmail_tool import (
    get_gmail_service,
    fetch_recent_emails,
    get_or_create_label,
    apply_label,
    save_draft,
)
from agents.classifier_agent import process_email

# ── Label Map ─────────────────────────────────────────────────────────────────
LABEL_MAP = {
    "REJECTION": os.getenv("LABEL_REJECTION", "Job/Rejection"),
    "INTERVIEW": os.getenv("LABEL_INTERVIEW", "Job/Interview"),
    "HOLD":      os.getenv("LABEL_HOLD",      "Job/On-Hold"),
    "FOLLOW_UP": os.getenv("LABEL_FOLLOWUP",  "Job/Follow-Up"),
    "APPLIED":   os.getenv("LABEL_APPLIED",   "Job/Applied"),
}

# Category colors for terminal
CATEGORY_COLOR = {
    "REJECTION":  Fore.RED,
    "INTERVIEW":  Fore.GREEN,
    "HOLD":       Fore.YELLOW,
    "FOLLOW_UP":  Fore.CYAN,
    "APPLIED":    Fore.BLUE,
    "IRRELEVANT": Fore.WHITE,
}

PROCESSED_LOG = Path("data/processed.json")


def load_processed() -> set:
    """Load IDs of already-processed emails."""
    if PROCESSED_LOG.exists():
        with open(PROCESSED_LOG) as f:
            return set(json.load(f))
    return set()


def save_processed(ids: set):
    """Persist processed email IDs."""
    PROCESSED_LOG.parent.mkdir(exist_ok=True)
    with open(PROCESSED_LOG, "w") as f:
        json.dump(list(ids), f, indent=2)


def print_banner():
    print(f"\n{Fore.CYAN}{'═' * 60}")
    print(f"  🤖  Job Email Agent")
    print(f"  📅  {datetime.now().strftime('%d %b %Y  %H:%M')}")
    print(f"{'═' * 60}{Style.RESET_ALL}\n")


def print_result(email: dict, result: dict, draft_saved: bool):
    cat = result["category"]
    action = result["action"]
    color = CATEGORY_COLOR.get(cat, Fore.WHITE)

    print(f"  {color}[{cat:<12}]{Style.RESET_ALL}  {email['subject'][:55]}")
    print(f"               From: {email['sender'][:50]}")
    print(f"               Action: {action}", end="")
    if draft_saved:
        print(f"  {Fore.GREEN}→ Draft saved to Gmail{Style.RESET_ALL}", end="")
    print()
    print()


def run():
    print_banner()

    # ── Authenticate ─────────────────────────────────────────────────────────
    print(f"{Fore.CYAN}🔑  Authenticating with Gmail...{Style.RESET_ALL}")
    try:
        service = get_gmail_service()
        print(f"{Fore.GREEN}✅  Connected to Gmail\n{Style.RESET_ALL}")
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    # ── Ensure Labels Exist ───────────────────────────────────────────────────
    print(f"{Fore.CYAN}🏷️   Setting up Gmail labels...{Style.RESET_ALL}")
    label_ids = {}
    for category, label_name in LABEL_MAP.items():
        label_ids[category] = get_or_create_label(service, label_name)
    print()

    # ── Fetch Emails ──────────────────────────────────────────────────────────
    days = int(os.getenv("SCAN_DAYS", "").strip() or 1)
    print(f"{Fore.CYAN}📬  Fetching emails from last {days} day(s)...{Style.RESET_ALL}")
    emails = fetch_recent_emails(service, days=days)
    print(f"    Found {len(emails)} emails\n")

    if not emails:
        print(f"{Fore.YELLOW}    No new emails to process.{Style.RESET_ALL}\n")
        return

    # ── Load processed set ────────────────────────────────────────────────────
    processed_ids = load_processed()

    # ── Process Each Email ────────────────────────────────────────────────────
    print(f"{Fore.CYAN}🧠  Processing emails...{Style.RESET_ALL}\n")
    print(f"  {'─' * 56}")

    stats = {k: 0 for k in ["REJECTION", "INTERVIEW", "HOLD", "FOLLOW_UP", "APPLIED", "IRRELEVANT"]}
    drafts_created = 0
    skipped = 0

    import time
    for email in emails:
        # Skip already processed
        if email["id"] in processed_ids:
            skipped += 1
            continue

        # Run agent with retry logic for rate limits
        max_retries = 3
        result = None
        for attempt in range(max_retries):
            try:
                result = process_email(email)
                break
            except Exception as e:
                # Check for rate limit error specifically if possible, else general wait
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    print(f"\n{Fore.YELLOW}⚠️  Rate limit hit. Waiting 60s...{Style.RESET_ALL}")
                    time.sleep(60)
                else:
                    print(f"\n{Fore.RED}❌ Error processing email: {e}{Style.RESET_ALL}")
                    if attempt == max_retries - 1:
                        raise e
                    time.sleep(5)

        if not result:
            continue

        category = result.get("category", "IRRELEVANT")
        action = result.get("action", "SKIP")
        stats[category] = stats.get(category, 0) + 1

        # Apply Gmail label
        if category in label_ids and label_ids[category]:
            apply_label(service, email["id"], label_ids[category])

        # Save draft if needed
        draft_saved = False
        if action in {"DRAFT_FEEDBACK", "DRAFT_CONFIRM", "DRAFT_RESPONSE"} and result.get("draft_body"):
            reply_to = email.get("reply_to") or email.get("sender")
            draft_id = save_draft(
                service=service,
                to=reply_to,
                subject=result.get("draft_subject"),
                body=result.get("draft_body"),
                thread_id=email.get("thread_id"),
            )
            if draft_id:
                draft_saved = True
                drafts_created += 1

        # Mark processed
        processed_ids.add(email["id"])
        print_result(email, result, draft_saved)
        
        # Small delay to prevent hitting burst limits
        time.sleep(1)

    # ── Save processed IDs ────────────────────────────────────────────────────
    save_processed(processed_ids)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"  {'─' * 56}")
    print(f"\n{Fore.CYAN}📊  Summary{Style.RESET_ALL}")
    for cat, count in stats.items():
        if count > 0:
            color = CATEGORY_COLOR.get(cat, Fore.WHITE)
            print(f"    {color}{cat:<14}{Style.RESET_ALL}  {count}")

    print(f"\n    {Fore.GREEN}📝 Drafts saved to Gmail: {drafts_created}{Style.RESET_ALL}")
    if skipped:
        print(f"    ⏭️  Already processed (skipped): {skipped}")
    print(f"\n{Fore.CYAN}✅  Done — check Gmail Drafts before sending!{Style.RESET_ALL}\n")


if __name__ == "__main__":
    run()
