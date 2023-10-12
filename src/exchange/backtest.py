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
from src.exchange.stub import Stub
from src.exchange_config import exchange_config
from src.exchange.binance_futures.binance_futures_stub import BinanceFuturesStub


OHLC_DIRNAME = os.path.join(os.path.dirname(__file__), "./ohlc/{}/{}/{}")
OHLC_FILENAME = os.path.join(os.path.dirname(__file__), "./ohlc/{}/{}/{}/data.csv")


class BackTest(Stub):   
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

    def __init__(self):
        """
        Get the current market price.

        Returns:
            float: The current market price.
        """
        Stub.__init__(self)
        # Market price
        self.market_price = 0         
        # Balance
        self.start_balance = self.get_balance()
        # OHLCV
        self.df_ohlcv = None
        # Current time axis
        self.index = None
        # Current time
        self.time = None
        # Order count
        self.order_count = 0
        # Buy signal history
        self.buy_signals = []
        # Sell signal history
        self.sell_signals = []
        # EXIT history
        self.close_signals = []
        # Balance history
        self.balance_history = []        
        # Drawdown history
        self.draw_down_history = []
        # Plot data
        self.plot_data = {}
        # Resample data
        self.resample_data = {}

    def get_market_price(self):
        """
        Get the current market price.

        Returns:
            float: The current market price.
        """
        return self.market_price

    def now_time(self):
        """
        Get the current time.

        Returns:
            datetime: The current time.
        """
        return self.time    
    
    def set_paths(self, exchange, pair=None, bin_size=None):
        """
        Sets the paths for OHLC (Open, High, Low, Close) data directory and filename.
        Args:
            exchange (str): The exchange name.
            pair (str, optional): The trading pair. Defaults to None.
            bin_size (str or list, optional): The bin size. Defaults to None.
        """
        # If bin_size is not provided, use the default bin_size from the class attribute
        bin_size = self.bin_size if not bin_size else bin_size
        
        # If pair is not provided, use the default pair from the class attribute
        pair = self.pair if not pair else pair    
    
        self.OHLC_DIRNAME = OHLC_DIRNAME.format(exchange, pair, bin_size)    
        self.OHLC_FILENAME = OHLC_FILENAME.format(exchange, pair, bin_size)

    def commit(
        self, 
        id, 
        long, 
        qty, 
        price, 
        need_commission=False, 
        callback=None, 
        reduce_only=False        
    ):
        """
        Commit a trade order.

        This function commits a trade order for the trading pair in the stub trading account.
        It updates the position size, average entry price, profit and loss, and other relevant account metrics.

        Args:
            id (str): The order ID.
            long (bool): True if it's a long order, False for a short order.
            qty (float): The order quantity.
            price (float): The price of the order.
            need_commission (bool, optional): True if a commission fee arises. Defaults to False.
            callback (function, optional): A callback function to be executed on order completion (not applicable in backtesting and paper trading).
            reduce_only (bool, optional): True if the order should be reduce-only. Defaults to False.
        """
        Stub.commit(self, id, long, qty, price, 
                                  need_commission, callback, reduce_only)

        if long:
            self.buy_signals.append(self.index)
        else:
            self.sell_signals.append(self.index)

    def close_all(self, post_only=False, callback=None, chaser=False):
        """
        Close all positions.

        This function closes all open positions in the stub trading account.

        Args:
            callback (function, optional): A callback function to be executed on order completion.
            chaser (bool, optional): If True, the orders will be submitted as trailing stop orders (not applicable in backtesting and paper trading).
        """
        if self.get_position_size() == 0:
            return 
        Stub.close_all(self, post_only, callback, chaser=chaser)
        self.close_signals.append(self.index)
    
    def close_all_at_price(self, price, callback=None, chaser=False):
        """
        Close all positions at a given price.

        This function closes all open positions in the stub trading account at a specified price.

        Args:
            price (float): The price at which the positions should be closed.
            callback (function, optional): A callback function to be executed on order completion.
            chaser (bool, optional): If True, the orders will be submitted as trailing stop orders (not applicable in backtesting and paper trading).
        """
        if self.get_position_size() == 0:
            return 
        Stub.close_all_at_price(self, price, callback, chaser=chaser)
        self.close_signals.append(self.index)        

    def crawler_run(self):
        """
        Run the crawler to get data and execute the strategy.

        This function iterates through the historical OHLC data and executes the trading strategy.
        It simulates the trading process for backtesting purposes.
        """      
        self.df_ohlcv = self.df_ohlcv.set_index(self.df_ohlcv.columns[0])       
        self.df_ohlcv.index = pd.to_datetime(self.df_ohlcv.index, errors='coerce')
        
        start = time.time()

        # load and resample warmup data
        self.warmup_len = (allowed_range_minute_granularity[self.warmup_tf][3] * self.ohlcv_len) \
             if self.minute_granularity else self.ohlcv_len           

        if self.timeframe_data is None: 
            self.timeframe_data = {}          
            for t in self.bin_size:            
                self.timeframe_data[t] = resample(self.df_ohlcv, t, minute_granularity=self.minute_granularity) \
                                        if self.minute_granularity else self.df_ohlcv # if a single timeframe is used without minute_granularity
                                                                                      # it already resampled the data after downloading it 
                self.timeframe_info[t] = {
                    "allowed_range": allowed_range_minute_granularity[t][0] if self.minute_granularity else self.bin_size[0], #allowed_range[t][0],
                    "ohlcv": self.timeframe_data[t][:-1], # Dataframe with closed candles,
                    "last_action_index": math.ceil(self.warmup_len / allowed_range_minute_granularity[t][3]) \
                                        if self.minute_granularity else self.warmup_len
                }                     

        #logger.info(f"timeframe info: {self.timeframe_info}")
        for i in range(self.warmup_len):
            self.balance_history.append((self.get_balance() - self.start_balance))
            self.draw_down_history.append(self. max_draw_down_session_perc)

        for i in range(len(self.df_ohlcv) - self.warmup_len):
            self.data = self.df_ohlcv.iloc[i:i + self.warmup_len + 1, :]
            index = self.data.iloc[-1].name
            new_data = self.data.iloc[-1:]              
            
            # action is either the(only) key of self.timeframe_info dictionary, which is a single timeframe string
            # or "1m" when minute granularity is needed - multiple timeframes or self.minute_granularity = True
            action = "1m" if (self.minute_granularity or len(self.timeframe_info) > 1) else self.bin_size[0]
            
            # Timeframes to be updated
            timeframes_to_process = [allowed_range_minute_granularity[t][3] if self.timeframes_sorted != None else 
                                t for t in self.timeframe_info if self.timeframe_info[t]['allowed_range'] == action] 

            # Sorting timeframes that will be updated
            if self.timeframes_sorted == True:
                timeframes_to_process.sort(reverse=True)
            if self.timeframes_sorted == False:
                timeframes_to_process.sort(reverse=False)
            
            # logger.info(f"timefeames to update: {timeframes_to_update}")        

            for t in timeframes_to_process:
                # Find timeframe string based on its minute count value
                if self.timeframes_sorted != None:             
                    t = find_timeframe_string(t)  

                last_action_index = self.timeframe_info[t]["last_action_index"]              
                
                # Append the latest candle if new              
                if self.timeframe_data[t].iloc[last_action_index].name != new_data.iloc[0].name:
                    continue     

                tf_ohlcv_data = self.timeframe_data[t].iloc[last_action_index-self.ohlcv_len : last_action_index+1]
                
                close = tf_ohlcv_data['close'].values
                open = tf_ohlcv_data['open'].values
                high = tf_ohlcv_data['high'].values
                low = tf_ohlcv_data['low'].values
                volume = tf_ohlcv_data['volume'].values

                if (t == "1m" and self.minute_granularity) or self.minute_granularity != True:
                    if self.get_position_size() > 0 and low[-1] > self.get_trail_price():
                        self.set_trail_price(low[-1])
                    if self.get_position_size() < 0 and high[-1] < self.get_trail_price():
                        self.set_trail_price(high[-1])
                    self.market_price = close[-1]
                    self.OHLC = {'open': open,
                                 'high': high,
                                 'low': low,
                                 'close': close}
            
                    self.index = index
                    self.balance_history.append((self.get_balance() - self.start_balance)) 

                #self.eval_sltp()
                self.timestamp = tf_ohlcv_data.iloc[-1].name.isoformat().replace("T"," ")
                self.strategy(t, open, close, high, low, volume)      
                self.timeframe_info[t]['last_action_index'] += 1           

                #self.balance_history.append((self.get_balance() - self.start_balance)) 
                #self.eval_exit()
                #self.eval_sltp()

        self.close_all()
        logger.info(f"Back test time : {time.time() - start}")    

    def security(self, bin_size, data=None):
        """
        Recalculate and obtain data of a timeframe higher than the current timeframe without looking into the future.

        Args:
            bin_size (str): The bin size of the higher timeframe.
            data (pd.DataFrame, optional): The historical OHLC data. Defaults to None.
        
        Returns:
            pd.DataFrame: The recalculated data of the higher timeframe.
        """
        if data == None and bin_size not in self.bin_size:           
            timeframe_list = [allowed_range_minute_granularity[t][3] for t in self.bin_size] # minute count of a timeframe for sorting when sorting is needed 
            timeframe_list.sort(reverse=True)
            t = find_timeframe_string(timeframe_list[-1])   
            data = self.timeframe_data[t]
          
        self.resample_data[bin_size] = resample(data, bin_size)
        return self.resample_data[bin_size][:self.data.iloc[-1].name].iloc[-1 * self.ohlcv_len:, :]
 
    def check_candles(self, df):
        """
        Check for missing candles in the historical OHLC data.

        This function checks for missing candles and duplicate candles in the provided data.

        Args:
            df (pd.DataFrame): The historical OHLC data.

        Returns:
            None
        """
        logger.info("-------")
        logger.info(f"Checking Candles:")
        logger.info("-------")
        logger.info(f"Start: {df.iloc[0][0]}")
        logger.info(f"End: {df.iloc[-1][0]}")
        logger.info("-------")

        diff = (dateutil.parser.isoparse(df.iloc[1][0])-dateutil.parser.isoparse(df.iloc[0][0])).total_seconds()

        logger.info(f"Interval: {diff}s")
        logger.info("-------")

        count = 0
        rows = df.shape[0]
        prev_current_date = None

        for index in range(0, rows-1):
            current_date = dateutil.parser.isoparse(df.iloc[index][0])
            next_date = dateutil.parser.isoparse(df.iloc[index+1][0])

            diff2 = (next_date-current_date).total_seconds()
            if diff2 != diff:
                count += abs((diff2-diff)/diff)
                
                # logger.info(current_date)
                # logger.info(next_date)
                # logger.info(f"Missing Candles: {(diff2-diff)/diff} Total: {count}")

                # if(prev_current_date != None):
                #     logger.info(f"Last Missing Candle Interval: {current_date-prev_current_date}")

                # logger.info("------------")

                prev_current_date = current_date 
            elif diff2 <= 0:
                logger.info(f"Duplicate Candle: {current_date}")

        logger.info(f"Total Missing Candles = {count}")
        logger.info("-------")
    
    def save_csv(self, data, file):
        """
        Save data to a CSV file.

        This function saves the provided data to a CSV file.

        Args:
            data (pd.DataFrame): The data to be saved.
            file (str): The file path where the data should be saved.

        Returns:
            None
        """

        if not os.path.exists(os.path.dirname(file)):
            os.makedirs(os.path.dirname(file))

        data.to_csv(file, index_label="time")

    def load_ohlcv(self, bin_size):
        """
        Load the historical OHLCV data.

        This function loads the historical OHLCV data from a CSV file or API based on the specified bin size.

        Args:
            bin_size (str or list): The bin size or list of bin sizes for the historical data.

        Returns:
            None
        """
       
        start_time = self.get_launch_date() + 1 * timedelta(days=1)
        end_time = datetime.now(timezone.utc)
        file = self.OHLC_FILENAME #OHLC_FILENAME.format("binance_futures", self.pair, bin_size) 
        print(file)
        print(self.bin_size)
        # Force minute granularity if multiple timeframes are used
        if len(bin_size) > 1:
            self.minute_granularity = True   

        if self.minute_granularity and "1m" not in bin_size:
            bin_size.append('1m') # add 1m timeframe to the list in case we need minute granularity    
        
        self.bin_size = bin_size    

        warmup = None # warmup needed for each timeframe in munutes         

        for t in bin_size:               
                if self.warmup_tf == None:
                    warmup = allowed_range_minute_granularity[t][3] 
                    self.warmup_tf = t
                elif warmup < allowed_range_minute_granularity[t][3]:
                    warmup = allowed_range_minute_granularity[t][3] 
                    self.warmup_tf = t
                else: continue       

        if os.path.exists(file):
            self.df_ohlcv = load_data(file)
            self.df_ohlcv.set_index(self.df_ohlcv.columns[0], inplace=True)

            if self.update_data:
                self.df_ohlcv = self.df_ohlcv[:-1] # exclude last candle
                data = self.download_data( bin_size, dateutil.parser.isoparse(self.df_ohlcv.iloc[-1].name), end_time)
                self.df_ohlcv = pd.concat([self.df_ohlcv, data])
                self.save_csv(self.df_ohlcv, file) 
                
            self.df_ohlcv.reset_index(inplace=True)
            self.df_ohlcv = load_data(file)  

        else:
            data = self.download_data(bin_size, start_time, end_time)
            self.save_csv(data, file)
            self.df_ohlcv = load_data(file)

        if self.check_candles_flag:
            self.check_candles(self.df_ohlcv)
			    
    def show_result(self):
        """
        Display the backtesting results.

        This function displays the backtesting results, including trade count, balance, profit rate, win rate,
        profit factor, Sharpe ratio, and max drawdown.

        It also plots the price chart and any additional plot data provided during backtesting.
        """
        DATA_FILENAME = self.OHLC_FILENAME #OHLC_FILENAME.format("binance_futures", self.pair, self.bin_size)
        symlink(DATA_FILENAME, 'html/data/data.csv', overwrite=True)
        ORDERS_FILENAME = os.path.join(os.getcwd(), "./orders.csv")
        symlink(ORDERS_FILENAME, 'html/data/orders.csv', overwrite=True)
        
        logger.info(f"============== Result ================")
        logger.info(f"TRADE COUNT         : {self.order_count}")
        logger.info(f"BALANCE             : {self.get_balance()}")
        logger.info(f"PROFIT RATE         : {self.get_balance()/self.start_balance*100} %")
        logger.info(f"WIN RATE            : {0 if self.order_count == 0 else self.win_count/(self.win_count + self.lose_count)*100} %")
        logger.info(f"PROFIT FACTOR       : {self.win_profit if self.lose_loss == 0 else self.win_profit/self.lose_loss}")
        logger.info(f"SHARPE RATIO        : {sharpe_ratio(self.balance_history, 0)}")
        logger.info(f"MAX DRAW DOWN TOTAL : {round(self.max_draw_down_session, 4)} or {round(self.max_draw_down_session_perc, 2)}%")
        logger.info(f"======================================")

        import matplotlib.pyplot as plt

        plt_num = len([k for k, v in self.plot_data.items() if not v['overlay']]) + 2
        i = 1

        plt.figure(figsize=(12,8))
        plt.suptitle(self.pair + f" - {self.bin_size}", fontsize=12)

        plt.subplot(plt_num,1,i)
        plt.plot(self.df_ohlcv.index, self.df_ohlcv["high"])
        plt.plot(self.df_ohlcv.index, self.df_ohlcv["low"])

        for k, v in self.plot_data.items():
            if v['overlay']:
                color = v['color']
                # Filter columns 
                filtered_columns = [col for col in self.df_ohlcv if col.startswith(k)]               

                if len(filtered_columns) == 1:
                    plt.plot(self.df_ohlcv.index, self.df_ohlcv[k], color, label=k)
                else:          
                    # Iterate over columns if multiple values are needed to plot per sublot          
                    for column in filtered_columns:
                        plt.plot(self.df_ohlcv.index, self.df_ohlcv[column], f'#{random.randint(0, 0xFFFFFF):06x}', label=column)
                plt.legend(fontsize=5)
        plt.ylabel("Price(USD)")
        ymin = min(self.df_ohlcv["low"]) - 0.05
        ymax = max(self.df_ohlcv["high"]) + 0.05
        plt.vlines(self.buy_signals, ymin, ymax, "blue", linestyles='dashed', linewidth=1)
        plt.vlines(self.sell_signals, ymin, ymax, "red", linestyles='dashed', linewidth=1)
        plt.vlines(self.close_signals, ymin, ymax, "green", linestyles='dashed', linewidth=1)

        i = i + 1

        for k, v in self.plot_data.items():
            if not v['overlay']:
                plt.subplot(plt_num,1,i)                                
                color = v['color']

                # Filter columns
                filtered_columns = [col for col in self.df_ohlcv if col.startswith(k)]               

                if len(filtered_columns) == 1:
                    plt.plot(self.df_ohlcv.index, self.df_ohlcv[k], color, label=k)
                else:          
                    # Iterate over columns if multiple values are needed to plot per sublot          
                    for column in filtered_columns:
                        plt.plot(self.df_ohlcv.index, self.df_ohlcv[column], f'#{random.randint(0, 0xFFFFFF):06x}', label=column)

                plt.ylabel(f"{k}")
                plt.legend(fontsize=5)
                i = i + 1

        plt.subplot(plt_num,1,i)
        plt.plot(self.df_ohlcv.index, self.balance_history)
        plt.hlines(y=0, xmin=self.df_ohlcv.index[0],
                   xmax=self.df_ohlcv.index[-1], colors='k', linestyles='dashed')
        plt.ylabel("PL(USD)")        
        plt.show()

    def plot(self, name, value, color, overlay=True):
        """
        Draw the graph
        Args:
            name (str): The name of the graph.
            value (dict, int, float): The data values for the graph. 
                If a dict is provided, each key-value pair represents a column name and its corresponding value.
                If a list or np.ndarray is provided, it represents a single column of values.
            color (str): The color of the graph.
            overlay (bool, optional): Specifies whether to overlay the graph on existing data.
                Defaults to True.
        Returns:
            None
        """        
        try:
            if isinstance(value, dict):
                for k,v in value.items():
                    self.df_ohlcv.at[self.index, name + '_' + k] = v
                            
            elif isinstance(value, (int, float, np.number)): #elif isinstance(value, list) or isinstance(value, np.ndarray):
                self.df_ohlcv.at[self.index, name] = value
            else:
                raise ValueError("Invalid value type. Expected dict, integer, or float.")
        except Exception as e:
            print(f"Error: {e}")    
        
        if name not in self.plot_data:
            self.plot_data[name] = {'color': color, 'overlay': overlay}