"""Regression guards for the Lidarr degrade-and-warn behavior.

The bridge is documented as optional ("Failures during mid-run add operations
are caught at the call site and never block playlist generation."). The
v1 implementation contradicted this by calling sys.exit(1) on validate()
failure, which took down the whole service when Lidarr was briefly
unreachable, restarting, or had a typo'd profile name.

Match the degrade-and-warn pattern used by Last.fm, ListenBrainz, and
AudioMuse: log a warning, set self.lidarr = None, and continue.
"""

import re
from pathlib import Path


_MAIN = Path(__file__).resolve().parent.parent / "octogen" / "main.py"


class TestLidarrValidateDegradeAndWarn:
    @classmethod
    def setup_class(cls):
        cls.source = _MAIN.read_text(encoding="utf-8")

    def test_validate_failure_does_not_call_sys_exit(self):
        """Locks in the fix: the except RuntimeError branch must not
        sys.exit. If a future commit reverts to sys.exit(1) in this block,
        this test fails."""
        # Match the Lidarr-specific except RuntimeError block and assert
        # sys.exit does not appear inside it.
        pattern = re.compile(
            r"self\.lidarr\.validate\(\).*?"
            r"except RuntimeError as e:\s*"
            r"(.*?)"
            r"(?=\n        \S|\nclass |\n    def )",
            re.DOTALL,
        )
        match = pattern.search(self.source)
        assert match, "Could not locate the Lidarr validate() except block"
        block = match.group(1)
        assert "sys.exit" not in block, (
            "Lidarr validate() failure must not sys.exit — "
            "it should log a warning and set self.lidarr = None to degrade gracefully"
        )

    def test_validate_failure_sets_lidarr_to_none(self):
        """The degrade path must clear self.lidarr so downstream code
        (_handle_missing_track) skips the Lidarr push branch."""
        pattern = re.compile(
            r"self\.lidarr\.validate\(\).*?"
            r"except RuntimeError as e:.*?"
            r"self\.lidarr\s*=\s*None",
            re.DOTALL,
        )
        assert pattern.search(self.source), (
            "Lidarr validate() failure must set self.lidarr = None"
        )

    def test_validate_failure_logs_warning_not_error(self):
        """Failure-to-validate is a degraded state, not a hard error.
        Use logger.warning so the noise level matches Last.fm/AudioMuse."""
        pattern = re.compile(
            r"self\.lidarr\.validate\(\).*?"
            r"except RuntimeError as e:.*?"
            r"logger\.warning\(",
            re.DOTALL,
        )
        assert pattern.search(self.source), (
            "Lidarr validate() failure should log at warning level"
        )


class TestLidarrPushErrorLogsTraceback:
    @classmethod
    def setup_class(cls):
        cls.source = _MAIN.read_text(encoding="utf-8")

    def test_push_error_uses_exc_info(self):
        """The Lidarr push error path should log with exc_info=True so
        the traceback is captured for diagnosis. Matches the DB error
        path's exc_info=True (consistency)."""
        pattern = re.compile(
            r'logger\.warning\(\s*'
            r'"Lidarr push error for %r: %s"[^)]*?exc_info\s*=\s*True',
            re.DOTALL,
        )
        assert pattern.search(self.source), (
            "Lidarr push-error log must include exc_info=True for traceback capture"
        )
