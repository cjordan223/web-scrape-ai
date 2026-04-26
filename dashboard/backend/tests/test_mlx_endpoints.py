"""Regression tests for removed MLX management endpoints."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestMLXEndpoints(unittest.TestCase):
    def _get_client(self):
        from app import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_mlx_management_routes_are_removed(self):
        client = self._get_client()
        for method, path in (
            ("get", "/api/llm/mlx/status"),
            ("post", "/api/llm/mlx/start"),
            ("post", "/api/llm/mlx/stop"),
            ("get", "/api/llm/mlx/models"),
            ("post", "/api/llm/mlx/pull"),
            ("get", "/api/llm/mlx/pull/status"),
        ):
            with self.subTest(path=path):
                if method == "post":
                    resp = client.post(path, json={})
                else:
                    resp = client.get(path)
                self.assertIn(resp.status_code, (404, 405))


if __name__ == "__main__":
    unittest.main()
