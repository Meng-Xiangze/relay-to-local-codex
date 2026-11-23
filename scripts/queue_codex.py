"""Queue a message to a local Codex desktop thread and wait for its reply.

The desktop app is the active writer of an open thread, so a second
app-server cannot thread/resume it. Queue the message for that writer,
then poll thread/turns/list until the new turn completes.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

DEFAULT_THREAD = "01a1804f-46e4-74c3-80f2-1fb7dffc524c"


def find_codex():
    root = Path(os.environ["LOCALAPPDATA"]) / "OpenAI" / "Codex" / "bin"
    exes = list(root.glob("*/codex.exe"))
    if not exes:
        sys.exit("codex.exe not found under LOCALAPPDATA/OpenAI/Codex/bin")
    return max(exes, key=lambda path: path.stat().st_mtime)


def queue(exe, thread_id, message):
    completed = subprocess.run(
        [str(exe), "queue", "--thread", thread_id, "--message", message, "--resume"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    print(output.strip(), flush=True)
    if completed.returncode != 0 or "Queued message" not in output:
        sys.exit(completed.returncode or 1)
    print("QUEUED", flush=True)


class AppServer:
    def __init__(self, exe):
        self.proc = subprocess.Popen(
            [str(exe), "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.next_id = 1

    def send(self, method, params=None, *, notify=False):
        message = {"method": method}
        if notify:
            message["params"] = params or {}
        else:
            message["id"] = self.next_id
            self.next_id += 1
            message["params"] = params or {}
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        return None if notify else message["id"]

    def read_until(self, request_id):
        for raw in self.proc.stdout:
            message = json.loads(raw.decode("utf-8"))
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                return message.get("result") or {}
        raise RuntimeError("app-server closed the connection")

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()


def initialize(server):
    request_id = server.send(
        "initialize",
        {
            "clientInfo": {
                "name": "relay_to_local_codex",
                "title": "Relay to local Codex",
                "version": "0.2.0",
            }
        },
    )
    server.read_until(request_id)
    server.send("initialized", {}, notify=True)


def list_turns(server, thread_id, limit=8):
    request_id = server.send(
        "thread/turns/list",
        {
            "threadId": thread_id,
            "limit": limit,
            "sortDirection": "desc",
            "itemsView": "full",
        },
    )
    result = server.read_until(request_id)
    return result.get("data") or []


def latest_turn(server, thread_id):
    turns = list_turns(server, thread_id, 1)
    return turns[0] if turns else None


def user_text(turn):
    parts = []
    for item in turn.get("items") or []:
        if item.get("type") != "userMessage":
            continue
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for piece in content:
                if isinstance(piece, dict) and piece.get("text"):
                    parts.append(piece["text"])
                elif isinstance(piece, str):
                    parts.append(piece)
    return "\n".join(parts)


def final_answer(turn):
    texts = [
        item.get("text") or ""
        for item in turn.get("items") or []
        if item.get("type") == "agentMessage"
        and item.get("phase") in (None, "final_answer")
        and item.get("text")
    ]
    return texts[-1] if texts else ""


def wait_for_reply(exe, thread_id, message, timeout):
    server = AppServer(exe)
    try:
        initialize(server)
        before = latest_turn(server, thread_id)
        before_id = before.get("id") if before else None
        before_status = before.get("status") if before else None
        queue(exe, thread_id, message)
        needle = message.strip()[:40]
        deadline = time.time() + timeout
        while time.time() < deadline:
            for turn in list_turns(server, thread_id):
                if needle not in user_text(turn):
                    continue
                if turn.get("id") == before_id and before_status == "completed":
                    continue
                if turn.get("status") == "completed":
                    print("REPLY:", flush=True)
                    print(final_answer(turn) or "(completed with no final answer)", flush=True)
                    return
            time.sleep(3)
        sys.exit("timed out waiting for the Codex reply")
    finally:
        server.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--thread", default=DEFAULT_THREAD)
    parser.add_argument("--message-file", required=True, type=Path)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    message = args.message_file.read_text(encoding="utf-8").strip()
    if not message:
        sys.exit("message file is empty")
    exe = find_codex()
    if args.wait:
        wait_for_reply(exe, args.thread, message, args.timeout)
    else:
        queue(exe, args.thread, message)


if __name__ == "__main__":
    main()
