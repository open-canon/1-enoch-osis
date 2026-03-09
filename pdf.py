# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "fire",
#     "pymupdf",
#     "pyosis",
#     "tqdm",
# ]
# ///
from __future__ import annotations

import dataclasses
import enum
import hashlib
import logging
import pathlib
import warnings
from typing import Any, Final, Literal, TypedDict, assert_never, cast

import pymupdf
import pyosis
import tqdm
import fire

LOGGER = logging.getLogger(__name__)

_CHECKSUM_WARNING_MSG = (
    "The checksum of the PDF file does not match the expected value. "
    "This may indicate that the file has been modified or corrupted. "
    "If you are sure the file is correct, you can ignore this warning by setting 'ignore_checksum=True'."
)

_OSIS_WORK_ID: Final[str] = "MentinahArchives"

BOOK_NAMES_LOOKUP: Final[dict[str, str]] = {
    "the book of hahgohtl": "Hahgohtl",
    "the book of hahgmehni": "Hahgmehni",
    "the record of sahnempet": "Sahnempet",
    "the record of ougou": "Ougou",
    "the temple writings of ougou": "Temple Writings of Ougou",
    "the first book of shi-tugohah": "1 Shi-Tugohah",
    "the second book of shi-tugohah": "2 Shi-Tugohah",
    "the first book of shimuel": "1 Shimuel",
    "the second book of shimuel": "2 Shimuel",
    "the book of the high place": "High Place",
    "appendix one": "Appendix One",
    "appendix two": "Appendix Two",
    "appendix three": "Appendix Three",
    "appendix four": "Appendix Four",
    "appendix five": "Appendix Five",
    "appendix six": "Appendix Six",
    "appendix seven": "Appendix Seven",
    "appendix eight": "Appendix Eight",
    "the book of manti": "Manti",
    "the book of shimlei": "Shimlei",
    "the record of shigoeth": "Shigoeth",
    "the first book of pa natan": "1 Pa Natan",
    "the second book of pa natan": "2 Pa Natan",
    "the book of heinmet": "Heinmet",
    "the record of mor-honayah": "Mor-Honayah",
    "the book of shi honayah akektim": "Shi Honayah Akektim",
    "the book of piahomet akekt": "Piahomet Akekt",
    "the book of henet peniet akekt": "Henet Peniet Akekt",
    "the book of pene im akekt": "Pene Im Akekt",
    "the book of chichtenah": "Chichtenah",
    "the book of pahnah tahnich": "Pahnah Tahnich",
    "the book of memish akekt": "Memish Akekt",
    "the book of winet memniet akekt": "Winet Memniet Akekt",
    "the book of momet akekt": "Momet Akekt",
    "the book of teanicumset": "Teanicumset",
    "the book of mipahnet": "Mipahnet",
    "the book of the generations of minisourit": "Minisourit",
    "the book of aku hawaohtim": "Aku Hawaohtim",
    "the words of shi timorah": "Shi Timorah",
    "the book of aku hawaohtim (continued)": "Aku Hawaohtim",
    "the words of shi timorah (continued)": "Shi Timorah",
    "the book of aku winaym": "Aku Winaym",
    "the book of osaraksit pen (penitosagis)": "Osaraksit Pen",
    "the first book of wahshahshay pen": "1 Wahshahshay Pen",
    "the second book of wahshahshay pen": "2 Wahshahshay Pen",
    "the book of menniosarik": "Menniosarik",
    "the book of menipahsits": "Menipahsits",
    "the first book of eapalekthiloom": "1 Eapalekthiloom",
    "the lamentation of menipahsits": "Lamentation of Menipahsits",
    "by the hand of meneminispah": "Meneminispah",
    "the second book of eapalekthiloom": "2 Eapalekthiloom",
    "the book of ordinances and ceremonies": "Ordinances and Ceremonies",
    "the second book of eapalekthiloom (continued)": "2 Eapalekthiloom",
    "the third book of eapalekthiloom": "3 Eapalekthiloom",
    "the book of wallahowah": "Wallahowah",
    "mentinah archives pronunciation guide": "Mentinah Archives Pronunciation Guide",
}

PREFACE_NAMES_LOOKUP = {
    "a short history of the archives": "Short History of the Archives",
    "foreword": "Foreword",
    "foreword by phillip r. (cloudpiler) landis": "Foreword",
}

APPENDIX_NAMES_LOOKUP = {
    "publisher‟s note": "Publisher's Note",
}


class BookType(enum.Enum):
    NORMAL = enum.auto()
    APPENDIX = enum.auto()
    PREFACE = enum.auto()


class SpanDict(TypedDict):
    """PyMuPdf doesn't provide strong enough types"""

    bbox: tuple[float, float, float, float]
    origin: tuple[float, float]
    font: str
    ascender: float
    descender: float
    size: float
    flags: int
    char_flags: int
    color: int
    alpha: int
    text: str


class LineDict(TypedDict):
    """PyMuPdf doesn't provide strong enough types"""

    bbox: tuple[float, float, float, float]
    wmode: Literal[0, 1]
    dir: tuple[int, int]
    spans: list[SpanDict]


class TextBlockDict(TypedDict):
    """PyMuPdf doesn't provide strong enough types"""

    type: Literal[0]
    bbox: tuple[float, float, float, float]
    number: int
    lines: list[LineDict]


class ImageBlockDict(TypedDict):
    """PyMuPdf doesn't provide strong enough types"""

    type: Literal[1]
    bbox: tuple[float, float, float, float]
    number: int
    ext: str
    width: int
    height: int
    colorspace: int
    xres: int
    yres: int
    bpc: int
    transform: tuple[float, float, float, float, float, float]
    size: int
    image: bytes
    mask: bytes


class ImageInfoDict(TypedDict):
    number: int
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    cs_name: str
    colospace: int
    xres: int
    yres: int
    bpc: int
    size: int
    digest: bytes | None
    xref: int
    matrix: Any
    has_mask: bool


@dataclasses.dataclass
class PageCenter:
    column_center_x: float
    column_width: float


def pixmap_to_bytes(pixmap: pymupdf.Pixmap) -> bytes:
    """Convert a Pixmap to PNG bytes (in memory)."""
    return cast("bytes", pixmap.tobytes("png"))


def hash_image(pixmap: pymupdf.Pixmap) -> str:
    """Return SHA256 hash of image bytes."""
    return hashlib.sha256(pixmap_to_bytes(pixmap)).hexdigest()


def extract_chapter_number(text: str) -> int:
    """Chapter headers use 'Chapter Three' format, so extract the number."""
    if not text.lower().startswith("chapter "):
        raise ValueError(f"Invalid chapter header: {text}")
    text = text[8:].strip()  # Remove 'Chapter ' prefix
    number_map = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "twenty-one": 21,
        "twenty-two": 22,
        "twenty-three": 23,
        "twenty-four": 24,
        "twenty-five": 25,
        "twenty-six": 26,
        "twenty-seven": 27,
        "twenty seven": 27,  # The pdf has a typo here
        "twenty-eight": 28,
        "twenty-nine": 29,
        "thirty": 30,
        "thirty-one": 31,
        "thirty-two": 32,
        "thirty-three": 33,
        "thirty-four": 34,
        "thirty-five": 35,
        "thirty-six": 36,
        "thirty six": 36,  # The pdf has a typo here
        "thirty-seven": 37,
        "thirty-eight": 38,
        "thirty-nine": 39,
        "forty": 40,
    }

    return number_map[text.lower()]


def is_bold(span: SpanDict) -> bool:
    """Check if a span is bold based on font flags."""
    return "bold" in span["font"].lower() or bool(span.get("flags", 0) & 2)  # font weight flag


def approximate_center(page: pymupdf.Page) -> PageCenter:
    """Heuristically compute average text column center (because the pdf's center is not necessarily the text center)."""
    blocks = cast("list[TextBlockDict | ImageBlockDict]", page.get_text("dict")["blocks"])
    text_spans = [
        span
        for block in blocks
        if block["type"] == 0
        for line in block["lines"]
        for span in line["spans"]
        if span["text"].strip()
    ]
    if not text_spans:
        raise ValueError("Page has no center? No text found.")
    min_x = min(span["bbox"][0] for span in text_spans)
    max_x = max(span["bbox"][2] for span in text_spans)
    column_center_x: float = (min_x + max_x) / 2
    column_width: float = max_x - min_x

    return PageCenter(column_center_x=column_center_x, column_width=column_width)


def is_centered(span: SpanDict, column_center_x: float, column_width: float) -> bool:
    """Check if a span is horizontally centered within the text column"""
    text_x0, text_x1 = span["bbox"][0], span["bbox"][2]
    center_x: float = (text_x0 + text_x1) / 2
    return abs(center_x - column_center_x) < column_width * 0.1  # within 10% of center


def is_centered_line(line: LineDict, column_center_x: float, column_width: float) -> bool:
    text_x0 = min(span["bbox"][0] for span in line["spans"])
    text_x1 = max(span["bbox"][2] for span in line["spans"])
    center_x = (text_x0 + text_x1) / 2
    near_center = abs(center_x - column_center_x) < column_width * 0.1  # within 10% of center
    full_width = (text_x1 - text_x0) > column_width * 0.98  # line covers at least 95% of column width
    return near_center and not full_width


def followed_by_linebreak(line: LineDict, estimated_center: PageCenter) -> bool:
    # Heuristic: lines followed by linebreaks are those that do not stretch all the way to the edge of the column.
    max_x: float = max(span["bbox"][2] for span in line["spans"])
    expected_column_end: float = estimated_center.column_center_x + estimated_center.column_width / 2
    return max_x < expected_column_end * 0.95


class PdfToPyosis:
    EXPECTED_FILE_SHA256: Final[str] = "bed51f6e3266e225f3cf401f0991913942617a0395edcb2125f20076fbe36947"

    def __init__(
        self,
        pdf_path: str | pathlib.Path,
        output_path: str | pathlib.Path,
        ignore_checksum: bool = False,
    ) -> None:
        self.pdf_path = pathlib.Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError("File not found")
        self.ignore_checksum = ignore_checksum
        self.passed_checksum = self._checksum(self.pdf_path)
        self.pdf: pymupdf.Document = pymupdf.open(pdf_path)

        self.output_path = pathlib.Path(output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.output_xml = self.output_path/"osis-mentinah-archives.xml"
        self.output_images = self.output_path / "images"
        self.output_images.mkdir(parents=True, exist_ok=True)
        self.output_image_stem: str = "page{page_number}_img{image_block_index}.png"

        self.contents: list[pyosis.DivCt] = []
        self.current_verse: list[object] = []
        self.current_verse_number = 0
        self.current_chapter: list[object] = []
        self.current_chapter_number = 0
        self.current_book: list[object] = []
        self.current_book_name = ""
        self.current_book_name_short = ""
        self.current_book_type = BookType.NORMAL
        self.current_book_group_name = ""
        self.current_book_group: list[object] = []
        self.current_line_group: list[pyosis.LCt] = []
        self.in_line_group: bool = False

        self.found_book_names: set[str] = set()

        self.parse()

    def _checksum(self, file_path: pathlib.Path) -> bool:
        """Calculate the MD5 checksum of a file.

        Args:
            file_path: The path to the file to check.

        Returns:
            True if the checksum matches the expected value, False otherwise.

        """
        hasher = hashlib.sha256()
        hasher.update(file_path.read_bytes())
        checksum = hasher.hexdigest()
        if checksum == self.EXPECTED_FILE_SHA256:
            LOGGER.info("Checksum matches for %s.", file_path)
            return True
        if self.ignore_checksum:
            LOGGER.warning(
                "Checksum mismatch for %s, but ignoring due to 'ignore_checksum=True'.",
                file_path,
            )
            return False
        raise ValueError(_CHECKSUM_WARNING_MSG)

    @staticmethod
    def hardcoded_header() -> pyosis.HeaderCt:
        return pyosis.HeaderCt(
            canonical=False,
            revision_desc=[
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(event=pyosis.OsisEvents.EDITION, lang="eng", content=["2004"]),
                ),
            ],
            work=[
                pyosis.WorkCt(
                    osis_work=_OSIS_WORK_ID,
                    lang="eng",
                    title=[
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.MAIN,
                            content=["The Sacred Records of the Nemenhah"],
                        ),
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.SUB,
                            content=["Revised Edition (only volume one) - The Mentinah Archives"],
                        ),
                    ],
                    contributor=[
                        pyosis.ContributorCt(
                            role=pyosis.OsisRoles.TRL,
                            value='Eapalekthiloom Hemeneot Toohyeloakekt (Phillip R. "Cloudpiler" Landis)',
                        ),
                        pyosis.ContributorCt(
                            role=pyosis.OsisRoles.TRL,
                            value="Cesar Padilla de Ramarra R.I.P.",
                        ),
                        pyosis.ContributorCt(role=pyosis.OsisRoles.TRL, value="Tui Xiu, R.I.P."),
                        pyosis.ContributorCt(role=pyosis.OsisRoles.TRL, value="Menemi Shen"),
                        pyosis.ContributorCt(
                            role=pyosis.OsisRoles.TRL,
                            value="Father Porfiro Munoz de Xiu",
                        ),
                    ],
                    publisher=[
                        pyosis.PublisherCt(
                            value="Mentinah Publishing and Distribution (MPD)\n105 S. State #504\nOrem, UT 84058",
                        ),
                        pyosis.PublisherCt(value="Nemenhah People Press\nHumansville, Missouri"),
                    ],
                ),
            ],
        )

    def parse(self) -> pyosis.OsisXML:
        """Parse the PDF file and return an OSIS XML object.

        Returns:
            An instance of pyosis.OsisXML containing the parsed data.

        """
        # Special handling for first few pages
        # Page 1 -- Title page
        page = self.pdf[0]
        page1_images = self.extract_images_from_page(page_number=1, page=page)
        if len(page1_images) != 1:
            raise ValueError("Too many images on first page")

        page1 = pyosis.DivCt(
            canonical=True,
            type_value=pyosis.OsisDivs.TITLE_PAGE,
            content=[
                pyosis.HeadCt(content=["The Sacred Records of the Nemenhah"]),
                pyosis.TitleCt(canonical=False, type_value=pyosis.OsisTitles.SUB, content=["As of Sep. 7, 2011"]),
                pyosis.TitleCt(
                    canonical=False,
                    type_value=pyosis.OsisTitles.SUB,
                    content=["Revised Edition (only volume one) – The Mentinah Archives"],
                ),
                pyosis.PCt(content=["Translation Council:"]),
                pyosis.SignedCt(
                    content=[
                        pyosis.NameCt(
                            content=['Eapalekthiloom Hemeneot Toohyeloakekt (Phillip R. "Cloudpiler" Landis)'],
                        ),
                        pyosis.NameCt(content=["Cesar Padilla de Ramarra R.I.P., of Guatemala"]),
                        pyosis.NameCt(content=["Tui Xiu, R.I.P., of Guatemala"]),
                        pyosis.NameCt(content=["Menemi Shen, of Taiwan"]),
                        pyosis.NameCt(content=["Father Porfiro Munoz de Xiu, formerly of Ethiopia"]),
                    ],
                ),
                pyosis.PCt(content=["Translations faithfully compared"]),
                pyosis.PCt(content=["Clerks of the Council:"]),
                pyosis.DivCt(
                    canonical=True,
                    type_value="x-figure",
                    content=[
                        pyosis.FigureCt(
                            canonical=True,
                            src=str(next(iter(page1_images.values()))),
                            caption=[
                                pyosis.CaptionCt(
                                    content=[
                                        "Pencil sketch of the Glyph Stone shown to Cloudpiler when he was inducted into the Translation Council. The decorative elements of the original carving have been edited out so that the purely literative elements may be more clearly seen. Three distinct literary methods are employed in the glyph. The first is a phonetical system utilizing straight lines and dots. The second is a pictographic system utilizing stylized symbols. The third is animalistic figures taken from oral tradition.",
                                        pyosis.LbCt(),
                                        "The glyph is of personal application to Cloudpiler because it closely corresponds to a representation he received in Vision Quest as a young man. The Medicine Wheel depicted here has been adopted by the Modern Nemenhah People, and elements of it have been incorporated into the Logo of the Nemenhah Indigenous People.",
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        # Page 2 -- Copyright
        page2_copyright = pyosis.DivCt(
            canonical=False,
            type_value=pyosis.OsisDivs.COVER_PAGE,
            content=[
                pyosis.HeadCt(content=["The Sacred Records of the Nemenhah"]),
                pyosis.TitleCt(
                    type_value=pyosis.OsisTitles.SUB,
                    content=["Revised Edition (only volume one) - The Mentinah Archives"],
                ),
                pyosis.PCt(
                    content=[
                        "Copyright © 2004, 2005, 2006 Numi‟Pu Tsu‟Peli Chopunish, 2006, 2007, 2008, 2009, 2010, 2011",
                    ],
                ),
                pyosis.PCt(content=["Nemenhah Band and Native American Traditional Organization. All Rights Reserved"]),
                pyosis.DivCt(
                    type_value="x-publish-info",
                    content=[
                        pyosis.PCt(
                            content=[
                                "First Edition in English published in the United States of America by permission:",
                            ],
                        ),
                        pyosis.PCt(content=["Mentinah Publishing and Distribution (MPD)"]),
                        pyosis.PCt(content=["105 S. State #504"]),
                        pyosis.PCt(content=["Orem, UT 84058"]),
                        pyosis.PCt(
                            content=["Second Edition in English published in the United States of American by:"],
                        ),
                        pyosis.PCt(content=["Nemenhah People Press"]),
                        pyosis.PCt(content=["Humansville, Missouri"]),
                        pyosis.PCt(content=["ABCDEGabcdefg"]),
                        pyosis.PCt(content=["12345678910"]),
                    ],
                ),
                pyosis.DivCt(
                    type_value="x-copyright-info",
                    content=[
                        pyosis.PCt(
                            content=[
                                "This book is copyrighted. Unauthorized duplication of it in any manner is prohibited.",
                            ],
                        ),
                    ],
                ),
            ],
        )

        page2_updates = pyosis.DivCt(
            type_value=pyosis.OsisDivs.PREFACE,
            content=[
                pyosis.HeadCt(content=["Updates and Information"]),
                pyosis.PCt(
                    content=[
                        "The Mentinah Archives are ancient works of history out of which many of the principles of the Nemenhah "
                        "Constitution and Declaration of Good Faith and Practice are derived. The Modern Nemenhah People "
                        "consider these records to be the ancient writings and histories of their own ancestors. These writings, among "
                        "many other ancient writings, constitute Holy Scripture for the Nemenhah People, just as the Bible constitutes "
                        "the same for the world‟s Christian Peoples, the Torah for the world‟s Jewish Peoples, the Koran for the "
                        "Muslims of the world, and so forth.",
                    ],
                ),
                pyosis.PCt(
                    content=[
                        "For information about the Modern Nemenhah People, go to: ",
                        pyosis.LbCt(),
                        pyosis.HiCt(
                            type_value=pyosis.OsisHi.BOLD,
                            content=["http://www.nemenhah.org"],
                        ),
                    ],
                ),
            ],
        )

        # Pages 3-11 are ToC (ignore)
        # Pages 12-13 - A Short History of the Archive
        for page_number, page in enumerate(tqdm.tqdm(self.pdf[11:13], unit="page", desc="Processing pages"), start=12):
            images = self.extract_images_from_page(page_number, page)
            self.extract_text_and_images_from_page(page_number, page, images)

        short_history = pyosis.DivCt(
            canonical=False,
            type_value=pyosis.OsisDivs.PREFACE,
            content=[
                pyosis.HeadCt(canonical=True, content=[self.current_book_name]),
                *self.current_book,
            ],
        )
        self.current_book.clear()
        self.current_book_name = ""
        self.current_book_is_appendix = False

        # Page 14 - Foreword
        for page_number, page in enumerate(tqdm.tqdm(self.pdf[13:14], unit="page", desc="Processing pages"), start=14):
            images = self.extract_images_from_page(page_number, page)
            self.extract_text_and_images_from_page(page_number, page, images)

        foreword = pyosis.DivCt(
            canonical=False,
            type_value=pyosis.OsisDivs.PREFACE,
            content=[
                pyosis.HeadCt(canonical=True, content=[self.current_book_name]),
                *self.current_book,
            ],
        )

        self.current_book.clear()
        self.current_book_name = ""
        self.current_book_is_appendix = False
        # Pages 15->end is the regular text

        front_matter = pyosis.DivCt(
            canonical=False,
            type_value=pyosis.OsisDivs.FRONT,
            content=[page1, page2_copyright, page2_updates, short_history, foreword],
        )

        for page_number, page in enumerate(tqdm.tqdm(self.pdf[14:], unit="page", desc="Processing pages"), start=15):
            images = self.extract_images_from_page(page_number, page)
            self.extract_text_and_images_from_page(page_number, page, images)

        pronunciation_guide = pyosis.DivCt(
            canonical=False,
            type_value=pyosis.OsisDivs.APPENDIX,
            content=[
                pyosis.HeadCt(content=["Mentinah Archives Pronunciation Guide"]),
                pyosis.TitleCt(type_value=pyosis.OsisTitles.SUB, content=["(for volumes 2-8)"]),
                pyosis.DivCt(
                    type_value=pyosis.OsisDivs.INTRODUCTION,
                    content=[
                        pyosis.TitleCt(type_value=pyosis.OsisTitles.SUB, content=["General Rules:"]),
                        pyosis.PCt(
                            content=[
                                "1) Accent is usually on the second to the last syllable. Exceptions exist where hyphens or spaces note the beginning and end of word parts, such as in the name Mor-Honayah. Him-pah-neth is accented equally on all syllables, whereas, Nin-Shepa is accented on Nin and on the first syllable of Shepa. Also excepted in certain words that end in N, R or T, which are stressed on the last syllable regardless of other rules.",
                            ],
                        ),
                        pyosis.PCt(content=["2) The 5 Vowels are pronounced thus."]),
                        pyosis.PCt(
                            content=[
                                "3) A = ah as awkward",
                                pyosis.LbCt(),
                                "E = ay as in lady",
                                pyosis.LbCt(),
                                "I = ee as in tea",
                                pyosis.LbCt(),
                                "O = oh as in go",
                                pyosis.LbCt(),
                                "U = oo as in zoo",
                                pyosis.LbCt(),
                                "Exception exist only in the I, which in some words is lightened to „i‟ as in pit.",
                            ],
                        ),
                        pyosis.PCt(
                            content=[
                                "4) The 24 Consonants are pronounced thus utilizing the English equivalents.",
                                pyosis.LbCt(),
                                "B = bat ",
                                pyosis.LbCt(),
                                "C = cat ",
                                pyosis.LbCt(),
                                "Ch = chat ",
                                pyosis.LbCt(),
                                "D = date ",
                                pyosis.LbCt(),
                                "F = fat ",
                                pyosis.LbCt(),
                                "G = get ",
                                pyosis.LbCt(),
                                "H = hat ",
                                pyosis.LbCt(),
                                "J = jot ",
                                pyosis.LbCt(),
                                "K = cat ",
                                pyosis.LbCt(),
                                "L = let ",
                                pyosis.LbCt(),
                                "M = mat ",
                                pyosis.LbCt(),
                                "N = net",
                                pyosis.LbCt(),
                                "P = pat",
                                pyosis.LbCt(),
                                "R = rat or soft D rolled as in Spanish",
                                pyosis.LbCt(),
                                "S = sat",
                                pyosis.LbCt(),
                                "T = tot",
                                pyosis.LbCt(),
                                "Tl = kl pronounced with back of tongue.",
                                pyosis.LbCt(),
                                "Ts = tsi-tsi",
                                pyosis.LbCt(),
                                "V = vat",
                                pyosis.LbCt(),
                                "W = wet",
                                pyosis.LbCt(),
                                "X = shed",
                                pyosis.LbCt(),
                                "Y = yet",
                                pyosis.LbCt(),
                                "Z = shed",
                                pyosis.LbCt(),
                            ],
                        ),
                    ],
                ),
                pyosis.DivCt(
                    type_value=pyosis.OsisDivs.INTRODUCTION,
                    content=[
                        pyosis.TitleCt(type_value=pyosis.OsisTitles.SUB, content=["Proper Nouns:"]),
                        pyosis.PCt(
                            content=[
                                "Proper nouns are pronounced phonetically. Some names are similar in the English "
                                "spelling to those found in the Book of Mormon. The reader should resist the temptation"
                                " to pronounce them as they have always heard, as this can cause confusion when trying"
                                " to pronounce a name they have not seen before.",
                            ],
                        ),
                    ],
                ),
            ],
        )

        final_xml = pyosis.OsisXML(
            pyosis.Osis(
                osis_text=pyosis.OsisTextCt(
                    lang="en",
                    osis_idwork=_OSIS_WORK_ID,
                    canonical=True,
                    header=self.hardcoded_header(),
                    div=[front_matter, *self.contents, pronunciation_guide],
                ),
            ),
        )
        self.output_xml.write_text(final_xml.to_xml().replace("‟", '"'))

        if (actual_names := set(self.found_book_names)) != (expected_names := set(BOOK_NAMES_LOOKUP.keys())):
            missing = expected_names - actual_names
            extra = actual_names - expected_names
            raise ValueError(
                f"Book names do not match expected values.\nMissing: {missing}\nExtra: {extra}",
            )
        return final_xml

    @property
    def in_verse(self) -> bool:
        return self.current_verse_number > 0

    def start_verse(self, verse_number: int) -> None:
        if self.in_verse:
            self.end_verse()
        self.current_verse_number = verse_number

    def end_verse(self) -> None:
        if self.current_verse:
            if isinstance(self.current_verse[-1], pyosis.LbCt):
                self.current_verse.pop()
            self.current_chapter.append(
                pyosis.VerseCt(
                    osis_id=[
                        f"{self.current_book_name_short}.{self.current_chapter_number}.{self.current_verse_number}",
                    ],
                    canonical=True,
                    content=self.current_verse,
                ),
            )
        self.current_verse.clear()
        self.current_verse_number = 0

    @property
    def in_chapter(self) -> bool:
        return self.current_chapter_number > 0

    def start_chapter(self, chapter_number: int) -> None:
        LOGGER.debug("Starting chapter: %d", chapter_number)
        if self.in_verse:
            self.end_verse()
        if self.in_chapter:
            self.end_chapter()
        self.current_verse_number = 0
        self.current_chapter_number = chapter_number

    def end_chapter(self) -> None:
        LOGGER.debug("Ending chapter: %d", self.current_chapter_number)
        if self.in_verse:
            self.end_verse()
        if self.current_chapter:
            self.current_book.append(
                pyosis.ChapterCt(
                    osis_id=[f"{self.current_book_name_short}.{self.current_chapter_number}"],
                    canonical=True,
                    content=self.current_chapter,
                ),
            )
        self.current_chapter.clear()

    @property
    def in_book(self) -> bool:
        return bool(self.current_book_name)

    def start_book(self, book_name: str, book_type: BookType = BookType.NORMAL) -> None:
        LOGGER.debug("Starting book: %s", book_name)
        if self.in_verse:
            self.end_verse()
        if self.in_chapter:
            self.end_chapter()
        if self.in_book:
            self.end_book()
        self.current_verse_number = 0
        self.current_chapter_number = 0
        self.current_book_name = book_name
        self.current_book_type = book_type

        lower = book_name.lower().strip()
        lookup_dict: dict[str, str]
        match book_type:
            case BookType.NORMAL:
                lookup_dict = BOOK_NAMES_LOOKUP
            case BookType.APPENDIX:
                lookup_dict = APPENDIX_NAMES_LOOKUP
            case BookType.PREFACE:
                lookup_dict = PREFACE_NAMES_LOOKUP
            case _:
                assert_never(book_type)
        self.current_book_name_short = lookup_dict[lower]

    def end_book(self) -> None:
        LOGGER.debug("Ending book: %s", self.current_book_name)
        if self.in_verse:
            self.end_verse()
        if self.in_chapter:
            self.end_chapter()

        if self.current_book:
            type_value: pyosis.OsisDivs = (
                {
                    BookType.NORMAL: pyosis.OsisDivs.BOOK,
                    BookType.APPENDIX: pyosis.OsisDivs.APPENDIX,
                    BookType.PREFACE: pyosis.OsisDivs.PREFACE,
                }
            )[self.current_book_type]
            book_div = pyosis.DivCt(
                osis_id=[self.current_book_name_short],
                canonical=True,
                type_value=type_value,
                content=[
                    pyosis.HeadCt(canonical=True, content=[self.current_book_name]),
                    *self.current_book,
                ],
            )
            if self.in_book_group:
                self.current_book_group.append(book_div)
            else:
                self.contents.append(book_div)

        self.current_book.clear()
        self.current_book_name = ""
        self.current_book_is_appendix = False

    @property
    def in_book_group(self) -> bool:
        return bool(self.current_book_group_name)

    def start_book_group(self, book_group_name: str) -> None:
        LOGGER.debug("Starting book group: %s", book_group_name)
        if self.in_verse:
            self.end_verse()
        if self.in_chapter:
            self.end_chapter()
        if self.in_book:
            self.end_book()
        if self.in_book_group:
            self.end_book_group()
        self.current_verse_number = 0
        self.current_chapter_number = 0
        self.current_book_name = ""
        self.current_book_name_short = ""
        self.current_book_group_name = book_group_name

    def end_book_group(self) -> None:
        if self.in_verse:
            self.end_verse()
        if self.in_chapter:
            self.end_chapter()
        if self.in_book:
            self.end_book()
        if self.current_book_group:
            book_group_div = pyosis.DivCt(
                type_value=pyosis.OsisDivs.BOOK_GROUP,
                canonical=True,
                content=[
                    pyosis.HeadCt(canonical=True, content=[self.current_book_group_name]),
                    *self.current_book_group,
                ],
            )
            self.contents.append(book_group_div)
        self.current_book_group_name = ""
        self.current_book_group.clear()

    def add_subtitle(self, text: str) -> None:
        LOGGER.debug("Adding subtitle: %s", text)
        subtitle = pyosis.TitleCt(
            canonical=True,
            type_value=pyosis.OsisTitles.SUB,
            content=[pyosis.PCt(canonical=True, content=[text.strip()])],
        )
        if self.in_verse:
            raise ValueError("Unclear how to handle subtitle within verse")
        if self.in_chapter:
            self.current_chapter.append(subtitle)
        elif self.in_book:
            self.current_book.append(subtitle)
        elif self.in_book_group:
            self.current_book_group.append(subtitle)
        else:
            raise ValueError("Unclear where to put subtitle")

    def add_string(self, text: str, is_bold: bool, followed_by_linebreak: bool) -> None:
        current_collection: list[object]
        if self.in_verse:
            current_collection = self.current_verse
        elif self.in_chapter:
            current_collection = self.current_chapter
        elif self.in_book:
            current_collection = self.current_book
        else:
            raise ValueError("Unknown collection to add string to")
        if not current_collection:
            if is_bold:
                current_collection.append(pyosis.HiCt(type_value=pyosis.OsisHi.BOLD, content=[text]))
            else:
                current_collection.append(text)
        elif is_bold:
            if (
                isinstance(current_collection[-1], pyosis.HiCt)
                and current_collection[-1].type_value == pyosis.OsisHi.BOLD
            ):
                current_collection[-1].content.append(" " + text.strip())
            else:
                current_collection.append(pyosis.HiCt(type_value=pyosis.OsisHi.BOLD, content=[text]))
        elif current_collection and isinstance(current_collection[-1], str):
            current_collection[-1] += " " + text.strip()
        else:
            current_collection.append(text)
        if followed_by_linebreak:
            current_collection.append(pyosis.LbCt())

    def add_image(self, img_path: pathlib.Path, inline: bool) -> None:
        current_collection: list[object]
        if self.in_verse:
            current_collection = self.current_verse
        elif self.in_chapter:
            current_collection = self.current_chapter
        elif self.in_book:
            current_collection = self.current_book
        else:
            raise ValueError("Unknown collection to add image to")
        if inline and isinstance(current_collection[-1], pyosis.LbCt):
            current_collection.pop(-1)
        current_collection.append(pyosis.FigureCt(canonical=True, src=str(img_path), size="inline" if inline else None))

    def start_line_group(self) -> None:
        self.in_line_group = True

    def end_line_group(self) -> None:
        line_group = pyosis.LgCt(l=[*self.current_line_group])
        self.current_verse.append(line_group)
        self.current_line_group.clear()
        self.in_line_group = False

    def extract_images_from_page(self, page_number: int, page: pymupdf.Page) -> dict[int, pathlib.Path | None]:
        images: dict[int, pathlib.Path | None] = {}
        # Create lookup of bbox -> xref from get_images
        page_images = cast(
            "list[tuple[int, int, int, int, int, str, str, str, str, int]]",
            page.get_images(full=True),
        )
        if not page_images:
            return {}
        image_infos: list[ImageInfoDict] = page.get_image_info(xrefs=True)

        xref_map: dict[int, int] = {image_info["number"]: image_info["xref"] for image_info in image_infos}

        blocks = cast("list[TextBlockDict | ImageBlockDict]", page.get_text("dict")["blocks"])
        for block in blocks:
            if block["type"] != 1:
                # Not images
                continue
            bbox = block["bbox"]
            LOGGER.debug("Image block Location (bbox): %s", str(bbox))

            # Heuristically try to match image block to xref by dimensions
            matched_xref = xref_map[block["number"]]

            try:
                pix = pymupdf.Pixmap(self.pdf, matched_xref)
                filename = self.output_image_stem.format(page_number=page_number, image_block_index=block["number"])
                filepath = self.output_images / filename

                # Convert CMYK if needed
                if pix.n >= 5:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

                # Optional: hash to detect duplicates
                img_hash = hash_image(pix)
                LOGGER.debug("SHA256: %s", img_hash)
                pix.save(str(filepath))
                LOGGER.debug("Saved as: %s", filepath)
                images[block["number"]] = pathlib.Path(filepath)
            except Exception as e:
                warnings.warn(f"Failed to save image from xref {matched_xref}: {e}", stacklevel=2)
                images[block["number"]] = None
        return images

    def extract_text_and_images_from_page(  # noqa: C901, PLR0912, PLR0915
        self,
        page_number: int,
        page: pymupdf.Page,
        images: dict[int, pathlib.Path | None],
    ) -> None:
        """Extract text and images from a page and parse them.

        Args:
            page_number: The page number from which the page comes.
            page: The pymupdf Page object.
            images: the result of `self.extract_images_from_page`.

        """
        estimated_center = approximate_center(page)
        LOGGER.debug(
            "Extracting text from page %d. Estimated center: %.2f. Estimated width: %.2f",
            page_number,
            estimated_center.column_center_x,
            estimated_center.column_width,
        )

        blocks = cast("list[TextBlockDict | ImageBlockDict]", page.get_text("dict")["blocks"])
        for block in blocks:
            if block["type"] not in (0, 1):
                raise ValueError("Unknown block type.")
            if block["type"] == 1:  # Image
                img_path = images[block["number"]]
                if img_path is None:
                    raise ValueError("Unknown image???")
                self.add_image(img_path, inline=True)
            elif block["type"] == 0:
                for line in block["lines"]:
                    text = (" ".join(span["text"] for span in line["spans"])).strip()
                    lower_case = text.lower()
                    if not text.strip():
                        continue
                    # Lines that are just numbers are probably page numbers, and should be skipped
                    if text.isdigit():
                        LOGGER.debug(
                            "Skipping line with only digits on page %d: %s",
                            page_number,
                            text,
                        )
                        continue
                    first_span = line["spans"][0]["text"]
                    # Extract verse number if it looks like a number at the start
                    # Appendix Four has numbered lists of things that look like this heuristic for verses
                    if (
                        first_span.endswith(".")
                        and first_span[:-1].strip().isdigit()
                        and self.current_book_name != "Appendix Four"
                    ):
                        first_span = first_span[:-1]
                        try:
                            first_span_int = int(first_span)
                        except ValueError:
                            pass
                        else:
                            if not self.in_chapter:
                                self.start_chapter(1)  # default to chapter 1 if not set
                            self.start_verse(first_span_int)
                            # There are no instances of lines that start with verse number that have any other text.
                            # We can simplify the logic.
                            continue
                    # Extract chapter
                    elif is_bold(line["spans"][0]) and "Chapter" in first_span:
                        chapter_number = extract_chapter_number(first_span)
                        self.start_chapter(chapter_number)
                        # There are no instances of lines that start with Bold Chapter that have any other text.
                        # We can simplify the logic.
                        continue
                    elif page_number == 100 and text.strip() == "The Book of the High Place":
                        self.start_book_group(text.strip())
                        self.current_book_group.append(pyosis.DivCt(type_value=pyosis.OsisDivs.COVER_PAGE, content=[]))
                        continue
                    elif (
                        page_number == 100
                        and self.in_book_group
                        and text.strip().startswith("The Sacred Temple Writing")
                    ):
                        # Hard code the cover page because it would be more difficult to parse this one
                        # page differently.
                        assert self.in_book_group
                        assert isinstance(self.current_book_group[0], pyosis.DivCt)
                        self.current_book_group[0].content.extend(
                            [
                                pyosis.HeadCt(content=["The Book of the High Place"]),
                                pyosis.TitleCt(
                                    type_value=pyosis.OsisTitles.SUB,
                                    content=[
                                        "The Sacred Temple Writings of the Nemenhah, as recorded by the Prophet, Ougou",
                                    ],
                                ),
                                pyosis.TitleCt(
                                    type_value=pyosis.OsisTitles.SUB,
                                    content=["With Appendices Added"],
                                ),
                                pyosis.DivCt(
                                    type_value="x-publish-info",
                                    content=[
                                        pyosis.PCt(content=["Translated from the Original"]),
                                        pyosis.PCt(
                                            content=[
                                                "With translations carefully compared By the Translation Council:",
                                                pyosis.LbCt(),
                                                pyosis.NameCt(
                                                    type_value=pyosis.OsisNames.PERSON,
                                                    content=[
                                                        "Hemene Ot To Oh Yelo Akekt (Phillip Cloudpiler Landis) of"
                                                        " Weaubleau, MO, ",
                                                    ],
                                                ),
                                                pyosis.NameCt(
                                                    type_value=pyosis.OsisNames.PERSON,
                                                    content=["Cesar Padilla de Ramarra of Guatemala, "],
                                                ),
                                                pyosis.NameCt(
                                                    type_value=pyosis.OsisNames.PERSON,
                                                    content=["Tui Xiu of Guatemala, "],
                                                ),
                                                pyosis.NameCt(
                                                    type_value=pyosis.OsisNames.PERSON,
                                                    content=["Menemi Shen of Taiwan, "],
                                                ),
                                                "and ",
                                                pyosis.NameCt(
                                                    type_value=pyosis.OsisNames.PERSON,
                                                    content=["Porfiro Munoz de Xiu of Ethiopia"],
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                                pyosis.DivCt(
                                    type_value="x-copyright-info",
                                    content=[
                                        pyosis.PCt(
                                            content=[
                                                "Copyright © 2005, 2006 Numi'Pu Tsu'Peli Chopunish,"
                                                " 2006, 2007, 2008, 2009 Nemenhah Band and Native American "
                                                "Traditional Organization",
                                            ],
                                        ),
                                        pyosis.PCt(content=["All rights reserved"]),
                                    ],
                                ),
                            ],
                        )
                        continue
                    elif page_number == 100 and self.in_book_group:
                        continue  # Handled above
                    elif (
                        all(is_bold(span) for span in line["spans"])
                        and is_centered_line(
                            line,
                            estimated_center.column_center_x,
                            estimated_center.column_width,
                        )
                        and text.strip() != "The Ways and Customs of the Ahmohnayhah"
                        and (
                            lower_case in BOOK_NAMES_LOOKUP
                            or lower_case in APPENDIX_NAMES_LOOKUP
                            or lower_case in PREFACE_NAMES_LOOKUP
                        )
                    ):
                        # Criteria: bold-ish font and horizontally centered
                        if page_number == 158 and text.strip() == "The Book of Manti":
                            self.end_book_group()
                        LOGGER.debug("Page %d: Found potential book name → %s", page_number, text)
                        if lower_case in BOOK_NAMES_LOOKUP:
                            self.found_book_names.add(lower_case)
                            self.start_book(text.strip(), book_type=BookType.NORMAL)
                        elif lower_case in APPENDIX_NAMES_LOOKUP:
                            self.start_book(text.strip(), book_type=BookType.APPENDIX)
                        elif lower_case in PREFACE_NAMES_LOOKUP:
                            self.start_book(text.strip(), book_type=BookType.PREFACE)
                        else:
                            raise ValueError("Unknown error occured.")
                        continue
                    elif (
                        page_number == 138
                        and not self.in_chapter
                        and (lower_case.startswith(("narrator", "be used", "man representing", "discipleship")))
                    ):
                        linebreak = followed_by_linebreak(line, estimated_center)
                        for i, span in enumerate(line["spans"]):
                            self.add_string(
                                span["text"],
                                is_bold=is_bold(span),
                                followed_by_linebreak=(linebreak and i == len(line["spans"]) - 1),
                            )
                        continue
                    elif lower_case and page_number == 352 and text == "yay-nay.":
                        continue  # This is a continuation of the previous line which is handled below.
                    elif lower_case and page_number == 352 and self.in_line_group:
                        assert self.current_verse_number == 12
                        osis_text: str | pyosis.HiCt = text
                        if text == (
                            "Chu-yayp-ku-chay Way-chee-eetay Cheem-ee-eem Hee-eemtay-chekt-toksayn-ay Keen-yay Yay-lay-"
                        ):
                            # Add the next line that got wrapped.
                            osis_text = text + "-yay-nay."
                        if any(is_bold(span) for span in line["spans"] if span["text"].strip()):
                            osis_text = pyosis.HiCt(type_value=pyosis.OsisHi.BOLD, content=[osis_text])
                        osis_line = pyosis.LCt(content=[osis_text])
                        self.current_line_group.append(osis_line)
                        if text == "It is a Sacred Talk.":
                            self.end_line_group()
                        continue

                    # If it's not a book name, but is bold, then it is probably a subtitle??
                    elif (
                        lower_case
                        and all(is_bold(span) for span in line["spans"])
                        and page_number != 352  # Song lyrics ending up as subtitles otherwise
                    ):
                        if self.in_verse:
                            self.end_verse()
                        self.add_subtitle(text)
                        continue
                    if (
                        page_number == 352
                        and self.current_verse_number == 12
                        and text == "these are the words of the song:"
                    ):
                        self.start_line_group()
                    if not text:
                        continue
                    if not self.in_book:
                        self.add_subtitle(text)
                        continue
                    if not self.in_chapter and self.current_book_name not in {
                        "Foreword by Phillip R. (Cloudpiler) Landis",
                        "Appendix Four",
                        "Appendix Five",
                        "Appendix Eight",
                        "A Short History of the Archives",
                        "Foreword",
                    }:
                        self.add_subtitle(text)
                        continue
                    linebreak = followed_by_linebreak(line, estimated_center)
                    for i, span in enumerate(line["spans"]):
                        should_end_with_linebreak = linebreak and i == len(line["spans"]) - 1
                        if (page_number in {147, 148}) and (
                            text.strip().removesuffix(".").isdigit()
                            or text in {"a.", "b.", "c.", "d.", "e.", "f.", "g.", "h.", "i."}
                        ):
                            should_end_with_linebreak = False
                        self.add_string(
                            span["text"],
                            is_bold=is_bold(span),
                            followed_by_linebreak=should_end_with_linebreak,
                        )
