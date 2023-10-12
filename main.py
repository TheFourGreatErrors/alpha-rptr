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
    
    parser.add_argument('--plot', action='store_true')
    parser.add_argument('--no-plot', dest='plot', action='store_false')
    parser.set_defaults(plot=True)

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
