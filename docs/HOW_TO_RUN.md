# How To Run `crochet-pattern-agent`

## Project Location

`C:\Users\trenp\crochet-pattern-agent`

## What It Does

`crochet-pattern-agent` collects subscriber preferences, generates crochet recommendations, and sends or previews personalized reports.

It includes:
- a Flask intake and admin app
- a SQLite subscriber database
- a multi-step orchestrator
- a scheduler for batch runs
- an email sender

## Setup

```powershell
cd C:\Users\trenp\crochet-pattern-agent
& 'C:\Users\trenp\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe' -m pip install --break-system-packages -r requirements.txt
```

## Environment

Suggested safe local config:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_anthropic_key_here
GMAIL_USER=your_email@gmail.com
GMAIL_APP_PASSWORD=your_app_password
FLASK_PORT=5050
EMAIL_DRY_RUN=true
ORIGINAL_PATTERN_COUNT=1
ORIGINAL_PATTERN_DETAIL=compact
```

Important:
- set `EMAIL_DRY_RUN=true` to avoid sending real emails while testing
- if you use Ollama, prefer `OLLAMA_MODEL=llama3.2:latest`
- `ORIGINAL_PATTERN_COUNT=1` is the faster, more token-efficient default
- `ORIGINAL_PATTERN_DETAIL=compact` keeps generated patterns shorter and cheaper

## Run The Web App

```powershell
& 'C:\Users\trenp\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe' .\server.py
```

Then open:

`http://localhost:5050`

## Run The Scheduler

```powershell
& 'C:\Users\trenp\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe' .\scheduler.py
```

## Local Python Note

The stub at `C:\Users\trenp\.local\bin\python3.14.exe` is not usable on this machine.
For local runs, use:

`C:\Users\trenp\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe`

## Success Looks Like

- the web app serves `/` and `/admin`
- the orchestrator prints all pipeline stages
- reports are logged under `logs\`
- with `EMAIL_DRY_RUN=true`, the scheduler reports that it would send email without actually sending it

## Deployment

For production deployment, use:
[DEPLOYMENT_RUNBOOK.md](/C:/Users/trenp/crochet-pattern-agent/docs/DEPLOYMENT_RUNBOOK.md)
