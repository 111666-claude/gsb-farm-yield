"""命令行入口：跑刷怪收益预算样例。"""

import argparse

from .core import Budget


def build_parser():
    parser = argparse.ArgumentParser(prog="farm-yield", description="刷怪收益预算")
    parser.add_argument("--sample", default="window", help="window / scope / dup / old / scan")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.sample == "window":
        book = Budget(cap=100, window_ms=5000)
        book.grant("p", "wolf", "e1", 100, 0)
        print("second=%d" % book.grant("p", "wolf", "e2", 100, 10000))
    elif args.sample == "scope":
        book = Budget(cap=100, window_ms=60000)
        book.grant("a", "wolf", "e1", 100, 0)
        print("second=%d" % book.grant("b", "wolf", "e2", 100, 0))
    elif args.sample == "dup":
        book = Budget(cap=100, window_ms=60000)
        book.grant("p", "wolf", "e1", 50, 0)
        print("second=%d" % book.grant("p", "wolf", "e1", 50, 0))
    elif args.sample == "old":
        book = Budget(cap=1000000, window_ms=1000)
        for index in range(3000):
            book.grant("p", "wolf", "e-%d" % index, 1, index)
        print("pending=%d" % book.pending("p", "wolf", 100000))
    elif args.sample == "scan":
        book = Budget(cap=1000000, window_ms=1000)
        for index in range(3000):
            book.grant("p", "wolf", "e-%d" % index, 1, index)
        for _ in range(3000):
            book.pending("p", "wolf", 3000)
        print("scanned=%d" % book.scanned_count())
    else:
        raise SystemExit("需要 --sample window|scope|dup|old|scan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
