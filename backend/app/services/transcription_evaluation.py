"""Unicode-aware edit-distance metrics for reference transcription evaluation."""

from __future__ import annotations

import unicodedata


def _normalized_words(text: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    for character in unicodedata.normalize("NFC", text).casefold():
        category = unicodedata.category(character)[0]
        if category in {"L", "M", "N"}:
            current.append(character)
        elif current:
            words.append("".join(current))
            current.clear()
    if current:
        words.append("".join(current))
    return words


def _edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_token in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_token in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[hypothesis_index] + 1,
                    previous[hypothesis_index - 1] + (reference_token != hypothesis_token),
                )
            )
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Return normalized word edit distance; words are Unicode letter/number runs."""
    reference_words = _normalized_words(reference)
    if not reference_words:
        raise ValueError("The reference transcript must contain at least one word.")
    return _edit_distance(reference_words, _normalized_words(hypothesis)) / len(reference_words)


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Return Unicode character edit distance, excluding spaces and punctuation."""
    reference_characters = [
        character for word in _normalized_words(reference) for character in word
    ]
    if not reference_characters:
        raise ValueError("The reference transcript must contain at least one character.")
    hypothesis_characters = [
        character for word in _normalized_words(hypothesis) for character in word
    ]
    return _edit_distance(reference_characters, hypothesis_characters) / len(reference_characters)
