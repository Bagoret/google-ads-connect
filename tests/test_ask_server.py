import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ask_server  # noqa: E402

FACTS = {"facts": {"account.current.roas": "1.86", "account.current.cost": "273.00", "meta.currency": "EUR",
                   "meta.current_period": "2026-10-13 to 2026-10-19"},
         "actions": [{"priority": "P2", "finding": "SYNTHETIC finding"}], "caveats": ["SYNTHETIC caveat"]}


class FakeMessages:
    def __init__(self, text, stop_reason="end_turn"):
        self.text, self.stop_reason, self.calls = text, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, stop_details=None,
                               content=[SimpleNamespace(type="text", text=self.text)])


class FakeClient:
    def __init__(self, text, stop_reason="end_turn"):
        self.beta = SimpleNamespace(messages=FakeMessages(text, stop_reason))


class AnswerTest(unittest.TestCase):
    def test_request_shape(self):
        client = FakeClient("ROAS is {{account.current.roas}}.")
        result = ask_server.answer_question("How is ROAS?", FACTS, client)
        call = client.beta.messages.calls[0]
        self.assertEqual(call["model"], "claude-opus-5-5")
        self.assertEqual(call["output_config"], {"effort": "medium"})
        self.assertEqual(call["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", call["betas"])
        self.assertEqual(call["system"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertIn("account.current.roas", call["system"][-1]["text"])  # facts are in the cached system block
        self.assertEqual(call["messages"], [{"role": "user", "content": "How is ROAS?"}])
        self.assertEqual(result, {"answer": "ROAS is 1.86.", "unverified": []})

    def test_answer_with_free_numbers_is_withheld(self):
        result = ask_server.answer_question("x", FACTS, FakeClient("ROAS fell 40%."))
        self.assertTrue(result["unverified"])
        self.assertNotIn("40%", result["answer"])
        self.assertIn("withheld", result["answer"])

    def test_refusal(self):
        result = ask_server.answer_question("x", FACTS, FakeClient("", stop_reason="refusal"))
        self.assertIn("declined", result["answer"])

    def test_empty_question_rejected(self):
        with self.assertRaises(ValueError):
            ask_server.answer_question("   ", FACTS, FakeClient("x"))


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "index.html").write_text('<html><section id="ask" data-token="__ASK_TOKEN__"></section></html>')
        (d / "facts.json").write_text(json.dumps(FACTS))
        self.client = FakeClient("Cost was {{account.current.cost}}.")
        self.server, self.token = ask_server.make_server(d, client=self.client, port=0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def post(self, body, token):
        req = urllib.request.Request(self.base + "/ask", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **({"X-Ask-Token": token} if token else {})})
        return urllib.request.urlopen(req, timeout=10)

    def test_binds_localhost_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_page_needs_the_printed_address(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/", timeout=10)
        self.assertEqual(ctx.exception.code, 403)
        self.assertNotIn(self.token, ctx.exception.read().decode())
        resp = urllib.request.urlopen(f"{self.base}/?t={self.token}", timeout=10)
        html = resp.read().decode()
        self.assertIn(self.token, html)
        self.assertNotIn("__ASK_TOKEN__", html)
        self.assertEqual(resp.headers["X-Frame-Options"], "DENY")
        self.assertEqual(resp.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")

    def test_token_placeholder_only_replaced_in_the_ask_attribute(self):
        d = Path(self.tmp.name)
        (d / "index.html").write_text('<p>__ASK_TOKEN__</p><section id="ask" data-token="__ASK_TOKEN__"></section>')
        server, token = ask_server.make_server(d, client=self.client, port=0)
        try:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            html = urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/?t={token}",
                                          timeout=10).read().decode()
            self.assertEqual(html.count(token), 1)
            self.assertIn("<p>__ASK_TOKEN__</p>", html)
        finally:
            server.shutdown()
            server.server_close()

    def test_other_host_names_refused(self):
        req = urllib.request.Request(f"{self.base}/?t={self.token}", headers={"Host": "evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 403)

    def raw_post(self, body: bytes, headers: dict):
        req = urllib.request.Request(self.base + "/ask", data=body, method="POST",
                                     headers={"X-Ask-Token": self.token, **headers})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        return ctx.exception.code

    def test_bad_requests_are_400s_not_api_errors(self):
        self.assertEqual(self.raw_post(b"[1]", {"Content-Type": "application/json"}), 400)
        self.assertEqual(self.raw_post(b'{"question": 5}', {"Content-Type": "application/json"}), 400)
        self.assertEqual(self.raw_post(b"{}", {"Content-Type": "text/plain"}), 415)
        self.assertEqual(self.raw_post(b"x" * 10_001, {"Content-Type": "application/json"}), 413)
        self.assertEqual(self.client.beta.messages.calls, [])

    def test_ask_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post({"question": "hi"}, None)
        self.assertEqual(ctx.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError):
            self.post({"question": "hi"}, "wrong")

    def test_ask_answers(self):
        data = json.loads(self.post({"question": "What did we spend?"}, self.token).read())
        self.assertEqual(data["answer"], "Cost was 273.00.")

    def test_only_known_files_served(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/../facts.json", timeout=10)
        self.assertEqual(ctx.exception.code, 404)


class MissingSdkTest(unittest.TestCase):
    def test_clear_message_without_sdk(self):
        if ask_server.sdk_available():
            self.skipTest("anthropic SDK installed")
        with self.assertRaisesRegex(SystemExit, "pip install anthropic"):
            ask_server.default_client()


if __name__ == "__main__":
    unittest.main()
