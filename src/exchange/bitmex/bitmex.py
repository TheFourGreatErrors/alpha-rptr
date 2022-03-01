# coding: UTF-8

import json
import math
#import os
import traceback
from datetime import datetime, timezone
import time

import pandas as pd
from bravado.exception import HTTPNotFound
from pytz import UTC

from src import logger, retry, allowed_range, allowed_range_minute_granularity, find_timeframe_string, \
    to_data_frame, resample, delta, FatalError, notify, ord_suffix
from src.exchange.bitmex.bitmex_api import bitmex_api
from src.config import config as conf
from src.exchange.bitmex.bitmex_websocket import BitMexWs


# Orderbook class
from src.exchange.bitmex.orderbook import OrderBook


class BitMex:      
    # Use minute granularity?
    minute_granularity = False
    # Sort timeframe execution when multiple timeframes
    timeframes_sorted = True # True for higher first, False for lower first and None when off      
    # Enable log output
    enable_trade_log = True
    # OHLCV length
    ohlcv_len = 100    
    # Round decimals
    round_decimals = 0

    def __init__(self, account, pair, demo=False, threading=True):
        """
        constructor
        :account:
        :pair:
        :param demo:
        :param run:
        """
        # Account
        self.account = account
        # Pair
        self.pair = pair
        # Use testnet?
        self.demo = demo
        # Is bot running
        self.is_running = threading
        # Wallet
        self.wallet = None
         # Price
        self.market_price = 0
        # Order update
        self.order_update = None
        # Position
        self.position = None
        # Margin
        self.margin = None
        # Time Frame
        self.bin_size = ['1h']
        # Client for private API
        self.private_client = None
        # Client for public API
        self.public_client = None
        # Bar crawler
        self.crawler = None
        # Strategy
        self.strategy = None
        # OHLCV data
        self.timeframe_data = None
        # Timeframe data info like partial candle data values, last candle values, last action etc.
        self.timeframe_info = {}
        # Profit target long and short for a simple limit exit strategy
        self.sltp_values = {
                        'profit_long': 0,
                        'profit_short': 0,
                        'stop_long': 0,
                        'stop_short': 0,
                        'eval_tp_next_candle': False,
                        'profit_long_callback': None,
                        'profit_short_callback': None,
                        'stop_long_callback': None,
                        'stop_short_callback': None
                        }         
        # Profit, Loss and Trail Offset
        self.exit_order = {
                        'profit': 0, 
                        'loss': 0, 
                        'trail_offset': 0, 
                        'profit_callback': None,
                        'loss_callback': None,
                        'trail_callbak': None
                        }
        # Trailing Stop
        self.trail_price = 0
        # Order callbacks
        self.callbacks = {}
        # Last strategy execution time
        self.last_action_time = None
        
    def __init_client(self):
        """
        initialization of client
        """
        if self.private_client is not None and self.public_client is not None:
            return
       
        api_key =  conf['bitmex_test_keys'][self.account]['API_KEY'] if self.demo else conf['bitmex_keys'][self.account]['API_KEY']        
        api_secret = conf['bitmex_test_keys'][self.account]['SECRET_KEY'] if self.demo else conf['bitmex_keys'][self.account]['SECRET_KEY']

        self.private_client = bitmex_api(test=self.demo, api_key=api_key, api_secret=api_secret)
        self.public_client = bitmex_api(test=self.demo)
        
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

    def get_lot(self):
        """
        lot calculation
        :return:
        """
        margin = self.get_margin()
        position = self.get_position()
        return math.floor((1 - self.get_retain_rate()) * self.get_market_price()
                          * margin['excessMargin'] / (position['initMarginReq'] * 100000000))        

    def get_balance(self):
        """
        get balance
        :return:
        """
        self.__init_client()
        return self.get_margin()["walletBalance"]

    def get_margin(self):
        """
        get margin
        :return:
        """
        self.__init_client()
        if self.margin is not None:
            return self.margin
        else:  # when the WebSocket cant get it
            self.margin = retry(lambda: self.private_client
                                .User.User_getMargin(currency="XBt").result())
            return self.margin        

    def get_leverage(self):
        """
        get leverage
        :return:
        """
        self.__init_client()
        return self.get_position()["leverage"]

    def get_position(self):
        """
        get the current position
        :return:
        """
        self.__init_client()
        if self.position is not None:
            return self.position
        else:  # when the WebSocket cant get it
            ret = retry(lambda: self.private_client
                                  .Position.Position_get(filter=json.dumps({"symbol": self.pair})).result())
            if len(ret) > 0:
                self.position = ret[0]
            return self.position

    def get_position_size(self):
        """
        get position size
        :return:
        """
        self.__init_client() 
        position_size = self.get_position()
        if position_size is not None:
            return position_size['currentQty']
        else:
            return 0

    def get_position_avg_price(self):
        """
        get average price of the current position
        :return:
        """
        self.__init_client()
        return self.get_position()['avgEntryPrice']

    def get_market_price(self):
        """
        get current price
        :return:
        """
        self.__init_client()
        if self.market_price != 0:
            return self.market_price
        else:  # when the WebSocket cant get it
            self.market_price = retry(lambda: self.public_client
                                      .Instrument.Instrument_get(symbol=self.pair).result())[0]["lastPrice"]
            return self.market_price
        
    def get_trail_price(self):
        """
        get Trail Price。
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
        return 0.075 / 100

    def cancel_all(self):
        """
        market close opened position for this pair
        """
        self.__init_client()
        orders = retry(lambda: self.private_client.Order.Order_cancelAll(symbol=self.pair).result())
        for order in orders:
            logger.info(f"Cancel Order : (orderID, orderType, side, orderQty, limit, stop) = "
                        f"({order['orderID']}, {order['ordType']}, {order['side']}, {order['orderQty']}, "
                        f"{order['price']}, {order['stopPx']})")
        logger.info(f"Cancel All Order")
        self.callbacks = {}

    def close_all(self, callback=None):
        """
        Close all positions for this pair
        """
        self.__init_client()
        order = retry(lambda: self.private_client.Order.Order_closePosition(symbol=self.pair).result())
        self.callbacks[order['orderID']] = callback
        logger.info(f"Close Position : (orderID, orderType, side, orderQty, limit, stop) = "
                    f"({order['orderID']}, {order['ordType']}, {order['side']}, {order['orderQty']}, "
                    f"{order['price']}, {order['stopPx']})")
        logger.info(f"Close All Position")

    def cancel(self, id):
        """
        Cancel a specific order by id
        :param id: id of the order
        :return: result
        """
        self.__init_client()
        order = self.get_open_order(id)
        if order is None:
            return False

        try:
            retry(lambda: self.private_client.Order.Order_cancel(orderID=order['orderID']).result())[0]
        except HTTPNotFound:
            return False
        logger.info(f"Cancel Order : (orderID, orderType, side, orderQty, limit, stop) = "
                    f"({order['orderID']}, {order['ordType']}, {order['side']}, {order['orderQty']}, "
                    f"{order['price']}, {order['stopPx']})")
        self.callbacks.pop(order['orderID'])
        return True

    def __new_order(self, ord_id, side, ord_qty, limit=0, stop=0, post_only=False, reduce_only=False):
        """
        create an order
        """
        logger.info(f"{ord_id} {side} {ord_qty} {stop}")
        if limit > 0 and post_only:
            ord_type = "Limit"
            retry(lambda: self.private_client.Order.Order_new(symbol=self.pair, ordType=ord_type, clOrdID=ord_id,
                                                              side=side, orderQty=ord_qty, price=limit,
                                                              execInst='ParticipateDoNotInitiate').result())
        elif limit > 0 and stop > 0 and reduce_only:
            ord_type = "StopLimit"
            retry(lambda: self.private_client.Order.Order_new(symbol=self.pair, ordType=ord_type, clOrdID=ord_id,
                                                              side=side, orderQty=ord_qty, price=limit,
                                                              stopPx=stop, execInst='LastPrice,Close').result())
        elif limit > 0 and reduce_only:
            ord_type = "Limit"
            retry(lambda: self.private_client.Order.Order_new(symbol=self.pair, ordType=ord_type, clOrdID=ord_id,
                                                              side=side, orderQty=ord_qty, price=limit,
                                                              execInst='ReduceOnly').result())        
        elif limit > 0 and stop > 0:
            ord_type = "StopLimit"
            retry(lambda: self.private_client.Order.Order_new(symbol=self.pair, ordType=ord_type, clOrdID=ord_id,
                                                              side=side, orderQty=ord_qty, price=limit,
                                                              stopPx=stop).result())
        elif limit > 0:
            ord_type = "Limit"
            retry(lambda: self.private_client.Order.Order_new(symbol=self.pair, ordType=ord_type, clOrdID=ord_id,
                                                              side=side, orderQty=ord_qty, price=limit).result())
        elif stop > 0 and reduce_only:
            ord_type = "Stop"
            retry(lambda: self.private_client.Order.Order_new(symbol=self.pair, ordType=ord_type, clOrdID=ord_id,
                                                              side=side, orderQty=ord_qty, stopPx=stop,
                                                              execInst='LastPrice,Close').result())
        elif stop > 0:
            ord_type = "Stop"
            retry(lambda: self.private_client.Order.Order_new(symbol=self.pair, ordType=ord_type, clOrdID=ord_id,
                                                              side=side, orderQty=ord_qty, stopPx=stop).result())
        elif post_only: # limit order with post only loop
            ord_type = "Limit"
            i = 0
            while True:
                prices = self.ob.get_prices()
                limit = prices[0] if side == "Buy" else prices[1]                
                retry(lambda: self.private_client.Order.Order_new(symbol=self.pair, ordType=ord_type, clOrdID=ord_id,
                                                                  side=side, orderQty=ord_qty, price=limit,
                                                                  execInst='ParticipateDoNotInitiate').result())
                time.sleep(1)

                if not self.cancel(ord_id):
                    break
                time.sleep(2)
                i += 1
                if i > 10:
                    notify(f"Order retry count exceed")
                    break
            self.cancel_all()
        else:
            ord_type = "Market"
            retry(lambda: self.private_client.Order.Order_new(symbol=self.pair, ordType=ord_type, clOrdID=ord_id,
                                                              side=side, orderQty=ord_qty).result())

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

    def __amend_order(self, ord_id, side, ord_qty, limit=0, stop=0, post_only=False):
        """
        Amend order
        """
        if limit > 0 and stop > 0:
            ord_type = "StopLimit"
            retry(lambda: self.private_client.Order.Order_amend(origClOrdID=ord_id,
                                                                orderQty=ord_qty, price=limit, stopPx=stop).result())
        elif limit > 0:
            ord_type = "Limit"
            retry(lambda: self.private_client.Order.Order_amend(origClOrdID=ord_id,
                                                                orderQty=ord_qty, price=limit).result())
        elif stop > 0:
            ord_type = "Stop"
            retry(lambda: self.private_client.Order.Order_amend(origClOrdID=ord_id,
                                                                orderQty=ord_qty, stopPx=stop).result())
        elif post_only: # market order with post only
            ord_type = "Limit"
            prices = self.ob.get_prices()
            limit = prices[1] if side == "Buy" else prices[0]
            retry(lambda: self.private_client.Order.Order_amend(origClOrdID=ord_id,
                                                                orderQty=ord_qty, price=limit).result())
        else:
            ord_type = "Market"
            retry(lambda: self.private_client.Order.Order_amend(origClOrdID=ord_id,
                                                                orderQty=ord_qty).result())

        if self.enable_trade_log:
            logger.info(f"========= Amend Order ==============")
            logger.info(f"ID     : {ord_id}")
            logger.info(f"Type   : {ord_type}")
            logger.info(f"Side   : {side}")
            logger.info(f"Qty    : {ord_qty}")
            logger.info(f"Limit  : {limit}")
            logger.info(f"Stop   : {stop}")
            logger.info(f"======================================")

            notify(f"Amend Order\nType: {ord_type}\nSide: {side}\nQty: {ord_qty}\nLimit: {limit}\nStop: {stop}")

    def entry(self, id, long, qty, limit=0, stop=0, post_only=False, reduce_only=False, allow_amend=False, when=True, round_decimals=0, callback=None):
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

        if self.get_margin()['excessMargin'] <= 0 or qty <= 0:
            return
       
        if not when:
            return
       
        pos_size = self.get_position_size()

        if long and pos_size > 0:
            return
            logger.info(f"11")
        if not long and pos_size < 0:
            logger.info(f"11")
            return
        
        ord_qty = qty + abs(pos_size)
        ord_qty = round(ord_qty, round_decimals)

        self.order(id, long, ord_qty, limit, stop, post_only, reduce_only, allow_amend, when, callback)

    def entry_pyramiding(self, id, long, qty, limit=0, stop=0, post_only=False, reduce_only=False, cancel_all=False, pyramiding=2, allow_amend=False, when=True, round_decimals=0, callback=None):
        """
        places an entry order, works as equivalent to tradingview pine script implementation with pyramiding
        https://tradingview.com/study-script-reference/#fun_strategy{dot}entry
        :param id: Order id
        :param long: Long or Short
        :param qty: Quantity
        :param limit: Limit price
        :param stop: Stop limit
        :param post_only: Post only
        :param reduce_only: Reduce Only means that your existing position cannot be increased only reduced by this order
        :param cancell_all: cancell all open order before sending the entry order?
        :param pyramiding: number of entries you want in pyramiding
        :param when: Do you want to execute the order or not - True for live trading
        :return:
        """       

        # if self.get_margin()['excessMargin'] <= 0 or qty <= 0:
        #     return
        if qty <= 0:
            return

        if not when:
            return

        pos_size = self.get_position_size()

        if long and pos_size >= pyramiding*qty:
            return

        if not long and pos_size <= -(pyramiding*qty):
            return
        
        if cancel_all:
            self.cancel_all()   

        if long and pos_size < 0:
            ord_qty = qty + abs(pos_size)
        elif not long and pos_size > 0:
            ord_qty = qty + abs(pos_size)
        else:
            ord_qty = qty  
        
        if long and (pos_size + qty > pyramiding*qty):
            ord_qty = pyramiding*qty - abs(pos_size)

        if not long and (pos_size - qty < -(pyramiding*qty)):
            ord_qty = pyramiding*qty - abs(pos_size)
        # make sure it doesnt spam small entries, which in most cases would trigger risk management orders evaluation, you can make this less than 2% if needed  
        if ord_qty < ((pyramiding*qty) / 100) * 2:
            return       

        ord_qty = round(ord_qty, round_decimals)

        self.order(id, long, ord_qty, limit, stop, post_only, reduce_only, allow_amend, when, callback)

    def order(self, id, long, qty, limit=0, stop=0, post_only=False, reduce_only=False, allow_amend=False, when=True, callback=None):
        """
        places an order, works as equivalent to tradingview pine script implementation
        https://www.tradingview.com/pine-script-reference/#fun_strategy{dot}order
        :param id: Order id
        :param long: Long or Short
        :param qty: Quantity
        :param limit: Limit price
        :param stop: Stop limit
        :param post_only: Post only
        :param reduce only: Reduce Only means that your existing position cannot be increased only reduced by this order by this order
        :param allow_amend: Allow amening existing orders
        :param when: Do you want to execute the order or not - True for live trading
        :return:
        """
        self.__init_client()        
        
        if self.get_margin()['excessMargin'] <= 0 or qty <= 0:            
            return
        
        if not when:
            return
        
        side = "Buy" if long else "Sell"
        ord_qty = qty             

        if allow_amend:
            order = self.get_open_order(id)
            ord_id = id + ord_suffix() if order is None else order["clOrdID"]

            if order is None:
                self.__new_order(ord_id, side, ord_qty, limit, stop, post_only, reduce_only)
            else:
                self.__amend_order(ord_id, side, ord_qty, limit, stop, post_only)
        else:
            ord_id = id + ord_suffix()
            self.__new_order(ord_id, side, ord_qty, limit, stop, post_only, reduce_only)
        
        self.callbacks[ord_id] = callback  

    def get_open_order(self, id):
        """
        Get order
        :param id: order id
        :return:
        """
        self.__init_client()
        open_orders = retry(lambda: self.private_client
                            .Order.Order_getOrders(filter=json.dumps({"symbol": self.pair, "open": True}))
                            .result())
        open_orders = [o for o in open_orders if o["clOrdID"].startswith(id)]
        if len(open_orders) > 0:
            return open_orders[0]
        else:
            return None

    def exit(self, profit=0, loss=0, trail_offset=0):
        """
        profit taking and stop loss and trailing, if both stop loss and trailing offset are set trailing_offset takes precedence
        :param profit: Profit (specified in ticks)
        :param loss: Stop loss (specified in ticks)
        :param trail_offset: Trailing stop price (specified in ticks)
        """
        self.exit_order = {'profit': profit, 'loss': loss, 'trail_offset': trail_offset}

    def sltp(self, profit_long=0, profit_short=0, stop_long=0, stop_short=0, eval_tp_next_candle=False, round_decimals=2,
                 profit_long_callback=None, profit_short_callback=None, stop_long_callback=None, stop_short_callback=None):
        """
        Simple take profit and stop loss implementation, which sends a reduce only stop loss order upon entering a position.
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
                            'stop_short': stop_short/100,
                            'eval_tp_next_candle': eval_tp_next_candle,
                            'profit_long_callback': profit_long_callback,
                            'profit_short_callback': profit_short_callback,
                            'stop_long_callback': stop_long_callback,
                            'stop_short_callback': stop_short_callback
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

        unrealised_pnl = self.get_position()['unrealisedPnl']

        # trail asset
        if self.get_exit_order()['trail_offset'] > 0 and self.get_trail_price() > 0:
            if self.get_position_size() > 0 and \
                    self.get_market_price() - self.get_exit_order()['trail_offset'] < self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all()
                self.close_all(self.get_exit_order()['trail_callback'])
            elif self.get_position_size() < 0 and \
                    self.get_market_price() + self.get_exit_order()['trail_offset'] > self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all()
                self.close_all(self.get_exit_order()['trail_callback'])

        # stop loss
        if unrealised_pnl < 0 and \
                0 < self.get_exit_order()['loss'] < abs(unrealised_pnl / 100000000):
            logger.info(f"Loss cut by stop loss: {self.get_exit_order()['loss']}")
            self.close_all()
            self.close_all(self.get_exit_order()['loss_callback'])

        # profit take
        if unrealised_pnl > 0 and \
                0 < self.get_exit_order()['profit'] < abs(unrealised_pnl / 100000000):
            logger.info(f"Take profit by stop profit: {self.get_exit_order()['profit']}")
            self.close_all()
            self.close_all(self.get_exit_order()['profit_callback'])
     
    def eval_sltp(self):
        """
        Simple take profit and stop loss implementation, which sends a reduce only stop loss order upon entering a position.
        - requires setting values with sltp() prior
        """
        pos_size = self.get_position_size()
        # sl_order = self.get_open_order('SL')
        # if pos_size == 0 and sl_order is not None:
        #     self.cancel(id=sl_order['clOrdID'])
        #     return
        if pos_size == 0:
            return
            
        # tp
        tp_order = self.get_open_order('TP')   
        
        is_tp_full_size = False 
        is_sl_full_size = False        

        if tp_order is not None:
            origQty = tp_order['orderQty']
            is_tp_full_size = origQty == abs(pos_size) if True else False
            #pos_size =  pos_size - origQty                 
        
        tp_percent_long = self.get_sltp_values()['profit_long']
        tp_percent_short = self.get_sltp_values()['profit_short']   

        avg_entry = self.get_position_avg_price()

        # tp execution logic                
        if tp_percent_long > 0 and is_tp_full_size == False:
            if pos_size > 0:                
                tp_price_long = round(avg_entry +(avg_entry*tp_percent_long), self.round_decimals) 
                if tp_order is not None:
                    #time.sleep(2)                    
                    self.__amend_order(tp_order['clOrdID'], False, abs(pos_size), limit=tp_price_long)
                else:               
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['profit_long_callback'])
        if tp_percent_short > 0 and is_tp_full_size == False:
            if pos_size < 0:                
                tp_price_short = round(avg_entry -(avg_entry*tp_percent_short), self.round_decimals)
                if tp_order is not None: 
                     #time.sleep(2)                   
                    self.__amend_order(tp_order['clOrdID'], True, abs(pos_size), limit=tp_price_short)
                else:
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['profit_short_callback'])
        #sl
        sl_order = self.get_open_order('SL')
        if sl_order is not None:
            origQty = sl_order['orderQty']
            orig_side = sl_order['side'] == "Buy" if True else False
            if orig_side == False:
                origQty = -origQty            
            is_sl_full_size = origQty == -pos_size if True else False           

        sl_percent_long = self.get_sltp_values()['stop_long']
        sl_percent_short = self.get_sltp_values()['stop_short']

        # sl execution logic
        if sl_percent_long > 0 and is_sl_full_size == False:
            if pos_size > 0:
                sl_price_long = round(avg_entry - (avg_entry*sl_percent_long), self.round_decimals)
                if sl_order is not None:                             
                    self.cancel(id=sl_order['clOrdID'])
                    time.sleep(2)
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['stop_long_callback'])
                    #self.__amend_order(sl_order['clOrdID'], False, abs(pos_size), stop=sl_price_long)
                else:  
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['stop_long_callback'])
        if sl_percent_short > 0 and is_sl_full_size == False:
            if pos_size < 0:
                sl_price_short = round(avg_entry + (avg_entry*sl_percent_short), self.round_decimals)
                if sl_order is not None:                                  
                    self.cancel(id=sl_order['clOrdID'])
                    time.sleep(2)
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['stop_short_callback'])
                    #self.__amend_order(sl_order['clOrdID'], True, abs(pos_size), stop=sl_price_short)
                else:  
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['stop_short_callback'])

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
            source = retry(lambda: self.public_client.Trade.Trade_getBucketed(symbol=self.pair, binSize=fetch_bin_size,
                                                                              startTime=left_time, endTime=right_time,
                                                                              count=500, partial=False).result())
            if len(source) == 0:
                break
            logger.info(f"fetching OHLCV data - {left_time}") 
            source = to_data_frame(source)
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
        get and update OHLCV data and execute the strategy
        """           
        if self.timeframe_data is None:
            self.timeframe_data = {}
            for t in self.bin_size:
                bin_size = t
                end_time = datetime.now(timezone.utc)
                start_time = end_time - self.ohlcv_len * delta(bin_size)
                self.timeframe_data[bin_size] = self.fetch_ohlcv(bin_size, start_time, end_time)
                self.timeframe_info[bin_size] = {
                                                    "allowed_range": allowed_range_minute_granularity[t][0] if self.minute_granularity else allowed_range[t][0], 
                                                    "ohlcv": self.timeframe_data[t][:-1], # Dataframe with closed candles                                                   
                                                    "last_action_time": None,#self.timeframe_data[bin_size].iloc[-1].name, # Last strategy execution time
                                                    "last_candle": self.timeframe_data[bin_size].iloc[-2].values,  # Store last complete candle
                                                    "partial_candle": self.timeframe_data[bin_size].iloc[-1].values  # Store incomplete candle
                                                }
                # The last candle is an incomplete candle with timestamp in future                
                if self.timeframe_data[bin_size].iloc[-1].name > end_time:
                    last_candle = self.timeframe_data[t].iloc[-1].values # Store last candle
                    self.timeframe_data[bin_size] = self.timeframe_data[t][:-1] # Exclude last candle
                    self.timeframe_data[bin_size].loc[end_time.replace(microsecond=0)] = last_candle #set last candle to end_time
                #d1 = self.timeframe_data[bin_size]
                # if len(d1) > 0:
                #     d2 = self.fetch_ohlcv(allowed_range[bin_size][0],
                #                         d1.iloc[-1].name + delta(allowed_range[bin_size][0]), end_time)

                #     self.timeframe_data[bin_size] = pd.concat([d1, d2])               
                # else:
                #     self.timeframe_data[bin_size] = d1                

                logger.info(f"Initial Buffer Fill - Last Candle: {self.timeframe_data[bin_size].iloc[-1].name}")   
        #logger.info(f"{self.timeframe_data}") 

        timeframes_to_update = []

        for t in self.timeframe_info:            
            if self.timeframe_info[t]["allowed_range"] == action:
                # append minute count of a timeframe when sorting when sorting is need otherwise just add a string timeframe
                timeframes_to_update.append(allowed_range_minute_granularity[t][3]) if self.timeframes_sorted != None else timeframes_to_update.append(t)  

        # Sorting timeframes that will be updated
        if self.timeframes_sorted == True:
            timeframes_to_update.sort(reverse=True)
        if self.timeframes_sorted == False:
            timeframes_to_update.sort(reverse=False)

        logger.info(f"timefeames to update: {timeframes_to_update}")        

        for t in timeframes_to_update:
            # Find timeframe string based on its minute count value
            if self.timeframes_sorted != None:             
                t = find_timeframe_string(t)               
                    
            # replace latest candle if timestamp is same or append
            if self.timeframe_data[t].iloc[-1].name == new_data.iloc[0].name:
                self.timeframe_data[t] = pd.concat([self.timeframe_data[t][:-1], new_data])
            else:
                self.timeframe_data[t] = pd.concat([self.timeframe_data[t], new_data])      

            # exclude current candle data and store partial candle data
            re_sample_data = resample(self.timeframe_data[t], t, minute_granularity=True if self.minute_granularity else False)
            self.timeframe_info[t]['partial_candle'] = re_sample_data.iloc[-1].values # store partial candle data
            re_sample_data =re_sample_data[:-1] # exclude current candle data

            logger.info(f"{self.timeframe_info[t]['last_action_time']} : {self.timeframe_data[t].iloc[-1].name} : {re_sample_data.iloc[-1].name}")  

            if self.timeframe_info[t]["last_action_time"] is not None and \
                self.timeframe_info[t]["last_action_time"] == re_sample_data.iloc[-1].name:
                continue

            # The last candle in the buffer needs to be preserved 
            # while resetting the buffer as it may be incomlete
            # or contains latest data from WS
            self.timeframe_data[t] = pd.concat([re_sample_data.iloc[-1 * self.ohlcv_len:, :], self.timeframe_data[t].iloc[[-1]]]) 
            #store ohlcv dataframe to timeframe_info dictionary
            self.timeframe_info[t]["ohlcv"] = re_sample_data
            #logger.info(f"Buffer Right Edge: {self.data.iloc[-1]}")
            
            open = re_sample_data['open'].values
            close = re_sample_data['close'].values
            high = re_sample_data['high'].values
            low = re_sample_data['low'].values
            volume = re_sample_data['volume'].values 
                                        
            try:
                if self.strategy is not None:   
                    self.timestamp = re_sample_data.iloc[-1].name.isoformat()           
                    self.strategy(t, open, close, high, low, volume)              
                self.timeframe_info[t]['last_action_time'] = re_sample_data.iloc[-1].name
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
        
    def __on_update_instrument(self, action, instrument):
        """
        Update instrument
        """
        if 'lastPrice' in instrument:
            self.market_price = instrument['lastPrice']

            # trail price update
            if self.get_position_size() > 0 and \
                    self.market_price > self.get_trail_price():
                self.set_trail_price(self.market_price)
            if self.get_position_size() < 0 and \
                    self.market_price < self.get_trail_price():
                self.set_trail_price(self.market_price)

    def __on_update_wallet(self, action, wallet):
        """
        update wallet
        """
        self.wallet = {**self.wallet, **wallet} if self.wallet is not None else self.wallet

    def __on_update_order(self, action, order):
        """
        Update order status        
        """
        self.order_update = order
        #logger.info(f"order: {order}")
        #logger.info(f"action:{ac tion}")

        #only after order if completely filled
        if order['leavesQty'] == 0: 
            logger.info(f"========= Order Update ==============")
            logger.info(f"ID     : {order['clOrdID']}") # Clinet Order ID
            logger.info(f"Pair   : {order['symbol']}") 
            logger.info(f"Type   : {order['ordType']}")
            #logger.info(f"Uses   : {order['wt']}")
            logger.info(f"Side   : {order['side']}")
            logger.info(f"Status : {order['ordStatus']}")
            logger.info(f"Qty    : {order['orderQty']}")
            logger.info(f"Leaves qty: {order['leavesQty']}")
            logger.info(f"Limit  : {order['price']}")
            logger.info(f"Stop   : {order['stopPx']}")
            logger.info(f"APrice : {order['avgPx']}")
            logger.info(f"======================================")

            # Call the respective order callback
            callback = self.callbacks.pop(order['clOrdID'], None)  # Removes the respective order callback and returns it
            if callback != None:
                callback()

        # Evaluation of profit and loss
        self.eval_exit()
        #self.eval_sltp()
        
    def __on_update_position(self, action, position):
        """
        Update position
        """
        # Was the position size changed?
        is_update_pos_size = self.get_position()['currentQty'] != position['currentQty']

        # Reset trail to current price if position size changes
        if is_update_pos_size and position['currentQty'] != 0:
            self.set_trail_price(self.market_price)

        if is_update_pos_size:            
            if 'avgEntryPrice' not in position:
                position.update( {'avgEntryPrice' : self.get_position()['avgEntryPrice']})
            logger.info(f"Updated Position\n"
                        f"Price: {self.get_position()['avgEntryPrice']} => {position['avgEntryPrice']}\n"
                        f"Qty: {self.get_position()['currentQty']} => {position['currentQty']}\n"
                        f"Balance: {self.get_balance()/100000000} XBT")
            notify(f"Updated Position\n"
                   f"Price: {self.get_position()['avgEntryPrice']} => {position['avgEntryPrice']}\n"
                   f"Qty: {self.get_position()['currentQty']} => {position['currentQty']}\n"
                   f"Balance: {self.get_balance()/100000000} XBT")

        self.position = {**self.position, **position} if self.position is not None else self.position

        # Evaluation of profit and loss
        self.eval_exit()
        self.eval_sltp()

    def __on_update_margin(self, action, margin):
        """
        Update margin
        """
        self.margin = {**self.margin, **margin} if self.margin is not None else self.margin

    def on_update(self, bin_size, strategy):
        """
        Register the strategy function
        bind functions with webosocket data streams        
        :param strategy: strategy
        """       
        logger.info(f"pair: {self.pair}")  
        logger.info(f"timeframes: {bin_size}")  
        self.bin_size = bin_size
        self.strategy = strategy       

        if self.is_running:
            self.ws = BitMexWs(account=self.account, pair=self.pair, test=self.demo)
            
            #if len(self.bin_size) > 0: 
                #for t in self.bin_size:                                        
                    #self.ws.bind(allowed_range_minute_granularity[t][0] if self.minute_granularity else allowed_range[t][0] \
                    #    , self.__update_ohlcv)

            if len(self.bin_size) > 1:   
                self.minute_granularity=True  

            if self.minute_granularity==True and '1m' not in self.bin_size:
                self.bin_size.append('1m')      
                             
            self.ws.bind('1m' if self.minute_granularity else allowed_range[bin_size[0]][0] \
                        , self.__update_ohlcv)       
            self.ws.bind('instrument', self.__on_update_instrument)
            self.ws.bind('wallet', self.__on_update_wallet)
            self.ws.bind('position', self.__on_update_position)
            self.ws.bind('order', self.__on_update_order)
            self.ws.bind('margin', self.__on_update_margin)
            self.ob = OrderBook(self.ws)
                        
    def stop(self):
        """
        Stop the crawler
        """
        if self.is_running:
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
