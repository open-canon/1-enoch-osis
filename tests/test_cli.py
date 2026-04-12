"""Unit tests for the unified CLI in 1_enoch_osis.cli.

These tests verify that:
- The Settings model correctly defines all four sub-commands.
- Each sub-command carries the expected default values.
- The dispatch logic in Settings.cli_cmd() calls the sub-command's cli_cmd().
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

_cli = importlib.import_module("1_enoch_osis.cli")

Settings = _cli.Settings
EnochSettings = _cli.EnochSettings
JubileesSettings = _cli.JubileesSettings
FBESettings = _cli.FBESettings
VitaSettings = _cli.VitaSettings


# ---------------------------------------------------------------------------
# Sub-command default values
# ---------------------------------------------------------------------------


class TestEnochDefaults:
    def test_output_default(self) -> None:
        s = EnochSettings()
        assert s.output.endswith("1-enoch.xml")

    def test_start_page_default(self) -> None:
        assert EnochSettings().start_page == 0

    def test_end_page_default(self) -> None:
        assert EnochSettings().end_page == 112

    def test_delay_default(self) -> None:
        assert EnochSettings().delay == 1.5

    def test_cache_dir_default(self) -> None:
        assert EnochSettings().cache_dir == ".cache/html"

    def test_log_level_default(self) -> None:
        assert EnochSettings().log_level == "INFO"


class TestJubileesDefaults:
    def test_output_default(self) -> None:
        s = JubileesSettings()
        assert s.output.endswith("jubilees.xml")

    def test_delay_default(self) -> None:
        assert JubileesSettings().delay == 1.5

    def test_cache_dir_default(self) -> None:
        assert JubileesSettings().cache_dir == ".cache/html"

    def test_log_level_default(self) -> None:
        assert JubileesSettings().log_level == "INFO"


class TestFBEDefaults:
    def test_output_dir_default(self) -> None:
        assert FBESettings().output_dir == "documents"

    def test_start_page_default(self) -> None:
        assert FBESettings().start_page == 0

    def test_end_page_default(self) -> None:
        assert FBESettings().end_page == 295

    def test_delay_default(self) -> None:
        assert FBESettings().delay == 1.5

    def test_cache_dir_default(self) -> None:
        assert FBESettings().cache_dir == ".cache/html"

    def test_log_level_default(self) -> None:
        assert FBESettings().log_level == "INFO"


class TestVitaDefaults:
    def test_output_default(self) -> None:
        s = VitaSettings()
        assert s.output.endswith("vita-adae-et-evae.xml")

    def test_delay_default(self) -> None:
        assert VitaSettings().delay == 1.5

    def test_cache_dir_default(self) -> None:
        assert VitaSettings().cache_dir == ".cache/html"

    def test_log_level_default(self) -> None:
        assert VitaSettings().log_level == "INFO"


# ---------------------------------------------------------------------------
# Dispatch: Settings.cli_cmd() delegates to the active sub-command
# ---------------------------------------------------------------------------


class TestDispatch:
    def _make_settings(self, **kwargs: Any) -> Settings:
        """Construct a Settings object with all sub-commands set to None except those in kwargs."""
        defaults = {f: None for f in ("enoch", "jubilees", "fbe", "vita")}
        defaults.update(kwargs)
        return Settings.model_construct(**defaults)

    def test_dispatch_enoch(self) -> None:
        subcmd = MagicMock(spec=EnochSettings)
        settings = self._make_settings(enoch=subcmd)
        settings.cli_cmd()
        subcmd.cli_cmd.assert_called_once_with()

    def test_dispatch_jubilees(self) -> None:
        subcmd = MagicMock(spec=JubileesSettings)
        settings = self._make_settings(jubilees=subcmd)
        settings.cli_cmd()
        subcmd.cli_cmd.assert_called_once_with()

    def test_dispatch_fbe(self) -> None:
        subcmd = MagicMock(spec=FBESettings)
        settings = self._make_settings(fbe=subcmd)
        settings.cli_cmd()
        subcmd.cli_cmd.assert_called_once_with()

    def test_dispatch_vita(self) -> None:
        subcmd = MagicMock(spec=VitaSettings)
        settings = self._make_settings(vita=subcmd)
        settings.cli_cmd()
        subcmd.cli_cmd.assert_called_once_with()

    def test_dispatch_only_first_active_subcommand(self) -> None:
        """When multiple sub-commands are set (shouldn't happen via CLI but can in code),
        only the first matching field is dispatched."""
        enoch = MagicMock(spec=EnochSettings)
        jubilees = MagicMock(spec=JubileesSettings)
        settings = self._make_settings(enoch=enoch, jubilees=jubilees)
        settings.cli_cmd()
        enoch.cli_cmd.assert_called_once_with()
        jubilees.cli_cmd.assert_not_called()


# ---------------------------------------------------------------------------
# CLI parsing via CliApp.run
# (patch each sub-command's cli_cmd so the real scraper is never invoked)
# ---------------------------------------------------------------------------


class TestCliParsing:
    def test_enoch_subcommand_parsed(self) -> None:
        from pydantic_settings import CliApp

        with patch.object(EnochSettings, "cli_cmd"):
            result = CliApp.run(Settings, cli_args=["enoch", "--output=out.xml"])
        assert result.enoch is not None
        assert result.enoch.output == "out.xml"
        assert result.jubilees is None
        assert result.fbe is None
        assert result.vita is None

    def test_jubilees_subcommand_parsed(self) -> None:
        from pydantic_settings import CliApp

        with patch.object(JubileesSettings, "cli_cmd"):
            result = CliApp.run(Settings, cli_args=["jubilees", "--delay=3.0"])
        assert result.jubilees is not None
        assert result.jubilees.delay == 3.0

    def test_fbe_subcommand_parsed(self) -> None:
        from pydantic_settings import CliApp

        with patch.object(FBESettings, "cli_cmd"):
            result = CliApp.run(Settings, cli_args=["fbe", "--start_page=10"])
        assert result.fbe is not None
        assert result.fbe.start_page == 10

    def test_vita_subcommand_parsed(self) -> None:
        from pydantic_settings import CliApp

        with patch.object(VitaSettings, "cli_cmd"):
            result = CliApp.run(Settings, cli_args=["vita", "--cache_dir="])
        assert result.vita is not None
        assert result.vita.cache_dir == ""


# ---------------------------------------------------------------------------
# Each sub-command's cli_cmd calls the right scraper main()
# (patch.object used because patch() rejects names starting with a digit)
# ---------------------------------------------------------------------------


class TestSubCommandCallsScraper:
    def test_enoch_cli_cmd_calls_scraper_main(self) -> None:
        import importlib
        mod = importlib.import_module("1_enoch_osis.scrape_sacred_texts")
        s = EnochSettings(output="out.xml", start_page=4, end_page=10, delay=0.0, cache_dir="", log_level="WARNING")
        with patch.object(mod, "main") as mock_main:
            s.cli_cmd()
        mock_main.assert_called_once_with(
            output="out.xml",
            start_page=4,
            end_page=10,
            delay=0.0,
            cache_dir="",
            log_level="WARNING",
        )

    def test_jubilees_cli_cmd_calls_scraper_main(self) -> None:
        import importlib
        mod = importlib.import_module("1_enoch_osis.scrape_jubilees")
        s = JubileesSettings(output="jub.xml", delay=0.0, cache_dir="", log_level="WARNING")
        with patch.object(mod, "main") as mock_main:
            s.cli_cmd()
        mock_main.assert_called_once_with(
            output="jub.xml",
            delay=0.0,
            cache_dir="",
            log_level="WARNING",
        )

    def test_fbe_cli_cmd_calls_scraper_main(self) -> None:
        import importlib
        mod = importlib.import_module("1_enoch_osis.scrape_fbe")
        s = FBESettings(output_dir="docs", start_page=1, end_page=5, delay=0.0, cache_dir="", log_level="WARNING")
        with patch.object(mod, "main") as mock_main:
            s.cli_cmd()
        mock_main.assert_called_once_with(
            output_dir="docs",
            start_page=1,
            end_page=5,
            delay=0.0,
            cache_dir="",
            log_level="WARNING",
        )

    def test_vita_cli_cmd_calls_scraper_main(self) -> None:
        import importlib
        mod = importlib.import_module("1_enoch_osis.scrape_vita_adae_et_evae")
        s = VitaSettings(output="vita.xml", delay=0.0, cache_dir="", log_level="WARNING")
        with patch.object(mod, "main") as mock_main:
            s.cli_cmd()
        mock_main.assert_called_once_with(
            output="vita.xml",
            delay=0.0,
            cache_dir="",
            log_level="WARNING",
        )
