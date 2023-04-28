# coding: UTF-8
import os
import random

import math
import re
import time

import numpy
from hyperopt import hp

from src import logger, notify
from src.indicators import (highest, lowest, med_price, avg_price, typ_price, 
                            atr, MAX, sma, bbands, macd, adx, sar, sarext, 
                            cci, rsi, crossover, crossunder, last, rci, 
                            double_ema, ema, triple_ema, wma, ssma, hull, 
                            supertrend, rsx, donchian)
from src.exchange.bitmex.bitmex import BitMex
from src.exchange.binance_futures.binance_futures import BinanceFutures
from src.exchange.bitmex.bitmex_stub import BitMexStub
from src.exchange.binance_futures.binance_futures_stub import BinanceFuturesStub
from src.bot import Bot
from src.gmail_sub import GmailSub

# Candle tester for multiple timeframes
class CandleTesterMult(Bot):
    def __init__(self):
        Bot.__init__(self, ['5m', '15m', '4h'])

        self.ohlcv = {}

        for i in self.bin_size:
            self.ohlcv[i] = open(f"ohlcv_{i}.csv", "w")
            self.ohlcv[i].write("time,open,high,low,close,volume\n") #header

    # this is for parameter optimization in hyperopt mode
    def options(self):
        return {}

    def strategy(self, action, open, close, high, low, volume):

        if action not in ['5m', '15m', '4h']:
            return

        logger.info(f"---------------------------")
        logger.info(f"Action: {action}")
        logger.info(f"---------------------------")
        logger.info(f"time: {self.exchange.timestamp}")
        logger.info(f"open: {open[-1]}")
        logger.info(f"high: {high[-1]}")
        logger.info(f"low: {low[-1]}")
        logger.info(f"close: {close[-1]}")
        logger.info(f"volume: {volume[-1]}") 
        logger.info(f"---------------------------")
        self.ohlcv[action].write(f"{self.exchange.timestamp},{open[-1]},{high[-1]},{low[-1]},{close[-1]},{volume[-1]}\n")
