"""Probabilistic beam search over Morse marks and gaps."""

from math import hypot, log


# A small, prior shared by both receive alphabets. Unknown words and calls remain possible.
CW_WORDS = frozenset(("CQ", "DE", "TEST", "TU", "73", "599", "5NN",
                      "ЦЩ", "ДЕ", "ТЕСТ", "ТУ", "5НН"))


def word_cost(word):
    if word in CW_WORDS:
        return -0.65
    return 0.0


class BayesianSequenceDecoder:
    """Search over marks and boundaries jointly on a bounded stretch of CW."""

    WIDTH = 24

    def __init__(self, codebook):
        self.codebook = codebook
        self.prefixes = {pattern[:i] for pattern in codebook for i in range(1, len(pattern) + 1)}

    def decode(self, marks, gaps, dot):
        if not marks:
            return "", ()

        # Each hypothesis carries the open Morse symbol and its current word.
        # The parts record the chosen marks for the existing tempo tracker.
        states = [(0.0, "", "", "", ())]
        for index, (duration, uncertainty) in enumerate(marks):
            spread = hypot(0.33, uncertainty / max(dot, duration))
            duration = max(duration / dot, 0.08)
            mark_cost = {mark: 0.5 * (log(duration / units) / spread) ** 2
                         for mark, units in ((".", 1), ("-", 3))}
            if index:
                gap = max(gaps[index - 1] / dot, 0.08)
                gap_cost = [0.5 * (log(gap / units) / spread) ** 2
                            for units, spread in ((1, 0.45), (3, 0.36), (7, 0.43))]
            expanded = {}
            for score, text, word, prefix, parts in states:
                options = [(score + (gap_cost[0] if index else 0), text, word, prefix)]
                if prefix:
                    next_word = word + self.codebook.get(prefix, "�")
                    penalty = 0 if prefix in self.codebook else 4.0
                    options.extend((
                        (score + gap_cost[1] + penalty, text, next_word, ""),
                        (score + gap_cost[2] + penalty + word_cost(next_word),
                         text + next_word + " ", "", ""),
                    ))
                for cost, output, current_word, stem in options:
                    for mark, change in mark_cost.items():
                        pattern = stem + mark
                        if pattern not in self.prefixes:
                            continue
                        key = output, current_word, pattern
                        total = cost + change
                        if key not in expanded or total < expanded[key][0]:
                            expanded[key] = (total, *key, parts + (mark,))
            states = sorted(expanded.values())[:self.WIDTH]

        def finish(state):
            score, text, word, pattern, parts = state
            word += self.codebook.get(pattern, "�")
            penalty = 0 if pattern in self.codebook else 4.0
            return score + word_cost(word) + penalty, text + word, parts

        cost, text, parts = min(map(finish, states))
        if cost > 3.0 * len(marks):
            return "�", ()
        return text, parts
