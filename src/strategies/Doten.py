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
                            supertrend, rsx, donchian, hurst_exponent,
                            lyapunov_exponent)
from src.exchange.bitmex.bitmex import BitMex
from src.exchange.binance_futures.binance_futures import BinanceFutures
from src.exchange.bitmex.bitmex_stub import BitMexStub
from src.exchange.binance_futures.binance_futures_stub import BinanceFuturesStub
from src.bot import Bot
from src.gmail_sub import GmailSub


# Channel breakout strategy
class Doten(Bot):
    def __init__(self):
        Bot.__init__(self, ['2h'])

    def options(self):
        return {
            'length': hp.randint('length', 1, 30, 1),
        }

    def strategy(self, action, open, close, high, low, volume):
        if action == '2h':
            lot = self.exchange.get_lot()
            length = self.input('length', int, 9)
            up = last(highest(high, length))
            dn = last(lowest(low, length))
            self.exchange.plot('up', up, 'b')
            self.exchange.plot('dn', dn, 'r')
            self.exchange.entry("Long", True, round(lot / 20), stop=up)
            self.exchange.entry("Short", False, round(lot / 20), stop=dn)
