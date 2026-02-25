import json
import tempfile
import threading
import unittest
from pathlib import Path

from tailor.tracing import TraceRecorder


class TestTraceRecorder(unittest.TestCase):
    def test_appends_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            rec = TraceRecorder(d, {"run_slug": "abc", "job_id": 1, "job_title": "Role"})
            rec.record({"event_type": "x", "doc_type": "resume"})
            rec.record({"event_type": "y", "doc_type": "cover"})

            lines = (d / "llm_trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            rows = [json.loads(line) for line in lines]
            self.assertEqual(rows[0]["run_slug"], "abc")
            self.assertEqual(rows[1]["event_type"], "y")

    def test_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            rec = TraceRecorder(d, {"run_slug": "abc", "job_id": 1, "job_title": "Role"})

            def worker(idx: int):
                rec.record({"event_type": "evt", "n": idx})

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            lines = (d / "llm_trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 50)
            parsed = [json.loads(line) for line in lines]
            self.assertEqual(sum(1 for p in parsed if p.get("event_type") == "evt"), 50)

    def test_serialization_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            rec = TraceRecorder(d, {"run_slug": "abc", "job_id": 1, "job_title": "Role"})
            rec.record({"event_type": "bad", "x": {1, 2, 3}})

            row = json.loads((d / "llm_trace.jsonl").read_text(encoding="utf-8").strip())
            self.assertEqual(row["event_type"], "trace_error")


if __name__ == "__main__":
    unittest.main()
