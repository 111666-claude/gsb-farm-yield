# farm-yield

刷怪收益预算：同一玩家同一来源在滑动窗口内的收益有上限，放不下的丢弃，只用 Python 标准库。

```
python3 -m farming.cli --sample window
python3 -m farming.cli --sample scope
python3 -m farming.cli --sample dup
python3 -m farming.cli --sample old
python3 -m farming.cli --sample scan
python3 -m unittest discover -s tests -v
```

## 口径（README 为准）

- **滑动窗口**：只统计 `[now - window_ms, now)` 内的发放记录，正好等于窗口边界的记录算过期。
- **额度**：同一（玩家, 来源）在窗口内累计发放的收益不超过 `cap`；本次放不下的部分丢弃并计入
  `dropped`，`grant` 返回实际发放额。
- **幂等**：同一个 `event_id` 只结算一次，重复调用返回 0，不占额度也不计丢弃。
- **回收**：窗口外的记录必须回收，`pending` 与 `granted` 只反映窗口内的记录。
- **不变量**：窗口内发放总额不超过 `cap`；同一串事件重复执行结果相同。
- **规模**：200 万条记录、每秒 10 万次发放，单次摊还 O(1)，`scanned_count()` 不随记录总数线性增长。

## 输出契约（不改格式）

```
second=..
pending=..
scanned=..
```

## 目录

```
farming/core.py   滑动窗口、额度截断与幂等
farming/cli.py    命令行入口
tests/            unittest 用例
```
