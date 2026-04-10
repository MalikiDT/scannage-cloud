# pipeline_ocr/extractor_scan.py

import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import numpy as np
import cv2

def preprocess_image(pil_image: Image.Image) -> Image.Image:
    """
    Améliore la qualité de l'image avant OCR :
    - Conversion en niveaux de gris
    - Suppression du bruit (denoising)
    - Binarisation adaptative (gère les ombres et variations d'éclairage)
    - Redressement automatique (deskew)
    """
    img = np.array(pil_image)

    # Niveaux de gris
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    # Suppression du bruit
    denoised = cv2.fastNlMeansDenoising(gray, h=10)

    # Binarisation adaptative — plus robuste qu'un seuil fixe
    binary = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=10
    )

    # Deskew — détection et correction de l'inclinaison
    coords = np.column_stack(np.where(binary < 128))
    if len(coords) > 100:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if abs(angle) > 0.3:  # Correction seulement si inclinaison > 0.3°
            h, w = binary.shape
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            binary = cv2.warpAffine(
                binary, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )

    return Image.fromarray(binary)


def _extract_text_scan(pdf_path: str, dpi: int, type_document: str | None = None) -> dict:
    pages = {}
    scores = []
    psm = 4 if type_document == "FACTURE" else 6
    config = f"--oem 3 --psm {psm}"

    try:
        images = convert_from_path(pdf_path, dpi=dpi)
    except Exception as e:
        return {
            "pages": {},
            "score_confiance": 0.0,
            "methode": "ocr",
            "erreur": f"Conversion PDF->image échouée : {e}"
        }

    for i, image in enumerate(images, start=1):
        processed = preprocess_image(image)

        data = pytesseract.image_to_data(
            processed,
            lang="fra+eng+por",
            config=config,
            output_type=pytesseract.Output.DICT
        )

        word_scores = []
        for confidence, word in zip(data["conf"], data["text"]):
            if str(confidence).strip() in ("-1", ""):
                continue
            if len(str(word).strip()) < 2:
                continue
            try:
                word_scores.append(int(float(confidence)))
            except (TypeError, ValueError):
                continue

        page_score = round(sum(word_scores) / len(word_scores) / 100, 3) if word_scores else 0.0
        scores.append(page_score)

        text = pytesseract.image_to_string(
            processed,
            lang="fra+eng+por",
            config=config
        )
        pages[i] = text.strip()

    score_global = round(sum(scores) / len(scores), 3) if scores else 0.0

    return {
        "pages": pages,
        "score_confiance": score_global,
        "methode": "ocr"
    }


def extract_text_scan(pdf_path: str, dpi: int = 300, type_document: str | None = None) -> dict:
    result = _extract_text_scan(pdf_path, dpi=dpi, type_document=type_document)
    if result.get("score_confiance", 0.0) < 0.5 and dpi < 400 and not result.get("erreur"):
        return _extract_text_scan(pdf_path, dpi=400, type_document=type_document)
    return result
