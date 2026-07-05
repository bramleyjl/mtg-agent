from itertools import product
from math import comb


def hypergeometric_probability(
    deck_size: int,
    successes_in_deck: int,
    sample_size: int,
    min_successes: int = 1,
) -> dict:
    """
    Compute draw probabilities for a card/category in a deck using the
    hypergeometric distribution (sampling without replacement).

    deck_size: total cards left to draw from (e.g. 99 for a Commander deck,
      minus any cards already seen if computing forward from a known hand).
    successes_in_deck: copies of the target card/type remaining in deck_size.
    sample_size: cards drawn/seen (e.g. opening hand + draws by a given turn).
    min_successes: the threshold used for probability_at_least/probability_at_most.
    """
    if deck_size < 0:
        raise ValueError("deck_size must be >= 0")
    if not (0 <= successes_in_deck <= deck_size):
        raise ValueError("successes_in_deck must be between 0 and deck_size")
    if not (0 <= sample_size <= deck_size):
        raise ValueError("sample_size must be between 0 and deck_size")
    if min_successes < 0:
        raise ValueError("min_successes must be >= 0")

    def exactly(k: int) -> float:
        if k < 0 or k > successes_in_deck:
            return 0.0
        remaining_draws = sample_size - k
        remaining_failures = deck_size - successes_in_deck
        if remaining_draws < 0 or remaining_draws > remaining_failures:
            return 0.0
        return (
            comb(successes_in_deck, k)
            * comb(remaining_failures, remaining_draws)
            / comb(deck_size, sample_size)
        )

    max_k = min(successes_in_deck, sample_size)
    probability_at_least = sum(exactly(k) for k in range(min_successes, max_k + 1))
    probability_at_most = sum(exactly(k) for k in range(0, min(min_successes, max_k) + 1))

    return {
        "deck_size": deck_size,
        "successes_in_deck": successes_in_deck,
        "sample_size": sample_size,
        "min_successes": min_successes,
        "probability_exactly": exactly(min_successes),
        "probability_at_least": probability_at_least,
        "probability_at_most": probability_at_most,
    }


def multivariate_hypergeometric_probability(
    deck_size: int,
    categories: list[dict],
    sample_size: int,
) -> dict:
    """
    Probability that several card categories simultaneously meet their own
    minimum thresholds in a single draw (e.g. "at least 2 lands AND at
    least 1 removal spell in my opening hand").

    categories: [{"name": str, "count_in_deck": int, "min_needed": int}, ...]
    """
    if deck_size < 0:
        raise ValueError("deck_size must be >= 0")
    if not (0 <= sample_size <= deck_size):
        raise ValueError("sample_size must be between 0 and deck_size")
    if not categories:
        raise ValueError("categories must be non-empty")

    counts = [c["count_in_deck"] for c in categories]
    mins = [c["min_needed"] for c in categories]
    if any(count < 0 for count in counts) or any(m < 0 for m in mins):
        raise ValueError("count_in_deck and min_needed must be >= 0")
    if sum(counts) > deck_size:
        raise ValueError("sum of count_in_deck must not exceed deck_size")

    other_in_deck = deck_size - sum(counts)
    ranges = [range(m, min(count, sample_size) + 1) for count, m in zip(counts, mins)]

    total_ways = comb(deck_size, sample_size)
    probability_all_met = 0.0
    for combo in product(*ranges):
        other_drawn = sample_size - sum(combo)
        if not (0 <= other_drawn <= other_in_deck):
            continue
        ways = comb(other_in_deck, other_drawn)
        for count, t in zip(counts, combo):
            ways *= comb(count, t)
        probability_all_met += ways / total_ways

    return {
        "deck_size": deck_size,
        "sample_size": sample_size,
        "categories": categories,
        "probability_all_met": probability_all_met,
    }


def mulligan_adjusted_probability(
    deck_size: int,
    successes_in_deck: int,
    min_successes: int,
    max_mulligans: int,
    hand_size: int = 7,
) -> dict:
    """
    Probability of reaching an acceptable hand within a London-mulligan
    sequence (draw hand_size cards, mulligan up to max_mulligans times).

    Each mulligan reshuffles the hand back into the library and draws a
    fresh hand_size-card hand, so each attempt is modeled as an independent
    hypergeometric trial on the full deck_size — the standard simplifying
    assumption used by MTG mulligan calculators. This ignores the
    post-keep bottoming step, which doesn't affect the keep/mulligan
    decision itself.
    """
    if max_mulligans < 0:
        raise ValueError("max_mulligans must be >= 0")

    single_hand_probability = hypergeometric_probability(
        deck_size, successes_in_deck, hand_size, min_successes
    )["probability_at_least"]

    attempts = max_mulligans + 1
    probability_success_overall = 1 - (1 - single_hand_probability) ** attempts

    return {
        "deck_size": deck_size,
        "successes_in_deck": successes_in_deck,
        "min_successes": min_successes,
        "hand_size": hand_size,
        "max_mulligans": max_mulligans,
        "single_hand_probability": single_hand_probability,
        "probability_by_attempt": [single_hand_probability] * attempts,
        "probability_success_overall": probability_success_overall,
    }


def sources_needed_for_probability(
    deck_size: int,
    sample_size: int,
    min_successes: int,
    target_probability: float,
) -> dict:
    """
    Inverse of hypergeometric_probability: the Frank Karsten-style question
    "how many sources of a color do I need for a target probability by a
    given turn?" Finds the minimal successes_in_deck (e.g. color sources)
    whose probability_at_least clears target_probability.

    Returns sources_needed=None if even deck_size successes can't reach
    target_probability (e.g. an unreachable target for the given sample_size).
    """
    if not (0 < target_probability <= 1):
        raise ValueError("target_probability must be in (0, 1]")

    for successes_in_deck in range(min_successes, deck_size + 1):
        result = hypergeometric_probability(
            deck_size, successes_in_deck, sample_size, min_successes
        )
        if result["probability_at_least"] >= target_probability:
            return {
                "deck_size": deck_size,
                "sample_size": sample_size,
                "min_successes": min_successes,
                "target_probability": target_probability,
                "sources_needed": successes_in_deck,
                "achieved_probability": result["probability_at_least"],
            }

    return {
        "deck_size": deck_size,
        "sample_size": sample_size,
        "min_successes": min_successes,
        "target_probability": target_probability,
        "sources_needed": None,
        "achieved_probability": None,
    }


def cards_seen_by_turn(turn: int, starting_hand: int = 7) -> int:
    """
    Cards seen by the end of a given turn's draw step. Commander is a
    multiplayer format, so the "skip your first draw step" rule (which only
    applies in two-player games) does not apply — every player draws every
    turn, including turn 1.
    """
    if turn < 1:
        raise ValueError("turn must be >= 1")
    return starting_hand + turn
