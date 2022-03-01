# coding: UTF-8
import os
import random

import math
import re
import time

import numpy
from hyperopt import hp

from src import logger, notify
from src.indicators import highest, lowest, med_price, avg_price, typ_price, atr, MAX, sma, bbands, macd, adx, sar, cci, rsi, crossover, crossunder, \
    last, rci, double_ema, ema, triple_ema, wma, ssma, hull, supertrend, rsx, donchian
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


# SMA CrossOver with Callbacks
class SMA(Bot):
    def __init__(self):
        Bot.__init__(self, ['2h'])

    def options(self):
        return {
            'fast_len': hp.quniform('fast_len', 1, 30, 1),
            'slow_len': hp.quniform('slow_len', 1, 30, 1),
        }

    def strategy(self, action, open, close, high, low, volume):
        lot = self.exchange.get_lot()
        fast_len = self.input('fast_len', int, 9)
        slow_len = self.input('slow_len', int, 16)
        fast_sma = sma(close, fast_len)
        slow_sma = sma(close, slow_len)
        golden_cross = crossover(fast_sma, slow_sma)
        dead_cross = crossunder(fast_sma, slow_sma)

        def entry_callback(avg_price=close[-1]):
            long = True if self.exchange.get_position_size() > 0 else False
            logger.info(f"{'Long' if long else 'Short'} Entry Order Successful")

        if golden_cross:
            self.exchange.entry("Long", True, lot, \
                round_decimals=3, callback=entry_callback)
        if dead_cross:
            self.exchange.entry("Short", False, lot, \
                round_decimals=3, callback=entry_callback)


# Rci
class Rci(Bot):
    def __init__(self):
        Bot.__init__(self, ['5m'])

    def options(self):
        return {
            'rcv_short_len': hp.quniform('rcv_short_len', 1, 10, 1),
            'rcv_medium_len': hp.quniform('rcv_medium_len', 5, 15, 1),
            'rcv_long_len': hp.quniform('rcv_long_len', 10, 20, 1),
        }

    def strategy(self, action, open, close, high, low, volume):
        lot = self.exchange.get_lot()

        itv_s = self.input('rcv_short_len', int, 5)
        itv_m = self.input('rcv_medium_len', int, 9)
        itv_l = self.input('rcv_long_len', int, 15)

        rci_s = rci(close, itv_s)
        rci_m = rci(close, itv_m)
        rci_l = rci(close, itv_l)

        long = ((-80 > rci_s[-1] > rci_s[-2]) or (-82 > rci_m[-1] > rci_m[-2])) \
               and (rci_l[-1] < -10 and rci_l[-2] > rci_l[-2])
        short = ((80 < rci_s[-1] < rci_s[-2]) or (rci_m[-1] < -82 and rci_m[-1] < rci_m[-2])) \
                and (10 < rci_l[-1] < rci_l[-2])
        close_all = 80 < rci_m[-1] < rci_m[-2] or -80 > rci_m[-1] > rci_m[-2]

        if long:
            self.exchange.entry("Long", True, lot)
        elif short:
            self.exchange.entry("Short", False, lot)
        elif close_all:
            self.exchange.close_all()


# OCC
class OCC(Bot):
    variants = [sma, ema, double_ema, triple_ema, wma, ssma, hull]
    eval_time = None

    def __init__(self):
        Bot.__init__(self, ['1m'])

    def ohlcv_len(self):
        return 15 * 30

    def options(self):
        return {
            'variant_type': hp.quniform('variant_type', 0, len(self.variants) - 1, 1),
            'basis_len': hp.quniform('basis_len', 1, 30, 1),
            'resolution': hp.quniform('resolution', 1, 10, 1),
            'sma_len': hp.quniform('sma_len', 1, 15, 1),
            'div_threshold': hp.quniform('div_threshold', 1, 6, 0.1),
        }

    def strategy(self, action, open, close, high, low, volume):
        lot = self.exchange.get_lot()

        variant_type = self.input(defval=5, title="variant_type", type=int)
        basis_len = self.input(defval=19,  title="basis_len", type=int)
        resolution = self.input(defval=2, title="resolution", type=int)
        sma_len = self.input(defval=9, title="sma_len", type=int)
        div_threshold = self.input(defval=3.0, title="div_threshold", type=float)

        source = self.exchange.security(str(resolution) + 'm')

        if self.eval_time is not None and \
                self.eval_time == source.iloc[-1].name:
            return

        series_open = source['open'].values
        series_close = source['close'].values

        variant = self.variants[variant_type]

        val_open = variant(series_open,  basis_len)
        val_close = variant(series_close, basis_len)

        if val_open[-1] > val_close[-1]:
            high_val = val_open[-1]
            low_val = val_close[-1]
        else:
            high_val = val_close[-1]
            low_val = val_open[-1]

        sma_val = sma(close, sma_len)
        logger.info("lagging log")
        self.exchange.plot('val_open', val_open[-1], 'b')
        self.exchange.plot('val_close', val_close[-1], 'r')

        self.exchange.entry("Long", True,   lot, stop=math.floor(low_val), when=(sma_val[-1] < low_val))
        self.exchange.entry("Short", False, lot, stop=math.ceil(high_val), when=(sma_val[-1] > high_val))

        open_close_div = sma(numpy.abs(val_open - val_close), sma_len)

        if open_close_div[-1] > div_threshold and \
                open_close_div[-2] > div_threshold < open_close_div[-2]:
            self.exchange.close_all()

        self.eval_time = source.iloc[-1].name


# TradingView
class TV(Bot):
    subscriber = None

    def __init__(self):
        Bot.__init__(self, ['1m'])

        user_id = os.environ.get("GMAIL_ADDRESS")
        if user_id is None:
            raise Exception("Please set GMAIL_ADDRESS into env to use Trading View Strategy.")
        self.subscriber = GmailSub(user_id)
        self.subscriber.set_from_address('noreply@tradingview.com')

    def __on_message(self, messages):
        for message in messages:
            if 'payload' not in message:
                continue
            if 'headers' not in message['payload']:
                continue
            subject_list = [header['value']
                       for header in message['payload']['headers'] if header['name'] == 'Subject']
            if len(subject_list) == 0:
                continue
            subject = subject_list[0]
            if subject.startswith('TradingViewアラート:'):
                action = subject.replace('TradingViewアラート:', '')
                self.__action(action)

    def __action(self, action):
        lot = self.exchange.get_lot()
        if re.search('buy', action, re.IGNORECASE):
            self.exchange.entry('Long', True, lot)
        elif re.search('sell', action, re.IGNORECASE):
            self.exchange.entry('Short', True, lot)
        elif re.search('exit', action, re.IGNORECASE):
            self.exchange.close_all()

    def run(self):
        if self.hyperopt:
            raise Exception("Trading View Strategy dose not support hyperopt Mode.")
        elif self.back_test:
            raise Exception("Trading View Strategy dose not support backtest Mode.")
        elif self.stub_test:
            # if you want to use binance futures
            # self.exchange = BinanceFuturesStub(account=self.account, pair=self.pair)
            self.exchange = BitMexStub(account=self.account, pair=self.pair)
            logger.info(f"Bot Mode : Stub")
        else:
            # if you want to use binance
            #self.exchange = BinanceFutures(account=self.account, pair=self.pair, demo=self.test_net) 
            self.exchange = BitMex(account=self.account, pair=self.pair, demo=self.test_net)
            logger.info(f"Bot Mode : Trade")

        logger.info(f"Starting Bot")
        logger.info(f"Strategy : {type(self).__name__}")
        logger.info(f"Balance : {self.exchange.get_balance()}")

        notify(f"Starting Bot\n"
               f"Strategy : {type(self).__name__}\n"
               f"Balance : {self.exchange.get_balance()/100000000} XBT")

        self.subscriber.on_message(self.__on_message)

    def stop(self):
        self.subscriber.stop()


# Candle tester
class CandleTester(Bot):
    def __init__(self):
        Bot.__init__(self, ['1m'])


    # this is for parameter optimization in hyperopt mode
    def options(self):
        return {}

    def strategy(self, action, open, close, high, low, volume):
        logger.info(f"open: {open[-1]}")
        logger.info(f"high: {high[-1]}")
        logger.info(f"low: {low[-1]}")
        logger.info(f"close: {close[-1]}")
        logger.info(f"volume: {volume[-1]}")          


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

    def strategy(self, action, open, close, high, low, volume):    
        # this is your strategy function
        # use action argument for mutli timeframe implementation, since a timeframe string will be passed as `action`        
        # get lot or set your own value which will be used to size orders 
        # don't forget to round properly
        # careful default lot is about 20x your account size !!!
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
