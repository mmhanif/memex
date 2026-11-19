"""Matching ignores case and accents (SPEC §9.3) by the same rule in the server and the
browser (#66). Each case is (text, what fold() makes of it). tests/core/test_names.py
checks them against the server's fold(), tests/e2e/test_search.py against the
browser's, so the two can't drift apart again.
"""

FOLD_CASES = [
    ("José Ruiz", "jose ruiz"),  # precomposed é
    ("Jose\u0301", "jose"),  # e + combining acute
    ("Straße", "strasse"),  # full case folding, not just lowercase
    ("STRAẞE", "strasse"),  # capital sharp s
    ("ﬁle", "file"),  # compatibility ligature
    ("דָּוִד", "דוד"),  # Hebrew niqqud
    ("हिंदी", "हद"),  # Devanagari vowel signs (Mc) and anusvara: marks of combining class 0
    ("ΟΔΟΣ", "οδοσ"),  # capital sigma at a word end
    ("οδός", "οδοσ"),  # final sigma folds to the medial form
    ("K\u0131rm\u0131z\u0131", "k\u0131rm\u0131z\u0131"),  # dotless i (U+0131) stays itself
    ("ᏣᎳᎩ ꮳꮃꭹ", "ᏣᎳᎩ ᏣᎳᎩ"),  # Cherokee folds to its uppercase
]
