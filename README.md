# Coding Agent

A Claude-powered coding agent that can read, write, and edit files and run shell commands on your behalf.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  

cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

## Usage

```bash
python main.py                          # interactive mode
python main.py --task "add unit tests"  # one-shot task
python main.py --work-dir /my/project   # point to a project
```