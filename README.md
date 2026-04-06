# 1-enoch-osis

Text of R. H. Charles's translation of 1 Enoch, in OSIS XML format.

## Overview

This repository contains OSIS XML documents for 1 Enoch and related works from The Forgotten Books of Eden.

## Files

- `1-enoch.xml` - OSIS document scraped from sacred-texts.com using the `scrape_sacred_texts.py` script, with formatting preserved but without inline annotations
- `adam-and-eve.xml` - Combined OSIS document containing the First and Second Books of Adam and Eve as separate OSIS book divs
- `scrape_fbe.py` - Forgotten Books of Eden scraper that combines the Adam and Eve books into one document, uses canonical OSIS IDs such as `2En`, normalizes simple intro pages to an `Introduction` title plus source-heading subtitle, and preserves more complex source title blocks where needed
- `scrape_sacred_texts.py` - Python script to download and parse from sacred-texts.com
- `pdf.py` - Previous pyosis compiler example (for reference)

## Scraping from sacred-texts.com

The `scrape_sacred_texts.py` script downloads each chapter page from https://sacred-texts.com/bib/boe/ and converts it to OSIS XML format using pyosis.

### Features

- Downloads and parses HTML pages from sacred-texts.com
- **HTML caching** - saves downloaded pages to avoid re-downloading on subsequent runs
- **Dynamic proxy fetching** - automatically fetches fresh free proxies from proxy list services
- **Rotating proxy pool** to avoid rate limiting (can be disabled)
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
# Basic usage (without proxies by default, fastest when cached)
uv run scrape_sacred_texts.py

# Custom options with proxies enabled
uv run scrape_sacred_texts.py \
  --start_page=0 \
  --end_page=112 \
  --output=1-enoch-new.xml \
  --delay=1.5 \
  --use_proxies=True \
  --fetch_dynamic_proxies=True \
  --cache_dir=.cache/html \
  --log_level=INFO

# Use dynamic proxy fetching for fresh proxies
uv run scrape_sacred_texts.py \
  --use_proxies=True \
  --fetch_dynamic_proxies=True

# Skip front matter and start at Chapter I
uv run scrape_sacred_texts.py \
  --start_page=4
```

### Parameters

- `--output`: Output XML filename (default: `1-enoch-new.xml`)
- `--start_page`: First page to process (default: 0 for Title Page, use 4 to skip front matter)
- `--end_page`: Last page to process (default: 112 for final appendix)
- `--delay`: Delay between requests in seconds (default: 1.5)
- `--use_proxies`: Use rotating proxy pool to avoid rate limiting (default: False)
- `--fetch_dynamic_proxies`: Fetch fresh proxies from proxy services (default: False)
- `--cache_dir`: Directory to cache downloaded HTML files (default: `.cache/html`, use empty string `""` to disable caching)
- `--log_level`: Logging level - DEBUG, INFO, WARNING, ERROR (default: INFO)

### Important Notes

**HTML Caching**: By default, the script caches downloaded HTML pages in `.cache/html/`. On subsequent runs, it will use the cached pages instead of downloading them again. This speeds up re-runs significantly and reduces load on the server. To disable caching, use `--cache_dir=""`.

**Dynamic Proxy Fetching**: By default, the script fetches fresh free proxies from proxy list services (proxy-list.download and geonode.com) before starting. It fetches up to 50 of the most recently checked proxies from a pool of 500, which helps avoid rate limiting by using different IPs. If dynamic fetching fails, it falls back to a hardcoded proxy list.

**Proxy Pool**: The script rotates through proxies to distribute requests and avoid rate limiting. If a proxy fails, it automatically tries a direct connection as fallback.

**Rate Limiting**: The sacred-texts.com website implements rate limiting. The script includes:
- Dynamic proxy fetching for fresh, working proxies (50 from 500 most recent)
- Rotating proxy pool (automatically fetches 50 proxies)
- Automatic retry logic with exponential backoff
- Direct connection fallback if proxy fails
- Configurable delay between requests

If you still encounter 429 errors:
- Increase the `--delay` parameter (try 3.0 or higher)
- Wait several hours before retrying if temporarily blocked
- Enable proxy fetching to distribute requests across IPs (`--use_proxies=True --fetch_dynamic_proxies=True`)

**Recommended Approach**:
```bash
# Use cached pages (fastest, default - no proxies needed if already cached)
uv run scrape_sacred_texts.py

# Or with dynamic proxy fetching for fresh downloads
uv run scrape_sacred_texts.py --use_proxies=True --fetch_dynamic_proxies=True --log_level=INFO
```

### How It Works

1. **Fetching**: Downloads HTML pages with proper User-Agent headers, rotating through a proxy pool, with configurable delay between requests
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
- **URL**: https://sacred-texts.com/bib/boe/
- **Translation**: R.H. Charles (1917)
- **Original Publisher**: Oxford University Press

## License

The R.H. Charles translation is in the public domain. The OSIS conversion scripts in this repository are provided for educational and archival purposes.
