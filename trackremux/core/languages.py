# ISO 639-2/B (Bibliographic) code definitions
# Format: "3_letter_code": ["alias1", "alias2", ...]

LANGUAGES = {
    # European
    "bul": ["bg", "bulgarian", "bul"],
    "cat": ["ca", "catalan", "cat"],
    "cze": ["cs", "czech", "ces", "cze"],
    "dan": ["da", "danish", "dan"],
    "eng": ["en", "english", "eng"],
    "fin": ["fi", "finnish", "fin"],
    "fre": ["fr", "french", "fra", "fre"],
    "ger": ["de", "german", "deu", "ger"],
    "gre": ["el", "greek", "ell", "gre"],
    "hrv": ["hr", "croatian", "scr", "hrv"],
    "hun": ["hu", "hungarian", "hun"],
    "isl": ["is", "icelandic", "isl"],
    "ita": ["it", "italian", "ita"],
    "nld": ["nl", "dutch", "dut", "nld"],
    "nor": ["no", "norwegian", "nor"],
    "pol": ["pl", "polish", "pol"],
    "por": ["pt", "portuguese", "por"],
    "rum": ["ro", "romanian", "ron", "rum"],
    "rus": ["ru", "russian", "rus"],
    "slv": ["sl", "slovenian", "slv"],
    "spa": ["es", "spanish", "spa"],
    "srp": ["sr", "serbian", "scc", "srp"],
    "svk": ["sk", "slovak", "svk"],
    "swe": ["sv", "swedish", "swe"],
    "tur": ["tr", "turkish", "tur"],
    "ukr": ["uk", "ukrainian", "ukr"],
    # Asian
    "ara": ["ar", "arabic", "ara"],
    "chi": ["zh", "chinese", "zho", "chi"],
    "heb": ["he", "hebrew", "heb"],
    "hin": ["hi", "hindi", "hin"],
    "ind": ["id", "indonesian", "ind"],
    "jpn": ["jp", "japanese", "jpn"],
    "kor": ["ko", "korean", "kor"],
    "may": ["ms", "malay", "msa", "may"],
    "tha": ["th", "thai", "tha"],
    "vie": ["vi", "vietnamese", "vie"],
    # African
    "afr": ["af", "afrikaans", "afr"],
    "amh": ["am", "amharic", "amh"],
    "swa": ["sw", "swahili", "swa"],
    "zul": ["zu", "zulu", "zul"],
    # Other
    "und": ["und", "undefined", "unknown"],
}

# Generate quick lookup map (alias -> 3_letter_code)
# This allows O(1) matching for any known alias
LANGUAGE_MAP = {}
for code, aliases in LANGUAGES.items():
    for alias in aliases:
        LANGUAGE_MAP[alias] = code


def guess_language_from_filename(filename: str) -> str | None:
    """
    Attempts to guess language from filename parts (e.g. 'movie.eng.mkv' -> 'eng').
    """
    # Normalize
    normalized = filename.lower().replace("-", ".").replace("_", ".")
    parts = normalized.split(".")

    # Check each part
    for part in parts:
        if part in LANGUAGE_MAP:
            return LANGUAGE_MAP[part]

    return None
