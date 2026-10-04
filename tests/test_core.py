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


class SlidingWindowTest(unittest.TestCase):
    def test_boundary_record_expires(self):
        book = Budget(100, 5000)
        book.grant("p", "wolf", "e1", 40, 0)
        self.assertEqual(book.granted("p", "wolf", 5000), 0)
        self.assertEqual(book.pending("p", "wolf", 5000), 0)

    def test_record_inside_window_kept(self):
        book = Budget(100, 5000)
        book.grant("p", "wolf", "e1", 40, 1)
        self.assertEqual(book.granted("p", "wolf", 5000), 40)
        self.assertEqual(book.pending("p", "wolf", 5000), 1)

    def test_cap_frees_after_window_slides(self):
        book = Budget(100, 5000)
        self.assertEqual(book.grant("p", "wolf", "e1", 100, 0), 100)
        self.assertEqual(book.grant("p", "wolf", "e2", 100, 4999), 0)
        self.assertEqual(book.grant("p", "wolf", "e3", 100, 5000), 100)

    def test_expired_records_reclaimed(self):
        book = Budget(1000000, 1000)
        for index in range(3000):
            book.grant("p", "wolf", "e-%d" % index, 1, index)
        self.assertEqual(book.pending("p", "wolf", 100000), 0)
        self.assertEqual(book.granted("p", "wolf", 100000), 0)


class CapTest(unittest.TestCase):
    def test_partial_grant_truncated_by_cap(self):
        book = Budget(100, 60000)
        self.assertEqual(book.grant("p", "wolf", "e1", 70, 0), 70)
        self.assertEqual(book.grant("p", "wolf", "e2", 70, 0), 30)
        self.assertEqual(book.dropped_count(), 40)
        self.assertEqual(book.granted("p", "wolf", 0), 100)

    def test_full_cap_drops_everything(self):
        book = Budget(100, 60000)
        book.grant("p", "wolf", "e1", 100, 0)
        self.assertEqual(book.grant("p", "wolf", "e2", 50, 0), 0)
        self.assertEqual(book.dropped_count(), 50)

    def test_scope_is_per_player_and_source(self):
        book = Budget(100, 60000)
        book.grant("a", "wolf", "e1", 100, 0)
        self.assertEqual(book.grant("b", "wolf", "e2", 100, 0), 100)
        self.assertEqual(book.grant("a", "boar", "e3", 100, 0), 100)
        self.assertEqual(book.dropped_count(), 0)


class IdempotencyTest(unittest.TestCase):
    def test_duplicate_event_settles_once(self):
        book = Budget(100, 60000)
        self.assertEqual(book.grant("p", "wolf", "e1", 50, 0), 50)
        self.assertEqual(book.grant("p", "wolf", "e1", 50, 0), 0)
        self.assertEqual(book.granted("p", "wolf", 0), 50)
        self.assertEqual(book.pending("p", "wolf", 0), 1)
        self.assertEqual(book.dropped_count(), 0)

    def test_duplicate_event_does_not_consume_cap(self):
        book = Budget(100, 60000)
        book.grant("p", "wolf", "e1", 100, 0)
        self.assertEqual(book.grant("p", "wolf", "e1", 100, 0), 0)
        self.assertEqual(book.dropped_count(), 0)
        self.assertEqual(book.grant("p", "wolf", "e2", 100, 60000), 100)


class QueryCostTest(unittest.TestCase):
    def test_query_cost_does_not_scale_with_history(self):
        book = Budget(1000000, 1000)
        for index in range(3000):
            book.grant("p", "wolf", "e-%d" % index, 1, index)
        for _ in range(3000):
            book.pending("p", "wolf", 3000)
        self.assertLessEqual(book.scanned_count(), 3000)

    def test_repeated_queries_scan_nothing(self):
        book = Budget(1000000, 1000)
        for index in range(3000):
            book.grant("p", "wolf", "e-%d" % index, 1, index)
        book.pending("p", "wolf", 3000)
        before = book.scanned_count()
        for _ in range(1000):
            book.pending("p", "wolf", 3000)
            book.granted("p", "wolf", 3000)
        self.assertEqual(book.scanned_count(), before)


class ReferenceBudget:
    """滑动窗口 + 额度截断 + 幂等的朴素参考实现，用于对照。"""

    def __init__(self, cap, window_ms):
        self.cap = cap
        self.window_ms = window_ms
        self.records = []
        self.seen = set()
        self.dropped = 0

    def _active(self, player, source, now_ms):
        cutoff = now_ms - self.window_ms
        return [
            record
            for record in self.records
            if record[0] == player and record[1] == source and record[3] > cutoff
        ]

    def grant(self, player, source, event_id, amount, now_ms):
        if event_id in self.seen:
            return 0
        self.seen.add(event_id)
        used = sum(record[2] for record in self._active(player, source, now_ms))
        granted = max(0, min(amount, self.cap - used))
        if granted:
            self.records.append((player, source, granted, now_ms))
        self.dropped += amount - granted
        return granted

    def pending(self, player, source, now_ms):
        return len(self._active(player, source, now_ms))

    def granted(self, player, source, now_ms):
        return sum(record[2] for record in self._active(player, source, now_ms))


class DifferentialTest(unittest.TestCase):
    def _run_script(self, book, script):
        outcomes = []
        for op in script:
            if op[0] == "grant":
                outcomes.append(book.grant(op[1], op[2], op[3], op[4], op[5]))
            elif op[0] == "granted":
                outcomes.append(book.granted(op[1], op[2], op[3]))
            else:
                outcomes.append(book.pending(op[1], op[2], op[3]))
        return outcomes

    def _make_script(self, rng, cap, window_ms):
        players = ["p%d" % i for i in range(rng.randint(1, 3))]
        sources = ["s%d" % i for i in range(rng.randint(1, 3))]
        event_pool = ["e-%d" % i for i in range(rng.randint(1, 40))]
        script = []
        clock = 0
        for _ in range(rng.randint(1, 120)):
            clock += rng.randint(0, window_ms)
            player = rng.choice(players)
            source = rng.choice(sources)
            roll = rng.random()
            if roll < 0.7:
                if rng.random() < 0.3:
                    event_id = rng.choice(event_pool)
                else:
                    event_id = "e-new-%d" % rng.randint(0, 10 ** 9)
                amount = rng.randint(1, max(1, cap * 2))
                script.append(("grant", player, source, event_id, amount, clock))
            elif roll < 0.85:
                script.append(("granted", player, source, clock))
            else:
                script.append(("pending", player, source, clock))
        return script

    def test_matches_reference_on_random_scripts(self):
        import random

        rng = random.Random(20261004)
        for case in range(200):
            cap = rng.randint(1, 200)
            window_ms = rng.randint(1, 5000)
            script = self._make_script(rng, cap, window_ms)
            book = Budget(cap, window_ms)
            reference = ReferenceBudget(cap, window_ms)
            expected = self._run_script(reference, script)
            actual = self._run_script(book, script)
            self.assertEqual(actual, expected, "case %d" % case)
            self.assertEqual(book.dropped_count(), reference.dropped, "case %d" % case)
            replay = self._run_script(Budget(cap, window_ms), script)
            self.assertEqual(replay, actual, "case %d replay" % case)
