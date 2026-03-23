# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "beautifulsoup4",
#     "fire",
#     "pyosis",
#     "requests",
#     "tqdm",
# ]
# ///
"""Download and parse Book of Enoch from sacred-texts.com to OSIS XML."""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import fire
import pyosis
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

LOGGER = logging.getLogger(__name__)

BASE_URL: Final[str] = "https://sacred-texts.com/bib/boe/"
BOOK_OSIS_ID: Final[str] = "1En"
# Files range from boe000.htm (title page) to boe112.htm (appendix)
FILE_RANGE: Final[tuple[int, int]] = (0, 112)
VERSE_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d{1,3})\.?\s+(?=(?:<[^>]+>\s*)*[A-Z\"'\(\[\u2308\u3008])",
    re.IGNORECASE,
)


def fetch_free_proxies(limit: int = 50) -> list[dict[str, str]]:
    """Fetch fresh free proxies from proxy list services.

    Args:
        limit: Maximum number of proxies to fetch (default: 50)

    Returns:
        List of proxy dictionaries in requests format
    """
    proxies = []

    try:
        response = requests.get(
            "https://advanced.name/freeproxy/69ae3e144bf53?type=https"
        )
        if not response.ok:
            LOGGER.warning(
                f"Failed to fetch proxies from advanced.name: {response.status_code}"
            )
            raise ValueError("Failed to fetch proxies from advanced.name")
        proxy_list = response.text.strip().splitlines()
        for proxy in proxy_list:
            if ":" not in proxy:
                continue
            ip, port = proxy.split(":")
            proxy_url = f"http://{ip}:{port}"
            proxies.append({"http": proxy_url, "https": proxy_url})
            if len(proxies) >= limit:
                break
        LOGGER.info(f"Successfully fetched {len(proxies)} proxies from advanced.name")
        return proxies

    except Exception as e:
        LOGGER.warning(f"Error fetching proxies from advanced.name: {e}")

    LOGGER.info("Trying proxy source (geonode.com)...")
    response = requests.get(
        "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc",
        timeout=10,
    )

    if response.status_code == 200:
        data = response.json()
        if "data" not in data:
            LOGGER.warning(
                "Unexpected response format from geonode: 'data' key not found"
            )
            return proxies
        for proxy_data in data["data"]:
            if "http" not in proxy_data.get("protocols", []):
                continue  # Skip proxies that don't support HTTP
            ip = proxy_data.get("ip")
            port = proxy_data.get("port")
            if ip and port:
                proxy_url = f"http://{ip}:{port}"
                proxies.append({"http": proxy_url, "https": proxy_url})

        LOGGER.info(f"Successfully fetched {len(proxies)} proxies from geonode")
        return proxies


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
        use_proxies: bool = True,
        fetch_dynamic_proxies: bool = True,
        cache_dir: str | None = None,
    ) -> None:
        self.current_chapter: int | None = None
        self.current_verse: int | None = None
        self.current_div: pyosis.DivCt | None = None
        self.root_div: pyosis.DivCt | None = None
        self.chapters: list[pyosis.DivCt] = []
        self.footnotes: dict[str, FootnoteInfo] = {}
        self.use_proxies = use_proxies

        # Setup cache directory
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            LOGGER.info(f"Using cache directory: {self.cache_dir}")

        # Initialize proxy pool
        self.proxy_pool = []
        if use_proxies:
            if fetch_dynamic_proxies:
                LOGGER.info("Fetching fresh proxies dynamically...")
                proxies = fetch_free_proxies(limit=500)
                for proxy in proxies:
                    LOGGER.debug(f"Added proxy to pool: {proxy['http']}")
                    try:
                        r = requests.get(
                            "https://httpbin.org/ip",
                            proxies=proxy,
                            timeout=5,
                        )
                        if r.ok:
                            LOGGER.debug(f"Proxy {proxy['http']} is working")
                            self.proxy_pool.append(proxy)
                        else:
                            LOGGER.debug(
                                f"Proxy {proxy['http']} failed with status code {r.status_code}"
                            )
                    except Exception as e:
                        LOGGER.debug(f"Proxy {proxy['http']} failed with error: {e}")
                LOGGER.info(
                    f"Proxy pool initialized with {len(self.proxy_pool)} working proxies from dynamic fetching"
                )

            LOGGER.info(f"Proxy pool initialized with {len(self.proxy_pool)} proxies")

    def fetch_page(
        self, page_num: int, retry_count: int = 3, delay: float = 1.0
    ) -> str:
        """Fetch a single page from sacred-texts.com with retry logic and proxy rotation.

        Checks cache first, then fetches from web if not cached.

        Args:
            page_num: Page number to fetch
            retry_count: Number of retries for failed requests
            delay: Base delay between requests in seconds
        """
        # Check cache first
        if self.cache_dir:
            cache_file = self.cache_dir / f"boe{page_num:03d}.html"
            if cache_file.exists():
                LOGGER.debug(f"Loading page {page_num} from cache")
                return cache_file.read_text(encoding="utf-8")

        url = f"{BASE_URL}boe{page_num:03d}.htm"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        for attempt in range(retry_count):
            # Select a random proxy from the pool if enabled
            proxy = None
            if self.use_proxies and self.proxy_pool:
                proxy = random.choice(self.proxy_pool)
                LOGGER.debug(f"Using proxy: {proxy['http']}")

            try:
                LOGGER.debug(
                    f"Fetching {url} (attempt {attempt + 1}/{retry_count}){'with proxy' if proxy else ''}"
                )
                response = requests.get(url, headers=headers, proxies=proxy, timeout=30)
                response.raise_for_status()
                html_content = response.text

                # Cache the HTML if caching is enabled
                if self.cache_dir:
                    cache_file = self.cache_dir / f"boe{page_num:03d}.html"
                    cache_file.write_text(html_content, encoding="utf-8")
                    LOGGER.debug(f"Cached page {page_num} to {cache_file}")

                # Add delay after successful request to avoid rate limiting
                time.sleep(delay)
                return html_content
            except requests.exceptions.ProxyError as e:
                LOGGER.warning(
                    f"Proxy error for {url}: {e}. Retrying with a different proxy..."
                )
                if attempt == retry_count - 1:
                    raise
                time.sleep(delay)
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as e:
                # Proxy failed, try without proxy on next attempt
                if proxy:
                    LOGGER.warning(
                        f"Proxy failed for {url}: {e}. Trying direct connection..."
                    )
                    # Try direct connection immediately
                    try:
                        response = requests.get(url, headers=headers, timeout=30)
                        response.raise_for_status()
                        html_content = response.text

                        # Cache the HTML if caching is enabled
                        if self.cache_dir:
                            cache_file = self.cache_dir / f"boe{page_num:03d}.html"
                            cache_file.write_text(html_content, encoding="utf-8")
                            LOGGER.debug(f"Cached page {page_num} to {cache_file}")

                        time.sleep(delay)
                        return html_content
                    except Exception as direct_error:
                        LOGGER.warning(f"Direct connection also failed: {direct_error}")
                if attempt == retry_count - 1:
                    raise
                time.sleep(delay)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:  # Too Many Requests
                    wait_time = delay * (2**attempt)  # Exponential backoff
                    LOGGER.warning(
                        f"Rate limited on {url}. Waiting {wait_time}s before retry..."
                    )
                    time.sleep(wait_time)
                    if attempt == retry_count - 1:
                        raise
                else:
                    raise
            except Exception as e:
                if attempt == retry_count - 1:
                    raise
                LOGGER.warning(f"Error fetching {url}: {e}. Retrying...")
                time.sleep(delay)

        raise Exception(f"Failed to fetch {url} after {retry_count} attempts")

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
            osis_id=[BOOK_OSIS_ID],
            canonical=True,
            content=[pyosis.HeadCt(content=["The Book of Enoch"])],
        )

    def add_front_matter(self, title: str, content_paragraphs: list[Tag]) -> None:
        """Add front matter sections like preface, introduction, etc."""
        if not self.root_div:
            self.start_book()

        # Parse each paragraph to preserve formatting
        p_elements = []
        for p_tag in content_paragraphs:
            parsed_content = self.parse_inline_annotations(p_tag)
            if parsed_content:
                # If paragraph contains only a milestone, add it directly (not wrapped in PCt)
                if len(parsed_content) == 1 and isinstance(
                    parsed_content[0], pyosis.MilestoneCt
                ):
                    p_elements.append(parsed_content[0])
                else:
                    # Regular paragraph with text/formatting
                    p_elements.append(pyosis.PCt(content=parsed_content))

        front_matter_div = pyosis.DivCt(
            type_value=pyosis.OsisDivs.FRONT,
            canonical=False,
            content=[pyosis.HeadCt(content=[title]), *p_elements],
        )
        self.root_div.content.append(front_matter_div)

    def start_chapter(self, chapter_num: int, title: str = "") -> None:
        """Start a new chapter."""
        if self.current_div and self.current_chapter:
            # Close previous chapter
            pass

        self.current_chapter = chapter_num
        self.current_verse = None
        chapter_osis_id = f"{BOOK_OSIS_ID}.{chapter_num}"

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

        verse_osis_id = f"{BOOK_OSIS_ID}.{self.current_chapter}.{verse_num}"

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

    def append_to_current_verse(self, content: VerseContent) -> None:
        """Append paragraph content to the current verse.

        sacred-texts sometimes continues a verse in a new paragraph or starts a
        short chapter without an explicit verse number.
        """
        if not self.current_div or not self.current_div.content:
            LOGGER.warning("No current verse available for paragraph continuation")
            return

        last_item = self.current_div.content[-1]
        if not isinstance(last_item, pyosis.VerseCt):
            LOGGER.warning(
                "Last chapter item is not a verse; cannot append continuation"
            )
            return

        if content.has_poetry and content.poetry_lines:
            continuation_items: list[
                str | pyosis.HiCt | pyosis.MilestoneCt | pyosis.LgCt
            ] = [
                pyosis.LgCt(
                    l=[
                        pyosis.LCt(content=line_parts)
                        for line_parts in content.poetry_lines
                    ]
                )
            ]
        else:
            continuation_items = (
                content.content_parts if content.content_parts else [content.text]
            )

        if not continuation_items:
            return

        existing_content = list(last_item.content or [])
        if (
            existing_content
            and isinstance(existing_content[-1], str)
            and isinstance(continuation_items[0], str)
        ):
            needs_space = not existing_content[-1].endswith(
                (" ", "\n")
            ) and not continuation_items[0].startswith(
                (" ", "\n", ",", ".", ";", ":", "!", "?")
            )
            existing_content[-1] += (" " if needs_space else "") + continuation_items[0]
            existing_content.extend(continuation_items[1:])
        else:
            existing_content.extend(continuation_items)

        last_item.content = self.consolidate_strings(existing_content)

    @staticmethod
    def build_paragraph_tag(fragment_html: str) -> Tag:
        """Wrap an HTML fragment in a paragraph for re-parsing."""
        fragment_soup = BeautifulSoup(f"<p>{fragment_html}</p>", "html.parser")
        paragraph = fragment_soup.find("p")
        if paragraph is None:
            raise ValueError("Failed to build paragraph tag from fragment")
        return paragraph

    @staticmethod
    def is_valid_verse_marker(fragment_html: str, start: int) -> bool:
        """Check whether a numeric marker sits at a plausible verse boundary."""
        previous_index = start - 1
        while previous_index >= 0 and fragment_html[previous_index].isspace():
            previous_index -= 1

        if previous_index < 0:
            return True

        return fragment_html[previous_index] in {
            ".",
            ",",
            ";",
            ":",
            "?",
            "!",
            "'",
            '"',
            ")",
            ">",
        }

    def extract_paragraph_verses(
        self, paragraph: Tag, *, infer_first_verse: bool
    ) -> list[tuple[int | None, VerseContent]]:
        """Split a paragraph into verse entries.

        Returns `(verse_number, content)` pairs. A `None` verse number means the
        parsed content should be appended to the current verse.
        """
        paragraph_soup = BeautifulSoup(str(paragraph), "html.parser")
        paragraph_copy = paragraph_soup.find("p")
        if paragraph_copy is None:
            return []

        for continuation_note in paragraph_copy.select(".contnote"):
            continuation_note.decompose()

        fragment_html = paragraph_copy.decode_contents().strip()
        if not fragment_html:
            return []

        matches = [
            match
            for match in VERSE_MARKER_RE.finditer(fragment_html)
            if self.is_valid_verse_marker(fragment_html, match.start())
        ]
        if not matches:
            content = self.parse_verse_text(paragraph_copy)
            if not content.text.strip() and not content.content_parts:
                return []
            if infer_first_verse:
                return [(1, content)]
            if self.current_verse is not None:
                return [(None, content)]
            return []

        verse_entries = []
        for index, match in enumerate(matches):
            verse_num = int(match.group(1))
            segment_start = match.end()
            segment_end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(fragment_html)
            )
            segment_html = fragment_html[segment_start:segment_end].strip()
            if not segment_html:
                continue

            verse_paragraph = self.build_paragraph_tag(segment_html)
            content = self.parse_verse_text(verse_paragraph)
            if not content.text.strip() and not content.content_parts:
                continue
            verse_entries.append((verse_num, content))

        return verse_entries

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
            # Extract main title from h1 or h2
            title_tag = soup.find("h1") or soup.find("h2")
            if title_tag:
                title = title_tag.get_text().strip()
            else:
                title = [
                    "Title Page",
                    "Editors' Preface",
                    "Introduction",
                    "Abbreviations, Brackets and Symbols",
                ][page_num]

            # Extract all paragraphs that are actual content
            content_paragraphs = []
            for p in soup.find_all("p"):
                if p.find_parent(["nav", "header", "footer"]):
                    continue

                # Skip footnote paragraphs (they have <a name="fn_X">)
                if p.find("a", attrs={"name": lambda x: x and x.startswith("fn_")}):
                    continue

                text = p.get_text().strip()
                # Skip navigation and empty paragraphs
                if (
                    not text
                    or "Next:" in text
                    or "Previous:" in text
                    or "Sacred Texts" in text
                    or "Index" in text
                    or "«" in text
                    or "»" in text
                ):
                    continue
                content_paragraphs.append(p)  # Pass the Tag object, not plain text

            if content_paragraphs:
                self.add_front_matter(title, content_paragraphs)
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
        content_paragraphs = [
            p
            for p in paragraphs
            if not p.find_parent(["nav", "header", "footer"])
            and "at sacred-texts.com" not in p.get_text()
        ]
        page_has_explicit_verses = any(
            self.is_valid_verse_marker(fragment_html, match.start())
            for p in content_paragraphs
            for fragment_html in [
                BeautifulSoup(str(p), "html.parser").find("p").decode_contents().strip()
            ]
            for match in VERSE_MARKER_RE.finditer(fragment_html)
        )

        for p in paragraphs:
            # Skip if paragraph is within navigation/header elements
            if p.find_parent(["nav", "header", "footer"]):
                continue

            text = p.get_text().strip()
            has_continuation_note = p.select_one(".contnote") is not None

            # Skip empty paragraphs, navigation links, and page numbers
            if not text:
                continue
            if text.startswith("p.") and len(text) < 10:
                continue
            if "at sacred-texts.com" in text:
                continue
            if (
                (text.startswith("[") and not has_continuation_note)
                or "Next:" in text
                or "Previous:" in text
            ):
                continue
            if "Sacred Texts" in text or "Index" in text or "«" in text or "»" in text:
                continue
            if text.startswith("⌈") and text.endswith("⌉") and len(text) < 20:
                continue  # Skip standalone bracketed notes

            if not self.current_chapter:
                continue

            verse_entries = self.extract_paragraph_verses(
                p,
                infer_first_verse=self.current_verse is None
                and not page_has_explicit_verses,
            )
            for verse_num, verse_content in verse_entries:
                if verse_num is None:
                    self.append_to_current_verse(verse_content)
                    LOGGER.debug(
                        f"Appended continuation to {self.current_chapter}.{self.current_verse}"
                    )
                    continue

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
                    osis_work=BOOK_OSIS_ID,
                    lang="en",
                    title=[
                        pyosis.TitleCt(canonical=True, content=["The Book of Enoch"]),
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
            osis_idwork=BOOK_OSIS_ID,
            osis_ref_work="1 Enoch",
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
    use_proxies: bool = False,  # Use proxy rotation to avoid rate limiting
    fetch_dynamic_proxies: bool = False,  # Fetch fresh proxies dynamically
    cache_dir: str = ".cache/html",  # Directory to cache downloaded HTML files
    log_level: str = "INFO",
) -> None:
    """Download and convert Book of Enoch to OSIS XML.

    Args:
        output: Output XML filename
        start_page: First page to process (default 0 for title page, use 4 for Chapter I)
        end_page: Last page to process (default 112)
        delay: Delay between requests in seconds (default 1.5 to avoid rate limiting)
        use_proxies: Use rotating proxy pool to avoid rate limiting (default False)
        fetch_dynamic_proxies: Fetch fresh proxies dynamically from proxy services (default False)
        cache_dir: Directory to cache downloaded HTML files (default ".cache/html", use empty string to disable)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = SacredTextsParser(
        use_proxies=use_proxies,
        fetch_dynamic_proxies=fetch_dynamic_proxies,
        cache_dir=cache_dir if cache_dir else None,
    )

    LOGGER.info(f"Processing pages {start_page} to {end_page} with {delay}s delay")
    parser.process_all_pages(start_page, end_page, delay=delay)

    LOGGER.info("Generating OSIS XML")
    osis_doc = parser.generate_osis()

    LOGGER.info(f"Writing to {output}")
    with open(output, "w", encoding="utf-8") as f:
        f.write(osis_doc.to_xml())

    LOGGER.info("Done!")


if __name__ == "__main__":
    fire.Fire(main)
