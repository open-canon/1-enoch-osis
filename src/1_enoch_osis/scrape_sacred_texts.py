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
"""Download and parse Book of Enoch from sacred-texts.com to OSIS XML."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import fire
import pyosis
from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

from .http_client import CachedHttpFetcher

LOGGER = logging.getLogger(__name__)

BASE_URL: Final[str] = "https://sacred-texts.com/bib/boe/"
# Files range from boe000.htm (title page) to boe112.htm (appendix)
FILE_RANGE: Final[tuple[int, int]] = (0, 112)
OSIS_BOOK_ID: Final[str] = "1En"
BOOK_TITLE: Final[str] = "The Book of Enoch"
BOOK_SHORT_TITLE: Final[str] = "1 Enoch"
FRONT_MATTER_TITLES: Final[dict[int, str]] = {
    0: "Title Page",
    1: "Editors' Preface",
    2: "Introduction",
    3: "Abbreviations, Brackets and Symbols",
}
FRONT_MATTER_BOILERPLATE: Final[set[str]] = {
    "The Book of Enoch, by R.H. Charles, [1917], at sacred-texts.com",
    "Scanned at sacred-texts.com, June 2004. Proofed and formatted by John Bruno Hare. This text is in the public domain in the United States because it was published prior to 1923.",
}


@dataclass
@dataclass
class VerseContent:
    """Represents parsed verse content with annotations and formatting preserved."""

    text: str  # Plain text version for reference
    content_parts: list[
        str | pyosis.HiCt | pyosis.MilestoneCt
    ]  # Parsed content with formatting
    has_poetry: bool = False
    poetry_lines: list[list[str | pyosis.HiCt | pyosis.MilestoneCt]] | None = (
        None  # Parsed lines with formatting
    )


@dataclass
class FootnoteInfo:
    """Information about a footnote."""

    ref_id: str  # e.g., "fn_0"
    label: str  # e.g., "viii:1"
    content: str  # The footnote text


@dataclass
class ChapterInfo:
    """Information about a chapter."""

    number: int
    title: str
    section_title: str | None = None
    verses: dict[int, VerseContent] | None = None


class SacredTextsParser:
    """Parse Book of Enoch from sacred-texts.com."""

    def __init__(
        self,
        cache_dir: str | None = None,
        delay: float = 1.0,
    ) -> None:
        self.current_chapter: int | None = None
        self.current_verse: int | None = None
        self.current_div: pyosis.DivCt | None = None
        self.root_div: pyosis.DivCt | None = None
        self.chapters: list[pyosis.DivCt] = []
        self.footnotes: dict[str, FootnoteInfo] = {}
        self.http = CachedHttpFetcher(cache_dir=cache_dir, delay=delay, logger=LOGGER)

        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            LOGGER.info(f"Using cache directory: {self.cache_dir}")

    def fetch_page(
        self, page_num: int, retry_count: int = 3, delay: float = 1.0
    ) -> str:
        """Fetch a single page from sacred-texts.com.

        Args:
            page_num: Page number to fetch
            retry_count: Number of retries for failed requests
            delay: Base delay between requests in seconds
        """
        if delay != self.http.delay:
            self.http.delay = delay

        url = f"{BASE_URL}boe{page_num:03d}.htm"
        return self.http.fetch_text(url=url, retry_count=retry_count)

    def close(self) -> None:
        self.http.close()

    def consolidate_strings(
        self, content: list[str | pyosis.HiCt | pyosis.MilestoneCt]
    ) -> list[str | pyosis.HiCt | pyosis.MilestoneCt]:
        """Consolidate consecutive strings in a content list.

        pyosis has a bug where PCt/LCt/VerseCt don't handle multiple consecutive
        strings correctly - they only keep the first and last, dropping middle ones.
        This function merges consecutive strings to avoid that bug.
        """
        if not content:
            return []

        result = []
        current_string = None

        for item in content:
            if isinstance(item, str):
                if current_string is None:
                    current_string = item
                else:
                    current_string += item
            else:
                # Hit a non-string (HiCt or MilestoneCt)
                if current_string is not None:
                    result.append(current_string)
                    current_string = None
                result.append(item)

        # Don't forget the last accumulated string
        if current_string is not None:
            result.append(current_string)

        return result

    def parse_inline_annotations(
        self, element: Tag | NavigableString, is_green_font: bool = False
    ) -> list[str | pyosis.HiCt | pyosis.MilestoneCt]:
        """Parse text, preserving inline formatting, brackets, and page markers.

        Converts HTML formatting tags to OSIS equivalents:
        - <i>, <em> → <hi type="italic">
        - <b>, <strong> → <hi type="bold">
        - <sup> → <hi type="super">
        - <sub> → <hi type="sub">

        Page markers like "p. xvii" in green font tags are converted to milestone elements.
        Inline page references (e.g., "pp. 35, 36") are preserved as text.
        Brackets (⌈⌉) are preserved as literal characters.

        Args:
            element: The HTML element or text node to parse
            is_green_font: True if we're inside a green font tag (for page markers)
        """
        if isinstance(element, NavigableString):
            text = str(element)
            # Only convert page markers if inside a green font tag
            if is_green_font:
                # Pattern: "p. 31" or "p. xvii" (roman numerals)
                parts = []
                last_end = 0
                for match in re.finditer(
                    r"\s*p\.\s+(\d+|[ivxlcdm]+)\s*", text, re.IGNORECASE
                ):
                    # Add text before the page marker
                    if match.start() > last_end:
                        parts.append(text[last_end : match.start()])
                    # Add milestone element for the page marker
                    page_n = match.group(1)
                    parts.append(pyosis.MilestoneCt(type_value="page", n=page_n))
                    last_end = match.end()

                # Add any remaining text after the last page marker
                if last_end < len(text):
                    parts.append(text[last_end:])

                # Filter out empty strings
                return [
                    p
                    for p in parts
                    if isinstance(p, pyosis.MilestoneCt)
                    or (isinstance(p, str) and p.strip())
                ]
            else:
                # Not in green font - preserve text as-is
                return [text] if text.strip() else []

        result: list[str | pyosis.HiCt | pyosis.MilestoneCt] = []

        # Track elements to skip (footnote number links)
        skip_elements = set()

        # Process all children of the element
        for child in element.children:
            if isinstance(child, NavigableString):
                # Recursively call to handle page marker conversion
                child_result = self.parse_inline_annotations(
                    child, is_green_font=is_green_font
                )
                result.extend(child_result)
            elif isinstance(child, Tag):
                # Skip if this element was marked for skipping
                if child in skip_elements:
                    continue

                # Skip navigation elements
                if child.get("class") and any(
                    cls in str(child.get("class"))
                    for cls in ["navigation", "next", "prev"]
                ):
                    continue

                # Check if this is a green font tag (for page markers)
                is_child_green_font = (
                    child.name == "font" and child.get("color", "").lower() == "green"
                )

                # Handle footnote references specially before recursing
                if child.name == "a" and child.get("name", "").startswith("fr_"):
                    # This is a footnote anchor - look for the corresponding link
                    ref_id = child.get("name").replace("fr_", "fn_")
                    # Look ahead to next sibling for the actual link
                    next_sib = child.find_next_sibling("a")
                    if next_sib and next_sib.get("href", "") == f"#{ref_id}":
                        # Found a footnote reference
                        if ref_id in self.footnotes:
                            footnote = self.footnotes[ref_id]
                            # Create note element
                            note = pyosis.NoteCt(
                                type_value="explanation",
                                n=footnote.label,
                                content=[footnote.content],
                            )
                            result.append(note)
                        # Mark the footnote number link to skip
                        skip_elements.add(next_sib)
                        continue

                # Recursively parse the child's content
                child_content = self.parse_inline_annotations(
                    child, is_green_font=is_child_green_font
                )

                # Map HTML tags to OSIS formatting
                if child.name in ["i", "em"]:
                    if child_content:
                        result.append(
                            pyosis.HiCt(
                                type_value=pyosis.OsisHi.ITALIC, content=child_content
                            )
                        )
                elif child.name in ["b", "strong"]:
                    if child_content:
                        result.append(
                            pyosis.HiCt(
                                type_value=pyosis.OsisHi.BOLD, content=child_content
                            )
                        )
                elif child.name == "sup":
                    if child_content:
                        result.append(
                            pyosis.HiCt(
                                type_value=pyosis.OsisHi.SUPER, content=child_content
                            )
                        )
                elif child.name == "sub":
                    if child_content:
                        result.append(
                            pyosis.HiCt(
                                type_value=pyosis.OsisHi.SUB, content=child_content
                            )
                        )
                elif child.name == "br":
                    # Skip br tags - handled at poetry level
                    continue
                elif child.name == "a":
                    # Regular link - passthrough
                    result.extend(child_content)
                elif child.name in ["font", "span", "div"]:
                    # For styling/formatting tags without semantic meaning, just include their content
                    # Note: Green font tags are handled specially above for page markers
                    result.extend(child_content)
                else:
                    # For other tags, just include their content
                    result.extend(child_content)

        return self.consolidate_strings(result)

    def parse_verse_text(self, verse_element: Tag) -> VerseContent:
        """Parse verse text, handling poetry and inline annotations."""
        text_parts = self.parse_inline_annotations(verse_element)

        # Extract plain text for comparison (flatten HiCt content)
        full_text = ""
        for part in text_parts:
            if isinstance(part, str):
                full_text += part
            elif hasattr(part, "content"):
                # Recursively extract text from HiCt content
                for item in part.content:
                    if isinstance(item, str):
                        full_text += item
                    elif hasattr(item, "content"):
                        full_text += "".join(
                            str(c) for c in item.content if isinstance(c, str)
                        )

        # Check if verse contains poetry (multiple line breaks)
        has_poetry = bool(verse_element.find_all(["br"]))

        poetry_lines = None
        if has_poetry:
            # Get the HTML content and split by <br> tags
            # This preserves inline formatting within each line
            verse_html = str(verse_element)
            # Split by various forms of br tags
            line_htmls = re.split(r"<br\s*/?>", verse_html, flags=re.IGNORECASE)

            lines = []
            for line_html in line_htmls:
                # Parse each line as HTML, preserving formatting
                line_soup = BeautifulSoup(line_html, "html.parser")

                # Parse the line to extract formatted content
                line_parts = self.parse_inline_annotations(line_soup)

                # Check if line is not empty
                line_text = ""
                for part in line_parts:
                    if isinstance(part, str):
                        line_text += part
                    elif hasattr(part, "content"):
                        for item in part.content:
                            if isinstance(item, str):
                                line_text += item

                line_text = line_text.strip()

                # Skip empty lines and navigation elements
                if line_text and not any(
                    nav in line_text
                    for nav in ["Next:", "Previous:", "Sacred Texts", "Index"]
                ):
                    lines.append(line_parts)

            poetry_lines = lines if lines else None

        return VerseContent(
            text=full_text.strip(),
            content_parts=text_parts,
            has_poetry=has_poetry,
            poetry_lines=poetry_lines if poetry_lines else None,
        )

    def extract_chapter_number(self, text: str) -> int | None:
        """Extract chapter number from chapter heading."""
        # Handle "CHAPTER I", "CHAPTER II", etc.
        match = re.search(r"CHAPTER\s+([IVXLC]+)", text, re.IGNORECASE)
        if match:
            roman = match.group(1)
            return self.roman_to_int(roman)
        return None

    @staticmethod
    def roman_to_int(s: str) -> int:
        """Convert Roman numeral to integer."""
        roman_values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        total = 0
        prev_value = 0
        for char in reversed(s.upper()):
            value = roman_values.get(char, 0)
            if value < prev_value:
                total -= value
            else:
                total += value
            prev_value = value
        return total

    def start_book(self) -> None:
        """Initialize the OSIS book structure."""
        self.root_div = pyosis.DivCt(
            type_value=pyosis.OsisDivs.BOOK,
            osis_id=[OSIS_BOOK_ID],
            canonical=True,
            content=[
                pyosis.TitleCt(
                    type_value=pyosis.OsisTitles.MAIN,
                    short=BOOK_SHORT_TITLE,
                    content=[BOOK_TITLE],
                )
            ],
        )

    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """Collapse internal whitespace so scraped headings compare consistently."""
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def is_navigation_text(text: str) -> bool:
        """Return True if text is site navigation or other sacred-texts chrome."""
        nav_phrases = [
            "Next:",
            "Previous:",
            "Sacred Texts",
            "Buy this Book",
            "Index",
            "«",
            "»",
            "sacred-texts.com",
        ]
        return any(phrase in text for phrase in nav_phrases)

    def should_skip_front_matter_paragraph(self, p_tag: Tag) -> bool:
        """Return True if a front-matter paragraph is site chrome or metadata."""
        if p_tag.find_parent(["nav", "header", "footer"]):
            return True

        if p_tag.find("a", attrs={"name": lambda x: x and x.startswith("fn_")}):
            return True

        text = self.normalize_whitespace(p_tag.get_text(" ", strip=True))
        if not text:
            return True

        if text in FRONT_MATTER_BOILERPLATE:
            return True

        return self.is_navigation_text(text)

    def extract_front_matter_lead_lines(
        self, soup: BeautifulSoup, title: str
    ) -> list[str]:
        """Extract heading lines that belong to the front-matter page itself.

        This preserves the title-page block on boe000 and leading subheadings like
        the introduction's opening section, while avoiding duplicated section titles.
        """
        root = soup.body if soup.body else soup
        lead_lines = []
        seen = {title.casefold()}

        for element in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"]):
            if element.name == "p":
                if self.should_skip_front_matter_paragraph(element):
                    continue
                break

            line = self.normalize_whitespace(element.get_text(" ", strip=True))
            if not line or line in FRONT_MATTER_BOILERPLATE:
                continue
            if self.is_navigation_text(line):
                continue
            if line.casefold() in seen:
                continue

            seen.add(line.casefold())
            lead_lines.append(line)

        return lead_lines

    def add_front_matter(
        self,
        title: str,
        content_paragraphs: list[Tag],
        lead_lines: list[str] | None = None,
    ) -> None:
        """Add front matter sections like preface, introduction, etc."""
        if not self.root_div:
            self.start_book()

        front_content: list[pyosis.TitleCt | pyosis.PCt | pyosis.MilestoneCt] = [
            pyosis.TitleCt(
                type_value=pyosis.OsisTitles.MAIN,
                canonical=False,
                content=[title],
            )
        ]

        for line in lead_lines or []:
            front_content.append(pyosis.PCt(content=[line]))

        for p_tag in content_paragraphs:
            parsed_content = self.parse_inline_annotations(p_tag)
            if parsed_content:
                # If paragraph contains only a milestone, add it directly (not wrapped in PCt)
                if len(parsed_content) == 1 and isinstance(
                    parsed_content[0], pyosis.MilestoneCt
                ):
                    front_content.append(parsed_content[0])
                else:
                    # Regular paragraph with text/formatting
                    front_content.append(pyosis.PCt(content=parsed_content))

        front_matter_div = pyosis.DivCt(
            type_value=pyosis.OsisDivs.FRONT,
            canonical=False,
            content=front_content,
        )
        self.root_div.content.append(front_matter_div)

    def start_chapter(self, chapter_num: int, title: str = "") -> None:
        """Start a new chapter."""
        if self.current_div and self.current_chapter:
            # Close previous chapter
            pass

        self.current_chapter = chapter_num
        chapter_osis_id = f"{OSIS_BOOK_ID}.{chapter_num}"

        chapter_content = []
        if title:
            chapter_content.append(
                pyosis.TitleCt(type_value=pyosis.OsisTitles.MAIN, content=[title])
            )

        self.current_div = pyosis.DivCt(
            type_value=pyosis.OsisDivs.CHAPTER,
            osis_id=[chapter_osis_id],
            canonical=True,
            content=chapter_content,
        )

        if self.root_div:
            self.root_div.content.append(self.current_div)

    def add_verse(self, verse_num: int, content: VerseContent) -> None:
        """Add a verse to the current chapter."""
        if not self.current_chapter or not self.current_div:
            LOGGER.warning(f"No chapter started for verse {verse_num}")
            return

        verse_osis_id = f"{OSIS_BOOK_ID}.{self.current_chapter}.{verse_num}"

        if content.has_poetry and content.poetry_lines:
            # Create line group for poetry
            lines = []
            for line_parts in content.poetry_lines:
                # Poetry lines contain parsed content with formatting
                lines.append(pyosis.LCt(content=line_parts))

            lg = pyosis.LgCt(l=lines)

            verse = pyosis.VerseCt(
                osis_id=[verse_osis_id], canonical=True, content=[lg]
            )
        else:
            # Regular verse - use parsed content with formatting
            verse = pyosis.VerseCt(
                osis_id=[verse_osis_id],
                canonical=True,
                content=content.content_parts
                if content.content_parts
                else [content.text],
            )

        self.current_div.content.append(verse)
        self.current_verse = verse_num

    def extract_footnotes(self, soup: BeautifulSoup) -> None:
        """Extract footnotes from the page and store them for inline insertion.

        Footnotes are typically in a section with <H3>Footnotes</H3> heading.
        Each footnote has the format:
        <A NAME="fn_X"></A><A HREF="...#fr_X">label</A> content
        """
        # Look for "Footnotes" heading
        for h3 in soup.find_all("h3"):
            if "Footnotes" in h3.get_text():
                # Found footnotes section - extract all paragraphs after it
                current = h3.find_next_sibling()
                while current:
                    if current.name == "p":
                        # Parse footnote: <A NAME="fn_X"></A><A HREF="...">label</A> text
                        anchor = current.find(
                            "a", attrs={"name": lambda x: x and x.startswith("fn_")}
                        )
                        if anchor:
                            ref_id = anchor.get("name")  # e.g., "fn_0"

                            # Find the label link
                            label_link = anchor.find_next_sibling("a")
                            label = label_link.get_text().strip() if label_link else ""

                            # Get the footnote content (everything after the label link)
                            # Remove the anchors and get text
                            content_parts = []
                            for elem in current.children:
                                if isinstance(elem, NavigableString):
                                    text = str(elem).strip()
                                    if text:
                                        content_parts.append(text)
                                elif elem.name not in ["a"]:  # Skip anchor tags
                                    text = elem.get_text().strip()
                                    if text:
                                        content_parts.append(text)

                            # Join and clean up the content
                            content = " ".join(content_parts).strip()

                            # Store the footnote
                            if content:
                                self.footnotes[ref_id] = FootnoteInfo(
                                    ref_id=ref_id, label=label, content=content
                                )
                                LOGGER.debug(
                                    f"Extracted footnote {ref_id}: {label} = {content[:50]}..."
                                )

                    current = current.find_next_sibling()
                    # Stop if we hit another heading
                    if current and current.name in ["h1", "h2", "h3", "h4"]:
                        break

    def parse_page(self, html: str, page_num: int = -1) -> None:
        """Parse a single page and extract chapter/verse content or front matter.

        Args:
            html: HTML content to parse
            page_num: Page number (used to identify front matter pages 0-3)
        """
        soup = BeautifulSoup(html, "html.parser")

        # Extract footnotes first (they'll be inserted inline)
        self.extract_footnotes(soup)

        # Handle front matter pages (0-3)
        if page_num in [0, 1, 2, 3]:
            title = FRONT_MATTER_TITLES[page_num]
            lead_lines = self.extract_front_matter_lead_lines(soup, title)

            # Extract all paragraphs that are actual content
            content_paragraphs = []
            for p in soup.find_all("p"):
                if self.should_skip_front_matter_paragraph(p):
                    continue
                content_paragraphs.append(p)  # Pass the Tag object, not plain text

            if lead_lines or content_paragraphs:
                self.add_front_matter(title, content_paragraphs, lead_lines)
                LOGGER.debug(f"Added front matter: {title}")
            return

        # First look for chapter headings in h3 tags
        for h3 in soup.find_all("h3"):
            text = h3.get_text().strip()
            if "CHAPTER" in text.upper():
                chapter_num = self.extract_chapter_number(text)
                if chapter_num:
                    clean_title = re.sub(r"\s+", " ", text).strip()
                    self.start_chapter(chapter_num, clean_title)
                    LOGGER.debug(f"Started chapter {chapter_num}: {clean_title}")

        # Now process paragraphs for verses
        paragraphs = soup.find_all("p")

        for p in paragraphs:
            # Skip if paragraph is within navigation/header elements
            if p.find_parent(["nav", "header", "footer"]):
                continue

            text = p.get_text().strip()

            # Skip empty paragraphs, navigation links, and page numbers
            if not text:
                continue
            if text.startswith("p.") and len(text) < 10:
                continue
            if text.startswith("[") or "Next:" in text or "Previous:" in text:
                continue
            if "Sacred Texts" in text or "Index" in text or "«" in text or "»" in text:
                continue
            if text.startswith("⌈") and text.endswith("⌉") and len(text) < 20:
                continue  # Skip standalone bracketed notes

            # Check if text starts with a verse number
            verse_match = re.match(r"^(\d+)\.\s+", text)
            if verse_match and self.current_chapter:
                verse_num = int(verse_match.group(1))

                # Parse the verse content preserving inline annotations
                verse_content = self.parse_verse_text(p)

                # Remove verse number from the beginning of all content
                verse_content.text = re.sub(r"^\d+\.\s+", "", verse_content.text)

                # Remove verse number from content_parts
                if verse_content.content_parts and isinstance(
                    verse_content.content_parts[0], str
                ):
                    verse_content.content_parts[0] = re.sub(
                        r"^\d+\.\s+", "", verse_content.content_parts[0]
                    )

                # Remove verse number from poetry lines
                if verse_content.has_poetry and verse_content.poetry_lines:
                    first_line = verse_content.poetry_lines[0]
                    if first_line and isinstance(first_line[0], str):
                        first_line[0] = re.sub(r"^\d+\.\s+", "", first_line[0])

                self.add_verse(verse_num, verse_content)
                LOGGER.debug(f"Added verse {self.current_chapter}.{verse_num}")

    def generate_osis(self) -> pyosis.OsisXML:
        """Generate complete OSIS document."""
        # Get current date in ISO format
        from datetime import datetime

        current_date = datetime.now().strftime("%Y.%m.%dT%H:%M:%S")

        # Create header with multiple revision descriptions
        header = pyosis.HeaderCt(
            canonical=False,
            revision_desc=[
                # Latest revision - scraping from sacred-texts.com
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
                                "Scraped from https://sacred-texts.com/bib/boe/, and converted to OSIS by Andrew P. Sansom."
                            ]
                        )
                    ],
                ),
                # Original 1913 edition
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EDITION,
                        type_value="ISO",
                        lang="en",
                        content=["1913"],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "The Apocrypha and Pseudepigrapha of the Old Testament in English : with introductions and critical and explanatory notes to the several books, Robert Henry Charles."
                            ]
                        )
                    ],
                ),
            ],
            work=[
                pyosis.WorkCt(
                    osis_work=OSIS_BOOK_ID,
                    lang="en",
                    title=[
                        pyosis.TitleCt(canonical=True, content=[BOOK_TITLE]),
                    ],
                    description=[
                        pyosis.DescriptionCt(
                            value='Excerpt from "The Apocrypha and Pseudepigrapha of the Old Testament in English : with introductions and critical and explanatory notes to the several books" by Robert Henry Charles, 1913. Transcribed by Joshua Williams, Northwest Nazarene College, 1995. Converted to OSIS by Andrew P. Sansom, 2026.'
                        )
                    ],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                    creator=[
                        pyosis.CreatorCt(
                            role=pyosis.OsisRoles.TRL,
                            value="Robert Henry (R.H.) Charles",
                        )
                    ],
                    publisher=[pyosis.PublisherCt(value="The Clarendon Press")],
                ),
            ],
        )

        # Create the OSIS text with all divisions
        divs = []
        if self.root_div:
            divs.append(self.root_div)

        osis_text = pyosis.OsisTextCt(
            lang="en",
            osis_idwork=OSIS_BOOK_ID,
            osis_ref_work=BOOK_SHORT_TITLE,
            canonical=True,
            header=header,
            div=divs,
        )

        # Create the final OSIS XML
        osis_xml = pyosis.OsisXML(pyosis.Osis(osis_text=osis_text))

        return osis_xml

    def process_all_pages(
        self, start: int = 0, end: int = 112, delay: float = 1.0
    ) -> None:
        """Download and process all pages in range.

        Args:
            start: First page number to process
            end: Last page number to process
            delay: Delay between requests in seconds
        """
        self.start_book()

        for page_num in tqdm(range(start, end + 1), desc="Processing pages"):
            try:
                html = self.fetch_page(page_num, delay=delay)
                self.parse_page(html, page_num=page_num)
            except Exception as e:
                LOGGER.error(f"Error processing page {page_num}: {e}")
                continue


def main(
    output: str = "1-enoch.xml",
    start_page: int = 0,  # Start at 0 to include title page and front matter
    end_page: int = 112,
    delay: float = 1.5,  # Delay between requests in seconds
    cache_dir: str = ".cache/html",  # Directory to cache downloaded HTML files
    log_level: str = "INFO",
) -> None:
    """Download and convert Book of Enoch to OSIS XML.

    Args:
        output: Output XML filename
        start_page: First page to process (default 0 for title page, use 4 for Chapter I)
        end_page: Last page to process (default 112)
        delay: Delay between requests in seconds (default 1.5 to avoid rate limiting)
        cache_dir: Directory to cache downloaded HTML files (default ".cache/html", use empty string to disable)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = SacredTextsParser(cache_dir=cache_dir if cache_dir else None, delay=delay)

    try:
        LOGGER.info(f"Processing pages {start_page} to {end_page} with {delay}s delay")
        parser.process_all_pages(start_page, end_page, delay=delay)

        LOGGER.info("Generating OSIS XML")
        osis_doc = parser.generate_osis()

        LOGGER.info(f"Writing to {output}")
        with open(output, "w", encoding="utf-8") as f:
            f.write(osis_doc.to_xml())

        LOGGER.info("Done!")
    finally:
        parser.close()


if __name__ == "__main__":
    fire.Fire(main)
