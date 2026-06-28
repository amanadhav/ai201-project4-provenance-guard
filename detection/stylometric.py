"""
Stylometric heuristics detection signal.

Measures four statistical surface properties of text to estimate AI-probability:
  1. Sentence Length Variance (SLV)
  2. Type-Token Ratio (TTR)
  3. Punctuation Density (PD)
  4. Average Word Length (AWL)

Returns a score from 0.0 (definitely human) to 1.0 (definitely AI).
"""

import re
import math
import string


def _tokenize_sentences(text: str) -> list[str]:
    """Split text into sentences on . ! ? boundaries."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s for s in sentences if s.strip()]


def _tokenize_words(text: str) -> list[str]:
    """Extract alphabetic word tokens (lowercase)."""
    return re.findall(r"\b[a-zA-Z']+\b", text.lower())


def sentence_length_variance(text: str) -> float:
    """
    Compute normalized sentence-length variance.

    AI text tends toward uniform sentence lengths; human text varies widely.
    Returns a score 0.0–1.0 where 1.0 = very uniform (AI-like).
    """
    sentences = _tokenize_sentences(text)
    if len(sentences) < 2:
        return 0.5  # can't measure variance on a single sentence

    lengths = [len(s.split()) for s in sentences]
    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    std_dev = math.sqrt(variance)

    # Humans typically show std_dev of 5–15 words; AI tends toward 2–6.
    # We map std_dev to a 0–1 human-variance score, then invert for AI-score.
    # Cap at std_dev = 20 to avoid edge cases with very long texts.
    normalized_variance = min(std_dev / 20.0, 1.0)
    ai_score = 1.0 - normalized_variance  # low variance → higher AI score
    return round(ai_score, 4)


def type_token_ratio(text: str) -> float:
    """
    Compute type-token ratio (unique words / total words).

    AI text at moderate lengths tends toward a slightly higher, very consistent TTR.
    Human text is more erratic — topic and register affect it strongly.
    Returns a score 0.0–1.0 where values near 0.7 are AI-typical for prose.
    """
    words = _tokenize_words(text)
    if not words:
        return 0.5

    ttr = len(set(words)) / len(words)

    # AI prose 100–500 words typically lands around 0.55–0.75 TTR.
    # Very high TTR (short text) or very low (repetitive) are both more human-like.
    # Peak AI-likelihood around 0.65; we model this as a bell-curve inverted.
    ai_peak = 0.65
    spread = 0.20
    ai_score = math.exp(-((ttr - ai_peak) ** 2) / (2 * spread ** 2))
    return round(ai_score, 4)


def punctuation_density(text: str) -> float:
    """
    Compute punctuation per word ratio.

    Humans use em-dashes, ellipses, exclamation points erratically.
    AI output tends toward clean, period-terminated sentences with minimal
    expressive punctuation.
    Returns a score 0.0–1.0 where 1.0 = very low punctuation density (AI-like).
    """
    words = _tokenize_words(text)
    if not words:
        return 0.5

    # Exclude apostrophes — they appear in contractions (I've, don't) rather than
    # as expressive punctuation, so they don't discriminate human vs AI writing.
    expressive_punct = set('—–…!?;:()"')
    count = sum(1 for ch in text if ch in expressive_punct)
    density = count / len(words)

    # Humans typically produce 0.02–0.12 expressive punct per word.
    # AI typically produces 0.0–0.02 (very clean, period-only sentences).
    # Map: low density → high AI score.
    # Clamp at 0.15 (quite expressive human writing).
    normalized = min(density / 0.15, 1.0)
    ai_score = 1.0 - normalized
    return round(ai_score, 4)


def average_word_length(text: str) -> float:
    """
    Compute average word length.

    AI text clusters around medium-length words (4–6 chars) due to training
    on "clear writing" norms. Human writing mixes short function words with
    unusual long vocabulary.
    Returns a score 0.0–1.0 where 1.0 = AI-typical word length pattern.
    """
    words = _tokenize_words(text)
    if not words:
        return 0.5

    avg_len = sum(len(w) for w in words) / len(words)

    # AI prose avg word length: typically 4.5–5.5 chars.
    # Human writing: wider range (3.5–7.0).
    ai_peak = 5.0
    spread = 0.80
    ai_score = math.exp(-((avg_len - ai_peak) ** 2) / (2 * spread ** 2))
    return round(ai_score, 4)


def analyze(text: str) -> dict:
    """
    Run all stylometric signals and return a combined AI-probability score.

    Weights:
      - Sentence length variance: 40% (strongest differentiator)
      - Punctuation density:      30% (reliable for prose)
      - Type-token ratio:         20% (context-dependent)
      - Average word length:      10% (weakest signal alone)
    """
    if not text or len(text.strip()) < 20:
        return {
            "score": 0.5,
            "confidence": "low",
            "sub_scores": {},
            "note": "Text too short for reliable stylometric analysis",
        }

    slv = sentence_length_variance(text)
    ttr = type_token_ratio(text)
    pd_ = punctuation_density(text)
    awl = average_word_length(text)

    combined = (
        0.50 * slv   # strongest signal — AI is notably more uniform
        + 0.15 * ttr
        + 0.25 * pd_
        + 0.10 * awl
    )

    word_count = len(_tokenize_words(text))
    confidence = "high" if word_count >= 100 else ("medium" if word_count >= 40 else "low")

    return {
        "score": round(combined, 4),
        "confidence": confidence,
        "sub_scores": {
            "sentence_length_variance": slv,
            "type_token_ratio": ttr,
            "punctuation_density": pd_,
            "average_word_length": awl,
        },
        "word_count": word_count,
    }
