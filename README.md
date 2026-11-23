# relay-to-local-codex

Cursor skill that queues a task to an open Codex desktop thread and waits for the finished reply.

Cursor writes the task. Codex does the work in its existing desktop thread. Cursor reads the completed reply.

## Install

Copy this folder to your user Agent Store:

```text
skills/relay-to-local-codex/
```

The folder must contain `SKILL.md` and `scripts/queue_codex.py`.

## Requirements

- Codex desktop is open on the target thread.
- `codex.exe` is installed under `%LOCALAPPDATA%\OpenAI\Codex\bin`.

The default thread is the one named in `SKILL.md`. Pass `--thread` when the work belongs to a different Codex thread.

## Queue and wait

Save the message as UTF-8, then run:

```bash
python scripts/queue_codex.py --thread THREAD_ID --message-file message.txt --wait --timeout 3600
```

The script prints `QUEUED`, then polls until it prints `REPLY:`. A queued message waits until the desktop finishes the turn already in progress. The default timeout is 3600 seconds.
