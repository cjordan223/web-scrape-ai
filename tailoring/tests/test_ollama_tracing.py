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
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "ok response"}}]}

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


if __name__ == "__main__":
    unittest.main()
