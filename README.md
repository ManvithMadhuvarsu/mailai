# 🤖 MailAI — Intelligent Job Email Agent

An AI-powered agent that **continuously monitors your Gmail**, classifies job application emails, applies labels, and drafts professional reply emails — all running **24/7 via Docker**.

---

## ✨ Features

- **🔍 Smart Classification** — Automatically categorizes emails into Rejection, Interview, Follow-Up, Applied, Hold, or Irrelevant
- **🏷️ Gmail Labels** — Creates and applies organized labels (`Job/Rejection`, `Job/Interview`, etc.)
- **✍️ Professional Drafts** — Generates multi-paragraph, HR-quality reply drafts using an experienced Career Strategist persona
- **🚫 No-Reply Detection** — Skips drafting replies to automated `noreply@` addresses
- **🔄 24/7 Daemon Mode** — Polls your inbox every 15 minutes (configurable)
- **🐳 Docker Ready** — Deploy with a single `docker-compose up` command
- **🛡️ Resilient Fallback** — Tries Ollama (local) first, falls back to Groq Cloud automatically
- **📊 Rate Limit Handling** — Auto-retries on API throttling with graceful backoff
- **💾 Progress Tracking** — Remembers processed emails; safe to stop and restart anytime

---

## Stack

| Component | Tool | Cost |
|---|---|---|
| Email | Gmail API (OAuth) | Free |
| AI Brain (Cloud) | Groq API — LLaMA 3.3 70B | Free (100K tokens/day) |
| AI Brain (Local) | Ollama — Any Model | Free / Local |
| Orchestration | LangChain + LangGraph | Free / Open Source |
| Deployment | Docker + Docker Compose | Free |

---

## Project Structure

```
mailai/
├── main.py                   ← Core orchestrator (classify → label → draft)
├── daemon.py                 ← 24/7 polling loop (runs main.py on interval)
├── agents/
│   ├── __init__.py
│   └── classifier_agent.py   ← LangGraph agent (classify → decide → draft)
├── tools/
│   ├── __init__.py
│   └── gmail_tool.py         ← Gmail API wrapper (auth, fetch, label, draft)
├── config/
│   └── credentials.json      ← ⚠️ YOU ADD THIS (Google OAuth — not committed)
├── data/
│   ├── token.pickle          ← Auto-generated after first Gmail login
│   └── processed.json        ← Tracks already-processed email IDs
├── .env                      ← YOUR secrets (copy from .env.example)
├── .env.example              ← Template with all config variables
├── Dockerfile                ← Container image definition
├── docker-compose.yml        ← One-command deployment
├── requirements.txt          ← Python dependencies
└── .gitignore                ← Keeps secrets out of git
```

---

## Setup (One Time — 15 minutes)

### Step 1 — Get Groq API Key (Free)
1. Go to [console.groq.com](https://console.groq.com)
2. Sign up → Create API Key
3. Copy the key

### Step 2 — Set Up Gmail API (Free)
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (name it anything)
3. Search "Gmail API" → Enable it
4. Go to **APIs & Services** → **OAuth consent screen** → Add your email as a **Test User**
5. Go to "Credentials" → Create Credentials → **OAuth 2.0 Client ID**
6. Application type: **Desktop app**
7. Download the JSON file
8. Save it as `config/credentials.json`

### Step 3 — Configure Environment
```bash
cp .env.example .env
# Edit .env and fill in your GROQ_API_KEY and personal details
```

### Step 4 — Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 5 — First Run (Manual)
```bash
python main.py
```
A browser window opens asking you to log in to Gmail — approve it.
After that, it runs silently without needing a browser.

---

## Running Modes

### 🖥️ Manual (One-shot)
```bash
python main.py
```
Processes all new emails once and exits.

### 🔄 Daemon (24/7 polling)
```bash
python daemon.py
```
Runs continuously, checking for new emails every 15 minutes.

### 🐳 Docker (Production)
```bash
docker-compose up -d --build
```
Runs the daemon inside a container with auto-restart.

**OAuth client file (`config/credentials.json`):**
- The Docker **image does not include** this file (it is listed in `.dockerignore` on purpose).
- At **runtime**, Compose mounts your project folder: `./config` → `/app/config`, so place the JSON on your machine as `config/credentials.json` before starting.
- Alternatively, set **`GMAIL_CREDENTIALS_JSON`** in `.env` to the full JSON string; the app will write `config/credentials.json` on startup when the file is missing.

First-time OAuth in Docker:
- Keep `GMAIL_OAUTH_LOCAL_PORT=8080` in `.env`
- Run `docker logs mailai-agent -f`
- Open the Google auth URL shown in logs, approve access, and let Google redirect back to `http://localhost:8080`
- Token is saved to `data/token.pickle`; future starts are automatic

Check logs:
```bash
docker logs mailai-agent -f
```

Stop:
```bash
docker-compose down
```

---

## Email Categories & Actions

| Category | What it means | Action |
|---|---|---|
| REJECTION | Company said no | Drafts professional feedback request (skips `noreply@`) |
| INTERVIEW | Interview invite / next steps | Drafts enthusiastic confirmation reply |
| HOLD | Application on hold | Labels only |
| FOLLOW_UP | Recruiter wants more info | Drafts helpful response |
| APPLIED | Auto-confirmation email | Labels only |
| IRRELEVANT | Spam / unrelated | Skipped entirely |

### Gmail Labels Created Automatically
```
Job/
  ├── Rejection
  ├── Interview
  ├── On-Hold
  ├── Follow-Up
  └── Applied
```

### Draft Quality
All drafts are written using an **HR Manager / Career Strategist** persona:
- Multi-paragraph structure (150-200 words)
- Professional business vocabulary
- Graceful feedback requests for rejections
- Enthusiastic confirmations for interviews
- No generic clichés or placeholders

> ⚠️ Drafts are saved to **Gmail Drafts** — NOT auto-sent. You review and send manually.

---

## Configuration (.env)

| Variable | Description | Default |
|---|---|---|
| `GROQ_API_KEY` | Your Groq API key | Required |
| `YOUR_NAME` | Your full name (used in draft signatures) | Required |
| `YOUR_PHONE` | Your phone number | Optional |
| `YOUR_EMAIL` | Your email address | Optional |
| `YOUR_LINKEDIN` | Your LinkedIn URL | Optional |
| `SCAN_DAYS` | How many days back to scan | `1` |
| `POLL_INTERVAL_MINUTES` | Minutes between daemon checks | `180` |
| `GMAIL_OAUTH_LOCAL_PORT` | Docker callback port for first OAuth login | `8080` |
| `USE_OLLAMA` | Use local Ollama model (`true`/`false`) | `false` |
| `OLLAMA_MODEL` | Ollama model name | `bjoernb/claude-opus-4-5:latest` |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |

---

## Using Ollama (Local AI — Free & Unlimited)

To run completely locally without any cloud API:

1. Install [Ollama](https://ollama.ai)
2. Pull a model: `ollama pull llama3`
3. Update `.env`:
   ```
   USE_OLLAMA=true
   OLLAMA_MODEL=llama3
   ```

The agent will automatically fall back to Groq Cloud if Ollama is unavailable.

---

## Resetting Processed Emails

To reprocess all emails (e.g., for testing):
```bash
rm data/processed.json
```

---

## Security Notes
- `credentials.json` and `.env` are **never committed** to Git
- OAuth token stored locally in `data/token.pickle`
- No email content is stored — only message IDs
- Groq processes email text to classify — for full privacy, use Ollama (fully local)
