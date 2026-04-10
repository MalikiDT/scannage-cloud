# pipeline_ocr/parser.py

import re
from typing import Optional

# ─── Patterns numéro B/L ─────────────────────────────────────────────────────
#
# Formats observés sur les vrais documents :
#   BADDT-1   : "COREOR CONTAINER : S329083002"
#   BL-1      : "Booking No. S329083002" / "Bl. No. S329083002"
#   Facture-1 : "Num B/L | S329083002" (dans un tableau)

BL_LABELS = [
    r"(?:Booking|Ref\.?)\s+No\.?\s*[:\-]?\s*",
    r"COREOR\s+(?:CONTAINER|Vehicule)\s*[:\-]?\s*",
    r"Num[eé]ro\s+de\s+B/?L\s*[:\-]?\s*",
    r"\bCN\s*[:\-]?\s*",
    r"B[lLiI1][/\\]?\.?\s*[Ll]\.?\s*[Nn][Oo]?\.?\s*[:\-]?\s*",
    r"Num\s+B/?L\s*[:\-]?\s*\|?\s*",   # tableau avec | comme séparateur
    r"Marks\s+and\s+Nos\.?\s*[:\-]?\s*",
]

BL_VALUE = r"\$?([A-Z][A-Z0-9]{6,24})"
BL_PATTERNS = [re.compile(label + BL_VALUE, re.IGNORECASE) for label in BL_LABELS]

BL_TABLE_PATTERN = re.compile(
    r"Num\s+B/?L.*?([A-Z][A-Z0-9]{6,})",
    re.IGNORECASE | re.DOTALL,
)

FAUX_POSITIFS_BL = {
    "REPUBLIQUE", "SENEGAL", "MINISTERE", "TRANSITAIRE",
    "CONTAINER", "CONTAINERS", "LIVORNO", "GRIMALDI",
    "MARSEILLE", "COMBINED", "TRANSPORT", "ORIGINAL",
}

# ─── Patterns numéro de déclaration ──────────────────────────────────────────
#
# Format observé sur Declaration-1 :
#   Cases séparées : "2026 | 14V | 20430"
#   Bureau frontière : "18N" (dans une case séparée)
#
# Deux formats possibles :
#   - Cases jointes  : 2026 14V 20430
#   - Cases séparées : 2026 | 14V | 20430  ou  2026 [14V] 20430

DECL_STRICT = re.compile(
    r"\b(20\d{2})\s+(\d{2}[A-Z])\s+(\d{4,6})\b",
    re.MULTILINE,
)

_SEP = r"[\s\|\(\)\{\}\[\]|:,.\-]*"
DECL_SOUPLE = re.compile(
    r"(20\d{2})" + _SEP + r"(\d{2}[A-Z])" + _SEP + r"(\d{4,6})",
    re.IGNORECASE,
)

# Pattern spécifique cases douanières séparées par |
DECL_CASES = re.compile(
    r"(20\d{2})\s*[\|]\s*(\d{2}[A-Z])\s*[\|]\s*(\d{4,6})",
    re.IGNORECASE,
)

# ─── Patterns numéro de facture ───────────────────────────────────────────────
#
# Format observé sur Facture-1 :
#   "Facture N° 2607929"

FACTURE_PATTERNS = [
    re.compile(r"Facture\s+N[°o°º]\.?\s*[:\-]?\s*(\d{5,10})", re.IGNORECASE),
    re.compile(r"N[°o°º]\s+[:\-]?\s*(\d{5,10})", re.IGNORECASE),
    re.compile(r"FACT(?:URE)?\s*[:\-]?\s*(\d{5,10})", re.IGNORECASE),
]

# ─── Fonctions d'extraction ───────────────────────────────────────────────────

def _normalize_bl(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("$"):
        raw = "S" + raw[1:]
    return raw.upper()


def extract_numero_bl(text: str) -> Optional[str]:
    # 1. Patterns contextuels label + valeur
    for pattern in BL_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = _normalize_bl(match.group(1))
            if candidate not in FAUX_POSITIFS_BL:
                return candidate

    # 2. Pattern tableau multiligne
    match = BL_TABLE_PATTERN.search(text)
    if match:
        candidate = _normalize_bl(match.group(1))
        if candidate not in FAUX_POSITIFS_BL:
            return candidate

    # 3. Fallback : séquence commençant par S + chiffres (format Grimaldi)
    fallback = re.search(r"\bS\d{8,12}\b", text)
    if fallback:
        return fallback.group(0).upper()

    return None


def extract_numero_declaration(text: str) -> Optional[str]:
    # Passe 0 — cases avec | (format douanier sénégalais)
    m = DECL_CASES.search(text)
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"

    # Passe 1 — texte propre
    m = DECL_STRICT.search(text)
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"

    # Passe 2 — séparateurs parasites
    m = DECL_SOUPLE.search(text)
    if m:
        start = m.start()
        prefix = text[max(0, start - 30):start]
        if not re.search(r"Manifeste|Sommier", prefix, re.IGNORECASE):
            return f"{m.group(1)} {m.group(2)} {m.group(3)}"

    # Passe 3 — reconstruction
    bureau_m = re.search(r"Bureau\s+\w*\s*(\d{2}[A-Z])", text, re.IGNORECASE)
    # Cherche aussi "Bureau frontière : 18N" sur la déclaration
    bureau_m = bureau_m or re.search(r"Bureau\s+fronti[eè]re\s*[:\-]?\s*(\d{2}[A-Z])", text, re.IGNORECASE)
    label_m  = re.search(r"d.claration", text, re.IGNORECASE)
    year_m   = re.search(r"\b(20\d{2})\b", text)

    if bureau_m and label_m and year_m:
        bureau = bureau_m.group(1)
        annee  = year_m.group(1)
        context = text[label_m.end(): label_m.end() + 200]
        candidats = [n for n in re.findall(r"\b(\d{4,6})\b", context) if n != annee]
        if candidats:
            return f"{annee} {bureau} {candidats[0]}"

    return None


def extract_numero_facture(text: str) -> Optional[str]:
    for pattern in FACTURE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


# ─── Dispatcher ───────────────────────────────────────────────────────────────

DOCUMENT_FIELDS = {
    "BAD_DAKAR_TERMINAL": ["numero_bl", "numero_declaration"],
    "BAD_SHIPPING":       ["numero_bl"],
    "DECLARATION":        ["numero_bl", "numero_declaration"],
    "BILL_OF_LADING":     ["numero_bl"],
    "PROCURATION":        ["numero_bl"],
    "CNI_TRANSITAIRE":    [],
    "CNI_CLIENT":         [],
    "FACTURE":            ["numero_bl", "numero_facture"],
}

EXTRACTORS = {
    "numero_bl":          extract_numero_bl,
    "numero_declaration": extract_numero_declaration,
    "numero_facture":     extract_numero_facture,
}


def parse_document(full_text: str, type_document: str) -> dict:
    champs_cibles = DOCUMENT_FIELDS.get(type_document, [])
    resultats = {}
    for champ in champs_cibles:
        extracteur = EXTRACTORS.get(champ)
        if extracteur:
            resultats[champ] = extracteur(full_text)
    return resultats
