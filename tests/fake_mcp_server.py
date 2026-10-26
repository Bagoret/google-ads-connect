"""Fake MCP stdio server for tests. SYNTHETIC — never talks to Google.

Publishes the real upstream tool contract (tests/fixtures/upstream_golden_tools_list.json,
copied from googleads/google-ads-mcp v0.0.5).

Env:
  FAKE_FIXTURE  path to a JSON file whose "result" object is returned by tools/call
                ("result_raw", a JSON string, is sent byte-for-byte instead).
  FAKE_RECORD   optional path; the tools/call params are written there for assertions.
  FAKE_MODE     "exit_on_call" = write to stderr and exit during tools/call.
"""
import json
import os
import sys
from pathlib import Path

TOOLS = json.loads((Path(__file__).parent / "fixtures" / "upstream_golden_tools_list.json").read_text())["tools"]


def reply(msg_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method, msg_id = msg.get("method"), msg.get("id")
        if msg_id is None:
            continue
        if method == "initialize":
            reply(msg_id, {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                           "serverInfo": {"name": "fake-google-ads-mcp", "version": "0.0.0-synthetic"}})
        elif method == "tools/list":
            reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            if os.environ.get("FAKE_RECORD"):
                Path(os.environ["FAKE_RECORD"]).write_text(json.dumps(msg["params"]))
            if os.environ.get("FAKE_MODE") == "exit_on_call":
                sys.stderr.write("SYNTH_STDERR_SECRET request details\n")
                sys.exit(1)
            with open(os.environ["FAKE_FIXTURE"], encoding="utf-8") as fh:
                fixture = json.load(fh)
            if "result_raw" in fixture:  # exact bytes, e.g. floats with more digits than a double holds
                sys.stdout.write(f'{{"jsonrpc": "2.0", "id": {msg_id}, "result": {fixture["result_raw"]}}}\n')
                sys.stdout.flush()
            else:
                reply(msg_id, fixture["result"])
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id,
                                         "error": {"code": -32601, "message": "not found"}}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
