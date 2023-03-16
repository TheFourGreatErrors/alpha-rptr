# coding: UTF-8

import os
import time
import math
from datetime import timedelta, datetime, timezone
import dateutil.parser

import pandas as pd

from src import (logger, allowed_range,
                 allowed_range_minute_granularity,
                 retry, delta, load_data,
                 resample, symlink,
                 find_timeframe_string)
from src.exchange_config import exchange_config
from src.exchange.bybit.bybit_stub import BybitStub

OHLC_DIRNAME = os.path.join(os.path.dirname(__file__), "../ohlc/{}/{}/{}")
OHLC_FILENAME = os.path.join(os.path.dirname(__file__), "../ohlc/{}/{}/{}/data.csv")


class BybitBackTest(BybitStub):   
    # Update Data before Backtest
    update_data = True
    # Minute granularity
    minute_granularity = False
    # Check candles
    check_candles_flag = True
    # Number of days to download and test historical data 
    days = 66
    # Enable log output
    enable_trade_log = True
    # Start balance
    start_balance = 0
    # Warmup timeframe - used for loading warmup candles for indicators when minute granularity is need
    warmup_tf = None # highest tf, if None its going to find it automatically based on highest tf and ohlcv_len

    def __init__(self, account, pair):
        """
        constructor
        :account:
        :pair:
        :param periods:
        """
        BybitStub.__init__(self, account, pair=pair, threading=False)
        # Pair
        self.pair = pair
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

        for k,v in exchange_config['bybit'].items():
            if k in dir(BybitBackTest):
                logger.info(f"{k}")
                setattr(self, k, v)

    def get_market_price(self):
        """
        get market price
        :return:
        """
        return self.market_price

    def now_time(self):
        """
        current time
        :return:
        """
        return self.time    
    
    def entry(
            self,
            id,
            long,
            qty,
            limit=0,
            stop=0,
            post_only=False,
            when=True,
            round_decimals=None,
            callback=None,
            workingType="CONTRACT_PRICE"
            ):
        """
        places an entry order, works equivalent to tradingview pine script implementation
        https://jp.tradingview.com/study-script-reference/#fun_strategy{dot}entry
        :param id: Order id
        :param long: Long or Short
        :param qty: Quantity
        :param limit: Limit price
        :param stop: Stop limit
        :param post_only: Post only        
        :param when: Do you want to execute the order or not - True for live trading
        :round_decimals: Round qty to decimals
        :callback
        :return:
        """
        BybitStub.entry(self, id, long, qty, limit, stop,
                         post_only, when, round_decimals, callback)

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
        Commit
        :param id: order
        :param long: long or short
        :param qty: quantity
        :param price: price
        :param need_commission: use commision or not?
        :param callback
        """
        BybitStub.commit(
            self,
            id,
            long,
            qty,
            price,
            need_commission,
            callback,
            reduce_only
            )

        if long:
            self.buy_signals.append(self.index)
        else:
            self.sell_signals.append(self.index)

    def close_all(self, callback=None):
        """
        Close all positions
        """
        if self.get_position_size() == 0:
            return 
        BybitStub.close_all(self, callback)
        self.close_signals.append(self.index)
    
    def close_all_at_price(self, price, callback=None):
        """
        close the current position at price, for backtesting purposes its important to have a function that closes at given price
        :param price: price
        """
        if self.get_position_size() == 0:
            return 
        BybitStub.close_all_at_price(self, price, callback)
        self.close_signals.append(self.index)        

    def __crawler_run(self):
        """
        Get the data and execute the strategy.
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
            self.balance_history.append((self.get_balance() - self.start_balance))#/100000000*self.get_market_price())
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
                    self.OHLC = {
                                'open': open,
                                'high': high,
                                'low': low,
                                'close': close
                                }
            
                    self.index = index
                    self.balance_history.append((self.get_balance() - self.start_balance)) #/ 100000000 * self.get_market_price())    

                #self.eval_sltp()
                self.timestamp = tf_ohlcv_data.iloc[-1].name.isoformat().replace("T"," ")
                self.strategy(t, open, close, high, low, volume)      
                self.timeframe_info[t]['last_action_index'] += 1           

                #self.balance_history.append((self.get_balance() - self.start_balance)) #/ 100000000 * self.get_market_price())
                #self.eval_exit()
                #self.eval_sltp()

        self.close_all()
        logger.info(f"Back test time : {time.time() - start}")    

    def on_update(self, bin_size, strategy):
        """
        Register the strategy function.
        :param strategy:
        """
        self.__load_ohlcv(bin_size)

        BybitStub.on_update(self, bin_size, strategy)
        self.__crawler_run()
    
    def security(self, bin_size, data=None):
        """
        Recalculate and obtain data of a timeframe higher than the current chart timeframe without looking into the furute that would cause undesired effects.
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
        Check for missing candles
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

        if not os.path.exists(os.path.dirname(file)):
            os.makedirs(os.path.dirname(file))

        data.to_csv(file, index_label="time")
    
    def download_data(self, bin_size, start_time, end_time):
        """
        download or get amd return ohlcv data
        """ 
        data = pd.DataFrame()        
        left_time = None
        source = None
        is_last_fetch = False            

        if self.minute_granularity == True:            
            bin_size = '1m' 
        else:
            bin_size = bin_size[0]        

        while True:
            if left_time is None:
                left_time = start_time 
                right_time = left_time + delta(allowed_range[bin_size][0]) * 99
            else:
                left_time = source.iloc[-1].name #+ delta(allowed_range[bin_size][0]) * allowed_range[bin_size][2]
                right_time = left_time + delta(allowed_range[bin_size][0]) * 99

            if right_time > end_time:
                right_time = end_time
                is_last_fetch = True    

            source = self.fetch_ohlcv(bin_size=bin_size, start_time=left_time, end_time=right_time)      
            
            # if(data.shape[0]):
            #     logger.info(f"Last: {data.iloc[-1].name} Left: {left_time} Start: {source.iloc[0].name} Right: {right_time} End: {source.iloc[-1].name}")         
     
            data = pd.concat([data, source])

            if is_last_fetch:
                return data

            time.sleep(0.25)

    def __load_ohlcv(self, bin_size):
        """
        Read the data.
        :return:
        """
        start_time = datetime.now(timezone.utc) - 1 * timedelta(days=self.days)
        end_time = datetime.now(timezone.utc)
        file = OHLC_FILENAME.format("bybit", self.pair, bin_size)
        
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
        Display results
        """
        DATA_FILENAME = OHLC_FILENAME.format("bybit", self.pair, self.bin_size)
        symlink(DATA_FILENAME, 'html/data/data.csv', overwrite=True)
        ORDERS_FILENAME = os.path.join(os.getcwd(), "./orders.csv")
        symlink(ORDERS_FILENAME, 'html/data/orders.csv', overwrite=True)
        
        logger.info(f"============== Result ================")
        logger.info(f"TRADE COUNT         : {self.order_count}")
        logger.info(f"BALANCE             : {self.get_balance()}")
        logger.info(f"PROFIT RATE         : {self.get_balance()/self.start_balance*100} %")
        logger.info(f"WIN RATE            : {0 if self.order_count == 0 else self.win_count/(self.win_count + self.lose_count)*100} %")
        logger.info(f"PROFIT FACTOR       : {self.win_profit if self.lose_loss == 0 else self.win_profit/self.lose_loss}")
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
                plt.plot(self.df_ohlcv.index, self.df_ohlcv[k], color)
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
                plt.plot(self.df_ohlcv.index, self.df_ohlcv[k], color)
                plt.ylabel(f"{k}")
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
        """
        self.df_ohlcv.at[self.index, name] = value
        if name not in self.plot_data:
            self.plot_data[name] = {'color': color, 'overlay': overlay}