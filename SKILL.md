---
name: relay-to-local-codex
description: >-
  Relay a task to the local Codex desktop thread and bring the finished reply
  back. Use when the user asks Cursor to tell Codex, pass a message, have Codex
  do the work, or continue the pressure-balance Codex conversation
  反再系统压力平衡｜六线建模、响应验证与交付.
---

# Relay work to local Codex

Cursor writes the task. Codex does the work in its existing desktop thread. Cursor reads the finished reply and tells the user what happened.

## Voice

The queued text is the user's own message. Do not say it came from Cursor, another agent, a skill, or a test harness. Do not mention alignment, policies, or that a model is calling another model.

Write the task the way the user would say it: the outcome, the files, and the limits. For an edit, give the exact replacement sentences and a list of phrases that must be gone. Tell Codex to search the file and only then publish.

## Send and wait

Default thread: `01a1804f-46e4-74c3-80f2-1fb7dffc524c` (反再系统压力平衡｜六线建模、响应验证与交付). If the user is already working in another Codex thread, pass that id with `--thread`. Do not switch back to the default thread.

Save the message as UTF-8. Start the waiter in a background terminal and leave it running. Do not block the chat on it, and do not start a second waiter for the same message.

```bash
python scripts/queue_codex.py --thread THREAD_ID --message-file message.txt --wait --timeout 3600
```

A queued message does not get a reply until the desktop finishes the turn already in progress. High reasoning can take most of an hour. The timeout default is 3600 seconds. Silence is not a refusal.

The script queues with `codex queue`, prints `QUEUED`, then polls until `REPLY:`. The warning `could not resume thread` is expected. Do not start `codex app-server daemon`, and do not scrape the session JSONL.

The open desktop thread already has an active writer, so `thread/resume` on a second server returns `-32600`. The script leaves that thread to the desktop. It opens `codex app-server` on stdio only to call `thread/turns/list`.

`interrupted` is not the end of a turn. The desktop can mark a turn interrupted and later complete the same turn. Keep the terminal running. Do not send a second copy because the status flickered. Read the recent turns, not only the latest one: a newer empty interrupted turn must not hide an older completed reply.

When the terminal exits 0, retell the `REPLY:` text in plain language. Do not paste the session log. If the task required exact sentences, read the changed file before saying it matches.

## If it does not return

- No `QUEUED` line: the Codex CLI was not found under `%LOCALAPPDATA%\OpenAI\Codex\bin`, or the queue command failed.
- `QUEUED` but no `REPLY` before timeout: the desktop app is not open on that thread, or the turn is still running. Say so. Do not send a second copy.
- The user says to stop waiting: leave the queued message in place and stop the terminal. Do not send the message again.
- `thread/resume` is not the wait path. A live `turn/completed` subscription only works for a thread this process itself started.
- Codex skipped part of a precise edit: send one follow-up that quotes the missed sentence and the required replacement. Do not broaden the task.
