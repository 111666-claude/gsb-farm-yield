import unittest

from farming.core import Budget


class BudgetTest(unittest.TestCase):
    def test_grant_returns_amount(self):
        self.assertEqual(Budget(100, 60000).grant("p", "wolf", "e1", 10, 0), 10)

    def test_granted_totals_records(self):
        book = Budget(100, 60000)
        book.grant("p", "wolf", "e1", 10, 0)
        book.grant("p", "wolf", "e2", 20, 0)
        self.assertEqual(book.granted("p", "wolf", 0), 30)

    def test_pending_counts_records(self):
        book = Budget(100, 60000)
        book.grant("p", "wolf", "e1", 10, 0)
        book.grant("p", "wolf", "e2", 10, 0)
        self.assertEqual(book.pending("p", "wolf", 0), 2)

    def test_counters_start_at_zero(self):
        book = Budget(100, 60000)
        self.assertEqual(book.scanned_count(), 0)
        self.assertEqual(book.dropped_count(), 0)


if __name__ == "__main__":
    unittest.main()
