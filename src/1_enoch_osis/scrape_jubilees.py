# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "beautifulsoup4",
#     "fire",
#     "httpx",
#     "pyosis",
#     "tqdm",
# ]
# ///
"""Download and parse Jubilees to OSIS XML."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

import fire
import pyosis
from bs4 import BeautifulSoup
from tqdm import tqdm

from .http_client import CachedHttpFetcher
from .osis_parsing import normalize_whitespace, roman_to_int

LOGGER = logging.getLogger(__name__)

BASE_URL: Final[str] = "https://sacred-texts.com/bib/jub/"
PAGE_RANGE: Final[tuple[int, int]] = (0, 87)
FRONT_MATTER_END_PAGE: Final[int] = 11
CONTENT_START_PAGE: Final[int] = 12
DEFAULT_OUTPUT: Final[str] = str(Path("documents") / "jubilees.xml")
OSIS_WORK_ID: Final[str] = "Jub"
BOOK_TITLE: Final[str] = "The Book of Jubilees"
BOOK_SHORT_TITLE: Final[str] = "Jubilees"
FRONT_MATTER_TITLES: Final[dict[int, str]] = {
    0: "Title Page",
    1: "Editors' Preface",
    2: "Introduction: Short Account of the Book",
    3: "Introduction: Titles",
    4: "Introduction: Versions and Original Language",
    5: "Introduction: Affinities with Other Literature",
    6: "Introduction: The Special Aims and General Character of the Book",
    7: "Introduction: Authorship and Date",
    8: "Introduction: Bibliography",
    9: "Short Titles, Abbreviations and Brackets Used in this Edition",
    10: "Erratum",
    11: "Prologue",
}

FOOTNOTE_LINK_RE: Final[re.Pattern[str]] = re.compile(
    r"\[\]\([^)]*\)\[\d+\]\([^)]*\)|\[\d+\]\([^)]*\)"
)
MARKDOWN_LINK_RE: Final[re.Pattern[str]] = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MARKDOWN_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^#+\s+")
HEADING_CHAPTER_RE: Final[re.Pattern[str]] = re.compile(
    r"\((?P<chapter>[ivxlcdm]+)\.", re.IGNORECASE
)
RANGE_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\((?P<chapter>[ivxlcdm]+)\..*\)\.?$", re.IGNORECASE
)
CHAPTER_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<chapter>[IVXLCDM]+)\.\s+(?P<text>.+)$"
)
VERSE_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<verse>\d+)\.\s+(?P<text>.+)$")
INLINE_VERSE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?<=^)|(?<=\s))(?P<verse>\d+)\.\s+"
)
JOIN_WITH_PREVIOUS_PREFIXES: Final[tuple[str, ...]] = (
    "and ",
    "or ",
    "but ",
    "for ",
    "that ",
    "which ",
    "who ",
    "whom ",
    "whose ",
    "when ",
    "where ",
    "while ",
    "to ",
    "of ",
    "in ",
    "on ",
    "at ",
)


@dataclass
class VerseBlock:
    verse_numbers: list[int]
    text: str


@dataclass
class FrontMatterSection:
    page_number: int
    title: str
    paragraphs: list[str]


@dataclass
class Section:
    page_number: int
    title: str
    chapter_number: int
    verses: list[VerseBlock]


@dataclass
class Chapter:
    number: int
    sections: list[Section]


class JubileesParser:
    def __init__(self, cache_dir: str | None = None, delay: float = 3.0) -> None:
        self.delay = delay
        self.http = CachedHttpFetcher(cache_dir=cache_dir, delay=delay, logger=LOGGER)

    def close(self) -> None:
        self.http.close()

    def fetch_page(
        self,
        page_number: int,
        retry_count: int = 3,
        delay: float | None = None,
    ) -> str:
        url = self.page_url(page_number)
        cache_path = self.http.cache_path_for(url)

        if delay is not None and delay != self.http.delay:
            self.delay = delay
            self.http.delay = delay

        if cache_path and cache_path.exists():
            cached = cache_path.read_text(encoding="utf-8")
            if self.is_valid_page(cached):
                return cached

            LOGGER.warning(
                "Discarding invalid cached Jubilees source at %s", cache_path
            )
            cache_path.unlink()

        fetched = self.http.fetch_text(url=url, retry_count=retry_count)
        if self.is_valid_page(fetched):
            return fetched

        if cache_path and cache_path.exists():
            cache_path.unlink()

        raise RuntimeError(
            "Source page did not contain a usable Jubilees witness; direct access to sacred-texts.com may be blocked in this environment"
        )

    @staticmethod
    def page_url(page_number: int) -> str:
        return f"{BASE_URL}jub{page_number:02d}.htm"

    @staticmethod
    def is_valid_page(text: str) -> bool:
        return (
            "Book of Jubilees" in text
            and "Just a moment" not in text
            and "Markdown Content:" not in text
            and "<html" in text.lower()
        )

    @staticmethod
    def clean_line(line: str) -> str:
        cleaned = line.strip()
        cleaned = MARKDOWN_HEADING_RE.sub("", cleaned)
        cleaned = FOOTNOTE_LINK_RE.sub("", cleaned)
        cleaned = MARKDOWN_LINK_RE.sub(r"\1", cleaned)
        cleaned = cleaned.replace("[paragraph continues]", "")
        cleaned = cleaned.replace("**", "")
        cleaned = cleaned.replace("__", "")
        cleaned = cleaned.replace("\\_", "_")
        cleaned = cleaned.replace("_", "")
        cleaned = html.unescape(cleaned)
        return normalize_whitespace(cleaned)

    def extract_page_components(self, raw_text: str) -> tuple[list[str], list[str]]:
        if not self.is_valid_page(raw_text):
            raise RuntimeError(
                "Jubilees scraper expects original sacred-texts HTML, not mirror-derived markdown or interstitial pages"
            )

        soup = BeautifulSoup(raw_text, "html.parser")
        body = soup.body if soup.body else soup

        headings: list[str] = []
        content_lines: list[str] = []
        in_footnotes = False

        for element in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"]):
            stripped = element.get_text(" ", strip=True)
            if not stripped:
                continue

            cleaned = self.clean_line(stripped)
            if not cleaned:
                continue

            if cleaned.endswith("Internet Sacred Text Archive"):
                continue

            if cleaned in {"Contents", "Start Reading", "Index", "Previous", "Next"}:
                continue

            if cleaned.startswith("["):
                continue

            if "Sacred Texts" in cleaned and element.name == "p":
                continue

            if cleaned == "Footnotes":
                in_footnotes = True
                continue

            if in_footnotes:
                continue

            if cleaned.startswith("p. "):
                continue

            if element.name.startswith("h"):
                headings.append(cleaned)
                continue

            content_lines.append(cleaned)

        return headings, content_lines

    @staticmethod
    def should_join_with_previous(paragraph: str, previous: str) -> bool:
        lower = paragraph.lower()
        return (
            lower.startswith(JOIN_WITH_PREVIOUS_PREFIXES)
            or paragraph[:1].islower()
            or previous.endswith(("and", "or", "of", "the", "a"))
        )

    def build_paragraphs(self, lines: list[str]) -> list[str]:
        paragraphs: list[str] = []
        for line in lines:
            if not paragraphs:
                paragraphs.append(line)
                continue

            if self.should_join_with_previous(line, paragraphs[-1]):
                paragraphs[-1] = normalize_whitespace(f"{paragraphs[-1]} {line}")
                continue

            paragraphs.append(line)

        return paragraphs

    def parse_front_matter_page(
        self, page_number: int, raw_text: str
    ) -> FrontMatterSection:
        headings, content_lines = self.extract_page_components(raw_text)
        title = FRONT_MATTER_TITLES[page_number]

        if page_number == 0:
            body_lines = [heading for heading in headings if heading] + content_lines
        else:
            body_lines = content_lines

        duplicate_lines = {title, title.upper()}
        if page_number != 0 and ":" in title:
            for part in title.split(":"):
                normalized_part = part.strip()
                duplicate_lines.add(normalized_part)
                duplicate_lines.add(normalized_part.upper())

        paragraphs = [
            line
            for line in self.build_paragraphs(body_lines)
            if line not in duplicate_lines
        ]
        return FrontMatterSection(
            page_number=page_number, title=title, paragraphs=paragraphs
        )

    def extract_chapter_number(self, title: str, content_lines: list[str]) -> int:
        title_match = HEADING_CHAPTER_RE.search(title)
        if title_match:
            return roman_to_int(title_match.group("chapter"))

        if content_lines:
            range_match = RANGE_LINE_RE.match(content_lines[0])
            if range_match:
                return roman_to_int(range_match.group("chapter"))

            chapter_match = CHAPTER_LINE_RE.match(content_lines[0])
            if chapter_match:
                return roman_to_int(chapter_match.group("chapter"))

        raise RuntimeError(
            f"Could not determine Jubilees chapter from section title: {title}"
        )

    def parse_verses(
        self,
        page_number: int,
        chapter_number: int,
        content_lines: list[str],
    ) -> list[VerseBlock]:
        lines = content_lines[:]
        if lines and RANGE_LINE_RE.match(lines[0]):
            lines = lines[1:]

        text = normalize_whitespace(
            " ".join(
                line
                for line in lines
                if line
                != "Herewith is completed the account of the division of the days."
            )
        )

        chapter_match = CHAPTER_LINE_RE.match(text)
        if chapter_match:
            line_chapter_number = roman_to_int(chapter_match.group("chapter"))
            if line_chapter_number != chapter_number:
                raise RuntimeError(
                    f"Unexpected Jubilees chapter marker on page {page_number}: expected {chapter_number}, got {line_chapter_number}"
                )
            text = f"1. {chapter_match.group('text')}"

        verse_matches = list(INLINE_VERSE_RE.finditer(text))
        if not verse_matches:
            raise RuntimeError(
                f"No verse markers parsed for Jubilees page {page_number}"
            )

        verses: list[VerseBlock] = []
        for index, match in enumerate(verse_matches):
            verse_number = int(match.group("verse"))
            start = match.end()
            end = (
                verse_matches[index + 1].start()
                if index + 1 < len(verse_matches)
                else len(text)
            )
            verse_text = normalize_whitespace(text[start:end])
            verses.append(VerseBlock(verse_numbers=[verse_number], text=verse_text))

        if not verses:
            raise RuntimeError(f"No verses parsed for Jubilees page {page_number}")

        return verses

    def parse_section_page(self, page_number: int, raw_text: str) -> Section:
        headings, content_lines = self.extract_page_components(raw_text)
        if not headings:
            raise RuntimeError(
                f"Missing section heading for Jubilees page {page_number}"
            )

        title = headings[0]
        chapter_number = self.extract_chapter_number(title, content_lines)
        verses = self.parse_verses(page_number, chapter_number, content_lines)
        return Section(
            page_number=page_number,
            title=title,
            chapter_number=chapter_number,
            verses=verses,
        )

    @staticmethod
    def generate_osis(
        front_matter: list[FrontMatterSection],
        chapters: list[Chapter],
    ) -> pyosis.OsisXML:
        current_date = datetime.now().strftime("%Y.%m.%dT%H:%M:%S")

        book_div = pyosis.DivCt(
            type_value=pyosis.OsisDivs.BOOK,
            osis_id=[OSIS_WORK_ID],
            canonical=True,
            content=[
                pyosis.TitleCt(
                    type_value=pyosis.OsisTitles.MAIN,
                    short=BOOK_SHORT_TITLE,
                    content=[BOOK_TITLE],
                )
            ],
        )

        for section in front_matter:
            div_type = (
                pyosis.OsisDivs.TITLE_PAGE
                if section.page_number == 0
                else pyosis.OsisDivs.FRONT
            )
            book_div.content.append(
                pyosis.DivCt(
                    type_value=div_type,
                    canonical=False,
                    content=[
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.MAIN,
                            canonical=False,
                            content=[section.title],
                        ),
                        *[
                            pyosis.PCt(content=[paragraph])
                            for paragraph in section.paragraphs
                        ],
                    ],
                )
            )

        for chapter in chapters:
            chapter_div = pyosis.DivCt(
                type_value=pyosis.OsisDivs.CHAPTER,
                osis_id=[f"{OSIS_WORK_ID}.{chapter.number}"],
                canonical=True,
                content=[],
            )

            for section_index, section in enumerate(chapter.sections, start=1):
                section_div = pyosis.DivCt(
                    type_value=pyosis.OsisDivs.SECTION,
                    osis_id=[f"{OSIS_WORK_ID}.{chapter.number}.s{section_index}"],
                    canonical=False,
                    content=[
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.SUB,
                            canonical=False,
                            content=[section.title],
                        )
                    ],
                )

                for verse in section.verses:
                    verse_ids = [
                        f"{OSIS_WORK_ID}.{chapter.number}.{verse_number}"
                        for verse_number in verse.verse_numbers
                    ]
                    section_div.content.append(
                        pyosis.VerseCt(
                            osis_id=verse_ids,
                            canonical=True,
                            content=[verse.text],
                        )
                    )

                chapter_div.content.append(section_div)

            book_div.content.append(chapter_div)

        header = pyosis.HeaderCt(
            canonical=False,
            revision_desc=[
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EVERSION,
                        type_value="ISO",
                        lang="en",
                        content=[current_date],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "Scraped from https://www.sacred-texts.com/bib/jub/ and converted to OSIS by Andrew P. Sansom."
                            ]
                        )
                    ],
                ),
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EDITION,
                        type_value="ISO",
                        lang="en",
                        content=["1917"],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "The Book of Jubilees, translated by Robert Henry Charles with an introduction by G. H. Box, Society for Promoting Christian Knowledge, 1917."
                            ]
                        )
                    ],
                ),
            ],
            work=[
                pyosis.WorkCt(
                    osis_work=OSIS_WORK_ID,
                    lang="en",
                    title=[pyosis.TitleCt(canonical=True, content=[BOOK_TITLE])],
                    description=[
                        pyosis.DescriptionCt(
                            value='The Book of Jubilees from "Translations of Early Documents: Palestinian Jewish Texts" by Robert Henry Charles, 1917. Transcribed at sacred-texts.com and converted to OSIS in this repository.'
                        )
                    ],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                    creator=[
                        pyosis.CreatorCt(
                            role=pyosis.OsisRoles.TRL,
                            value="Robert Henry (R.H.) Charles",
                        )
                    ],
                    publisher=[
                        pyosis.PublisherCt(
                            value="Society for Promoting Christian Knowledge"
                        )
                    ],
                )
            ],
        )

        osis_text = pyosis.OsisTextCt(
            lang="en",
            osis_idwork=OSIS_WORK_ID,
            osis_ref_work=BOOK_SHORT_TITLE,
            canonical=True,
            header=header,
            div=[book_div],
        )

        return pyosis.OsisXML(pyosis.Osis(osis_text=osis_text))

    def process(self) -> pyosis.OsisXML:
        front_matter = [
            self.parse_front_matter_page(page_number, self.fetch_page(page_number))
            for page_number in tqdm(
                range(PAGE_RANGE[0], FRONT_MATTER_END_PAGE + 1),
                desc="Front matter",
                unit="page",
            )
        ]

        chapters_by_number: dict[int, Chapter] = {}
        for page_number in tqdm(
            range(CONTENT_START_PAGE, PAGE_RANGE[1] + 1),
            desc="Chapters",
            unit="page",
        ):
            section = self.parse_section_page(page_number, self.fetch_page(page_number))
            chapter = chapters_by_number.setdefault(
                section.chapter_number,
                Chapter(number=section.chapter_number, sections=[]),
            )
            chapter.sections.append(section)

        expected_chapters = list(range(1, 51))
        actual_chapters = sorted(chapters_by_number)
        if actual_chapters != expected_chapters:
            raise RuntimeError(
                f"Unexpected Jubilees chapter sequence: expected {expected_chapters}, got {actual_chapters}"
            )

        chapters = [chapters_by_number[number] for number in expected_chapters]
        return self.generate_osis(front_matter, chapters)


def main(
    output: str = DEFAULT_OUTPUT,
    delay: float = 1.5,
    cache_dir: str = ".cache/html",
    log_level: str = "INFO",
) -> None:
    """Download and convert Jubilees to OSIS XML."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = JubileesParser(
        cache_dir=cache_dir if cache_dir else None,
        delay=delay,
    )
    try:
        osis_doc = parser.process()
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(osis_doc.to_xml(), encoding="utf-8")
    finally:
        parser.close()


if __name__ == "__main__":
    fire.Fire(main)
