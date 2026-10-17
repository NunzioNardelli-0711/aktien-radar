"""Aufruf: python -m radar scan | daily | weekly | test-alert | selfcheck"""
import argparse
import sys

from . import jobs


def main() -> int:
    p = argparse.ArgumentParser(prog="radar")
    p.add_argument("command", choices=["scan", "daily", "weekly", "test-alert", "selfcheck"])
    p.add_argument("--push", action="store_true", help="bei selfcheck Probleme per Push melden")
    args = p.parse_args()

    if args.command == "test-alert":
        return 0 if jobs.test_alert() else 1
    if args.command == "selfcheck":
        return 1 if jobs.selfcheck(push=args.push) else 0

    from .provider import YahooProvider
    provider = YahooProvider()
    fn = {"scan": jobs.scan, "daily": jobs.daily, "weekly": jobs.weekly}[args.command]
    jobs.run_guarded(args.command, fn, provider)
    return 0


if __name__ == "__main__":
    sys.exit(main())
