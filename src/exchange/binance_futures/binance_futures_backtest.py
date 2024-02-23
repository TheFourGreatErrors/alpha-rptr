# coding: UTF-8

import os
import time
import math
from datetime import timedelta, datetime, timezone
import dateutil.parser
import random

import numpy as np
import pandas as pd

from src import (logger, allowed_range,
                 allowed_range_minute_granularity, 
                 retry, delta, load_data, resample, symlink,
                 find_timeframe_string, sync_obj_with_config)
from src.indicators import sharpe_ratio
from src.exchange_config import exchange_config
from src.exchange.backtest import BackTest
from src.exchange.binance_futures.binance_futures_stub import BinanceFuturesStub


class BinanceFuturesBackTest(BackTest, BinanceFuturesStub):   
    # Update Data before Backtest
    update_data = True
    # Minute granularity
    minute_granularity = False
    # Check candles
    check_candles_flag = True
    # Number of days to download and test historical data 
    days = 120
    # Search for the oldest historical data
    search_oldest = 10 # Search for the oldest historical data, integer for increments in days, False or 0 to turn it off
    # Enable log output
    enable_trade_log = True
    # Start balance
    start_balance = 0
    # Warmup timeframe - used for loading warmup candles for indicators when minute granularity is need
    warmup_tf = None # highest tf, if None its going to find it automatically based on highest tf and ohlcv_len

    def __init__(self, account, pair):
        """
        Constructor for BinanceFuturesBackTest class.
        Args:
            account (str): The account to use for the backtest.
            pair (str): The trading pair to backtest.
        """        
        # Call the constructor of the BinanceFuturesStub parent class to initialize the instance.  
        BinanceFuturesStub.__init__(self, account, pair=pair, threading=False)        
        # Call the constructor of the BackTest parent class to initialize the instance. 
        BackTest.__init__(self)
        
        # Pair
        self.pair = pair

        sync_obj_with_config(exchange_config['binance_f'], BinanceFuturesBackTest, self)       

    def on_update(self, bin_size, strategy):
        """
        Register the strategy function.
        Args:
            bin_size (str): The bin size for the OHLCV data.
            strategy (function): The strategy function to be executed during the backtest.
        """   
        self.bin_size = bin_size
        self.set_paths('binance_futures', pair=self.pair, bin_size=self.bin_size)  
        self.load_ohlcv(bin_size)

        BinanceFuturesStub.on_update(self, bin_size, strategy)
        BackTest.crawler_run(self)
    
    def download_data(self, bin_size, start_time, end_time):
        """
        Download or get the data and set variables related to OHLCV data.
        Args:
            bin_size (str): The bin size for the OHLCV data.
            start_time (datetime): The start time for downloading data.
            end_time (datetime): The end time for downloading data.
        Returns:
            pd.DataFrame: The downloaded OHLCV data.
        """
        data = pd.DataFrame()        
        left_time = None
        source = None
        is_last_fetch = False                  
        file = self.OHLC_FILENAME #OHLC_FILENAME.format("binance_futures", self.pair, self.bin_size)
        search_left = self.search_oldest           

        if self.minute_granularity == True:
            #self.timeframe = bin_size.add('1m')  # add 1m timeframe to the set (sets wont allow duplicates) in case we need minute granularity 
            bin_size = '1m'                                  
        else:
            bin_size = bin_size[0]                                

        while True:
            try:
                if left_time is None:
                    left_time = start_time
                    right_time = left_time + delta(allowed_range[bin_size][0]) * 99
                else:
                    left_time = source.iloc[-1].name #+ delta(allowed_range[bin_size][0]) * allowed_range[bin_size][2]
                    right_time = left_time + delta(allowed_range[bin_size][0]) * 99

                if right_time > end_time:
                    right_time = end_time
                    is_last_fetch = True
            
            except IndexError as e:                
                time.sleep(0.25)
                start_time = start_time + timedelta(days=self.search_oldest if self.search_oldest else 1)
                left_time = None
                logger.info(f"Failed to fetch data, start stime is too far in history. \n"
                            f"                               >>>  Searching, please wait. <<<\n"
                            f"Searching for oldest viable historical data, next start time attempt: {start_time}")
                continue

            source = self.fetch_ohlcv(bin_size=bin_size, start_time=left_time, end_time=right_time)       

            # if search_left and not os.path.exists(file):
            #     time.sleep(0.35)                
            #     logger.info(f"Searching for older historical data. \n"
            #                 f"                               >>>  Searching, please wait. <<<")                
            #     start_time = start_time - timedelta(days=self.search_oldest)
            #     left_time = None
                
            #     if len(source) == 0:
            #         search_left = False
            #     continue
            
            # if(data.shape[0]):
            #     logger.info(f"Last: {data.iloc[-1].name} Left: {left_time} Start: {source.iloc[0].name} Right: {right_time} End: {source.iloc[-1].name}")         
     
            data = pd.concat([data, source])   

            if is_last_fetch:
                return data

            time.sleep(0.25)