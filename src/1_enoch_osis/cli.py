"""Unified CLI for all scrapers, dispatching via pydantic-settings sub-commands."""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, CliApp, CliSubCommand

from .scrape_fbe import (
    FILE_RANGE as FBE_FILE_RANGE,
    DEFAULT_OUTPUT_DIR as FBE_DEFAULT_OUTPUT_DIR,
)
from .scrape_jubilees import DEFAULT_OUTPUT as JUBILEES_DEFAULT_OUTPUT
from .scrape_sacred_texts import (
    FILE_RANGE as ENOCH_FILE_RANGE,
    DEFAULT_OUTPUT as ENOCH_DEFAULT_OUTPUT,
)
from .scrape_vita_adae_et_evae import DEFAULT_OUTPUT as VITA_DEFAULT_OUTPUT

LOGGER = logging.getLogger(__name__)


def _configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


# ---------------------------------------------------------------------------
# Per-scraper sub-command settings
# ---------------------------------------------------------------------------


class EnochSettings(BaseSettings):
    """Settings for the 1 Enoch scraper (sacred-texts.com/bib/boe/)."""

    output: str = Field(
        default=ENOCH_DEFAULT_OUTPUT,
        description="Output XML filename.",
    )
    start_page: int = Field(
        default=ENOCH_FILE_RANGE[0],
        description="First page to process (0 = title page, 4 = Chapter I).",
    )
    end_page: int = Field(
        default=ENOCH_FILE_RANGE[1],
        description="Last page to process.",
    )
    delay: float = Field(
        default=1.5,
        description="Delay between HTTP requests in seconds.",
    )
    cache_dir: str = Field(
        default=".cache/html",
        description="Directory for caching downloaded HTML. Empty string disables caching.",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR.",
    )

    def cli_cmd(self) -> None:
        """Run the 1 Enoch scraper."""
        _configure_logging(self.log_level)
        from .scrape_sacred_texts import main

        main(
            output=self.output,
            start_page=self.start_page,
            end_page=self.end_page,
            delay=self.delay,
            cache_dir=self.cache_dir,
            log_level=self.log_level,
        )


class JubileesSettings(BaseSettings):
    """Settings for the Jubilees scraper (sacred-texts.com/bib/jub/)."""

    output: str = Field(
        default=JUBILEES_DEFAULT_OUTPUT,
        description="Output XML filename.",
    )
    delay: float = Field(
        default=1.5,
        description="Delay between HTTP requests in seconds.",
    )
    cache_dir: str = Field(
        default=".cache/html",
        description="Directory for caching downloaded HTML. Empty string disables caching.",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR.",
    )

    def cli_cmd(self) -> None:
        """Run the Jubilees scraper."""
        _configure_logging(self.log_level)
        from .scrape_jubilees import main

        main(
            output=self.output,
            delay=self.delay,
            cache_dir=self.cache_dir,
            log_level=self.log_level,
        )


class FBESettings(BaseSettings):
    """Settings for the Forgotten Books of Eden scraper (sacred-texts.com/bib/fbe/)."""

    output_dir: str = Field(
        default=FBE_DEFAULT_OUTPUT_DIR,
        description="Directory to write output XML files.",
    )
    start_page: int = Field(
        default=FBE_FILE_RANGE[0],
        description="First page number to fetch.",
    )
    end_page: int = Field(
        default=FBE_FILE_RANGE[1],
        description="Last page number to fetch.",
    )
    delay: float = Field(
        default=1.5,
        description="Delay between HTTP requests in seconds.",
    )
    cache_dir: str = Field(
        default=".cache/html",
        description="Directory for caching downloaded HTML. Empty string disables caching.",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR.",
    )

    def cli_cmd(self) -> None:
        """Run the Forgotten Books of Eden scraper."""
        _configure_logging(self.log_level)
        from .scrape_fbe import main

        main(
            output_dir=self.output_dir,
            start_page=self.start_page,
            end_page=self.end_page,
            delay=self.delay,
            cache_dir=self.cache_dir,
            log_level=self.log_level,
        )


class VitaSettings(BaseSettings):
    """Settings for the Vita Adae et Evae scraper (sacred-texts.com/chr/apo/adamnev.htm)."""

    output: str = Field(
        default=VITA_DEFAULT_OUTPUT,
        description="Output XML filename.",
    )
    delay: float = Field(
        default=1.5,
        description="Delay between HTTP requests in seconds.",
    )
    cache_dir: str = Field(
        default=".cache/html",
        description="Directory for caching downloaded HTML. Empty string disables caching.",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR.",
    )

    def cli_cmd(self) -> None:
        """Run the Vita Adae et Evae scraper."""
        _configure_logging(self.log_level)
        from .scrape_vita_adae_et_evae import main

        main(
            output=self.output,
            delay=self.delay,
            cache_dir=self.cache_dir,
            log_level=self.log_level,
        )


# ---------------------------------------------------------------------------
# Root settings / dispatcher
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Unified scraper CLI.  Choose a sub-command to run the corresponding scraper."""

    enoch: CliSubCommand[EnochSettings]
    jubilees: CliSubCommand[JubileesSettings]
    fbe: CliSubCommand[FBESettings]
    vita: CliSubCommand[VitaSettings]

    def cli_cmd(self) -> None:
        """Dispatch to the activated sub-command."""
        for field_name in ("enoch", "jubilees", "fbe", "vita"):
            subcmd = getattr(self, field_name)
            if subcmd is not None:
                subcmd.cli_cmd()
                return


def main() -> None:
    """Entry point for the unified scraper CLI."""
    CliApp.run(Settings)


if __name__ == "__main__":
    main()
