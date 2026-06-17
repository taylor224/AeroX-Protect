"""License-plate text normalization (PLAN P7 A7). OCR output varies in spacing/case/
separators and confuses visually-similar glyphs (O↔0, I↔1, B↔8). We store the raw read
AND a normalized key so watchlist matching is robust across those variations. Locale rules
stay minimal (uppercase + alnum-only); per-country plate grammars are a later refinement.
"""
import re

_NON_ALNUM = re.compile(r'[^A-Z0-9]')
# Canonicalize ambiguous OCR glyphs to a single representative for *matching only*
# (the raw text is preserved separately for display).
_CONFUSABLES = str.maketrans({'O': '0', 'Q': '0', 'D': '0', 'I': '1', 'L': '1',
                              'Z': '2', 'S': '5', 'B': '8'})


def normalize(text: str | None) -> str:
    """Raw plate text → uppercase alnum-only key (for storage/equality)."""
    if not text:
        return ''
    return _NON_ALNUM.sub('', text.upper())


def match_key(text: str | None) -> str:
    """Normalized key with confusable glyphs folded — used for watchlist matching so an
    O↔0 OCR slip still hits. Lossy on purpose; never shown to users."""
    return normalize(text).translate(_CONFUSABLES)
