"""Settlement arithmetic for a hypothetical contract paying one dollar on a win."""

from decimal import Decimal, InvalidOperation


def settlement_value(win_probability, price, entry_fee):
    """Return amounts in dollars per contract using caller-supplied fees."""
    try:
        probability, price, fee = (Decimal(str(value)) for value in
                                   (win_probability, price, entry_fee))
    except InvalidOperation as exc:
        raise ValueError('Probability, price and fee must be numeric') from exc
    if not all(value.is_finite() and 0 <= value <= 1 for value in (probability, price, fee)):
        raise ValueError('Probability, price and entry fee must be finite values between 0 and 1')
    cost = price + fee
    return {
        'model_value': probability,
        'all_in_cost': cost,
        'break_even_probability': cost if cost <= 1 else None,
        'expected_profit': probability - cost,
        'win_profit': 1 - cost,
        'loss_profit': -cost,
    }
