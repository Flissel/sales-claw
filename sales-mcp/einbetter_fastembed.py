"""Lokale Einbettungen mit fastembed (nur im Beobachter-/Arbeiter-Abbild vorhanden).

Der Import von fastembed steht bewusst nur hier und in der Klasse, damit das
Test-Abbild ohne fastembed laeuft. Modelle werden einmal in __init__ geladen.
"""
from __future__ import annotations

import io

MODELL_BILD = "Qdrant/clip-ViT-B-32-vision"
MODELL_TEXT_CLIP = "Qdrant/clip-ViT-B-32-text"
MODELL_TEXT = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class FastEmbedEinbetter:
    def __init__(self) -> None:
        from fastembed import ImageEmbedding, TextEmbedding  # lazy

        self._bild = ImageEmbedding(model_name=MODELL_BILD)
        self._text_clip = TextEmbedding(model_name=MODELL_TEXT_CLIP)
        self._text = TextEmbedding(model_name=MODELL_TEXT)

    def bild(self, jpeg: bytes) -> list[float]:
        from PIL import Image

        with Image.open(io.BytesIO(jpeg)) as b:
            b = b.convert("RGB")
            return [float(x) for x in next(iter(self._bild.embed([b])))]

    def text_clip(self, text: str) -> list[float]:
        return [float(x) for x in next(iter(self._text_clip.embed([text])))]

    def text(self, text: str) -> list[float]:
        return [float(x) for x in next(iter(self._text.embed([text])))]
