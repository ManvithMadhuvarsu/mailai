import time
import os
import sys
from pathlib import Path
from colorama import Fore, Style, init
from dotenv import load_dotenv

# Ensure we can import from main
sys.path.insert(0, str(Path(__file__).parent))

from main import run

def start_daemon():
    load_dotenv()
    init(autoreset=True)
    
    # Default to checking every 15 minutes (900 seconds)
    interval_minutes = int(os.getenv("POLL_INTERVAL_MINUTES", 15))
    interval_seconds = interval_minutes * 60
    
    print(f"{Fore.GREEN}================================================={Style.RESET_ALL}")
    print(f"{Fore.GREEN}🚀 Starting MailAI in 24/7 Daemon Mode...{Style.RESET_ALL}")
    print(f"{Fore.GREEN}⏳ Polling frequency: Every {interval_minutes} minutes{Style.RESET_ALL}")
    print(f"{Fore.GREEN}================================================={Style.RESET_ALL}")

    while True:
        target_run_time = time.time() + interval_seconds
        
        try:
            run()
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}🛑 Daemon gracefully stopped by user.{Style.RESET_ALL}")
            break
        except Exception as e:
            print(f"\n{Fore.RED}💥 Critical error in daemon execution: {e}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Retrying on next cycle...{Style.RESET_ALL}")
        
        # Calculate how long to sleep (if run() took a long time, we subtract it)
        sleep_time = max(0, target_run_time - time.time())
        next_run = time.strftime('%H:%M:%S', time.localtime(time.time() + sleep_time))
        
        print(f"\n{Fore.CYAN}💤 Sleeping... Next mailbox check at {next_run}{Style.RESET_ALL}\n")
        
        try:
            time.sleep(sleep_time)
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}🛑 Daemon gracefully stopped by user during sleep.{Style.RESET_ALL}")
            break

if __name__ == "__main__":
    start_daemon()
