# -*- coding: utf-8 -*-
"""Удаление явных звуков-паразитов («э-э», «эээ», «а-а-а», «эм», «ммм»).

Аналог SpeechTextCleaner из VoiceCapture 3.6.1 (macOS): локальный фильтр по тексту,
без нейросети. Обычные «ну», «вот», «как бы» и одиночное «а» не трогает.
"""
import re

_W = r"(?<![\w-])"          # слева не буква/цифра/дефис
_E = r"(?![\w-])"           # справа тоже
_DASH = r"[-–—]"

_FILLER = re.compile(
    _W + r"(?:"
    + r"э{2,}(?:" + _DASH + r"э+)*"          # ээ, эээ, ээ-э
    + r"|э(?:" + _DASH + r"э+)+"             # э-э, э-э-э
    + r"|э+м+"                                # эм, эмм, ээм
    + r"|м{2,}(?:" + _DASH + r"м+)*"          # мм, ммм
    + r"|м(?:" + _DASH + r"м+)+"              # м-м-м
    + r"|а{3,}(?:" + _DASH + r"а+)*"          # ааа
    + r"|а(?:" + _DASH + r"а+)+"              # а-а, а-а-а
    + r")" + _E,
    re.IGNORECASE,
)

_SENT_START = re.compile(
    r"(^|[.!?…]\s+)" + _FILLER.pattern + r"[,;:]?\s*([а-яё])",
    re.IGNORECASE,
)


def clean_fillers(text: str) -> str:
    if not text:
        return text
    # паразит в начале предложения: следующее слово становится заглавным
    out = _SENT_START.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    out = _FILLER.sub(" ", out)
    out = re.sub(r"\s+([,.;:!?…])", r"\1", out)          # пробел перед знаком
    out = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", out)     # «, ,» -> «,»
    out = re.sub(r"([.!?…])\s*[,;:]+", r"\1", out)        # «. ,» -> «.»
    out = re.sub(r"^[\s,;:]+", "", out)                   # запятая в начале
    out = re.sub(r"\s{2,}", " ", out).strip()
    if out and out[0].islower() and text[:1].isupper():
        out = out[0].upper() + out[1:]                    # заглавная после выреза начала
    return out
