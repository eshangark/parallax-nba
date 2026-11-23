import unittest
from decimal import Decimal

from nba_forecast.contract_value import settlement_value


class ContractValueTests(unittest.TestCase):
    def test_hypothetical_settlement(self):
        self.assertEqual(settlement_value('0.70', '0.66', '0.02'), {
            'model_value': Decimal('0.70'),
            'all_in_cost': Decimal('0.68'),
            'break_even_probability': Decimal('0.68'),
            'expected_profit': Decimal('0.02'),
            'win_profit': Decimal('0.32'),
            'loss_profit': Decimal('-0.68'),
        })

    def test_unreachable_break_even(self):
        self.assertIsNone(settlement_value(1, 1, '.01')['break_even_probability'])

    def test_invalid_inputs(self):
        for inputs in [('NaN', '.5', 0), ('.5', '-.01', 0), ('.5', '.5', 'Infinity')]:
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                settlement_value(*inputs)
