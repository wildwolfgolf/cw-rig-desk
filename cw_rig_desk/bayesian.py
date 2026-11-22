"""Posterior decoding of a single Morse symbol from measured key timings."""

from itertools import product

import numpy as np


class BayesianSymbolDecoder:
    """Score mark sequences under a shared dot duration and a tempo prior."""

    def __init__(self, codebook, adaptive=True):
        self.codebook = codebook
        self.max_marks = max(map(len, codebook))
        self.scales = np.linspace(0.70, 1.30, 13) if adaptive else np.array([1.0])
        self.log_prior = -0.5 * ((self.scales - 1.0) / 0.17) ** 2
        self.candidates = {}
        for length in range(1, self.max_marks + 1):
            patterns = tuple("".join(bits) for bits in product(".-", repeat=length))
            units = np.array([[1 if mark == "." else 3 for mark in pattern] for pattern in patterns])
            expected = units[None, :, :] * self.scales[:, None, None]
            spread = (0.24 + 0.065 * units[None, :, :]) * self.scales[:, None, None]
            self.candidates[length] = patterns, expected, spread

    def decode(self, marks, gaps, dot):
        if len(marks) not in self.candidates:
            return "�", None
        patterns, expected, spread = self.candidates[len(marks)]
        durations, uncertainty = np.asarray(marks, dtype=float).T / dot
        # Broaden each likelihood when the two key edges were close to the
        # tone detector's threshold. Keep an absolute fit check for noise.
        sigma = np.hypot(spread, uncertainty)
        residual = (durations - expected) / sigma
        scores = (-0.5 * residual ** 2 - np.log(sigma)).sum(axis=2)
        scores += self.log_prior[:, None]
        if gaps:
            # Internal spaces are also evidence of the common dot length.
            error = (np.asarray(gaps)[None, :] / dot - self.scales[:, None]) / 0.36
            scores -= 0.5 * np.mean(error ** 2, axis=1)[:, None]

        log_weights = np.logaddexp.reduce(scores, axis=0)
        choice = int(np.argmax(log_weights))
        probability = np.exp(log_weights[choice] - np.logaddexp.reduce(log_weights))
        best_tempo = int(np.argmax(scores[:, choice]))
        fit = np.mean(residual[best_tempo, choice] ** 2)
        pattern = patterns[choice]
        if probability < 0.60 or fit > 4.0 or pattern not in self.codebook:
            return "�", None
        return self.codebook[pattern], pattern
