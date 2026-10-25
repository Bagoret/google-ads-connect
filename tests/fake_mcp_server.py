"""Fake MCP stdio server for tests. SYNTHETIC — never talks to Google.

Env:
  FAKE_FIXTURE  path to a JSON file whose "result" object is returned by tools/call.
"""
import json
import os
import sys

TOOLS = [{
    "name": "search",
    "description": "fake search",
    "inputSchema": {"type": "object", "properties": {"customer_id": {"type": "string"}, "query": {"type": "string"}}},
}]


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
            with open(os.environ["FAKE_FIXTURE"], encoding="utf-8") as fh:
                reply(msg_id, json.load(fh)["result"])
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id,
                                         "error": {"code": -32601, "message": "not found"}}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
