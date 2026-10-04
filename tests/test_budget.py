"""滑动窗口、额度截断、幂等、回收与查询代价测试，含随机差分与规模测试。"""

import random
import time
import unittest

from farming.core import Budget


class WindowTest(unittest.TestCase):
    def test_record_at_window_boundary_is_expired(self):
        book = Budget(cap=100, window_ms=5000)
        self.assertEqual(book.grant("p", "wolf", "e1", 10, 0), 10)
        self.assertEqual(book.pending("p", "wolf", 5000), 0)
        self.assertEqual(book.granted("p", "wolf", 5000), 0)

    def test_record_just_inside_window_is_alive(self):
        book = Budget(cap=100, window_ms=5000)
        self.assertEqual(book.grant("p", "wolf", "e1", 10, 1), 10)
        self.assertEqual(book.pending("p", "wolf", 5000), 1)
        self.assertEqual(book.granted("p", "wolf", 5000), 10)

    def test_sliding_window_releases_cap(self):
        book = Budget(cap=100, window_ms=5000)
        self.assertEqual(book.grant("p", "wolf", "e1", 100, 0), 100)
        self.assertEqual(book.grant("p", "wolf", "e2", 100, 4999), 0)
        # e2 在满额时已结算为 0：重放按幂等返回 0，不再计丢弃。
        self.assertEqual(book.grant("p", "wolf", "e2", 100, 5000), 0)
        self.assertEqual(book.dropped_count(), 100)
        # 窗口滑出后额度释放，新事件可以发满。
        self.assertEqual(book.grant("p", "wolf", "e3", 100, 5000), 100)
        self.assertEqual(book.granted("p", "wolf", 5000), 100)
        self.assertEqual(book.pending("p", "wolf", 5000), 1)
        self.assertEqual(book.dropped_count(), 100)

    def test_expired_records_are_reclaimed(self):
        book = Budget(cap=1_000_000, window_ms=1000)
        for index in range(3000):
            book.grant("p", "wolf", "e-%d" % index, 1, index)
        self.assertEqual(book.pending("p", "wolf", 100000), 0)
        self.assertEqual(book.granted("p", "wolf", 100000), 0)
        self.assertEqual(len(book._ledgers[("p", "wolf")][0]), 0)


class CapTest(unittest.TestCase):
    def test_partial_overflow_is_truncated_and_dropped(self):
        book = Budget(cap=100, window_ms=60000)
        self.assertEqual(book.grant("p", "wolf", "e1", 60, 0), 60)
        self.assertEqual(book.grant("p", "wolf", "e2", 60, 0), 40)
        self.assertEqual(book.granted("p", "wolf", 0), 100)
        self.assertEqual(book.dropped_count(), 20)

    def test_full_overflow_returns_zero(self):
        book = Budget(cap=100, window_ms=60000)
        self.assertEqual(book.grant("p", "wolf", "e1", 100, 0), 100)
        self.assertEqual(book.grant("p", "wolf", "e2", 50, 0), 0)
        self.assertEqual(book.granted("p", "wolf", 0), 100)
        self.assertEqual(book.dropped_count(), 50)

    def test_cap_is_scoped_per_player_and_source(self):
        book = Budget(cap=100, window_ms=60000)
        self.assertEqual(book.grant("a", "wolf", "e1", 100, 0), 100)
        self.assertEqual(book.grant("b", "wolf", "e2", 100, 0), 100)
        self.assertEqual(book.grant("a", "boar", "e3", 100, 0), 100)
        self.assertEqual(book.granted("a", "wolf", 0), 100)
        self.assertEqual(book.granted("b", "wolf", 0), 100)
        self.assertEqual(book.granted("a", "boar", 0), 100)
        self.assertEqual(book.dropped_count(), 0)

    def test_window_total_never_exceeds_cap(self):
        book = Budget(cap=100, window_ms=1000)
        for index in range(500):
            book.grant("p", "wolf", "e-%d" % index, 30, index * 3)
            self.assertLessEqual(book.granted("p", "wolf", index * 3), 100)


class IdempotencyTest(unittest.TestCase):
    def test_duplicate_event_returns_zero_without_quota_or_drop(self):
        book = Budget(cap=100, window_ms=60000)
        self.assertEqual(book.grant("p", "wolf", "e1", 50, 0), 50)
        self.assertEqual(book.grant("p", "wolf", "e1", 50, 0), 0)
        self.assertEqual(book.granted("p", "wolf", 0), 50)
        self.assertEqual(book.pending("p", "wolf", 0), 1)
        self.assertEqual(book.dropped_count(), 0)

    def test_duplicate_event_across_window_still_settled_once(self):
        book = Budget(cap=100, window_ms=5000)
        self.assertEqual(book.grant("p", "wolf", "e1", 100, 0), 100)
        self.assertEqual(book.grant("p", "wolf", "e1", 100, 100000), 0)
        self.assertEqual(book.granted("p", "wolf", 100000), 0)
        self.assertEqual(book.pending("p", "wolf", 100000), 0)
        self.assertEqual(book.dropped_count(), 0)


class ReplayTest(unittest.TestCase):
    def test_same_event_sequence_replays_identically(self):
        ops = [
            ("g", "p", "wolf", "e1", 60, 0),
            ("g", "p", "wolf", "e2", 60, 0),
            ("g", "p", "wolf", "e1", 60, 1000),
            ("g", "p", "wolf", "e3", 60, 6000),
            ("q", "p", "wolf", None, None, 6000),
            ("g", "p", "wolf", "e4", 30, 6000),
        ]

        def run():
            book = Budget(cap=100, window_ms=5000)
            results = []
            for op in ops:
                if op[0] == "g":
                    results.append(book.grant(op[1], op[2], op[3], op[4], op[5]))
                else:
                    results.append((
                        book.pending(op[1], op[2], op[5]),
                        book.granted(op[1], op[2], op[5]),
                    ))
            results.append(book.dropped_count())
            results.append(book.scanned_count())
            return results

        self.assertEqual(run(), run())


class QueryCostTest(unittest.TestCase):
    def test_scanned_does_not_grow_with_total_records(self):
        book = Budget(cap=1_000_000, window_ms=1000)
        for index in range(3000):
            book.grant("p", "wolf", "e-%d" % index, 1, index)
        for _ in range(3000):
            book.pending("p", "wolf", 3000)
        # 旧实现全扫：3000 * 3000 = 9_000_000；摊还回收只可能触及现存记录。
        self.assertLessEqual(book.scanned_count(), 3000)

    def test_query_on_empty_key_is_constant_cost(self):
        book = Budget(cap=100, window_ms=1000)
        for _ in range(1000):
            book.pending("p", "wolf", 0)
            book.granted("p", "wolf", 0)
        self.assertEqual(book.scanned_count(), 0)


class ReferenceBudget:
    """朴素参考实现：全量表 + 每次全扫，严格按 README 口径。"""

    def __init__(self, cap, window_ms):
        self.cap = cap
        self.window_ms = window_ms
        self.records = []
        self.seen = set()
        self.dropped = 0

    def grant(self, player, source, event_id, amount, now_ms):
        if event_id in self.seen:
            return 0
        self.seen.add(event_id)
        total = self.granted(player, source, now_ms)
        actual = min(amount, self.cap - total)
        if actual < 0:
            actual = 0
        self.dropped += amount - actual
        if actual > 0:
            self.records.append((player, source, event_id, actual, now_ms))
        return actual

    def _live(self, player, source, now_ms):
        cutoff = now_ms - self.window_ms
        return [
            record
            for record in self.records
            if record[0] == player
            and record[1] == source
            and record[4] > cutoff
            and record[4] <= now_ms
        ]

    def pending(self, player, source, now_ms):
        return len(self._live(player, source, now_ms))

    def granted(self, player, source, now_ms):
        return sum(record[3] for record in self._live(player, source, now_ms))


class DifferentialTest(unittest.TestCase):
    def test_matches_reference_across_200_random_sequences(self):
        for trial in range(200):
            rng = random.Random(1000 + trial)
            cap = rng.choice([100, 500, 1000])
            window_ms = rng.choice([100, 1000, 5000])
            book = Budget(cap=cap, window_ms=window_ms)
            ref = ReferenceBudget(cap=cap, window_ms=window_ms)

            players = ["p%d" % i for i in range(rng.randint(2, 4))]
            sources = ["wolf", "boar", "boss"][: rng.randint(1, 3)]
            keys = [(p, s) for p in players for s in sources]
            event_ids = ["ev-%d" % i for i in range(60)]
            now_ms = 0

            for _ in range(150):
                now_ms += rng.randint(0, 300)
                key = rng.choice(keys)
                if rng.random() < 0.2:
                    pending = book.pending(key[0], key[1], now_ms)
                    granted = book.granted(key[0], key[1], now_ms)
                    self.assertEqual(pending, ref.pending(key[0], key[1], now_ms))
                    self.assertEqual(granted, ref.granted(key[0], key[1], now_ms))
                    continue
                event_id = rng.choice(event_ids)
                amount = rng.randint(0, 150)
                expected = ref.grant(key[0], key[1], event_id, amount, now_ms)
                actual = book.grant(key[0], key[1], event_id, amount, now_ms)
                self.assertEqual(actual, expected)
                self.assertEqual(book.dropped_count(), ref.dropped)

            for key in keys:
                self.assertEqual(
                    book.pending(key[0], key[1], now_ms),
                    ref.pending(key[0], key[1], now_ms),
                )
                self.assertEqual(
                    book.granted(key[0], key[1], now_ms),
                    ref.granted(key[0], key[1], now_ms),
                )
                # 窗口彻底滑出后两本账都应清空且额度释放。
                far = now_ms + window_ms + 1
                self.assertEqual(book.pending(key[0], key[1], far), 0)
                self.assertEqual(book.granted(key[0], key[1], far), 0)
            self.assertEqual(book.dropped_count(), ref.dropped)


class ScaleTest(unittest.TestCase):
    def test_two_million_records_amortized_constant_query_cost(self):
        total = 2_000_000
        book = Budget(cap=1_000_000_000, window_ms=1000)
        started = time.perf_counter()
        now_ms = 0
        for index in range(total):
            now_ms += index % 2
            book.grant("p", "wolf", index, 1, now_ms)
        elapsed = time.perf_counter() - started
        # 每秒 10 万次发放的门槛：200 万次应在 20 秒内完成。
        self.assertLess(elapsed, 20.0)

        for _ in range(10_000):
            book.pending("p", "wolf", now_ms)
        # 旧实现会扫 total * 10_000 = 2*10^10；摊还回收最多触及插入总量。
        self.assertLessEqual(book.scanned_count(), total)
        self.assertEqual(book.granted("p", "wolf", now_ms + 1001), 0)
        self.assertEqual(book.pending("p", "wolf", now_ms + 1001), 0)
        self.assertLessEqual(book.scanned_count(), total)


if __name__ == "__main__":
    unittest.main()
