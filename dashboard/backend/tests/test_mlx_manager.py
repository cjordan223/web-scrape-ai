"""Tests for MLX server process management."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure dashboard/backend is on sys.path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.mlx_manager as mgr
from services.mlx_manager import cached_models, start, status, stop


class TestMLXStatus(unittest.TestCase):
    def setUp(self):
        mgr._proc = None
        mgr._model = None

    def test_status_when_not_running(self):
        result = status()
        self.assertFalse(result["running"])
        self.assertIsNone(result["pid"])
        self.assertIsNone(result["model"])


class TestMLXStartStop(unittest.TestCase):
    def setUp(self):
        mgr._proc = None
        mgr._model = None

    @patch("services.mlx_manager.subprocess.Popen")
    def test_start_launches_server(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc
        result = start("mlx-community/Qwen2.5-Coder-32B-Instruct-4bit")
        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], 12345)
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertIn("mlx_lm.server", cmd[0])
        self.assertIn("--model", cmd)

    @patch("services.mlx_manager.subprocess.Popen")
    def test_stop_kills_process(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc
        start("mlx-community/Qwen2.5-Coder-32B-Instruct-4bit")
        result = stop()
        self.assertTrue(result["ok"])
        mock_proc.terminate.assert_called_once()

    @patch("services.mlx_manager.subprocess.Popen")
    def test_start_while_running_restarts(self, mock_popen):
        mock_proc1 = MagicMock()
        mock_proc1.pid = 111
        mock_proc1.poll.return_value = None
        mock_proc2 = MagicMock()
        mock_proc2.pid = 222
        mock_proc2.poll.return_value = None
        mock_popen.side_effect = [mock_proc1, mock_proc2]
        start("mlx-community/model-a")
        start("mlx-community/model-b")
        mock_proc1.terminate.assert_called_once()
        self.assertEqual(status()["pid"], 222)

    def test_stop_when_not_running(self):
        result = stop()
        self.assertTrue(result["ok"])
        self.assertFalse(result["was_running"])


class TestCachedModels(unittest.TestCase):
    def test_cached_models_scans_directory(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            # Create fake model dirs matching HF cache layout
            (td_path / "models--mlx-community--Qwen2.5-Coder-32B-Instruct-4bit" / "snapshots" / "abc").mkdir(parents=True)
            (td_path / "models--mlx-community--Llama-3.1-8B-Instruct-4bit" / "snapshots" / "def").mkdir(parents=True)
            with patch.object(mgr, "HF_CACHE_DIR", td_path):
                result = cached_models()
            ids = [m["id"] for m in result]
            self.assertIn("mlx-community/Qwen2.5-Coder-32B-Instruct-4bit", ids)
            self.assertIn("mlx-community/Llama-3.1-8B-Instruct-4bit", ids)

    def test_cached_models_empty_when_no_dir(self):
        with patch.object(mgr, "HF_CACHE_DIR", Path("/nonexistent/path")):
            result = cached_models()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
