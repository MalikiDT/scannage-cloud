import pdfplumber

def extract_text_native(pdf_path: str) -> dict:
    """
    Extrait le texte page par page depuis un PDF natif.
    Retourne un dict { numero_page: texte } et un score de confiance.
    
    Pour les PDF natifs le score est toujours 1.0 —
    le texte est exact, pas d'ambiguïté OCR.
    """
    pages = {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages[i] = text.strip()
        return {
            "pages": pages,
            "score_confiance": 1.0,
            "methode": "natif"
        }
    except Exception as e:
        return {
            "pages": {},
            "score_confiance": 0.0,
            "methode": "natif",
            "erreur": str(e)
        }
