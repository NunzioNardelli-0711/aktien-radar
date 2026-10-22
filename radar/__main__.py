"""Aufruf: python -m radar scan | daily | weekly | test-alert | selfcheck
                          | daytrade [--max-minutes N] | daytrade-once | congress | smoke"""
import argparse
import sys

from . import jobs


def main() -> int:
    p = argparse.ArgumentParser(prog="radar")
    p.add_argument("command", choices=["scan", "daily", "weekly", "test-alert", "selfcheck",
                                       "daytrade", "daytrade-once", "congress", "smoke"])
    p.add_argument("--push", action="store_true", help="bei selfcheck Probleme per Push melden")
    p.add_argument("--max-minutes", type=float, default=330,
                   help="daytrade: Laufzeit-Grenze in Minuten (danach übernimmt der nächste Lauf)")
    args = p.parse_args()

    if args.command == "test-alert":
        return 0 if jobs.test_alert() else 1
    if args.command == "selfcheck":
        return 1 if jobs.selfcheck(push=args.push) else 0
    if args.command == "smoke":
        from . import smoke
        return smoke.main()
    if args.command in ("daytrade", "daytrade-once"):
        from . import daytrade
        net = daytrade.YahooNet()
        if args.command == "daytrade-once":
            jobs.run_guarded("daytrade", daytrade.cycle, net, daytrade.utcnow())
        else:
            print(daytrade.session(net, max_minutes=args.max_minutes))
        return 0
    if args.command == "congress":
        from . import congress
        jobs.run_guarded("congress", congress.run)
        return 0

    from .provider import YahooProvider
    provider = YahooProvider()
    fn = {"scan": jobs.scan, "daily": jobs.daily, "weekly": jobs.weekly}[args.command]
    jobs.run_guarded(args.command, fn, provider)
    return 0


if __name__ == "__main__":
    sys.exit(main())
