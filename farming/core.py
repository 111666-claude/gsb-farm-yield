"""刷怪收益预算：同一玩家同一来源在滑动窗口内的收益有上限，超出的丢弃。

实现口径（与 README 一致）：
- 滑动窗口：只统计 (now - window_ms, now] 内的记录，落在边界上的算过期。
- 额度：按（玩家, 来源）分桶累计窗口内发放额，超过 cap 的部分丢弃并计入 dropped。
- 幂等：event_id 全局去重，重复事件返回 0，不占额度也不计丢弃。
- 回收：每个桶用双端队列按时间升序存记录，操作时从队首摊还回收过期记录，
  单次操作摊还 O(1)，查询代价不随历史总量线性增长。
"""

from collections import deque

CAP = 100
WINDOW_MS = 60000


class _Ledger:
    """同一（玩家, 来源）的台账：按时间升序的 (发放时间, 发放额) 队列与窗口内总额。"""

    __slots__ = ("records", "total")

    def __init__(self):
        self.records = deque()
        self.total = 0


class Budget:
    """刷怪收益台账。"""

    def __init__(self, cap=CAP, window_ms=WINDOW_MS):
        self.cap = cap
        self.window_ms = window_ms
        self._ledgers = {}
        self._seen = set()
        self.dropped = 0
        self.scanned = 0

    def _evict(self, ledger, now_ms):
        """回收窗口外的记录：时间 <= now_ms - window_ms 的算过期。"""
        cutoff = now_ms - self.window_ms
        records = ledger.records
        while records and records[0][0] <= cutoff:
            self.scanned += 1
            ledger.total -= records.popleft()[1]

    def grant(self, player, source, event_id, amount, now_ms):
        """发放收益，返回实际发放额；重复 event_id 返回 0，超额部分丢弃。"""
        if event_id in self._seen:
            return 0
        self._seen.add(event_id)
        key = (player, source)
        ledger = self._ledgers.get(key)
        if ledger is None:
            ledger = self._ledgers[key] = _Ledger()
        self._evict(ledger, now_ms)
        granted = min(amount, self.cap - ledger.total)
        if granted < 0:
            granted = 0
        if granted:
            ledger.records.append((now_ms, granted))
            ledger.total += granted
        self.dropped += amount - granted
        return granted

    def pending(self, player, source, now_ms):
        """窗口内的记录数。"""
        ledger = self._ledgers.get((player, source))
        if ledger is None:
            return 0
        self._evict(ledger, now_ms)
        return len(ledger.records)

    def granted(self, player, source, now_ms):
        """窗口内已发放总额。"""
        ledger = self._ledgers.get((player, source))
        if ledger is None:
            return 0
        self._evict(ledger, now_ms)
        return ledger.total

    def dropped_count(self):
        return self.dropped

    def scanned_count(self):
        return self.scanned
