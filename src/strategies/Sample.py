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

# sample strategy
class Sample(Bot):
    def __init__(self): 
        # set time frame here       
        Bot.__init__(self, ['15m'])
        # initiate variables
        self.isLongEntry = []
        self.isShortEntry = []
        
    def options(self):
        return {}
    
    # override this bot class function to setup warmup candlestick data - needed for your indicators to calculate from sufficient lenght of candlestick historical data
    # in our case here we have our longest source requirement length 18(sma2) so 100 is more than enough
    def ohlcv_len(self):
        return 100

    def strategy(self, action, open, close, high, low, volume):    
        # this is your strategy function
        # use action argument for mutli timeframe implementation, since a timeframe string will be passed as `action`        
        # get lot or set your own value which will be used to size orders 
        # don't forget to round properly - Binance Futures and FTX should round automatically now, so you dont need to pass `round_decimals` argument or leave it None
        # careful default lot is about 20x your account size !!!
        # its always best log the values prior going live!
        lot = round(self.exchange.get_lot() / 20, 3)

        # Example of a callback function, which we can utilize for order execution etc.
        def entry_callback(avg_price=close[-1]):
            long = True if self.exchange.get_position_size() > 0 else False
            logger.info(f"{'Long' if long else 'Short'} Entry Order Successful")

        # if you are using minute granularity or multiple timeframes its important to use `action` as its going pass a timeframe string
        # this way you can separate functionality and use proper ohlcv timeframe data that get passed each time
        if action == '1m':
            #if you use minute_granularity you can make use of 1m timeframe for various operations
            pass
        if action == '15m':
            # indicator lengths
            fast_len = self.input('fast_len', int, 6)
            slow_len = self.input('slow_len', int, 18)

            # setting indicators, they usually take source and length as arguments
            sma1 = sma(close, fast_len)
            sma2 = sma(close, slow_len)

            # entry conditions
            long_entry_condition = crossover(sma1, sma2)
            short_entry_condition = crossunder(sma1, sma2)

            # setting a simple stop loss and profit target in % using built-in simple profit take and stop loss implementation 
            # which is placing the sl and tp automatically after entering a position
            self.exchange.sltp(profit_long=1.25, profit_short=1.25, stop_long=1, stop_short=1.1, round_decimals=0)

            # example of calculation of stop loss price 0.8% round on 2 decimals hardcoded inside this class
            # sl_long = round(close[-1] - close[-1]*0.8/100, 2)
            # sl_short = round(close[-1] - close[-1]*0.8/100, 2)
            
            # order execution logic
            if long_entry_condition:
                # entry - True means long for every other order other than entry use self.exchange.order() function
                self.exchange.entry("Long", True, lot, callback=entry_callback)
                # stop loss hardcoded inside this class
                #self.exchange.order("SLLong", False, lot/20, stop=sl_long, reduce_only=True, when=False)
                
            if short_entry_condition:
                # entry - False means short for every other order other than entry use self.exchange.order() function
                self.exchange.entry("Short", False, lot, callback=entry_callback)
                # stop loss hardcoded inside this class
                # self.exchange.order("SLShort", True, lot/20, stop=sl_short, reduce_only=True, when=False)
            
            # storing history for entry signals, you can store any variable this way to keep historical values
            self.isLongEntry.append(long_entry_condition)
            self.isShortEntry.append(short_entry_condition)

            # OHLCV and indicator data, you can access history using list index        
            # log indicator values 
            logger.info(f"sma1: {sma1[-1]}")
            logger.info(f"second last sma2: {sma2[-2]}")
            # log last candle OHLCV values
            logger.info(f"open: {open[-1]}")
            logger.info(f"high: {high[-1]}")
            logger.info(f"low: {low[-1]}")
            logger.info(f"close: {close[-1]}")
            logger.info(f"volume: {volume[-1]}")            
            # log history entry signals
            #logger.info(f"long entry signal history list: {self.isLongEntry}")
            #logger.info(f"short entry signal history list: {self.isShortEntry}")  
            #logger.info(f"timestamp: {self.exchange.timestamp}")
