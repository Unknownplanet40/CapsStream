"""
backend/sub_naming.py - Unified subtitle language normalization, parsing, and filename formatting.

Single source of truth for:
  - ISO 639-1 / 639-2 language code normalization and display names
  - Subtitle flag parsing (SDH / Hearing Impaired, Forced)
  - Duplicate index parsing / formatting
  - Display label generation for player track listings
"""

import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any


# Standard ISO 639-1 code -> English display name
LANG_MAP: Dict[str, str] = {
    "en": "English",
    "ja": "Japanese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "zh": "Chinese",
    "ko": "Korean",
    "ru": "Russian",
    "pt": "Portuguese",
    "tl": "Filipino",
    "fil": "Filipino",
    "ar": "Arabic",
    "hi": "Hindi",
    "id": "Indonesian",
    "ms": "Malay",
    "th": "Thai",
    "vi": "Vietnamese",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "sv": "Swedish",
    "no": "Norwegian",
    "da": "Danish",
    "fi": "Finnish",
    "el": "Greek",
    "he": "Hebrew",
    "cs": "Czech",
    "hu": "Hungarian",
    "ro": "Romanian",
    "uk": "Ukrainian",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "is": "Icelandic",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sr": "Serbian",
    "et": "Estonian",
    "fa": "Persian",
}

# Alias mapping: ISO 639-2/B/T codes and english terms -> ISO 639-1 standard code
LANG_ALIASES: Dict[str, str] = {
    # English
    "en": "en", "eng": "en", "english": "en",
    # Tagalog / Filipino
    "tl": "tl", "tag": "tl", "tgl": "tl", "tagalog": "tl", "fil": "tl", "filipino": "tl",
    # Japanese
    "ja": "ja", "jpn": "ja", "japanese": "ja",
    # Spanish
    "es": "es", "spa": "es", "spanish": "es",
    # French
    "fr": "fr", "fre": "fr", "fra": "fr", "french": "fr",
    # German
    "de": "de", "ger": "de", "deu": "de", "german": "de",
    # Italian
    "it": "it", "ita": "it", "italian": "it",
    # Chinese
    "zh": "zh", "chi": "zh", "zho": "zh", "chinese": "zh",
    # Korean
    "ko": "ko", "kor": "ko", "korean": "ko",
    # Russian
    "ru": "ru", "rus": "ru", "russian": "ru",
    # Portuguese
    "pt": "pt", "por": "pt", "portuguese": "pt",
    # Arabic
    "ar": "ar", "ara": "ar", "arabic": "ar",
    # Hindi
    "hi": "hi", "hin": "hi", "hindi": "hi",
    # Indonesian
    "id": "id", "ind": "id", "indonesian": "id",
    # Malay
    "ms": "ms", "may": "ms", "msa": "ms", "malay": "ms",
    # Thai
    "th": "th", "tha": "th", "thai": "th",
    # Vietnamese
    "vi": "vi", "vie": "vi", "vietnamese": "vi",
    # Dutch
    "nl": "nl", "dut": "nl", "nld": "nl", "dutch": "nl",
    # Polish
    "pl": "pl", "pol": "pl", "polish": "pl",
    # Turkish
    "tr": "tr", "tur": "tr", "turkish": "tr",
    # Swedish
    "sv": "sv", "swe": "sv", "swedish": "sv",
    # Norwegian
    "no": "no", "nor": "no", "norwegian": "no", "nob": "no", "nno": "no",
    # Danish
    "da": "da", "dan": "da", "danish": "da",
    # Finnish
    "fi": "fi", "fin": "fi", "finnish": "fi",
    # Greek
    "el": "el", "ell": "el", "gre": "el", "greek": "el",
    # Hebrew
    "he": "he", "heb": "he", "hebrew": "he",
    # Czech
    "cs": "cs", "ces": "cs", "cze": "cs", "czech": "cs",
    # Hungarian
    "hu": "hu", "hun": "hu", "hungarian": "hu",
    # Romanian
    "ro": "ro", "ron": "ro", "rum": "ro", "romanian": "ro",
    # Ukrainian
    "uk": "uk", "ukr": "uk", "ukrainian": "uk", "ukraine": "uk",
    # Bulgarian
    "bg": "bg", "bul": "bg", "bulgarian": "bg",
    # Croatian
    "hr": "hr", "hrv": "hr", "croatian": "hr",
    # Icelandic
    "is": "is", "ice": "is", "isl": "is", "icelandic": "is",
    # Latvian
    "lv": "lv", "lav": "lv", "latvian": "lv",
    # Lithuanian
    "lt": "lt", "lit": "lt", "lithuanian": "lt",
    # Slovak
    "sk": "sk", "slo": "sk", "slk": "sk", "slovak": "sk",
    # Slovenian
    "sl": "sl", "slv": "sl", "slovenian": "sl", "slovenia": "sl",
    # Serbian
    "sr": "sr", "srp": "sr", "serbian": "sr", "serbia": "sr",
    # Estonian
    "et": "et", "est": "et", "estonian": "et", "estonia": "et",
    # Persian / Farsi
    "fa": "fa", "per": "fa", "fas": "fa", "persian": "fa", "farsi": "fa",
}

# Backward compatibility map: maps both 2-letter and 3-letter codes to English name
LANG_NAMES: Dict[str, str] = {}
for _alias, _canon in LANG_ALIASES.items():
    if len(_alias) in (2, 3) and _canon in LANG_MAP:
        LANG_NAMES[_alias] = LANG_MAP[_canon]


@dataclass
class ParsedSub:
    lang: str                  # ISO 639-1 code or "und"
    is_hi: bool                # Hearing Impaired / SDH / CC
    is_forced: bool            # Forced track
    suffix_index: Optional[int]# Disambiguation index, e.g. 2 for .2
    original_name: str         # Full filename or stem
    is_recognized: bool        # True if a known language was detected


def normalize_lang(token: Optional[str]) -> Optional[str]:
    """Normalize a language token, code, or word to ISO 639-1, or None if unknown."""
    if not token:
        return None
    cleaned = token.strip().lower()
    return LANG_ALIASES.get(cleaned)


def parse_filename(name: str, parent_folder: str = "") -> ParsedSub:
    """
    Parse a subtitle filename (and optional parent folder) into structured metadata.
    Does NOT assume English when flags (HI/SDH) are present without a language token.
    """
    raw_name = os.path.basename(name)
    stem, _ = os.path.splitext(raw_name)

    stem_lower = stem.lower()
    parent_lower = (parent_folder or "").lower()

    # Match tokens separated by dot, hyphen, underscore, space, brackets
    text_to_search = f"{parent_lower} {stem_lower}"

    # 1. Detect Hearing Impaired (HI / SDH / CC)
    # Check for specific words or isolated tokens like .hi., -hi-, _hi_
    is_hi = bool(
        re.search(r"(?:^|[._\-\s\[\(])(sdh|cc|hearing[._\-\s]?impaired)(?:[._\-\s\]\)]|$)", text_to_search) or
        re.search(r"(?:^|[._\-\s\[\(])hi(?:[._\-\s\]\)]|$)", stem_lower)
    )

    # 2. Detect Forced
    is_forced = bool(re.search(r"(?:^|[._\-\s\[\(])(forced?|foreign)(?:[._\-\s\]\)]|$)", text_to_search))

    # 3. Detect duplicate/numeric suffix index (e.g. "movie.en.2.srt", "movie.en.forced.3.srt")
    suffix_index: Optional[int] = None
    num_match = re.search(r"(?:^|[._\-\s])(\d{1,3})(?:[._\-\s]|$)", stem_lower)
    if num_match:
        # Check if the number is at the tail of the stem (or before hi/forced)
        tail_num_match = re.search(r"\.(\d{1,3})(?:\.(?:hi|sdh|forced?|foreign))?$", stem_lower)
        if tail_num_match:
            try:
                suffix_index = int(tail_num_match.group(1))
            except ValueError:
                pass
        else:
            # Check trailing number pattern e.g. " (2)", ".2"
            trailing_num = re.search(r"(?:[\.\s_\-])(\d{1,2})$", stem_lower)
            if trailing_num:
                try:
                    val = int(trailing_num.group(1))
                    # Avoid treating season/episode numbers as suffixes if part of S01E02
                    if not re.search(r"[se]\d+$", stem_lower):
                        suffix_index = val
                except ValueError:
                    pass

    # 4. Detect Language
    # First priority: check tokens in filename stem (split by dot/underscore/hyphen/space)
    detected_lang: Optional[str] = None

    tokens = [t.strip() for t in re.split(r"[._\-\s\[\]\(\)]+", stem_lower) if t.strip()]
    for token in reversed(tokens):
        if token in ("sdh", "cc", "forced", "force", "foreign"):
            continue
        if token == "hi" and is_hi:
            continue
        norm = normalize_lang(token)
        if norm:
            detected_lang = norm
            break

    # Second priority: check parent folder if not found in filename
    if not detected_lang and parent_lower:
        parent_tokens = [t.strip() for t in re.split(r"[._\-\s\[\]\(\)]+", parent_lower) if t.strip()]
        for token in parent_tokens:
            if token in ("sdh", "cc", "forced", "force", "foreign"):
                continue
            if token == "hi" and is_hi:
                continue
            norm = normalize_lang(token)
            if norm:
                detected_lang = norm
                break

    lang = detected_lang if detected_lang else "und"
    is_recognized = detected_lang is not None

    return ParsedSub(
        lang=lang,
        is_hi=is_hi,
        is_forced=is_forced,
        suffix_index=suffix_index,
        original_name=raw_name,
        is_recognized=is_recognized,
    )


def format_filename_tag(parsed: ParsedSub) -> str:
    """
    Format standard dot-separated subtitle filename tag, e.g.:
      .en
      .en.hi
      .en.forced
      .en.2
      .en.forced.2
    """
    lang = parsed.lang if (parsed.is_recognized and parsed.lang != "und") else ""
    parts = [lang] if lang else []
    if parsed.is_hi:
        parts.append("hi")
    elif parsed.is_forced:
        parts.append("forced")

    if parsed.suffix_index and parsed.suffix_index > 1:
        parts.append(str(parsed.suffix_index))

    if not parts:
        return ""
    return "." + ".".join(parts)


def display_label(parsed: ParsedSub, raw_name: str = "") -> str:
    """
    Build user-facing player track label:
      "English"
      "English (Forced)"
      "English (HI)"
      "English (2)"
      "English (Forced) (2)"
    Fallback to clean raw filename when language is undetermined. Must never throw.
    """
    try:
        if parsed.is_recognized and parsed.lang in LANG_MAP:
            lang_name = LANG_MAP[parsed.lang]
            label_parts = [lang_name]
            if parsed.is_forced:
                label_parts.append("(Forced)")
            elif parsed.is_hi:
                label_parts.append("(HI)")
            if parsed.suffix_index and parsed.suffix_index > 1:
                label_parts.append(f"({parsed.suffix_index})")
            return " ".join(label_parts)

        # Unrecognized: display sanitized filename stem without crash
        source = raw_name or parsed.original_name or "Subtitle"
        stem = os.path.splitext(os.path.basename(source))[0]
        clean = re.sub(r"[._\-]+", " ", stem).strip()
        if parsed.is_hi:
            clean += " (HI)"
        if parsed.is_forced:
            clean += " (Forced)"
        return clean or "Subtitle"
    except Exception:
        return raw_name or "Subtitle"
