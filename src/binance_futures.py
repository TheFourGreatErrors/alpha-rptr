# coding: UTF-8

import json
import math
import os
import traceback
from datetime import datetime, timezone
import time
#import threading

import pandas as pd
from bravado.exception import HTTPNotFound
from pytz import UTC

from src import logger, allowed_range, to_data_frame, \
    resample, delta, FatalError, notify, ord_suffix
from src import retry_binance_futures as retry
from src.config import config as conf

from src.binance_futures_api import Client
from src.binance_futures_websocket import BinanceFuturesWs


# Class for production transaction
from src.orderbook import OrderBook


class BinanceFutures:
    # Account
    account = ''
    # Pair
    pair = 'BTCUSDT'
    # wallet
    wallet = None
    # Price
    market_price = 0
    # Order update
    order_update = None
    # Position
    position = None
    # Position size
    position_size = None
    # Entry price
    entry_price = None
    # Margin
    margin = None
    # Account information
    account_information = None
    # Time Frame
    bin_size = '1h'   
    # Binance futures client
    client = None
    # Is bot running
    is_running = True
    # Bar crawler
    crawler = None
    # Strategy
    strategy = None
    # Enable log output
    enable_trade_log = True
    # OHLCV length
    ohlcv_len = 100
    # OHLCV data
    data = None    
    # Profit target long and short for a simple limit exit strategy
    sltp_values = {
                    'profit_long': 0,
                    'profit_short': 0,
                    'stop_long': 0,
                    'stop_short': 0
                    }        
    # Round decimals
    round_decimals = 2
    # Profit, Loss and Trail Offset
    exit_order = {'profit': 0, 'loss': 0, 'trail_offset': 0}
    # Trailing Stop
    trail_price = 0
    # Last strategy execution time
    last_action_time = None
    # best bid price
    best_bid_price = None
    # best ask price
    best_ask_price = None 

    def __init__(self, account, pair, demo=False, threading=True):
        """
        constructor
        :account:
        :pair:
        :param demo:
        :param run:
        """
        self.account = account
        self.pair = pair
        self.demo = demo
        self.is_running = threading
        
    def __init_client(self):
        """
        initialization of client
        """
        if self.client is not None:
            return        
        api_key = conf['binance_keys'][self.account]['API_KEY']        
        api_secret = conf['binance_keys'][self.account]['SECRET_KEY']
        
        self.client = Client(api_key=api_key, api_secret=api_secret)
        
    def now_time(self):
        """
        current time
        """
        return datetime.now().astimezone(UTC)
        
    def get_retain_rate(self):
        """
        maintenance margin
        :return:
        """
        return 0.8

    def lot_leverage(self):
        """
        get leverage for lot calculation
        :return:  
        """         
        return 20

    def get_lot(self, round_decimals=3):
        """        
        lot calculation
        :param round_decimals: round decimals
        :return:
        """
        account_information = self.get_account_information()        
        return round(float(account_information['totalMarginBalance']) / self.get_market_price() * self.lot_leverage(), round_decimals)    

    def get_balance(self):
        """
        get balance
        :return:
        """
        self.__init_client()
        return float(self.get_margin()[0]["balance"])

    def get_margin(self):
        """
        get margin        
        :return:
        """
        self.__init_client()
        if self.margin is not None:
            return self.margin
        else:  # when the WebSocket cant get it
            self.margin = retry(lambda: self.client
                                .futures_account_balance_v2())            
            return self.margin       

    def get_leverage(self):
        """
        get leverage
        :return:
        """
        self.__init_client()
        return float(self.get_position()["leverage"])

    def get_account_information(self):
        """
        get account information about all types of margin balances, assets and positions
        https://binance-docs.github.io/apidocs/futures/en/#account-information-v2-user_data
        """
        self.account_information = retry(lambda: self.client
                                .futures_account_v2())
        return self.account_information

    def get_position(self):
        """
        get current position
        :return:
        """
        self.__init_client()

        #Unfortunately we cannot rely just on the WebSocket updates (for instance PnL) since binance is not pushing updates for the ACCOUNT_UPDATE stream often enough
        #read more here https://binance-docs.github.io/apidocs/futures/en/#event-balance-and-position-update

        # if self.position is not None:

        #     return self.position[0]
        # else:  # when the WebSocket cant get it

        ret = retry(lambda: self.client
                              .futures_position_information())
        if len(ret) > 0:
            self.position = [p for p in ret if p["symbol"].startswith(self.pair)]            
            return self.position[0]
        else: return None

    def get_position_size(self):
        """
        get current position size。
        :return:
        """
        self.__init_client()
        if self.position_size is not None: #and self.position_size == 0:
            return  self.position_size

        position = self.get_position()        
        
        if position['symbol'] == self.pair:            
            return float(position['positionAmt'])
        else: return 0

        

    def get_position_avg_price(self):
        """
        get average price of the current position
        :return:
        """
        self.__init_client()
        return float(self.get_position()['entryPrice'])

    def get_market_price(self):
        """
        get current price
        :return:
        """
        self.__init_client()
        if self.market_price != 0:
            return self.market_price
        else:  # when the WebSocket cant get it
            self.market_price = retry(lambda: self.client
                                      .futures_symbol_ticker(symbol=self.pair))
            return float(self.market_price['price'])
        
    def get_trail_price(self):
        """
        Trail Price
        :return:
        """
        return self.trail_price

    def set_trail_price(self, value):
        """
        set Trail Price
        :return:
        """
        self.trail_price = value

    def get_commission(self):
        """
        get commission
        :return:
        """
        return 0.04 / 100

    def cancel_all(self):
        """
        cancel all orders
        """
        self.__init_client()
        res = retry(lambda: self.client.futures_cancel_all_open_orders(symbol=self.pair))
        #for order in orders:
        logger.info(f"Cancel all open orders: {res}")    

    def close_all(self):
        """
        market close opened position for this pair
        """
        self.__init_client()
        position_size = self.get_position_size()
        if position_size == 0:
            return

        side = False if position_size > 0 else True
        
        self.order("Close", side, abs(position_size))
        position_size = self.get_position_size()
        if position_size == 0:
            logger.info(f"Closed {self.pair} position")
        else:
            logger.info(f"Failed to close all {self.pair} position, still {position_size} amount remaining")


    def cancel(self, id):
        """
        cancel a specific order by id
        :param id: id of the order
        :return: result
        """
        self.__init_client()
        order = self.get_open_order(id)

        if order is None:
            return False

        try:
            retry(lambda: self.client.futures_cancel_order(symbol=self.pair, origClientOrderId=order['clientOrderId']))
        except HTTPNotFound:
            return False
        logger.info(f"Cancel Order : (clientOrderId, type, side, quantity, price, stop) = "
                    f"({order['clientOrderId']}, {order['type']}, {order['side']}, {order['origQty']}, "
                    f"{order['price']}, {order['stopPrice']})")
        return True

    def __new_order(self, ord_id, side, ord_qty, limit=0, stop=0, post_only=False, reduce_only=False, trailing_stop=0, activationPrice=0):
        """
        create an order
        """
        if  trailing_stop > 0 and activationPrice > 0:
            ord_type = "TRAILING_STOP_MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, activationPrice=activationPrice,
                                                              callbackRate=trailing_stop))
        elif trailing_stop > 0:
            ord_type = "TRAILING_STOP_MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, callbackRate=trailing_stop))
        elif limit > 0 and post_only:
            ord_type = "LIMIT"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, price=limit,
                                                              timeInForce="GTX"))
        elif limit > 0 and stop > 0 and reduce_only:
            ord_type = "STOP"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, price=limit,
                                                              stopPrice=stop, reduceOnly="true"))
        elif limit > 0 and reduce_only:
            ord_type = "LIMIT"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, price=limit,
                                                              reduceOnly="true", timeInForce="GTC"))
        elif limit > 0 and stop > 0:
            ord_type = "STOP"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, price=limit,
                                                              stopPrice=stop))
        elif limit > 0:   
            ord_type = "LIMIT"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, price=limit, timeInForce="GTC"))
        elif stop > 0 and reduce_only:
            ord_type = "STOP_MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, stopPrice=stop,
                                                              reduceOnly="true"))        
        elif stop > 0:
            ord_type = "STOP"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, stopPrice=stop))        
        elif post_only: # limit order with post only
            ord_type = "LIMIT"
            i = 0            
            while True:                 
                prices = self.get_orderbook_ticker()
                limit = float(prices['bidPrice']) if side == "Buy" else float(prices['askPrice'])                
                retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                                  side=side, quantity=ord_qty, price=limit,
                                                                  timeInForce="GTX"))
                time.sleep(4)

                self.cancel(ord_id)

                if float(self.get_position()['positionAmt']) > 0:
                    break
                i += 1
                if i > 10:
                    notify(f"Order retry count exceed")                    
                    break
                    
            self.cancel_all()
        else:
            ord_type = "MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty))

        if self.enable_trade_log:
            logger.info(f"========= New Order ==============")
            logger.info(f"ID     : {ord_id}")
            logger.info(f"Type   : {ord_type}")
            logger.info(f"Side   : {side}")
            logger.info(f"Qty    : {ord_qty}")
            logger.info(f"Limit  : {limit}")
            logger.info(f"Stop   : {stop}")
            logger.info(f"======================================")

            notify(f"New Order\nType: {ord_type}\nSide: {side}\nQty: {ord_qty}\nLimit: {limit}\nStop: {stop}")

    # def __amend_order(self, ord_id, side, ord_qty, limit=0, stop=0, post_only=False):
    #     """
    #    amend order
    #     """
    # todo, unfortunately binance ecosystem doesnt provide us with amend order functionality so we have to implement our own mechanism 

    #     if self.enable_trade_log:
    #         logger.info(f"========= Amend Order ==============")
    #         logger.info(f"ID     : {ord_id}")
    #         logger.info(f"Type   : {ord_type}")
    #         logger.info(f"Side   : {side}")
    #         logger.info(f"Qty    : {ord_qty}")
    #         logger.info(f"Limit  : {limit}")
    #         logger.info(f"Stop   : {stop}")
    #         logger.info(f"======================================")

    #         notify(f"Amend Order\nType: {ord_type}\nSide: {side}\nQty: {ord_qty}\nLimit: {limit}\nStop: {stop}")

    def entry(self, id, long, qty, limit=0, stop=0, post_only=False, reduce_only=False, when=True):
        """
        places an entry order, works as equivalent to tradingview pine script implementation
        https://tradingview.com/study-script-reference/#fun_strategy{dot}entry
        :param id: Order id
        :param long: Long or Short
        :param qty: Quantity
        :param limit: Limit price
        :param stop: Stop limit
        :param post_only: Post only
        :param reduce_only: Reduce Only means that your existing position cannot be increased only reduced by this order
        :param when: Do you want to execute the order or not - True for live trading
        :return:
        """
        self.__init_client()

        # if self.get_margin()['excessMargin'] <= 0 or qty <= 0:
        #     return

        if not when:
            return

        pos_size = self.get_position_size()
        logger.info(f"pos_size: {pos_size}")

        if long and pos_size > 0:
            return

        if not long and pos_size < 0:
            return

        ord_qty = qty + abs(pos_size)

        trailing_stop=0
        activationPrice=0

        self.order(id, long, ord_qty, limit, stop, post_only, reduce_only, trailing_stop, activationPrice, when)

    def order(self, id, long, qty, limit=0, stop=0, post_only=False, reduce_only=False, trailing_stop=0, activationPrice=0, when=True):
        """
        places an order, works as equivalent to tradingview pine script implementation
        https://www.tradingview.com/pine-script-reference/#fun_strategy{dot}order
        :param id: Order id
        :param long: Long or Short
        :param qty: Quantity
        :param limit: Limit price
        :param stop: Stop limit
        :param post_only: Post only 
        :param reduce_only: Reduce Only means that your existing position cannot be increased only reduced by this order
        :param trailing_stop: Binance futures built in implementation of trailing stop in %
        :param activationPrice: price that triggers Binance futures built in trailing stop      
        :param when: Do you want to execute the order or not - True for live trading
        :return:
        """
        self.__init_client()

        # if self.get_margin()['excessMargin'] <= 0 or qty <= 0:
        #     return

        if not when:
            return

        side = "BUY" if long else "SELL"
        ord_qty = qty

        order = self.get_open_order(id)
        ord_id = id + ord_suffix() #if order is None else order["clientOrderId"]

        if order is None:
            self.__new_order(ord_id, side, ord_qty, limit, stop, post_only, reduce_only, trailing_stop, activationPrice)
        else:
            self.__new_order(ord_id, side, ord_qty, limit, stop, post_only, reduce_only, trailing_stop, activationPrice)
            #self.__amend_order(ord_id, side, ord_qty, limit, stop, post_only)
            return

    def get_open_order(self, id):
        """
        Get open order by id
        :param id: Order id for this pair
        :return:
        """
        self.__init_client()
        open_orders = retry(lambda: self.client
                            .futures_get_open_orders(symbol=self.pair))                                   
        open_orders = [o for o in open_orders if o["clientOrderId"].startswith(id)]
        if len(open_orders) > 0:
            return open_orders[0]
        else:
            return None
    
    def get_open_orders(self, id):
        """
        Get open orders for this pair by id
        :param id: Order id
        :return:
        """
        self.__init_client()
        open_orders = retry(lambda: self.client
                            .futures_get_open_orders(symbol=self.pair))                                   
        open_orders = [o for o in open_orders if o["clientOrderId"].startswith(id)]
        if len(open_orders) > 0:
            return open_orders
        else:
            return None
    
    def get_all_open_orders(self):
        """
        Get all open orders for this pair
        :param id: Order id
        :return:
        """
        self.__init_client()
        open_orders = retry(lambda: self.client
                            .futures_get_open_orders(symbol=self.pair))        
        if len(open_orders) > 0:
            return open_orders
        else:
            return None

    def get_orderbook_ticker(self):
        orderbook_ticker = retry(lambda: self.client.futures_orderbook_ticker(symbol=self.pair))
        return orderbook_ticker

    def exit(self, profit=0, loss=0, trail_offset=0):
        """
        profit taking and stop loss and trailing, if both stop loss and trailing offset are set trailing_offset takes precedence
        :param profit: Profit (specified in ticks)
        :param loss: Stop loss (specified in ticks)
        :param trail_offset: Trailing stop price (specified in ticks)
        """
        self.exit_order = {'profit': profit, 'loss': loss, 'trail_offset': trail_offset}

    def sltp(self, profit_long=0, profit_short=0, stop_long=0, stop_short=0, round_decimals=2):
        """
        simple profit target triggered upon entering a position
        :param profit_long: profit target value in % for longs
        :param profit_short: profit target value in % for shorts
        :param stop_long: stop loss value for long position in %
        :param stop_short: stop loss value for short position in %
        :param round_decimals: round decimals 
        """
        self.sltp_values = {
                            'profit_long': profit_long/100,
                            'profit_short': profit_short/100,
                            'stop_long': stop_long/100,
                            'stop_short': stop_short/100
                            }        
        self.round_decimals = round_decimals

    def get_exit_order(self):
        """
        get profit take and stop loss and trailing settings
        """
        return self.exit_order

    def get_sltp_values(self):
        """
        get values for the simple profit target/stop loss in %
        """
        return self.sltp_values    

    def eval_exit(self):
        """
        evalution of profit target and stop loss and trailing
        """
        if self.get_position_size() == 0:
            return

        unrealised_pnl = float(self.get_position()['unRealizedProfit'])

        # trail asset
        if self.get_exit_order()['trail_offset'] > 0 and self.get_trail_price() > 0:
            if self.get_position_size() > 0 and \
                    self.get_market_price() - self.get_exit_order()['trail_offset'] < self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all()
            elif self.get_position_size() < 0 and \
                    self.get_market_price() + self.get_exit_order()['trail_offset'] > self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all()

        #stop loss
        if unrealised_pnl < 0 and \
                0 < self.get_exit_order()['loss'] < abs(unrealised_pnl):
            logger.info(f"Loss cut by stop loss: {self.get_exit_order()['loss']}")
            self.close_all()

        # profit take
        if unrealised_pnl > 0 and \
                0 < self.get_exit_order()['profit'] < abs(unrealised_pnl):
            logger.info(f"Take profit by stop profit: {self.get_exit_order()['profit']}")
            self.close_all()

    # simple TP implementation

    def eval_sltp(self):
        """
        evaluate simple profit target and stop loss
        """

        pos_size = float(self.get_position()['positionAmt'])
        if pos_size == 0:
            return
        # tp
        tp_order = self.get_open_order('TP')   
        
        is_tp_full_size = False 
        is_sl_full_size = False        

        if tp_order is not None:
            origQty = float(tp_order['origQty'])
            is_tp_full_size = origQty == pos_size if True else False
            #pos_size =  pos_size - origQty                 
        
        tp_percent_long = self.get_sltp_values()['profit_long']
        tp_percent_short = self.get_sltp_values()['profit_short']   

        avg_entry = self.get_position_avg_price()

        # tp execution logic                
        if tp_percent_long > 0 and is_tp_full_size == False:
            if pos_size > 0:                
                tp_price_long = round(avg_entry +(avg_entry*tp_percent_long), self.round_decimals) 
                if tp_order is not None:
                    time.sleep(2)                                         
                    self.cancel(id=tp_order['clientOrderId'])
                    time.sleep(2)
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True)
                else:               
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True)
        if tp_percent_short > 0 and is_tp_full_size == False:
            if pos_size < 0:                
                tp_price_short = round(avg_entry -(avg_entry*tp_percent_short), self.round_decimals)
                if tp_order is not None:
                    time.sleep(2)                                                        
                    self.cancel(id=tp_order['clientOrderId'])
                    time.sleep(2)
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True)
                else:
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True)
        #sl
        sl_order = self.get_open_order('SL')
        if sl_order is not None:
            origQty = float(sl_order['origQty'])
            is_sl_full_size = origQty == pos_size if True else False
            #pos_size =  pos_size - origQty

        sl_percent_long = self.get_sltp_values()['stop_long']
        sl_percent_short = self.get_sltp_values()['stop_short']

        # sl execution logic
        if sl_percent_long > 0 and is_sl_full_size == False:
            if pos_size > 0:
                sl_price_long = round(avg_entry - (avg_entry*sl_percent_long), self.round_decimals)
                if sl_order is not None:
                    time.sleep(2)                                    
                    self.cancel(id=sl_order['clientOrderId'])
                    time.sleep(2)
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True)
                else:  
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True)
        if sl_percent_short > 0 and is_sl_full_size == False:
            if pos_size < 0:
                sl_price_short = round(avg_entry + (avg_entry*sl_percent_short), self.round_decimals)
                if sl_order is not None: 
                    time.sleep(2)                                         
                    self.cancel(id=sl_order['clientOrderId'])
                    time.sleep(2)
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True) 
                else:  
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True)                         
        
    def fetch_ohlcv(self, bin_size, start_time, end_time):
        """
        fetch OHLCV data
        :param start_time: start time
        :param end_time: end time
        :return:
        """        
        self.__init_client()        
        fetch_bin_size = allowed_range[bin_size][0]
        left_time = start_time
        right_time = end_time
        data = to_data_frame([])

        while True:
            if left_time > right_time:
                break

            left_time_to_timestamp = int(datetime.timestamp(left_time)*1000)
            right_time_to_timestamp = int(datetime.timestamp(right_time)*1000)            

            source = retry(lambda: self.client.futures_klines(symbol=self.pair, interval=fetch_bin_size,
                                                                              startTime=left_time_to_timestamp, endTime=right_time_to_timestamp,
                                                                              limit=500))
            if len(source) == 0:
                break
            
            source_to_object_list =[]
           
            for s in source:   
                timestamp_to_datetime_str = datetime.fromtimestamp(s[6]/1000).strftime('%Y-%m-%dT%H:%M:%S')                           
                source_to_object_list.append({
                        "timestamp" : datetime.strptime(timestamp_to_datetime_str,'%Y-%m-%dT%H:%M:%S'),
                        "high" : float(s[2]),
                        "low" : float(s[3]),
                        "open" : float(s[1]),
                        "close" : float(s[4]),
                        "volume" : float(s[5])
                    })
                                   
            source = to_data_frame(source_to_object_list)

            data = pd.concat([data, source])
                       
            if right_time > source.iloc[-1].name + delta(fetch_bin_size):
                left_time = source.iloc[-1].name + delta(fetch_bin_size)
                time.sleep(2)                
            else:                
                break
        
        return resample(data, bin_size)        

    def security(self, bin_size):
        """
        Recalculate and obtain different time frame data
        """        
        return resample(self.data, bin_size)[:-1]

    def __update_ohlcv(self, action, new_data):
        """
        get OHLCV data and execute the strategy
        """        
        if self.data is None:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - self.ohlcv_len * delta(self.bin_size)
            #logger.info(f"start time fetch ohlcv: {start_time}")
            #logger.info(f"end time fetch ohlcv: {end_time}")
            d1 = self.fetch_ohlcv(self.bin_size, start_time, end_time)
            if len(d1) > 0:
                d2 = self.fetch_ohlcv(allowed_range[self.bin_size][0],
                                      d1.iloc[-1].name + delta(allowed_range[self.bin_size][0]), end_time)

                self.data = pd.concat([d1, d2])                
            else:
                self.data = d1
                
        else:
            self.data = pd.concat([self.data, new_data])            

        # exclude current candle data 
        re_sample_data = resample(self.data, self.bin_size)[:-1]
       
        if self.data.iloc[-1].name == re_sample_data.iloc[-1].name:
            self.data = re_sample_data.iloc[-1 * self.ohlcv_len:, :]

        if self.last_action_time is not None and \
                self.last_action_time == re_sample_data.iloc[-1].name:
            return

        open = re_sample_data['open'].values
        close = re_sample_data['close'].values
        high = re_sample_data['high'].values
        low = re_sample_data['low'].values
        volume = re_sample_data['volume'].values        

        try:
            if self.strategy is not None:                
                self.strategy(open, close, high, low, volume)                
            self.last_action_time = re_sample_data.iloc[-1].name
        except FatalError as e:
            # Fatal error
            logger.error(f"Fatal error. {e}")
            logger.error(traceback.format_exc())

            notify(f"Fatal error occurred. Stopping Bot. {e}")
            notify(traceback.format_exc())
            self.stop()
        except Exception as e:
            logger.error(f"An error occurred. {e}")
            logger.error(traceback.format_exc())

            notify(f"An error occurred. {e}")
            notify(traceback.format_exc())
   
    def __on_update_instrument(self, action, instrument):
        """
        Update instrument price
        """
        if 'c' in instrument:
            self.market_price = float(instrument['c'])            

            position_size = self.position_size

            if position_size == None:
                #position_size = self.get_position_size()
                return
            if position_size == 0:
                return  
            
            # trail price update
            if self.position_size > 0 and \
                    self.market_price > self.get_trail_price():
                self.set_trail_price(self.market_price)
            if self.position_size < 0 and \
                    self.market_price < self.get_trail_price():
                self.set_trail_price(self.market_price)

            # PnL calculation in %
            self.percent_PnL = (self.market_price - self.entry_price) * 100 / self.entry_price           

    def __on_update_wallet(self, action, wallet):
        """
        update wallet
        """
        self.wallet = wallet #{**self.wallet, **wallet} if self.wallet is not None else self.wallet        
    
    def __on_update_order(self, action, order):
        """
        Update order status
        https://binance-docs.github.io/apidocs/futures/en/#event-order-update
        """
        self.order_update = order
        # Evaluation of profit and loss
        self.eval_exit()
        #self.eval_sltp()
        
    def __on_update_position(self, action, position):
        """
        Update position
        """    

        if len(position) > 0:
            position = [p for p in position if p["s"].startswith(self.pair)]            
            
        # Was the position size changed?
        is_update_pos_size = self.get_position_size != float(position[0]['pa'])        

        # Reset trail to current price if position size changes
        if is_update_pos_size and float(position[0]['pa']) != 0:
            self.set_trail_price(self.market_price)
        
        if is_update_pos_size:
            logger.info(f"Updated Position\n"
                        f"Price: {self.position[0]['entryPrice']} => {position[0]['ep']}\n"
                        f"Qty: {self.position[0]['positionAmt']} => {position[0]['pa']}\n"
                        f"Balance: {self.get_balance()} USDT")
            notify(f"Updated Position\n"
                   f"Price: {self.position[0]['entryPrice']} => {position[0]['ep']}\n"
                   f"Qty: {self.position[0]['positionAmt']} => {position[0]['pa']}\n"
                   f"Balance: {self.get_balance()} USDT")
       
        self.position[0] = {
                            "entryPrice": position[0]['ep'],
                            "marginType": position[0]['mt'],                            
                            "positionAmt":  position[0]['pa'], 
                            "symbol": position[0]['s'], 
                            "unRealizedProfit":  position[0]['up'], 
                            "positionSide": position[0]['ps'],
                            } if self.position is not None else self.position

        self.position_size = float(self.position[0]['positionAmt'])
        self.entry_price = float(self.position[0]['entryPrice'])        
    
        # Evaluation of profit and loss
        self.eval_exit()
        self.eval_sltp()

    def __on_update_margin(self, action, margin):
        """
         Update margin 
        """
        if self.margin is not None:
            self.margin[0] = {
                              "balance": float(margin['wb']),
                              "crossWalletBalance": float(margin['cw'])
                             }             
        else: self.get_margin()       

    def __on_update_bookticker(self, action, bookticker):
        """
        best bid and best ask price 
        """
        self.best_bid_price = float(bookticker['b'])
        self.best_ask_price = float(bookticker['a'])        

    def on_update(self, bin_size, strategy):
        """
        Register the strategy function
        bind functions with webosocket data streams        
        :param strategy:
        """        
        logger.info(f"pair: {self.pair}")
        self.bin_size = bin_size
        self.strategy = strategy
        if self.is_running:
            self.ws = BinanceFuturesWs(account=self.account, pair=self.pair, test=self.demo)
            self.ws.bind(allowed_range[bin_size][0], self.__update_ohlcv)
            self.ws.bind('instrument', self.__on_update_instrument)
            self.ws.bind('wallet', self.__on_update_wallet)
            self.ws.bind('position', self.__on_update_position)
            self.ws.bind('order', self.__on_update_order)
            self.ws.bind('margin', self.__on_update_margin)
            self.ws.bind('IndividualSymbolBookTickerStreams', self.__on_update_bookticker)
            #todo orderbook
            #self.ob = OrderBook(self.ws)
        logger.info(f" on_update(self, bin_size, strategy)")

    def stop(self):
        """
        Stop the crawler
        """
        self.is_running = False
        self.ws.close()

    def show_result(self):
        """
        Show results
        """
        pass

    def plot(self, name, value, color, overlay=True):
        """
        Draw the graph
        """
        pass
