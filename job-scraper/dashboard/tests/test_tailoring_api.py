import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class TestTailoringAPI(unittest.TestCase):
    def test_tailoring_routes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "123-foo-role-2026-02-24"
            run_dir.mkdir(parents=True)

            (run_dir / "meta.json").write_text(json.dumps({"job_id": 123, "title": "Role"}), encoding="utf-8")
            (run_dir / "analysis.json").write_text("{}", encoding="utf-8")
            (run_dir / "llm_trace.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"event_type": "doc_attempt_result", "doc_type": "resume", "status": "passed", "attempt": 1, "timestamp": "2026-02-24T10:00:00+00:00"}),
                        json.dumps({"event_type": "validation_result", "doc_type": "resume", "passed": True, "attempt": 1, "timestamp": "2026-02-24T10:01:00+00:00"}),
                        json.dumps({"event_type": "doc_attempt_result", "doc_type": "cover", "status": "passed", "attempt": 1, "timestamp": "2026-02-24T10:02:00+00:00"}),
                        json.dumps({"event_type": "validation_result", "doc_type": "cover", "passed": True, "attempt": 1, "timestamp": "2026-02-24T10:03:00+00:00"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            old = server.TAILORING_OUTPUT_DIR
            server.TAILORING_OUTPUT_DIR = root
            client = TestClient(server.app)
            try:
                resp = client.get("/api/tailoring/runs")
                self.assertEqual(resp.status_code, 200)
                runs = resp.json()["runs"]
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0]["status"], "complete")

                slug = runs[0]["slug"]
                resp = client.get(f"/api/tailoring/runs/{slug}/trace?doc_type=resume")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(all(e.get("doc_type") == "resume" for e in resp.json()["events"]))

                resp = client.get(f"/api/tailoring/runs/{slug}/artifact/meta.json")
                self.assertEqual(resp.status_code, 200)

                resp = client.get(f"/api/tailoring/runs/{slug}/artifact/../../etc/passwd")
                self.assertIn(resp.status_code, (400, 404))

                resp = client.get("/api/packages?status=all")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(len(resp.json()["items"]), 1)

                resp = client.get(f"/api/packages/{slug}")
                self.assertEqual(resp.status_code, 200)
                self.assertIn("job_context", resp.json())

                resp = client.post(
                    f"/api/packages/{slug}/latex/resume",
                    json={"content": "test latex"},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["ok"])
            finally:
                server.TAILORING_OUTPUT_DIR = old


if __name__ == "__main__":
    unittest.main()
