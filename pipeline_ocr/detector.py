pipeline_ocr/detector.py

import pdfplumber

def is_native_pdf(pdf_path: str, min_chars: int = 50) -> bool:
    """
    Retourne True si le PDF contient du texte sélectionnable (PDF natif).
    Retourne False si c'est un scan (image sans texte extractible).
    
    On considère qu'un PDF est natif si au moins une page contient
    plus de `min_chars` caractères extractibles.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if len(text.strip()) >= min_chars:
                    return True
        return False
    except Exception:
        return False
