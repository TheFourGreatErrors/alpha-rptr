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
    parser.add_argument("--account", default="binanceaccount1",   required=True)
    parser.add_argument("--exchange", default="binance",   required=True)
    parser.add_argument("--pair", default="BTCUSDT",   required=False)
    parser.add_argument("--strategy", default="doten", required=True)
    args = parser.parse_args()
    conf["args"] = args

    # create the bot instance
    bot = BotFactory.create(args)
    # run the instance
    bot.run()

    if not args.test:
        # register stopping
        signal.signal(signal.SIGINT, lambda x, y: bot.stop())
        while True:
            time.sleep(1)
