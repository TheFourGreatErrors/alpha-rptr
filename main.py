#!/usr/bin/env python
# coding: UTF-8

import argparse
import signal
import time

from src.factory import BotFactory
from src.config import config as conf

if __name__ == "__main__":
    # Parse command line arguments.
    parser = argparse.ArgumentParser(description="This is trading script for cryptocurrency trading")
    parser.add_argument("--test", default=False, action="store_true", help="Run in backtest mode.")
    parser.add_argument("--stub", default=False, action="store_true", help="Run paper trading mode.")
    parser.add_argument("--demo", default=False, action="store_true", help="Use demo account.")
    parser.add_argument("--hyperopt", default=False, action="store_true", help="Use hyperopt strategy.")
    parser.add_argument("--spot", default=False, action="store_true", help="Trade spot market.")
    parser.add_argument("--account", type=str, default="binanceaccount1", help="Account name.")
    parser.add_argument("--exchange", type=str, default="binance", help="Exchange name.")
    parser.add_argument("--pair", type=str, default="BTCUSDT", help="Trading pair.")
    parser.add_argument("--strategy", type=str, default="Doten", help="Trading strategy.")
    parser.add_argument("--session", type=str, default=None, help="Session ID.")
    parser.add_argument("--profile", type=str, default=None, help="Configuration profile name.")

    parser.add_argument("--from", type=str, dest="from_date", default="epoch", help="Start Backtest from this UTC date[time] (yyyy-mm-dd[T00:00:00]) if possible.")
    parser.add_argument("--to", type=str, dest="to_date", default="now", help="End Backtest at this UTC date[time] (yyyy-mm-dd[T00:00:00]) if possible.")

    parser.add_argument("--order-log", type=str, dest="order_log", default="orders.csv", help="File to store order data.")
    
    parser.add_argument('--check-candles', dest="check_candles", action='store_true', help="Check candles before backtest")
    parser.add_argument('--dont-check-candles', dest='check_candles', action='store_false', help="Don't check candles before backtest")
    parser.set_defaults(check_candles=None)

    parser.add_argument('--update-ohlcv', dest="update_ohlcv", action='store_true', help="Update OHLCV before backtest")
    parser.add_argument('--dont-update-ohlcv', dest='update_ohlcv', action='store_false', help="Don't update OHLCV before backtest")
    parser.set_defaults(update_ohlcv=None)

    parser.add_argument('--plot', action='store_true')
    parser.add_argument('--no-plot', dest='plot', action='store_false', help="Do not show plot after backtest")
    parser.set_defaults(plot=True)

    parser.add_argument('--html-report', dest='html_report', action='store_true')
    parser.add_argument('--no-html-report', dest='html_report', action='store_false', help="Do not add this backtest to HTML Workbench")
    parser.set_defaults(html_report=True)

    parser.add_argument("--exchange-info", type=str, dest="exchange_info", default="fetch", help="Fetch <fetch> (default) or use cached <cached> exchange info.")

    parser.add_argument("--leverage", type=int, dest="leverage", help="Set the leverage on this trading account.")

    args = parser.parse_args()

    if args.profile and args.profile in conf["args_profile"]:
        # Merge profile values with command line argument values.
        for k,v in conf["args_profile"][args.profile].items():
            if k not in vars(args):
                setattr(args, k, v)

    conf["args"] = args

    # create the bot instance
    bot = BotFactory.create(args)
    # run the instance
    bot.run()

    if not args.test:
        # register stopping
        def term(signum, frame):
            bot.stop()
        signal.signal(signal.SIGINT, term)
        while True:
            time.sleep(1)
