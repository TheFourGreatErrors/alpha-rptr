#!/usr/bin/env python
# coding: UTF-8

import argparse
import signal
import time

from src.factory import BotFactory
from src.config import config as conf

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="This is trading script for cryptocurrency trading")
    parser.add_argument("--test",     default=False,   action="store_true")
    parser.add_argument("--stub",     default=False,   action="store_true")
    parser.add_argument("--demo",     default=False,   action="store_true")
    parser.add_argument("--hyperopt", default=False,   action="store_true")
    parser.add_argument("--spot", default=False,   action="store_true")
    parser.add_argument("--account", default="binanceaccount1",   required=True)
    parser.add_argument("--exchange", default="binance",   required=False)
    parser.add_argument("--pair", default="BTCUSDT",   required=False)
    parser.add_argument("--strategy", default="doten", required=False)
    parser.add_argument("--session", default=None, required=False)
    parser.add_argument("--profile", default=None, required=False)
    args = parser.parse_args()

    if args.profile and args.profile in conf["args_profile"]:
        print(conf["args_profile"])
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
