"""Tests for LLM model resolution logic."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tailor import ollama, config as cfg


class TestGetLoadedModel(unittest.TestCase):
    def setUp(self):
        ollama._MODEL_CACHE = None

    def tearDown(self):
        ollama._MODEL_CACHE = None

    @patch.object(cfg, "OLLAMA_MODEL", "default")
    def test_default_model_raises_when_no_explicit_override(self):
        """When model is 'default' and no env override, should raise instead of auto-picking."""
        with self.assertRaises(RuntimeError) as ctx:
            ollama.get_loaded_model()
        self.assertIn("No model configured", str(ctx.exception))

    @patch.object(cfg, "OLLAMA_MODEL", "qwen3:32b")
    def test_explicit_model_returns_directly(self):
        result = ollama.get_loaded_model()
        self.assertEqual(result, "qwen3:32b")

    @patch.object(cfg, "OLLAMA_MODEL", "qwen3:32b")
    def test_model_cache_is_populated(self):
        ollama.get_loaded_model()
        self.assertEqual(ollama._MODEL_CACHE, "qwen3:32b")

    @patch.object(cfg, "OLLAMA_MODEL", "")
    def test_empty_model_raises(self):
        with self.assertRaises(RuntimeError):
            ollama.get_loaded_model()


if __name__ == "__main__":
    unittest.main()
