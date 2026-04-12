"""Unit tests for the verse-splitting helpers in scrape_sacred_texts.

These tests exercise split_multi_verse_content(), split_multi_verse_poetry_lines(),
and the parse_page() handling of unnumbered poetry paragraphs directly and do NOT
require a network connection or HTML cache.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

_mod = importlib.import_module("1_enoch_osis.scrape_sacred_texts")
SacredTextsParser = _mod.SacredTextsParser


@pytest.fixture(scope="module")
def parser() -> SacredTextsParser:
    return SacredTextsParser(cache_dir=None, delay=0)


# ---------------------------------------------------------------------------
# split_multi_verse_content
# ---------------------------------------------------------------------------


class TestSplitMultiVerseContent:
    def test_single_verse_unchanged(self, parser: SacredTextsParser) -> None:
        parts = ["Just a single verse with no inline numbers."]
        result = parser.split_multi_verse_content(parts, 5)
        assert len(result) == 1
        verse_num, content = result[0]
        assert verse_num == 5
        assert content == parts

    def test_two_verses_plain_text(self, parser: SacredTextsParser) -> None:
        parts = ["First verse text. 2. Second verse text."]
        result = parser.split_multi_verse_content(parts, 1)
        assert len(result) == 2
        assert result[0][0] == 1
        assert result[1][0] == 2
        assert "First verse text." in result[0][1][0]
        assert "Second verse text." in result[1][1][0]

    def test_three_verses_plain_text(self, parser: SacredTextsParser) -> None:
        text = (
            "The words of the blessing of Enoch... "
            "2. And he took up his parable... "
            "3. Concerning the elect I said."
        )
        result = parser.split_multi_verse_content([text], 1)
        assert len(result) == 3
        assert [r[0] for r in result] == [1, 2, 3]
        assert "The words of the blessing" in result[0][1][0]
        assert "And he took up his parable" in result[1][1][0]
        assert "Concerning the elect" in result[2][1][0]

    def test_splits_preserve_inline_objects(self, parser: SacredTextsParser) -> None:
        """Non-string InlinePart objects should pass through unchanged."""
        import pyosis

        hi = pyosis.HiCt(type_value=pyosis.OsisHi.BOLD, content=["bold"])
        parts: list = ["Before bold ", hi, " after bold. 2. Next verse."]
        result = parser.split_multi_verse_content(parts, 1)
        assert len(result) == 2
        v1_parts = result[0][1]
        # hi element should be in verse 1
        assert any(isinstance(p, pyosis.HiCt) for p in v1_parts)
        # Verse 2 should be plain text
        assert result[1][1] == ["Next verse."]

    def test_no_false_positive_on_decimal_preceding_digit(
        self, parser: SacredTextsParser
    ) -> None:
        """'32. ' should NOT trigger a split when looking for verse 2."""
        parts = ["See figure 32. This is not a new verse."]
        result = parser.split_multi_verse_content(parts, 1)
        # '32' is preceded by a digit so (?<!\d) prevents a match; no split.
        assert len(result) == 1

    def test_split_at_tail_after_inline_element(
        self, parser: SacredTextsParser
    ) -> None:
        """Verse boundary that falls in a child element's tail is handled."""
        import pyosis

        # Simulates: "Verse 1 text <bold>word</bold> more text. 2. Verse 2 text."
        hi = pyosis.HiCt(type_value=pyosis.OsisHi.BOLD, content=["word"])
        parts: list = ["Verse 1 text ", hi, " more text. 2. Verse 2 text."]
        result = parser.split_multi_verse_content(parts, 1)
        assert len(result) == 2
        v1_parts = result[0][1]
        # hi should appear in verse 1
        assert any(isinstance(p, pyosis.HiCt) for p in v1_parts)
        # hi's tail in v1 should be cut before " 2. "
        hi_in_v1 = next(p for p in v1_parts if isinstance(p, pyosis.HiCt))
        # The string after hi in verse 1 should not contain "Verse 2"
        v1_text = " ".join(p for p in v1_parts if isinstance(p, str))
        assert "Verse 2" not in v1_text

    def test_multiple_boundaries_in_single_child_tail(
        self, parser: SacredTextsParser
    ) -> None:
        """Multiple verse numbers in a single child's tail are all split."""
        import pyosis

        # <hi>X</hi> followed by tail with three verse numbers
        hi = pyosis.HiCt(type_value=pyosis.OsisHi.BOLD, content=["X"])
        tail = " tail. 2. Second. 3. Third. 4. Fourth."
        # Build parts list with the tail embedded as a string (simulating tail)
        parts: list = ["Lead ", hi, tail]
        result = parser.split_multi_verse_content(parts, 1)
        assert len(result) == 4
        assert [r[0] for r in result] == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# split_multi_verse_poetry_lines
# ---------------------------------------------------------------------------


class TestSplitMultiVersePoetryLines:
    def test_single_verse_unchanged(self, parser: SacredTextsParser) -> None:
        lines = [["Line one"], ["Line two"]]
        result = parser.split_multi_verse_poetry_lines(lines, 3)
        assert len(result) == 1
        assert result[0][0] == 3
        assert result[0][1] == lines

    def test_split_on_next_verse_prefix(self, parser: SacredTextsParser) -> None:
        lines = [
            ["When the secrets of the righteous shall be revealed"],
            ["And the godless driven from the presence"],
            [" 4. From that time those that possess the earth"],
        ]
        result = parser.split_multi_verse_poetry_lines(lines, 3)
        assert len(result) == 2
        assert result[0][0] == 3
        assert len(result[0][1]) == 2  # two lines in verse 3
        assert result[1][0] == 4
        assert len(result[1][1]) == 1  # one line in verse 4
        # Verse-number prefix stripped from first line of verse 4
        assert not result[1][1][0][0].startswith("4.")
        assert "From that time" in result[1][1][0][0]

    def test_leading_whitespace_in_verse_prefix(
        self, parser: SacredTextsParser
    ) -> None:
        lines = [["Line A"], ["   5. Line B"]]
        result = parser.split_multi_verse_poetry_lines(lines, 4)
        assert len(result) == 2
        assert result[1][1][0][0].strip() == "Line B"


# ---------------------------------------------------------------------------
# parse_page: unnumbered poetry paragraphs
# ---------------------------------------------------------------------------


class TestParsePageUnnumberedPoetry:
    """Tests for parse_page() handling of poetry paragraphs without a verse number.

    Sacred-texts.com sometimes omits the verse number prefix from a poetry
    stanza that begins the next verse (e.g. 1 Enoch 1:4).  The parser should
    assign such a paragraph to ``current_verse + 1``.
    """

    def _make_parser_with_chapter(self) -> SacredTextsParser:
        p = SacredTextsParser(cache_dir=None, delay=0)
        p.start_book()
        return p

    def test_unnumbered_poetry_assigned_to_next_verse(self) -> None:
        """An unnumbered <br>-separated paragraph after verse 3 becomes verse 4."""
        parser = self._make_parser_with_chapter()
        html = (
            "<html><body>"
            "<h3>CHAPTER I.</h3>"
            "<p>3. Concerning the elect I said, and took up my parable concerning them:</p>"
            "<p>The Holy and Great One will come forth from His dwelling,<br/>"
            "And the eternal God will tread upon the earth, (even) on Mount Sinai,<br/>"
            "And appear in the strength of His might from the heaven of heavens.</p>"
            "<p>5. And all shall be smitten with fear<br/>"
            "And the Watchers shall quake.</p>"
            "</body></html>"
        )
        parser.parse_page(html, page_num=5)

        div = parser.current_div
        assert div is not None

        import pyosis

        verse_ids = []
        for item in div.content:
            if hasattr(item, "osis_id") and item.osis_id:
                verse_ids.append(item.osis_id[0])

        # Verse 4 must now be present between verse 3 and verse 5
        assert "1En.1.4" in verse_ids, f"1En.1.4 missing from {verse_ids}"
        assert verse_ids.index("1En.1.3") < verse_ids.index("1En.1.4")
        assert verse_ids.index("1En.1.4") < verse_ids.index("1En.1.5")

        # Verse 4 must be poetry (lgCt wrapper)
        verse4 = next(
            item
            for item in div.content
            if hasattr(item, "osis_id") and item.osis_id and item.osis_id[0] == "1En.1.4"
        )
        has_lg = any(isinstance(c, pyosis.LgCt) for c in verse4.content)
        assert has_lg, "verse 4 should be wrapped in a linegroup (lgCt)"

    def test_unnumbered_prose_paragraph_is_ignored(self) -> None:
        """An unnumbered paragraph WITHOUT <br> tags is not treated as a verse."""
        parser = self._make_parser_with_chapter()
        html = (
            "<html><body>"
            "<h3>CHAPTER I.</h3>"
            "<p>3. First verse text.</p>"
            "<p>This is a prose continuation without br tags or a verse number.</p>"
            "<p>5. Poetry verse<br/>Line two.</p>"
            "</body></html>"
        )
        parser.parse_page(html, page_num=5)

        div = parser.current_div
        assert div is not None

        verse_ids = [
            item.osis_id[0]
            for item in div.content
            if hasattr(item, "osis_id") and item.osis_id
        ]
        # Only verse 3 and verse 5 should be present; no spurious verse 4
        assert "1En.1.3" in verse_ids
        assert "1En.1.5" in verse_ids
        assert "1En.1.4" not in verse_ids, "prose paragraph should not become verse 4"

    def test_unnumbered_poetry_before_first_verse_is_ignored(self) -> None:
        """A poetry paragraph before any verse has been added is ignored."""
        parser = self._make_parser_with_chapter()
        html = (
            "<html><body>"
            "<h3>CHAPTER I.</h3>"
            "<p>Some poetry before first verse<br/>Line two.</p>"
            "<p>1. First verse text.</p>"
            "</body></html>"
        )
        parser.parse_page(html, page_num=5)

        div = parser.current_div
        assert div is not None

        verse_ids = [
            item.osis_id[0]
            for item in div.content
            if hasattr(item, "osis_id") and item.osis_id
        ]
        # Only verse 1 should be present; no verse 0 created from pre-verse poetry
        assert "1En.1.1" in verse_ids
        assert len([v for v in verse_ids if v.startswith("1En.1.")]) == 1
