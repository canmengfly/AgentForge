"""Minimal Okapi BM25 scorer — pure Python, no extra dependencies."""
from __future__ import annotations

import math
import re
from typing import Sequence


def _tokenize(text: str) -> list[str]:
    # Latin/numeric words as whole tokens; each CJK character is its own token
    return re.findall(r"[a-z0-9_]+|[一-鿿]", text.lower())


class BM25:
    """Okapi BM25 over a fixed corpus of strings."""

    def __init__(self, corpus: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._tokenized: list[list[str]] = [_tokenize(doc) for doc in corpus]
        n = len(self._tokenized)
        self._avgdl = (sum(len(d) for d in self._tokenized) / n) if n else 1.0

        df: dict[str, int] = {}
        for tokens in self._tokenized:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1

        self._idf: dict[str, float] = {
            term: math.log((n - freq + 0.5) / (freq + 0.5) + 1)
            for term, freq in df.items()
        }

    def scores(self, query: str) -> list[float]:
        """Return a BM25 score for each document in the corpus."""
        q_tokens = _tokenize(query)
        result: list[float] = []
        for tokens in self._tokenized:
            dl = len(tokens)
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for term in q_tokens:
                idf = self._idf.get(term, 0.0)
                if idf == 0.0:
                    continue
                f = tf.get(term, 0)
                num = f * (self.k1 + 1)
                den = f + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
                score += idf * num / den
            result.append(score)
        return result

    def top_k(self, query: str, k: int) -> list[tuple[int, float]]:
        """Return (corpus_index, score) pairs sorted descending."""
        return sorted(enumerate(self.scores(query)), key=lambda x: x[1], reverse=True)[:k]
