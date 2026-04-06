# 1-enoch-osis

Text of R. H. Charles's translation of 1 Enoch, in OSIS XML format.

## Overview

This repository contains OSIS XML documents for 1 Enoch and related works from The Forgotten Books of Eden.

## Files

- `documents/1-enoch.xml` - OSIS document scraped from sacred-texts.com using the `1_enoch_osis.scrape_sacred_texts` module, with formatting preserved but without inline annotations
- `documents/adam-and-eve.xml` - Combined OSIS document containing the First and Second Books of Adam and Eve as separate OSIS book divs
- `src/1_enoch_osis/scrape_fbe.py` - Forgotten Books of Eden scraper that combines the Adam and Eve books into one document, uses canonical OSIS IDs such as `2En`, normalizes simple intro pages to an `Introduction` title plus source-heading subtitle, and preserves more complex source title blocks where needed
- `src/1_enoch_osis/scrape_sacred_texts.py` - Python module to download and parse from sacred-texts.com
- `pdf.py` - Previous pyosis compiler example (for reference)
- `tests/test_scrape_fbe_snapshot.py` - Snapshot regression test that regenerates FBE XML from the local HTML cache and compares it against the committed OSIS XML files
- `tests/test_scrape_sacred_texts_snapshot.py` - Snapshot regression test that regenerates the 1 Enoch XML from the local HTML cache and compares it against the committed OSIS XML file

## Regression Testing

The repository includes snapshot tests for `1_enoch_osis.scrape_fbe` and `1_enoch_osis.scrape_sacred_texts`. They regenerate the OSIS XML documents and compare them against the committed XML files in `documents/`.

The test is intentionally narrow:

- It treats the committed OSIS XML files as the snapshots.
- It normalizes the generated scrape timestamp before comparison.
- It uses the local `.cache/fbe-html/` and `.cache/html/` directories as scraper input sources so the tests can run offline.

The cache layout now mirrors the source URLs under each cache directory. For example, a page from `https://sacred-texts.com/bib/boe/boe012.htm` is cached at `.cache/html/sacred-texts.com/bib/boe/boe012.htm`.

Run it with:

```bash
pytest tests
```

If `.cache/fbe-html/` or `.cache/html/` is missing, the relevant test will skip. In that case, populate the cache by running the corresponding scraper once before relying on the snapshot tests. Generated XML documents now live under `documents/` by default.

## Scraping from sacred-texts.com

The `1_enoch_osis.scrape_sacred_texts` module downloads each chapter page from <https://sacred-texts.com/bib/boe/> and converts it to OSIS XML format using pyosis.

### Features

- Downloads and parses HTML pages from sacred-texts.com
- **HTML caching** - saves downloaded pages to avoid re-downloading on subsequent runs, using a cache path derived from the source URL
- Includes front matter (Title Page, Editors' Preface, Introduction, Abbreviations)
- **Formatting preservation** - preserves italics, bold, superscripts, subscripts from original HTML
- Preserves inline annotations marked with ⌈⌉ brackets (editorial additions/textual variants)
- **Inline footnotes** - converts footnotes from separate section to inline `<note>` elements
- **Page number milestones** - converts page markers (e.g. "p. xvii") to OSIS milestone elements
- Detects and converts poetry to OSIS line groups
- Handles rate limiting with exponential backoff retry logic
- Generates valid OSIS XML output with proper metadata

### Usage

```bash
# Basic usage (fastest when cached)
uv run python -m 1_enoch_osis.scrape_sacred_texts

# Custom options
uv run python -m 1_enoch_osis.scrape_sacred_texts \
  --start_page=0 \
  --end_page=112 \
  --output=documents/1-enoch-new.xml \
  --delay=1.5 \
  --cache_dir=.cache/html \
  --log_level=INFO

# Skip front matter and start at Chapter I
uv run python -m 1_enoch_osis.scrape_sacred_texts \
  --start_page=4
```

### Parameters

- `--output`: Output XML filename (default: `documents/1-enoch.xml`)
- `--start_page`: First page to process (default: 0 for Title Page, use 4 to skip front matter)
- `--end_page`: Last page to process (default: 112 for final appendix)
- `--delay`: Delay between requests in seconds (default: 1.5)
- `--cache_dir`: Directory to cache downloaded HTML files (default: `.cache/html`, use empty string `""` to disable caching)
- `--log_level`: Logging level - DEBUG, INFO, WARNING, ERROR (default: INFO)

### Important Notes

**HTML Caching**: By default, the script caches downloaded HTML pages in `.cache/html/`, using a directory structure that mirrors the source URLs. On subsequent runs, it will use the cached pages instead of downloading them again. This speeds up re-runs significantly and reduces load on the server. To disable caching, use `--cache_dir=""`.

**Rate Limiting**: The sacred-texts.com website implements rate limiting. The script includes:

- Automatic retry logic with exponential backoff
- Configurable delay between requests

If you still encounter 429 errors:

- Increase the `--delay` parameter (try 3.0 or higher)
- Wait several hours before retrying if temporarily blocked

**Recommended Approach**:

```bash
# Use cached pages when available
uv run python -m 1_enoch_osis.scrape_sacred_texts
```

### How It Works

1. **Fetching**: Downloads HTML pages with proper User-Agent headers, URL-derived disk caching, retry logic, and configurable delay between requests
2. **Front Matter**: Processes pages 0-3 (Title Page, Editors' Preface, Introduction, Abbreviations) as separate front matter divisions
3. **Footnote Extraction**: Extracts footnotes from the "Footnotes" section and stores them for inline insertion
4. **Parsing**: Uses BeautifulSoup to extract chapter headings, verses, and content from pages 4-112
5. **Formatting Preservation**: Converts HTML formatting tags to OSIS equivalents:
   - `<i>`, `<em>` → `<hi type="italic">`
   - `<b>`, `<strong>` → `<hi type="bold">`
   - `<sup>` → `<hi type="super">`
   - `<sub>` → `<hi type="sub">`
6. **Inline Footnotes**: Inserts footnotes as inline `<note>` elements at the point of reference in the text
7. **Annotations**: Preserves inline annotations (⌈⌉ brackets) that mark editorial additions
8. **Page Markers**: Converts page numbers (e.g. "p. xvii") to OSIS milestone elements: `<milestone type="page" n="xvii"/>`
9. **Poetry Detection**: Identifies poetry sections and converts them to OSIS line groups
10. **OSIS Generation**: Uses pyosis library to create valid OSIS XML structure with proper metadata

## OSIS Structure

The generated OSIS XML includes:

- **Header with proper metadata**:
  - Multiple revisionDesc entries (2026 scrape, 1913 original edition)
  - Work metadata (title, description, creator, publisher)
- **Front matter divisions**: Title Page, Editors' Preface, Introduction, Abbreviations
- **Normalized front matter titles** using OSIS `<title>` elements, with sacred-texts site boilerplate removed from the body text
- **Book structure** with proper osisID (`1En`)
- **Chapter divisions** (`1En.1`, `1En.2`, etc.) for chapters I-CVIII
- **Verse markers** with canonical IDs (`1En.1.1`, `1En.1.2`, etc.)
- **Inline formatting** preserved as `<hi>` elements (italic, bold, superscript, subscript)
- **Inline annotations** marked with ⌈⌉ brackets (literal characters, not tags)
- **Inline footnotes** as `<note>` elements with type="explanation" and label in `n` attribute
- **Page markers** as milestone elements (`<milestone type="page" n="xvii"/>`)
- **Poetry formatted** as line groups (`<lg>` and `<l>` elements)

## Source

The Book of Enoch text is sourced from:

- **URL**: <https://sacred-texts.com/bib/boe/>
- **Translation**: R.H. Charles (1917)
- **Original Publisher**: Oxford University Press

## License

The R.H. Charles translation is in the public domain. The OSIS conversion scripts in this repository are provided for educational and archival purposes.
