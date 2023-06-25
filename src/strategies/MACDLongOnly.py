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

# Strategy for ETHUSDT, BTCUSDT and other major pairs
class MACDLongOnly(Bot):

    leverage = 1

    def __init__(self):
        Bot.__init__(self, ['1d'])
        self.supertrend = None

    def ohlcv_len(self):
        return 60

    def entry_position_size(self, balance):
        position = balance*self.leverage/self.exchange.get_market_price()
        return round(position, self.asset_rounding)

    def entry_position_size(self, balance):
        position = balance*self.leverage/self.exchange.get_market_price()
        return round(position, self.asset_rounding)

    def pnl(self, close, avg_entry_price, position_size, commission):

        profit = 0

        if abs(position_size):
            if avg_entry_price > close:
                close_rate = ((avg_entry_price - close) / close - commission)
                profit = round(position_size * close_rate * -close, self.quote_rounding)
            else:
                close_rate = ((close - avg_entry_price) / avg_entry_price - commission)
                profit = round(position_size * close_rate * avg_entry_price, self.quote_rounding)

        return profit

    def liquidation_price(self, position_size, avg_entry_price, balance):

        if position_size >= 0:
            liquidation_price = ((position_size*avg_entry_price*1.012)-balance)/position_size #long
        else:
            liquidation_price = ((position_size*avg_entry_price*0.988)-balance)/position_size #Short

        return round(liquidation_price, self.quote_rounding)

    def strategy(self, action, open, close, high, low, volume):
        self.asset_rounding = self.exchange.asset_rounding
        self.quote_rounding = self.exchange.quote_rounding
        self.exchange.leverage = self.leverage
        balance = self.exchange.get_balance()       

        # ******************** Entry Type, Trade Type, Exit Type and Trigger Input ************************* #
        # -------------------------------------------------------------------------------------------------- #
        trade_side = True # True for long only, False for short only, None trading both       
        # -------------------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------- #  
        # ------- Parameters ------------------------------------------------------------------------------ #
        fast_period = 12
        slow_period = 26
        signal_period = 9
        #//////////////////////////////   MACD      ////////////////////////////////////////////////////      
     
        macd_line, signal_line, histogram = macd(close, fastperiod=fast_period, slowperiod=slow_period, signalperiod=signal_period)

        #///////////////////////////////     Signals      /////////////////////////////////////////////////////

        long = crossover(macd_line, signal_line)
        short = crossunder(macd_line, signal_line)

        #//////////////////////////////     Execution     /////////////////////////////////////////////////////
        
        if long and trade_side != False:             
            self.exchange.entry("Long", True, abs(self.entry_position_size(balance))) 

        if short and trade_side != True:           
            self.exchange.entry("Short", False, abs(self.entry_position_size(balance)))


        #/////////////////////////////     Exit for long only  /////////////////////////////////////////////////
        

        if short and trade_side != False:               
            self.exchange.close_all()

        #/////////////////////////////     Exit for long only  /////////////////////////////////////////////////
        

        if long and trade_side != True:               
            self.exchange.close_all()
       
        #/////////////////////////////      Plot MACD (and other indicotors to showcase)    /////////////////////
        cci1 = cci(high, low, close, 20)
        sma1 = sma(close, 20)
        ewma1 = ewma(close, 0.5)
        hurst = hurst_exponent(close)       
       
        self.exchange.plot('MACD', {"signal_line": signal_line[-1], "macd_line": macd_line[-1], "histogram": histogram[-1]}, 'r', overlay=False)    
        self.exchange.plot('CCI', {"CCI": cci1[-1], "threshold_upper": 100, "threshold_lower": -100}, 'r', overlay=False)      
        self.exchange.plot('hurst', hurst, 'r', False)          
        self.exchange.plot('SMA', sma1[-1], 'r', overlay=True)         
        self.exchange.plot('EWMA', ewma1[-1], 'b', overlay=True)        
        
            