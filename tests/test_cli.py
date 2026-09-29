"""Tests for :mod:`omnidoc.ui.cli` (the console-script entry point).

Drives the typer app with ``CliRunner`` so the previously-uncovered CLI
layer gets a regression net: chunking-param validation (exit code 2),
successful conversion (exit 0), the pure helpers, and the LLM probe exit
codes.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from typer.testing import CliRunner

from omnidoc.ui import cli

runner = CliRunner()


class TestUniqueCliName(unittest.TestCase):

    def test_first_name_claimed_unchanged(self):
        used: set[str] = set()
        self.assertEqual(cli._unique_cli_name("report", "jsonl", used), "report.jsonl")

    def test_collision_gets_numeric_suffix(self):
        used: set[str] = set()
        first = cli._unique_cli_name("report", "chunks.jsonl", used)
        second = cli._unique_cli_name("report", "chunks.jsonl", used)
        self.assertEqual(first, "report.chunks.jsonl")
        self.assertEqual(second, "report_1.chunks.jsonl")


class TestResolveLlm(unittest.TestCase):

    def test_env_fallbacks_applied(self):
        with mock.patch.dict(
            os.environ,
            {
                "OMNIDOC_LLM_BASE_URL": "http://env-url",
                "OMNIDOC_LLM_API_KEY": "env-key",
                "OMNIDOC_LLM_MODEL": "env-model",
            },
        ):
            llm = cli._resolve_llm(True, "", "", "", "p", False)
        self.assertEqual(llm.base_url, "http://env-url")
        self.assertEqual(llm.api_key, "env-key")
        self.assertEqual(llm.model, "env-model")

    def test_flags_win_over_env(self):
        with mock.patch.dict(
            os.environ, {"OMNIDOC_LLM_API_KEY": "env-key"}, clear=False
        ):
            llm = cli._resolve_llm(True, "http://flag", "flag-key", "m", "", False)
        self.assertEqual(llm.api_key, "flag-key")

    def test_offline_disables_llm(self):
        llm = cli._resolve_llm(True, "u", "k", "m", "", True)
        self.assertFalse(llm.enabled)


class TestBuildConfig(unittest.TestCase):

    def test_chunking_settings_wired(self):
        cfg = cli._build_config("md", False, True, True, True, "markdown", 256, 32, 0, False, False, "", "", "", "")
        self.assertTrue(cfg.chunking.enabled)
        self.assertEqual(cfg.chunking.strategy, "markdown")
        self.assertEqual(cfg.chunking.chunk_size, 256)
        self.assertEqual(cfg.chunking.chunk_overlap, 32)

    def test_validate_mirrors_chunker_rules(self):
        cfg = cli._build_config("md", False, True, True, True, "fixed", 64, 64, 0, False, False, "", "", "", "")
        issues = cfg.chunking.validate_issues()
        self.assertTrue(any("chunk_overlap" in i for i in issues))


class TestConvertCommand(unittest.TestCase):

    def _make_file(self, ext: str = ".md") -> str:
        fd, path = tempfile.mkstemp(suffix=ext)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# hello\n\nbody text")
        return path

    def test_invalid_chunk_params_exit_code_2(self):
        # M2 regression: invalid chunking params are rejected before the
        # pipeline runs, instead of silently skipping chunking with exit 0.
        path = self._make_file()
        try:
            result = runner.invoke(
                cli.app,
                ["convert", path, "--chunk", "--chunk-overlap", "100", "--chunk-size", "64"],
            )
            self.assertEqual(result.exit_code, 2)
            self.assertIn("分块参数校验失败", result.output)
        finally:
            os.unlink(path)

    def test_zero_chunk_size_exit_code_2(self):
        path = self._make_file()
        try:
            result = runner.invoke(cli.app, ["convert", path, "--chunk", "--chunk-size", "0"])
            self.assertEqual(result.exit_code, 2)
        finally:
            os.unlink(path)

    def test_successful_conversion_exits_zero(self):
        path = self._make_file()
        try:
            result = runner.invoke(cli.app, ["convert", path])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("hello", result.output)
            self.assertIn("状态=ok", result.output)
        finally:
            os.unlink(path)

    def test_valid_chunk_params_produce_chunks(self):
        path = self._make_file()
        try:
            result = runner.invoke(
                cli.app, ["convert", path, "--chunk", "--chunk-size", "10", "--chunk-overlap", "2"]
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("分块", result.output)
        finally:
            os.unlink(path)

    def test_export_chunks_writes_jsonl(self):
        path = self._make_file()
        out_dir = tempfile.mkdtemp(prefix="omnidoc_cli_test_")
        try:
            result = runner.invoke(
                cli.app,
                ["convert", path, "--chunk", "--chunk-size", "10", "--chunk-overlap", "2",
                 "--output-dir", out_dir, "--export-chunks"],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("已导出分块", result.output)
            files = [f for f in os.listdir(out_dir) if f.endswith(".chunks.jsonl")]
            self.assertEqual(len(files), 1)
            with open(os.path.join(out_dir, files[0]), encoding="utf-8") as f:
                lines = [json.loads(line) for line in f if line.strip()]
            self.assertTrue(lines)
            self.assertIn("text", lines[0])
        finally:
            os.unlink(path)

    def test_json_output_flag(self):
        path = self._make_file()
        try:
            result = runner.invoke(cli.app, ["convert", path, "--json"])
            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload[0]["source"], path)
            self.assertTrue(payload[0]["success"])
        finally:
            os.unlink(path)


class TestTestLlmCommand(unittest.TestCase):

    def test_failure_exit_code_1(self):
        fake = mock.Mock()
        fake.chat.completions.create.side_effect = RuntimeError("boom")
        with mock.patch("openai.OpenAI", return_value=fake):
            result = runner.invoke(
                cli.app, ["test-llm", "--base-url", "http://x", "--api-key", "k", "--model", "m"]
            )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("连接失败", result.output)


if __name__ == "__main__":
    unittest.main()
