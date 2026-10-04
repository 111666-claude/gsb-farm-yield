"""刷怪收益预算：同一玩家同一来源在滑动窗口内的收益有上限，超出的丢弃。

口径（与 README 一致）：
- 滑动窗口：只统计 [now - window_ms, now) 内的发放记录，正好落在窗口边界的算过期。
- 额度：同一（玩家, 来源）在窗口内累计发放不超过 cap，放不下的部分丢弃并计入
  dropped，grant 返回实际发放额。
- 幂等：同一个 event_id 只结算一次，重复调用返回 0，不占额度也不计丢弃。
- 回收：窗口外的记录必须回收，pending 与 granted 只反映窗口内的记录。
- 规模：200 万条记录、每秒 10 万次发放，单次摊还 O(1)，scanned_count 不随记录
  总数线性增长。

实现：按（玩家, 来源）分账，每本账用 deque 按时间序保存 (now_ms, amount) 并维护
窗口内总额；事件流时间戳非递减（刷怪事件按发生顺序到达），过期记录只可能堆积在
队首，逐条弹出即摊还 O(1)。event_id 去重集合全局唯一、永久保留，重复事件在窗口
外重放也不会二次结算。
"""

from collections import deque

CAP = 100
WINDOW_MS = 60000


class Budget:
    """刷怪收益台账。"""

    def __init__(self, cap=CAP, window_ms=WINDOW_MS):
        self.cap = cap
        self.window_ms = window_ms
        # (player, source) -> [deque[(now_ms, amount)], 窗口内总额]
        self._ledgers = {}
        self._seen_events = set()
        self.dropped = 0
        self.scanned = 0

    def _evict_expired(self, ledger, now_ms):
        """弹出窗口外（含正好落在边界上）的记录并扣减总额，返回回收条数。"""
        entries = ledger[0]
        cutoff = now_ms - self.window_ms
        evicted = 0
        evicted_sum = 0
        while entries and entries[0][0] <= cutoff:
            evicted_sum += entries[0][1]
            entries.popleft()
            evicted += 1
        if evicted:
            ledger[1] -= evicted_sum
        return evicted

    def grant(self, player, source, event_id, amount, now_ms):
        """发放收益，返回实际发放额；重复 event_id 返回 0，超额部分丢弃。"""
        if event_id in self._seen_events:
            return 0
        self._seen_events.add(event_id)
        key = (player, source)
        ledger = self._ledgers.get(key)
        if ledger is None:
            ledger = self._ledgers[key] = [deque(), 0]
        self._evict_expired(ledger, now_ms)
        remaining = self.cap - ledger[1]
        actual = amount if amount < remaining else remaining
        if actual <= 0:
            self.dropped += amount
            return 0
        entries = ledger[0]
        entries.append((now_ms, actual))
        ledger[1] += actual
        self.dropped += amount - actual
        return actual

    def pending(self, player, source, now_ms):
        """窗口内的记录数；查询顺带摊还回收过期记录并计入 scanned。"""
        ledger = self._ledgers.get((player, source))
        if ledger is None:
            return 0
        self.scanned += self._evict_expired(ledger, now_ms)
        return len(ledger[0])

    def granted(self, player, source, now_ms):
        """窗口内已发放总额；查询顺带摊还回收过期记录并计入 scanned。"""
        ledger = self._ledgers.get((player, source))
        if ledger is None:
            return 0
        self.scanned += self._evict_expired(ledger, now_ms)
        return ledger[1]

    def dropped_count(self):
        return self.dropped

    def scanned_count(self):
        return self.scanned
