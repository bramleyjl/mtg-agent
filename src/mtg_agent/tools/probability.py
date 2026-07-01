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
