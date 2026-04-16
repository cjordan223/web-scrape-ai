import unittest
from contextlib import contextmanager
from unittest.mock import patch

import requests

from tailor import ollama


@contextmanager
def fake_lock():
    yield


class TestOllamaTracing(unittest.TestCase):
    def test_chat_emits_start_and_success(self):
        events = []

        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": "ok response"}}

        with (
            patch.object(ollama, "get_loaded_model", return_value="m1"),
            patch.object(ollama, "_ollama_lock", fake_lock),
            patch.object(ollama.requests, "post", return_value=FakeResp()),
        ):
            out = ollama.chat(
                "sys",
                "usr",
                max_tokens=123,
                temperature=0.2,
                trace={"doc_type": "resume", "phase": "draft", "attempt": 1},
                trace_recorder=events.append,
            )

        self.assertEqual(out, "ok response")
        self.assertEqual(events[0]["event_type"], "llm_call_start")
        self.assertEqual(events[1]["event_type"], "llm_call_success")
        self.assertEqual(events[1]["response_chars"], len("ok response"))
        self.assertEqual(events[1]["doc_type"], "resume")

    def test_chat_emits_error(self):
        events = []

        with (
            patch.object(ollama, "get_loaded_model", return_value="m1"),
            patch.object(ollama, "_ollama_lock", fake_lock),
            patch.object(ollama.requests, "post", side_effect=requests.ConnectionError("boom")),
        ):
            with self.assertRaises(requests.ConnectionError):
                ollama.chat(
                    "sys",
                    "usr",
                    trace={"doc_type": "cover", "phase": "qa", "attempt": 2},
                    trace_recorder=events.append,
                )

        self.assertEqual(events[0]["event_type"], "llm_call_start")
        self.assertEqual(events[1]["event_type"], "llm_call_error")
        self.assertIn("boom", events[1]["error"])

    def test_chat_expect_json_supports_runtime_override_and_cleanup(self):
        class FakeResp:
            status_code = 200

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '<think>hidden</think>\n```json\n{"pass": true, "reason": "ok"}\n```'
                            }
                        }
                    ]
                }

        with patch.object(ollama.requests, "post", return_value=FakeResp()) as post_mock:
            out = ollama.chat_expect_json(
                "sys",
                "usr",
                model="m1",
                runtime={
                    "provider": "custom",
                    "chat_url": "http://127.0.0.1:4000/v1/chat/completions",
                    "api_key": "secret",
                    "use_lock": False,
                    "timeout": 45,
                },
            )

        self.assertEqual(out, {"pass": True, "reason": "ok"})
        self.assertEqual(post_mock.call_args.kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(post_mock.call_args.kwargs["timeout"], (30, 45))
        self.assertEqual(post_mock.call_args.args[0], "http://127.0.0.1:4000/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
