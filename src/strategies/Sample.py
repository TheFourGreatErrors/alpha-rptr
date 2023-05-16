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
                            double_ema, ema, triple_ema, wma, ewma, ssma, hull, 
                            supertrend, Supertrend, rsx, donchian, hurst_exponent,
                            lyapunov_exponent)
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
    
    # Override this bot class function to set the length of historical candlestick data required for your indicators
    # In our case, the longest indicator we use requires 18(sma2) historical candle data values, so 100 is more than enough
    def ohlcv_len(self):
        return 100

    def strategy(self, action, open, close, high, low, volume):    
        # this is your strategy function
        # use action argument for mutli timeframe implementation, since a timeframe string will be passed as `action`        
        
        # Determine the lot size for your orders
        # You can set your own value or use your account balance, e.g. lot = self.exchange.get_balance()
        # Default lot is about 20 times your account size, so use with caution!
        lot = self.exchange.get_lot()
     
        # Example of a callback function, which can be used for order execution
        # For example, this function will log a message when a long or short entry order is successfully executed
        def entry_callback(avg_price=close[-1]):
            long = True if self.exchange.get_position_size() > 0 else False
            logger.info(f"{'Long' if long else 'Short'} Entry Order Successful")

        # if you are using minute granularity or multiple timeframes
        # its important to use `action` its going pass a timeframe string
        # This way, you can separate different operations and OHLCV timeframe data that gets passed each time
        if action == '1m':            
            # Perform operations on 1-minute timeframe data (if minute_granularity is used)            
            pass
        if action == '15m':
            # indicator lengths
            fast_len = self.input('fast_len', int, 6)
            slow_len = self.input('slow_len', int, 18)

            # Calculate the indicators using the OHLCV data and indicator lengths as arguments
            sma1 = sma(close, fast_len)
            sma2 = sma(close, slow_len)

            # Define the entry conditions for long and short positions
            long_entry_condition = crossover(sma1, sma2)
            short_entry_condition = crossunder(sma1, sma2)

            # Set a simple stop loss and profit target as percentages of entry price
            # Use the built-in `sltp` method to automatically place the stop loss and profit target after entering a position         
            self.exchange.sltp(profit_long=1.25, profit_short=1.25, stop_long=1, stop_short=1.1)
            
            # Execute orders based on entry conditions
            if long_entry_condition:
                # Enter a long position with the specified
                # lot, size and a callback function to be executed upon order execution
                # for non entry orders consider self.exchange.order() function
                self.exchange.entry("Long", True, lot, callback=entry_callback)                       
                
            if short_entry_condition:
                # Enter a short position with the specified 
                # lot, size and a callback function to be executed upon order execution
                # for non entry orders consider self.exchange.order() function
                self.exchange.entry("Short", False, lot, callback=entry_callback) 
            
           # Store historical entry signals, you can store any variable this way to keep historical values
            self.isLongEntry.append(long_entry_condition)
            self.isShortEntry.append(short_entry_condition)   