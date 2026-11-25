"""Relay a message to local Codex and wait for its reply.

Paths:
- Existing desktop thread: `codex queue`, then poll `thread/turns/list`.
- New local thread: `thread/start` + `turn/start`, wait `turn/completed`.
- Optional `--announce-desktop`: after start, broadcast `thread-unarchived`
  on `\\.\pipe\codex-ipc` so Desktop may ingest the thread (no focus steal).
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

IPC_PIPE = r"\\.\pipe\codex-ipc"


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

    def read_message(self):
        raw = self.proc.stdout.readline()
        if not raw:
            raise RuntimeError("app-server closed the connection")
        return json.loads(raw.decode("utf-8"))

    def read_until(self, request_id):
        while True:
            message = self.read_message()
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                return message.get("result") or {}

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
                "version": "0.4.0",
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


def announce_desktop(thread_id, cwd):
    """Best-effort Desktop sidebar ingest via private IPC. Never steals focus."""
    try:
        import win32file
        import win32pipe
    except ImportError:
        print("ANNOUNCE_SKIP: pywin32 not installed", flush=True)
        return False

    try:
        handle = win32file.CreateFile(
            IPC_PIPE,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )
    except Exception as exc:
        print(f"ANNOUNCE_SKIP: cannot open {IPC_PIPE}: {exc}", flush=True)
        return False

    buf = b""
    client_id = "initializing-client"

    def write_msg(obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        win32file.WriteFile(handle, struct.pack("<I", len(payload)) + payload)

    def read_msg(timeout=5.0):
        nonlocal buf
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                _, avail, _ = win32pipe.PeekNamedPipe(handle, 0)
            except Exception as exc:
                raise RuntimeError(exc) from exc
            if avail:
                _, data = win32file.ReadFile(handle, avail)
                buf += data
            while len(buf) >= 4:
                size = struct.unpack("<I", buf[:4])[0]
                if size <= 0 or size > 256 * 1024 * 1024:
                    raise RuntimeError(f"bad ipc frame length {size}")
                if len(buf) < 4 + size:
                    break
                payload = buf[4 : 4 + size]
                buf = buf[4 + size :]
                return json.loads(payload.decode("utf-8"))
            time.sleep(0.02)
        raise TimeoutError("ipc read timeout")

    def request(method, params, version, timeout=8.0):
        nonlocal client_id
        request_id = str(uuid.uuid4())
        write_msg(
            {
                "type": "request",
                "requestId": request_id,
                "sourceClientId": client_id,
                "version": version,
                "method": method,
                "params": params,
                "timeoutMs": int(timeout * 1000),
            }
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = read_msg(timeout=max(0.2, deadline - time.time()))
            if message.get("type") == "client-discovery-request":
                write_msg(
                    {
                        "type": "client-discovery-response",
                        "requestId": message["requestId"],
                        "response": {"canHandle": False},
                    }
                )
                continue
            if message.get("type") == "request":
                write_msg(
                    {
                        "type": "response",
                        "requestId": message.get("requestId"),
                        "resultType": "error",
                        "error": "no-handler-for-request",
                    }
                )
                continue
            if message.get("type") == "response" and message.get("requestId") == request_id:
                return message
        raise TimeoutError(f"no response for {method}")

    try:
        init = request("initialize", {"clientType": "codex-web"}, version=0, timeout=5)
        if init.get("resultType") != "success":
            print(f"ANNOUNCE_SKIP: initialize failed: {init}", flush=True)
            return False
        client_id = (init.get("result") or {}).get("clientId") or client_id
        write_msg(
            {
                "type": "broadcast",
                "method": "thread-unarchived",
                "sourceClientId": client_id,
                "version": 1,
                "params": {
                    "hostId": "local",
                    "conversationId": thread_id,
                    "cwd": cwd,
                },
            }
        )
        print("ANNOUNCED", flush=True)
        return True
    except Exception as exc:
        print(f"ANNOUNCE_SKIP: {exc}", flush=True)
        return False
    finally:
        try:
            win32file.CloseHandle(handle)
        except Exception:
            pass


def start_new_thread_and_wait(exe, message, timeout, cwd, name, announce):
    """Own the writer: thread/start -> turn/start -> wait turn/completed."""
    cwd_path = Path(cwd).resolve()
    if not cwd_path.is_dir():
        sys.exit(f"--cwd is not a directory: {cwd_path}")
    home = Path.home().resolve()
    if cwd_path == home:
        sys.exit(
            "--cwd must not be the user home directory (creates unwanted Codex projects). "
            "Pass an existing project/workspace path."
        )

    server = AppServer(exe)
    try:
        initialize(server)
        result = server.read_until(server.send("thread/start", {"cwd": str(cwd_path)}))
        thread = result.get("thread") or {}
        thread_id = thread.get("id")
        if not thread_id:
            sys.exit("thread/start returned no id")
        print("THREAD:", thread_id, flush=True)

        if name:
            try:
                server.read_until(
                    server.send("thread/name/set", {"threadId": thread_id, "name": name})
                )
                print("NAME:", name, flush=True)
            except RuntimeError as exc:
                print("NAME_SKIP:", exc, flush=True)

        if announce:
            announce_desktop(thread_id, str(cwd_path))

        turn_result = server.read_until(
            server.send(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": message}],
                },
            )
        )
        turn = turn_result.get("turn") or {}
        turn_id = turn.get("id")
        print("TURN:", turn_id or "", flush=True)
        print("STARTED", flush=True)

        deadline = time.time() + timeout
        while time.time() < deadline:
            event = server.read_message()
            if event.get("method") != "turn/completed":
                continue
            params = event.get("params") or {}
            if params.get("threadId") != thread_id:
                continue
            completed = params.get("turn") or {}
            if turn_id and completed.get("id") not in (None, turn_id):
                continue
            print("REPLY:", flush=True)
            print(final_answer(completed) or "(completed with no final answer)", flush=True)
            return
        sys.exit("timed out waiting for turn/completed on the new thread")
    finally:
        server.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--thread", help="Required when relaying to an existing Desktop thread")
    parser.add_argument(
        "--new-thread",
        action="store_true",
        help="Start a new Codex thread owned by this process and wait for its reply",
    )
    parser.add_argument(
        "--announce-desktop",
        action="store_true",
        help="After --new-thread start, broadcast thread-unarchived on codex-ipc (no focus steal)",
    )
    parser.add_argument(
        "--cwd",
        default="",
        help="Required with --new-thread: existing project/workspace directory (not user home)",
    )
    parser.add_argument("--name", default="", help="Optional display name for --new-thread")
    parser.add_argument("--message-file", required=True, type=Path)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    if not args.new_thread and not (args.thread or "").strip():
        parser.error("--thread is required when relaying to an existing Desktop thread")
    message = args.message_file.read_text(encoding="utf-8").strip()
    if not message:
        sys.exit("message file is empty")
    exe = find_codex()
    if args.new_thread:
        if not args.cwd:
            sys.exit("--new-thread requires --cwd pointing at an existing project/workspace")
        start_new_thread_and_wait(
            exe,
            message,
            args.timeout,
            args.cwd,
            args.name,
            args.announce_desktop,
        )
        return
    if args.announce_desktop:
        sys.exit("--announce-desktop only applies with --new-thread")
    if args.wait:
        wait_for_reply(exe, args.thread, message, args.timeout)
    else:
        queue(exe, args.thread, message)


if __name__ == "__main__":
    main()
