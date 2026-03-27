"""
daemon.py
Runs the MailAI agent continuously in a loop.
Checks for new emails every POLL_INTERVAL_MINUTES (default: 300 = 5 hours).
Tracks uptime and cycle count for monitoring.
"""

import time
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from colorama import Fore, Style, init
from dotenv import load_dotenv

# Ensure we can import from main
sys.path.insert(0, str(Path(__file__).parent))

from main import run


def _format_duration(seconds: float) -> str:
    """Convert seconds into a human-readable duration string."""
    if seconds >= 86400:
        return f"{seconds / 86400:.1f} days"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} hours"
    if seconds >= 60:
        return f"{seconds / 60:.0f} minutes"
    return f"{seconds:.0f} seconds"


def start_daemon():
    load_dotenv()
    init(autoreset=True)

    interval_minutes = int(os.getenv("POLL_INTERVAL_MINUTES", "").strip() or 300)
    interval_seconds = interval_minutes * 60

    display_interval = _format_duration(interval_seconds)

    print(f"\n{Fore.GREEN}{'═' * 55}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}  🚀  MailAI — 24/7 Daemon Mode{Style.RESET_ALL}")
    print(f"{Fore.GREEN}  ⏳  Polling:  Every {display_interval}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}  📅  Started:  {datetime.now().strftime('%d %b %Y  %H:%M:%S')}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}{'═' * 55}{Style.RESET_ALL}\n")

    start_time = time.time()
    cycle = 0
    consecutive_errors = 0

    while True:
        cycle += 1
        target_run_time = time.time() + interval_seconds
        uptime = _format_duration(time.time() - start_time)

        print(f"{Fore.MAGENTA}── Cycle #{cycle}  |  Uptime: {uptime} ──{Style.RESET_ALL}")

        try:
            run()
            consecutive_errors = 0
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}🛑 Daemon stopped by user after {cycle} cycles.{Style.RESET_ALL}")
            break
        except Exception as e:
            consecutive_errors += 1
            print(f"\n{Fore.RED}💥 Error in cycle #{cycle} (consecutive: {consecutive_errors}): {e}{Style.RESET_ALL}")
            traceback.print_exc()

            if consecutive_errors >= 5:
                backoff = min(consecutive_errors * 120, 3600)  # escalate: 120s…600s…max 1hr
                print(f"{Fore.YELLOW}⏸️  Backing off for {_format_duration(backoff)}...{Style.RESET_ALL}")
                try:
                    time.sleep(backoff)
                except KeyboardInterrupt:
                    break
            else:
                print(f"{Fore.YELLOW}↻  Will retry on next cycle...{Style.RESET_ALL}")

        # Calculate remaining sleep time
        sleep_time = max(0, target_run_time - time.time())
        next_run = datetime.fromtimestamp(time.time() + sleep_time).strftime('%d %b %Y  %H:%M:%S')

        print(f"\n{Fore.CYAN}💤 Sleeping for {_format_duration(sleep_time)}...")
        print(f"   Next check: {next_run}{Style.RESET_ALL}\n")

        try:
            time.sleep(sleep_time)
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}🛑 Daemon stopped during sleep after {cycle} cycles.{Style.RESET_ALL}")
            break

    # Final stats
    total_uptime = _format_duration(time.time() - start_time)
    print(f"\n{Fore.CYAN}📊 Final: {cycle} cycles completed in {total_uptime}{Style.RESET_ALL}\n")


if __name__ == "__main__":
    start_daemon()
