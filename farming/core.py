"""刷怪收益预算：同一玩家同一来源在滑动窗口内的收益有上限，超出的丢弃。

缺陷：窗口从不滑动、额度按全局历史总额算（不分玩家与来源）、事件不去重、
过期记录不回收、每次查询全扫记录表。
"""

CAP = 100
WINDOW_MS = 60000


class Budget:
    """刷怪收益台账。"""

    def __init__(self, cap=CAP, window_ms=WINDOW_MS):
        self.cap = cap
        self.window_ms = window_ms
        self.records = []
        self.dropped = 0
        self.scanned = 0

    def grant(self, player, source, event_id, amount, now_ms):
        """发放收益，返回实际发放额。缺陷：不去重、额度按全局历史总额算、窗口不滑动。"""
        used = 0
        for record in self.records:
            used += record[3]
        if used >= self.cap:
            return 0
        self.records.append((event_id, player, source, amount, now_ms))
        return amount

    def pending(self, player, source, now_ms):
        """窗口内的记录数。缺陷：过期记录也算、全扫记录表。"""
        self.scanned += len(self.records)
        return len(self.records)

    def granted(self, player, source, now_ms):
        """窗口内已发放总额。缺陷：过期记录也算、全扫记录表。"""
        self.scanned += len(self.records)
        total = 0
        for record in self.records:
            total += record[3]
        return total

    def dropped_count(self):
        return self.dropped

    def scanned_count(self):
        return self.scanned
