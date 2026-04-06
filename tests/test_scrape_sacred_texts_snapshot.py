from __future__ import annotations

import importlib.util
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRAPE_SACRED_TEXTS_PATH = REPO_ROOT / "scrape_sacred_texts.py"
SOURCE_CACHE_DIR = REPO_ROOT / ".cache" / "html"
SNAPSHOT_FILE = "1-enoch.xml"
EVERSION_DATE_PATTERN = re.compile(
    r'(<date event="eversion" type="ISO" xml:lang="en" TEIform="date">)'
    r"[^<]+"
    r"(</date>)"
)


def normalize_osis_snapshot(xml: str) -> str:
    normalized = xml.replace("\r\n", "\n")
    return EVERSION_DATE_PATTERN.sub(r"\1SCRAPE_TIMESTAMP\2", normalized)


@lru_cache(maxsize=1)
def load_scrape_sacred_texts_main() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scrape_sacred_texts",
        SCRAPE_SACRED_TEXTS_PATH,
    )
    if spec is None or spec.loader is None:
        raise ImportError(
            f"Unable to load scrape_sacred_texts module from {SCRAPE_SACRED_TEXTS_PATH}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main


@pytest.fixture(scope="session")
def generated_1_enoch_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not SOURCE_CACHE_DIR.exists():
        pytest.skip(f"Missing local 1 Enoch HTML cache at {SOURCE_CACHE_DIR}")

    output_dir = tmp_path_factory.mktemp("scrape-sacred-texts-output")
    output_path = output_dir / SNAPSHOT_FILE
    scrape_sacred_texts_main = load_scrape_sacred_texts_main()

    scrape_sacred_texts_main(
        output=str(output_path),
        start_page=0,
        end_page=112,
        delay=0,
        use_proxies=False,
        fetch_dynamic_proxies=False,
        cache_dir=str(SOURCE_CACHE_DIR),
        log_level="WARNING",
    )
    return output_path


def test_scrape_sacred_texts_matches_snapshot(generated_1_enoch_output: Path) -> None:
    expected_path = REPO_ROOT / SNAPSHOT_FILE

    assert generated_1_enoch_output.exists(), "Missing generated 1 Enoch snapshot"
    assert expected_path.exists(), f"Missing committed snapshot: {SNAPSHOT_FILE}"

    actual_xml = normalize_osis_snapshot(
        generated_1_enoch_output.read_text(encoding="utf-8")
    )
    expected_xml = normalize_osis_snapshot(expected_path.read_text(encoding="utf-8"))

    assert actual_xml == expected_xml


def test_scrape_sacred_texts_generates_expected_file(
    generated_1_enoch_output: Path,
) -> None:
    assert generated_1_enoch_output.name == SNAPSHOT_FILE
