"""Integration tests for MLX management endpoints."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.mlx_manager as mgr


class TestMLXEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["JOBFORGE_MANAGE_MLX"] = "1"

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("JOBFORGE_MANAGE_MLX", None)

    def setUp(self):
        mgr._proc = None
        mgr._model = None
        mgr._pull_proc = None
        mgr._pull_model = None
        mgr._pull_log = []

    def _get_client(self):
        from app import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_status_returns_not_running(self):
        client = self._get_client()
        resp = client.get("/api/llm/mlx/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["running"])
        self.assertIsNone(data["pid"])

    def test_cached_models_returns_list(self):
        client = self._get_client()
        resp = client.get("/api/llm/mlx/models")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("models", data)
        self.assertIsInstance(data["models"], list)

    @patch("services.mlx_manager.subprocess.Popen")
    def test_start_stop_lifecycle(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc
        client = self._get_client()

        resp = client.post("/api/llm/mlx/start", json={"model": "mlx-community/test-model"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

        resp = client.get("/api/llm/mlx/status")
        self.assertTrue(resp.json()["running"])
        self.assertEqual(resp.json()["model"], "mlx-community/test-model")

        resp = client.post("/api/llm/mlx/stop")
        self.assertTrue(resp.json()["ok"])

    def test_start_without_model_returns_400(self):
        client = self._get_client()
        resp = client.post("/api/llm/mlx/start", json={})
        self.assertEqual(resp.status_code, 400)

    def test_pull_without_model_id_returns_400(self):
        client = self._get_client()
        resp = client.post("/api/llm/mlx/pull", json={})
        self.assertEqual(resp.status_code, 400)

    def test_pull_status_when_idle(self):
        client = self._get_client()
        resp = client.get("/api/llm/mlx/pull/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["pulling"])

    def test_start_blocked_without_flag(self):
        os.environ.pop("JOBFORGE_MANAGE_MLX", None)
        client = self._get_client()
        resp = client.post("/api/llm/mlx/start", json={"model": "test"})
        self.assertEqual(resp.status_code, 403)
        os.environ["JOBFORGE_MANAGE_MLX"] = "1"

    def test_stop_blocked_without_flag(self):
        os.environ.pop("JOBFORGE_MANAGE_MLX", None)
        client = self._get_client()
        resp = client.post("/api/llm/mlx/stop")
        self.assertEqual(resp.status_code, 403)
        os.environ["JOBFORGE_MANAGE_MLX"] = "1"

    def test_pull_blocked_without_flag(self):
        os.environ.pop("JOBFORGE_MANAGE_MLX", None)
        client = self._get_client()
        resp = client.post("/api/llm/mlx/pull", json={"model_id": "test"})
        self.assertEqual(resp.status_code, 403)
        os.environ["JOBFORGE_MANAGE_MLX"] = "1"


if __name__ == "__main__":
    unittest.main()
