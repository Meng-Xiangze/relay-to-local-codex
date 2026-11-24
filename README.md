# relay-to-local-codex

Cursor Agent Skill: relay tasks to local OpenAI Codex (Desktop queue / local `thread/start`), wait for the reply, optionally announce new threads to Desktop via `codex-ipc` without stealing focus.

## Install

Copy this folder to your Cursor user Agent Store `skills/relay-to-local-codex/`, or invoke from a checkout.

## Usage

Existing Desktop thread:

```bash
python scripts/queue_codex.py --thread THREAD_ID --message-file message.txt --wait --timeout 3600
```

New local thread (requires existing project `--cwd`, never user home):

```bash
python scripts/queue_codex.py --new-thread --cwd /path/to/project --name "title" --message-file message.txt --timeout 3600
```

Announce to Desktop sidebar (experimental, no focus steal):

```bash
python scripts/queue_codex.py --new-thread --announce-desktop --cwd /path/to/project --name "title" --message-file message.txt --timeout 3600
```

See `SKILL.md` for hard rules (no focus steal, no inventing Codex projects).
