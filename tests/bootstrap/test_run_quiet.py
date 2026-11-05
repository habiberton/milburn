from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
RUN_QUIET = REPOSITORY / "scripts" / "run-quiet.sh"


class RunQuietCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.log_dir = self.root / "logs"
        self.environment = os.environ.copy()
        self.environment["MILBURN_LOG_DIR"] = str(self.log_dir)
        self.environment.pop("MILBURN_VERBOSE", None)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_quiet(
        self, *arguments: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(RUN_QUIET), *arguments],
            cwd=REPOSITORY,
            env=self.environment if environment is None else environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_missing_command_fails_without_creating_a_log_directory(self) -> None:
        result = self.run_quiet()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing command", result.stderr.lower())
        self.assertFalse(self.log_dir.exists())

    def test_verbose_without_a_command_still_fails_closed(self) -> None:
        result = self.run_quiet("--verbose")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing command", result.stderr.lower())

    def test_nonexistent_executable_fails_before_creating_a_log(self) -> None:
        result = self.run_quiet("milburn-command-that-does-not-exist")

        self.assertEqual(result.returncode, 127)
        self.assertIn("executable not found", result.stderr.lower())
        self.assertFalse(self.log_dir.exists())

    def test_existing_but_non_executable_file_is_rejected(self) -> None:
        impostor = self.root / "looks-like-a-command"
        impostor.write_text("#!/bin/sh\necho should-not-run\n", encoding="utf-8")
        impostor.chmod(stat.S_IRUSR | stat.S_IWUSR)

        result = self.run_quiet(str(impostor))

        self.assertEqual(result.returncode, 126)
        self.assertIn("not executable", result.stderr.lower())
        self.assertNotIn("should-not-run", result.stdout + result.stderr)
        self.assertFalse(self.log_dir.exists())

    def test_directory_cannot_be_used_as_an_executable(self) -> None:
        command_directory = self.root / "command-directory"
        command_directory.mkdir()

        result = self.run_quiet(str(command_directory))

        self.assertEqual(result.returncode, 126)
        self.assertIn("not executable", result.stderr.lower())
        self.assertFalse(self.log_dir.exists())

    def test_log_directory_that_is_a_file_fails_before_running_command(self) -> None:
        self.log_dir.write_text("not a directory", encoding="utf-8")
        marker = self.root / "command-ran"

        result = self.run_quiet("sh", "-c", f"touch {marker}")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("log directory", result.stderr.lower())
        self.assertFalse(marker.exists())
        self.assertEqual(self.log_dir.read_text(encoding="utf-8"), "not a directory")

    def test_uncreatable_nested_log_directory_does_not_run_command(self) -> None:
        parent_file = self.root / "parent-file"
        parent_file.write_text("occupied", encoding="utf-8")
        environment = self.environment.copy()
        environment["MILBURN_LOG_DIR"] = str(parent_file / "logs")
        marker = self.root / "command-ran"

        result = self.run_quiet(
            "sh", "-c", f"touch {marker}", environment=environment
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("log directory", result.stderr.lower())
        self.assertFalse(marker.exists())

    def test_unwritable_existing_log_directory_does_not_run_command(self) -> None:
        self.log_dir.mkdir()
        self.log_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        marker = self.root / "command-ran"
        try:
            result = self.run_quiet("sh", "-c", f"touch {marker}")
        finally:
            self.log_dir.chmod(stat.S_IRWXU)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("log", result.stderr.lower())
        self.assertFalse(marker.exists())

    def test_failure_returns_command_status_and_prints_only_last_40_log_lines(self) -> None:
        command = "i=1; while [ $i -le 45 ]; do echo line-$i; i=$((i+1)); done; exit 7"

        result = self.run_quiet("sh", "-c", command)

        self.assertEqual(result.returncode, 7)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 41)
        self.assertRegex(lines[0], r"^run-quiet FAILED exit=7 \([0-9]+s\): .+ \[log: .+\]$")
        self.assertEqual(lines[1:], [f"line-{number}" for number in range(6, 46)])
        self.assertEqual(result.stderr, "")
        log_path = self.log_path_from_summary(lines[0])
        self.assertEqual(
            log_path.read_text(encoding="utf-8").splitlines(),
            [f"line-{number}" for number in range(1, 46)],
        )

    def test_failing_command_output_is_retained_even_when_shorter_than_tail(self) -> None:
        result = self.run_quiet("sh", "-c", "echo diagnostic >&2; exit 19")

        self.assertEqual(result.returncode, 19)
        self.assertEqual(result.stdout.splitlines()[1:], ["diagnostic"])
        log_path = self.log_path_from_summary(result.stdout.splitlines()[0])
        self.assertEqual(log_path.read_text(encoding="utf-8"), "diagnostic\n")

    def test_success_prints_one_summary_and_retains_complete_combined_output(self) -> None:
        result = self.run_quiet(
            "sh", "-c", "printf 'standard output\\n'; printf 'standard error\\n' >&2"
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        summary = result.stdout.rstrip("\n")
        self.assertRegex(summary, r"^run-quiet OK \([0-9]+s\): .+ \[log: .+\]$")
        log_path = self.log_path_from_summary(summary)
        self.assertEqual(
            log_path.read_text(encoding="utf-8"),
            "standard output\nstandard error\n",
        )

    def test_command_arguments_are_not_reparsed_by_the_wrapper(self) -> None:
        argument = "spaces; wildcards * and $dollars"

        result = self.run_quiet("printf", "%s", argument)

        self.assertEqual(result.returncode, 0)
        summary = result.stdout.rstrip("\n")
        log_path = self.log_path_from_summary(summary)
        self.assertEqual(log_path.read_text(encoding="utf-8"), argument)

    def test_default_log_directory_uses_tmpdir(self) -> None:
        environment = self.environment.copy()
        environment.pop("MILBURN_LOG_DIR")
        environment["TMPDIR"] = str(self.root / "custom-tmp")

        result = self.run_quiet("printf", "ok", environment=environment)

        self.assertEqual(result.returncode, 0)
        log_path = self.log_path_from_summary(result.stdout.rstrip("\n"))
        self.assertEqual(log_path.parent, self.root / "custom-tmp" / "milburn-logs")
        self.assertEqual(log_path.read_text(encoding="utf-8"), "ok")

    def test_each_invocation_uses_a_distinct_log(self) -> None:
        first = self.run_quiet("printf", "first")
        second = self.run_quiet("printf", "second")

        first_log = self.log_path_from_summary(first.stdout.rstrip("\n"))
        second_log = self.log_path_from_summary(second.stdout.rstrip("\n"))
        self.assertNotEqual(first_log, second_log)
        self.assertEqual(first_log.read_text(encoding="utf-8"), "first")
        self.assertEqual(second_log.read_text(encoding="utf-8"), "second")

    def test_verbose_option_streams_stdout_and_stderr_without_wrapper_output(self) -> None:
        result = self.run_quiet(
            "--verbose",
            "sh",
            "-c",
            "printf 'direct stdout\\n'; printf 'direct stderr\\n' >&2",
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "direct stdout\n")
        self.assertEqual(result.stderr, "direct stderr\n")
        self.assertFalse(self.log_dir.exists())

    def test_verbose_environment_streams_output_and_propagates_failure(self) -> None:
        environment = self.environment.copy()
        environment["MILBURN_VERBOSE"] = "1"

        result = self.run_quiet(
            "sh",
            "-c",
            "printf 'direct failure\\n' >&2; exit 23",
            environment=environment,
        )

        self.assertEqual(result.returncode, 23)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "direct failure\n")
        self.assertFalse(self.log_dir.exists())

    @staticmethod
    def log_path_from_summary(summary: str) -> Path:
        match = re.search(r" \[log: (.+)\]$", summary)
        if match is None:
            raise AssertionError(f"summary has no log path: {summary!r}")
        return Path(match.group(1))


if __name__ == "__main__":
    unittest.main()
