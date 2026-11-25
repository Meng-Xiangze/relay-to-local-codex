---
name: relay-to-local-codex
description: >-
  Relay a task to the local Codex desktop thread and bring the finished reply
  back. Use when the user asks Cursor to tell Codex, pass a message, have Codex
  do the work, start a new Codex thread without stealing focus, or continue an
  existing Codex conversation selected by the user.
---

# Relay work to local Codex

Cursor writes the task. Codex does the work. Cursor reads the finished reply and tells the user what happened.

## Hard rules

- **Do not steal focus.** Do not activate/foreground Codex or ChatGPT, do not `SendKeys`, do not click the Codex window, do not bounce windows between Cursor and Codex.
- **Do not invent Codex projects.** Never pass the user home directory (or any random folder) as `path` / `--cwd` just to “have a path”. Only use a workspace the user already named, or ask first. Deep link `path=` and `thread/start` cwd both can create a Desktop project.
- **Do not claim Desktop-visible** unless the thread is Desktop-owned or the user confirms it appears under 最近.

## Paths

| Goal | Method |
|------|--------|
| Message an **existing Desktop** thread (shows in UI) | `codex queue` + wait (`scripts/queue_codex.py --thread … --wait`) |
| **Headless** new thread (no focus steal; usually **not** in Desktop 最近) | `--new-thread` |
| Headless new thread + try Desktop sidebar ingest (experimental) | `--new-thread --announce-desktop` (IPC `thread-unarchived` on `\\.\pipe\codex-ipc`) |
| Desktop-visible new chat via deep link | `codex://threads/new?…` — **steals focus**; only if the user explicitly allows focus steal. Prefill does **not** create a thread id until first send. |

There is **no** supported pure API that both (a) creates a Desktop-owned chat in 最近 and (b) never focuses the app. Community options are deep link (focus) or IPC announce after local `thread/start` (no focus; sidebar ingest is best-effort).

## Voice

The queued text is the user's own message. Do not say it came from Cursor, another agent, a skill, or a test harness. Do not mention alignment, policies, or that a model is calling another model.

Write the task the way the user would say it: the outcome, the files, and the limits. For an edit, give the exact replacement sentences and a list of phrases that must be gone. Tell Codex to search the file and only then publish.

## Existing desktop thread

Pass the intended conversation ID explicitly with `--thread`. If the intended conversation is not clear, ask which one to use.

Save the message as UTF-8. Start the waiter in a background terminal and leave it running. Do not block the chat on it, and do not start a second waiter for the same message.

```bash
python scripts/queue_codex.py --thread THREAD_ID --message-file message.txt --wait --timeout 3600
```

A queued message does not get a reply until the desktop finishes the turn already in progress. High reasoning can take most of an hour. The timeout default is 3600 seconds. Silence is not a refusal.

The script queues with `codex queue`, prints `QUEUED`, then polls until `REPLY:`. The warning `could not resume thread` is expected. Do not start `codex app-server daemon`, and do not scrape the session JSONL for the wait loop (polling `thread/turns/list` is the wait path).

The open desktop thread already has an active writer, so `thread/resume` on a second server returns `-32600`. The script leaves that thread to the desktop. It opens `codex app-server` on stdio only to call `thread/turns/list`.

`interrupted` is not the end of a turn. The desktop can mark a turn interrupted and later complete the same turn. Keep the terminal running. Do not send a second copy because the status flickered. Read the recent turns, not only the latest one: a newer empty interrupted turn must not hide an older completed reply.

## New thread (local writer)

```bash
python scripts/queue_codex.py --new-thread --cwd WORKDIR --name "optional title" --message-file message.txt --timeout 3600
```

- `--cwd` is **required** for `--new-thread`. It must be an existing project/workspace the user chose — not `%USERPROFILE%` by default.
- `--new-thread` always waits: this process is the writer, so exiting early kills the turn.
- Prints `THREAD:`, optional `NAME:`, `TURN:`, `STARTED`, then `REPLY:`.
- Originator is this relay (`relay_to_local_codex`), not `Codex Desktop`.

### Announce to Desktop sidebar (experimental, no focus)

```bash
python scripts/queue_codex.py --new-thread --announce-desktop --cwd WORKDIR --name "title" --message-file message.txt --timeout 3600
```

After `thread/start`, the script connects to `\\.\pipe\codex-ipc` (length-prefixed JSON frames), `initialize`s, then broadcasts `thread-unarchived` for that conversation id (community pattern used by Agents-Anywhere). This does **not** steal focus. Whether Desktop 最近 updates is best-effort — ask the user to confirm rather than focusing the app yourself. On newer Desktop builds the pipe may be missing.

## Deep link (focus steal — opt-in only)

Only if the user explicitly accepts window activation:

```text
codex://threads/new?path=<url-encoded absolute existing project dir>&prompt=<url-encoded text>
```

- Prefer `codex://threads/new` over bare `codex://new`.
- `prompt` prefills the composer; it does **not** auto-send and does **not** allocate a thread id until send.
- Never point `path` at the user home directory.

## After REPLY

When the terminal exits 0, retell the `REPLY:` text in plain language. Do not paste the session log. If the task required exact sentences, read the changed file before saying it matches.

## If it does not return

- No `QUEUED` / `STARTED` line: the Codex CLI was not found under `%LOCALAPPDATA%\OpenAI\Codex\bin`, or queue / `thread/start` / `turn/start` failed.
- Existing path: `QUEUED` but no `REPLY` before timeout — the desktop app is not open on that thread, or the turn is still running. Say so. Do not send a second copy.
- Existing path: `thread not loaded` while polling — that thread id is missing or not available to a fresh app-server. Use `--new-thread` only if headless is OK, or ask for a live desktop thread id.
- `--announce-desktop` fails to open the pipe: Desktop IPC unavailable; the local thread still ran. Say so. Do not fall back to deep link/focus unless the user asks.
- New path: `STARTED` but no `REPLY` — keep waiting. Do not start a second new thread for the same request.
- The user says to stop waiting: stop the terminal. For the existing path, leave the queued message in place and do not send it again. For the new path, stopping ends the owned writer; say the thread id.
- `thread/resume` is not the wait path for desktop-owned threads. A live `turn/completed` subscription only works for a thread this process itself started (`--new-thread`).
- Codex skipped part of a precise edit: send one follow-up that quotes the missed sentence and the required replacement. Do not broaden the task.
