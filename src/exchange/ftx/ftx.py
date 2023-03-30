# coding: UTF-8

import json
import math
import os
import traceback
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import time

import pandas as pd
from bravado.exception import HTTPNotFound
from pytz import UTC

from src import logger, bin_size_converter, allowed_range, allowed_range_minute_granularity, to_data_frame, \
    resample, find_timeframe_string, delta, FatalError, notify, ord_suffix, RepeatedTimer
from src import retry_ftx as retry
from src.exchange.ftx.ftx_api import FtxClient
from src.config import config as conf
from src.exchange_config import exchange_config
from src.exchange.ftx.ftx_websocket import FtxWs


class Ftx:
    # Positions in USDT?
    qty_in_usdt = False    
    # Use minute granularity?
    minute_granularity = False
    # Sort timeframes when multiple timeframes 
    timeframes_sorted = True # True for higher first, False for lower first and None when off 
    # Enable log output
    enable_trade_log = True   
    # Order Update Log
    order_update_log = True  
    # OHLCV length
    ohlcv_len = 100    
    # Call strategy function on start, this can be useful
    # when you dont want to wait for the candle to close to trigger the strategy function
    # this also can be problematic for certain operations like sending orders or duplicates of orders 
    # that have been already sent calculated based on closed candle data that are no longer relevant etc.    
    call_strat_on_start = False

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
        # Base Asset
        self.base_asset = None # on FTX only works for spot
	    # Asset Rounding
        self.asset_rounding = None
	    # Quote Asset
        self.quote_asset = None # on FTX only works for spot
	    # Quote Rounding
        self.quote_rounding = None
        # Use testnet?
        self.demo = demo
        # Is bot running?
        self.is_running = threading
        # wallet
        self.wallet = None
        # Position
        self.position = None
        # Position size
        self.position_size = None
        # Entry price
        self.entry_price = None
        # Margin
        self.margin = None
        # Account information
        self.account_information = None
        # Timeframe
        self.bin_size = ['1h'] 
        # Client for private API
        self.client = None
        # Price
        self.market_price = 0
        # Order update
        self.order_update = None
        # Bar crawler
        self.crawler = None
        # Strategy
        self.strategy = None
        # OHLCV data
        self.timeframe_data = None    
        # Timeframe data info like partial candle data values, last candle values, last action etc.
        self.timeframe_info = {}
        # New data timestamp after fetching
        self.last_new_data_timestamp = None
        # Profit target long and short for a simple limit exit strategy
        self.sltp_values = {
                        'profit_long': 0,
                        'profit_short': 0,
                        'stop_long': 0,
                        'stop_short': 0,
                        'eval_tp_next_candle': False,
                        'use_perc': True,
                        'profit_long_callback': None,
                        'profit_short_callback': None,
                        'stop_long_callback': None,
                        'stop_short_callback': None
                        }     
        # Is SLTP active
        self.is_sltp_active = False    
         # Profit, Loss and Trail Offset
        self.exit_order = {
                        'profit': 0, 
                        'loss': 0, 
                        'trail_offset': 0, 
                        'profit_callback': None,
                        'loss_callback': None,
                        'trail_callbak': None
                        }
        # Is exit order active
        self.is_exit_order_active = False
        # Trailing Stop
        self.trail_price = 0   
        # Order callbacks
        self.callbacks = {}    
        # best bid price
        self.best_bid_price = None
        # best ask price
        self.best_ask_price = None     
        # Warmup long and short entry lists for tp_next_candle option for sltp()
        self.isLongEntry = [False, False]
        self.isShortEntry = [False,False]    

        for k,v in exchange_config['ftx'].items():
            if k in dir(Ftx):      
                setattr(self, k, v)    
    
    def __init_client(self):
        """
        initialization of client
        """
        if self.client is not None:
            return
        
        api_key = conf['ftx_keys'][self.account]['API_KEY'] if self.demo else conf['ftx_keys'][self.account]['API_KEY']        
        api_secret = conf['ftx_keys'][self.account]['SECRET_KEY'] if self.demo else conf['ftx_keys'][self.account]['SECRET_KEY']
        
        if self.account == "None":
            self.account = None
        self.client = FtxClient(api_key=api_key, api_secret=api_secret, subaccount_name=self.account)
        
        if self.asset_rounding == None or self.quote_rounding == None:
            markets_list = retry(lambda: self.client.list_markets())   
            market = [market for market in markets_list if market.get('name')==self.pair]
            self.quote_asset = market[0]['quoteCurrency']                      
            self.quote_rounding = abs(Decimal(str(market[0]['priceIncrement'])).as_tuple().exponent) if market[0]['priceIncrement'] < 1 else 0
            self.base_asset = market[0]['baseCurrency'] if  market[0]['baseCurrency'] != None else  market[0]['underlying']      
            self.asset_rounding = abs(Decimal(str(market[0]['sizeIncrement'])).as_tuple().exponent) if market[0]['sizeIncrement'] < 1 else 0         

            logger.info(f"market: {market}")           
            logger.info(f"Asset: {self.base_asset} Rounding: {self.asset_rounding} - Quote: {self.quote_asset} Rounding: {self.quote_rounding}")

    def now_time(self):
        """
        current time
        """
        return datetime.now().astimezone(UTC)
    
    def get_lot(self):
        free_collateral = retry(lambda: self.client.get_account_info())['freeCollateral']
        return (free_collateral)/ self.get_market_price()
    
    def get_balance(self, free_collateral=True):
        """
        get balance
        :return:
        """
        self.__init_client()       
        
        account_info = retry(lambda: self.client.get_account_info())
        collateral = account_info['freeCollateral'] if free_collateral else account_info['collateral']

    def get_position(self, force_api_call=False, showAvgPrice=False):
        """
        get the current position
        :param force_api_call: force api call
        :return:
        """

        def get_position_api_call():
            ret = retry(lambda: self.client
                                  .get_position(name=self.pair, show_avg_price=showAvgPrice))
            
            if ret is None:
                return ret
            if len(ret) > 0:
                self.position = ret
            return self.position

        self.__init_client()

        if force_api_call:
            return get_position_api_call()
        
        elif self.position is not None:
            return self.position
        else:  # when the WebSocket cant get it
            return get_position_api_call()

    def get_position_size(self, force_api_call=False):
        """
        get position size
        :param force_api_call: force api call
        :return:
        """
        self.__init_client() 
        position_size = self.get_position(force_api_call)
        
        if position_size is not None:  
            self.position_size = float(position_size['netSize'])          
            return float(position_size['netSize'])
        else:
            self.position_size = 0
            return 0
    
    def get_position_avg_price(self):
        """
        get average price of the current position
        :return:
        """
        self.__init_client()
        pos = self.get_position(force_api_call=True, showAvgPrice=True) 
            
        if pos != None:
            if pos['size'] == 0.0:
                return 0
            return pos['recentAverageOpenPrice']
        else: return 0

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
                                      .get_futures(market=self.pair))["last"]
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
        return 0.15 / 100

    def cancel_all(self, conditional_orders=False, limit_orders=False):
        """
        close opened orders for this pair
        """
        self.__init_client()
        orders = retry(lambda: self.client.cancel_orders(conditional_orders=conditional_orders, limit_orders=limit_orders, market_name=self.pair))        
       
        logger.info(f"Cancel All Active Orders")
        self.callbacks = {}  
    
    def cancel_all_conditional(self):
        """
        cancel opened conditional orders for this pair
        """
        self.__init_client()
        orders = retry(lambda: self.client.cancel_orders(conditional_orders=True, limit_orders=False, market_name=self.pair))      
        logger.info(f"Cancel All Active Conditional Orders")

    def close_all(self, callback=None):
        """
        market close opened position for this pair
        """
        self.__init_client()
        position_size = self.get_position_size()
        if position_size == 0:
            return

        side = False if position_size > 0 else True
        
        self.order("Close", side, abs(position_size), callback=callback)
        position_size = self.get_position_size()
        if position_size == 0:
            logger.info(f"Closed {self.pair} position")
        else:
            logger.info(f"Failed to close all {self.pair} position, still {position_size} (quantity) remaining")
        
    def cancel(self, id):
        """
        Cancel a specific active order by id
        :param id: id of the order
        :return: result
        """
        self.__init_client()
        order = self.get_open_order(id)
        if order is None:
            return False

        try:
            retry(lambda: self.client.cancel_order(client_id=order['clientId']))[0]
        except HTTPNotFound:
            return False
        logger.info(f"Cancel Order : (orderID, orderType, side, orderQty, limit, stop) = "
                    f"({order['clientId']}, {order['type']}, {order['side']}, {order['size']}, "
                    f"{order['price']})")
        self.callbacks.pop(order['clientId'])
        return True

    def cancel_conditional_order(self, id):
        """
        Cancel a specific conditional order by id
        :param id: id of the order
        :return: result
        """
        self.__init_client()
        # order = self.get_open_order(id)
        # if order is None:
        #     return False

        try:
            retry(lambda: self.client.cancel_conditional_order(order_id=id))
        except HTTPNotFound:
            return False
        # logger.info(f"Cancel Order : (orderID, orderType, side, orderQty, limit, stop) = "
        #             f"({order['orderID']}, {order['ordType']}, {order['side']}, {order['orderQty']}, "
        #             f"{order['price']}, {order['stopPx']})")
        #self.callbacks.pop(order['clientId'])
        return True

    def __new_order(self, ord_id, side, ord_qty, limit=0, stop=0, trailValue=0, post_only=False, reduce_only=False, ioc=False,):
        """
        create an order
        """
        #logger.info(f"{ord_id} {side} {ord_qty} {limit} {stop}")
        if limit > 0 and post_only:
            ord_type = "limit"
            retry(lambda: self.client.place_order(market=self.pair, type=ord_type, client_id=ord_id,
                                                              side=side, size=ord_qty, price=limit,
                                                              post_only=True, ioc=ioc))
        elif limit > 0 and stop > 0 and reduce_only:
            ord_type = "stop"
            retry(lambda: self.client.place_conditional_order(market=self.pair, type=ord_type,
                                                              side=side, size=ord_qty, limit_price=limit,
                                                              trigger_price=stop, reduce_only=True))
        elif limit > 0 and reduce_only:
            ord_type = "limit"
            retry(lambda: self.client.place_order(market=self.pair, type=ord_type, client_id=ord_id,
                                                              side=side, size=ord_qty, price=limit,
                                                              reduce_only=True, ioc=ioc))        
        elif limit > 0 and stop > 0:
            ord_type = "stop"
            retry(lambda: self.client.place_conditional_order(market=self.pair, type=ord_type, 
                                                              side=side, size=ord_qty, limit_price=limit,
                                                              trigger_price=stop))
        elif limit > 0:
            ord_type = "limit"
            retry(lambda: self.client.place_order(market=self.pair, type=ord_type, client_id=ord_id,
                                                              side=side, size=ord_qty, price=limit, ioc=ioc))
        elif stop > 0 and reduce_only:
            ord_type = "stop"
            retry(lambda: self.client.place_conditional_order(market=self.pair, type=ord_type,
                                                              side=side, size=ord_qty, trigger_price=stop,
                                                              reduce_only=True))
        elif stop > 0:
            ord_type = "stop"
            retry(lambda: self.client.place_conditional_order(market=self.pair, type=ord_type, 
                                                              side=side, size=ord_qty, trigger_price=stop))
        elif post_only: # limit order with post only loop
            ord_type = "limit"
            i = 0
            while True:                
                limit = self.best_bid if side == "Buy" else self.best_ask
                
                retry(lambda: self.client.place_order(market=self.pair, type=ord_type, client_id=ord_id,
                                                                  side=side, size=ord_qty, price=limit, post_only=True, ioc=ioc))
                time.sleep(1)

                if not self.cancel(ord_id):
                    break
                time.sleep(2)
                i += 1
                if i > 10:
                    notify(f"Order retry count exceed")
                    break
            self.cancel_all(limit_orders=True)   
        else:
            ord_type = "market"
            retry(lambda: self.client.place_order(market=self.pair, type=ord_type, price=0, client_id=ord_id,
                                                              side=side, size=ord_qty, ioc=ioc))

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

    def __amend_order(self, side, ord_qty, ord_id=None, client_ord_id=None, limit=0, stop=0):
        """
        Amend order
        """
        if limit > 0 and stop > 0:
            ord_type = "stop"
            retry(lambda: self.client.modify_conditional_order(existing_order_id=ord_id, 
                                                                size=ord_qty, price=limit, trigger_price=stop))
        elif limit > 0:
            ord_type = "limit"
            retry(lambda: self.client.modify_order(existing_order_id=client_ord_id, existing_client_order_id=ord_id,
                                                                size=ord_qty, price=limit))
        elif stop > 0:
            ord_type = "stop"
            retry(lambda: self.client.modify_conditional_order(existing_order_id=ord_id, 
                                                                size=ord_qty, trigger_price=stop).result())
        # elif post_only: # market order with post only
        #     ord_type = "limit"
        #     prices = self.ob.get_prices()
        #     limit = prices[1] if side == "Buy" else prices[0]
        #     retry(lambda: self.client.modify_order(existing_ord_id=ord_id, existing_client_ord_id=client_ord_id,
        #                                                         size=ord_qty, price=limit))
        else:
            ord_type = "market"
            retry(lambda: self.client.modify_order(existing_ord_id=ord_id, existing_client_order_id=client_ord_id,
                                                                size=ord_qty))

        if self.enable_trade_log:
            logger.info(f"========= Amend Order ==============")
            logger.info(f"ID     : {ord_id}")
            logger.info(f"CLIENT_ID     : {client_ord_id}")
            logger.info(f"Type   : {ord_type}")
            logger.info(f"Side   : {side}")
            logger.info(f"Qty    : {ord_qty}")
            logger.info(f"Limit  : {limit}")
            logger.info(f"Stop   : {stop}")
            logger.info(f"======================================")

            notify(f"Amend Order\nType: {ord_type}\nSide: {side}\nQty: {ord_qty}\nLimit: {limit}\nStop: {stop}")

    def entry(self, id, long, qty, limit=0, stop=0, trailValue= 0, post_only=False, reduce_only=False, ioc=False, allow_amend=False, cancel_all=False,
                 when=True, round_decimals=None, callback=None):
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
        if qty <= 0:
            return

        if not when:
            return

        pos_size = self.get_position_size()

        if long and pos_size > 0:
            return

        if not long and pos_size < 0:
            return
        
        if cancel_all:
            self.cancel_all()           
            
        ord_qty = round(qty + abs(pos_size), round_decimals if round_decimals != None else self.asset_rounding)       
        self.order(id, long, ord_qty, limit, stop, trailValue, post_only, reduce_only, ioc, allow_amend, when, round_decimals, callback)

    def entry_pyramiding(self, id, long, qty, limit=0, stop=0, trailValue= 0, post_only=False, reduce_only=False, ioc=False, allow_amend=False, cancel_all=False,
                        pyramiding=2, when=True, round_decimals=None, callback=None):
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
        self.__init_client()
        logger.info(f"{id} {qty}{limit}")           

        # if self.get_margin()['excessMargin'] <= 0 or qty <= 0:
        #     return
        if qty <= 0:
            return

        if not when:
            return

        pos_size = self.get_position_size(force_api_call=True)

        if long and pos_size >= pyramiding*qty:
            return

        if not long and pos_size <= -(pyramiding*qty):
            return
        
        if cancel_all:
            self.cancel_all()   

        if (long and pos_size < 0) or (not long and pos_size > 0):
            ord_qty = qty + abs(pos_size)        
        else:
            ord_qty = qty  
        
        if (long and pos_size + qty > pyramiding*qty) or (not long and pos_size - qty < -pyramiding*qty):
            ord_qty = pyramiding*qty - abs(pos_size)
     
        # make sure it doesnt spam small entries, which in most cases would trigger risk management orders evaluation, you can make this less than 2% if needed  
        if ord_qty < ((pyramiding*qty) / 100) * 2:
            return       
        
        ord_qty = round(ord_qty, round_decimals if round_decimals != None else self.asset_rounding)
        
        self.order(id, long, ord_qty, limit, stop, trailValue, post_only, reduce_only, ioc, allow_amend, when, round_decimals, callback)

    def order(self, id, long, qty, limit=0, stop=0, trailValue=0, post_only=False, reduce_only=False, ioc=False, allow_amend=True, when=True,
                 round_decimals=None, callback=None):
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

        # if self.get_margin()['excessMargin'] <= 0 or qty <= 0:
        #     return
       
        if not when:
            return
        
        side = "buy" if long else "sell"
        ord_qty = round(qty, round_decimals if round_decimals != None else self.asset_rounding)        

        if allow_amend:
            order = self.get_open_order(id)
            ord_id = id + ord_suffix() if order is None else order["clOrdID"]

            self.callbacks[ord_id] = callback

            if order is None:
               
                self.__new_order(ord_id, side, ord_qty, limit, stop, post_only, reduce_only)
            else:
                self.__amend_order(ord_id, side, ord_qty, limit, stop, post_only)

        else:
            ord_id = id + ord_suffix()
            self.callbacks[ord_id] = callback            
            self.__new_order(ord_id, side, ord_qty, limit, stop, trailValue, post_only, reduce_only, ioc)

    def get_open_order(self, id, return_all=False):
        """
        Get order or all orders by id
        :param id: order id
        :param: return_all: return all orders that start with queried "id"
        :return:
        """
        self.__init_client()
        open_orders = retry(lambda: self.client
                            .get_open_orders(market= self.pair))
                            
        open_orders = [o for o in open_orders if o["clientId"].startswith(id)]
        if len(open_orders) > 0 and return_all:
            return open_orders
        elif len(open_orders) > 0:
            return open_orders[0]
        else:
            return None
    
    def get_open_conditional_orders(self, type=None, return_all=False):
        """
        Get order or opene conditional orders for this instrument        
        :return:
        """
        self.__init_client()
        open_orders = retry(lambda: self.client
                            .get_open_conditional_orders(market=self.pair, type=type))
                            
        #open_orders = [o for o in open_orders if o["id"].startswith(id)]
        if len(open_orders) > 0 and return_all:
            return open_orders
        elif len(open_orders) > 0:
            return open_orders[0]
        else:
            return None
    
    def get_open_conditional_order_triggers(self, id):
        """
        Get orders or conditional orders for this instrument        
        :return:
        """
        self.__init_client()
        open_orders = retry(lambda: self.client
                            .get_open_conditional_order_triggers(id=id))
                            
        
        if len(open_orders) > 0:
            return open_orders[0]
        else:
            return None

    def exit(self, profit=0, loss=0, trail_offset=0, profit_callback=None, loss_callback=None, trail_callback=None):
        """
        profit taking and stop loss and trailing, 
        if both stop loss and trailing offset are set trailing_offset takes precedence
        :param profit: Profit
        :param loss: Stop loss
        :param trail_offset: Trailing stop price
        """
        self.exit_order = {
                            'profit': profit, 
                            'loss': loss, 
                            'trail_offset': trail_offset, 
                            'profit_callback': profit_callback,
                            'loss_callback': loss_callback,
                            'trail_callback': trail_callback
                            }
        self.is_exit_order_active = self.exit_order['profit'] > 0 \
                                    or self.exit_order['loss'] > 0 \
                                    or self.exit_order['trail_offset'] >  0     

    def sltp(self, profit_long=0, profit_short=0, stop_long=0, stop_short=0, eval_tp_next_candle=False, use_perc=True, round_decimals=None,
                 profit_long_callback=None, profit_short_callback=None, stop_long_callback=None, stop_short_callback=None):
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
                            'stop_short': stop_short/100,
                            'eval_tp_next_candle': eval_tp_next_candle,
                            'use_perc': use_perc,
                            'profit_long_callback': profit_long_callback,
                            'profit_short_callback': profit_short_callback,
                            'stop_long_callback': stop_long_callback,
                            'stop_short_callback': stop_short_callback
                            }        
        self.is_sltp_active = self.sltp_values['profit_long'] > 0 \
                                or self.sltp_values['profit_short'] > 0 \
                                or self.sltp_values['stop_long'] >  0 \
                                or self.sltp_values['stop_short'] > 0    
         
        if self.quote_rounding == None and round_decimals != None:
            self.quote_rounding = round_decimals

    def get_sltp_values(self):
        """
        get values for the simple profit target/stop loss in %
        """
        return self.sltp_values 

    def get_exit_order(self):
        """
        get profit take and stop loss and trailing settings
        """
        return self.exit_order

    def eval_exit(self):
        """
        evalution of profit target and stop loss and trailing
        """
        if self.get_position_size() == 0:
            return

        position = self.get_position()
        if 'unrealizedPnl' in position:
            if position['unrealizedPnl'] != None:
                unrealised_pnl = position['unrealizedPnl'] 
            else:
                unrealised_pnl = 0

        # trail asset
        if self.get_exit_order()['trail_offset'] > 0 and self.get_trail_price() > 0:
            if self.get_position_size() > 0 and \
                    self.get_market_price() - self.get_exit_order()['trail_offset'] < self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all(self.get_exit_order()['trail_callback'])
            elif self.get_position_size() < 0 and \
                    self.get_market_price() + self.get_exit_order()['trail_offset'] > self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all(self.get_exit_order()['trail_callback'])

        # stop loss
        if unrealised_pnl < 0 and \
                0 < self.get_exit_order()['loss'] < abs(unrealised_pnl):
            logger.info(f"Loss cut by stop loss: {self.get_exit_order()['loss']}")
            self.close_all(self.get_exit_order()['loss_callback'])

        # profit take
        if unrealised_pnl > 0 and \
                0 < self.get_exit_order()['profit'] < abs(unrealised_pnl):
            logger.info(f"Take profit by stop profit: {self.get_exit_order()['profit']}")
            self.close_all(self.get_exit_order()['profit_callback'])

    def eval_sltp(self):
        """
        evaluate simple profit target and stop loss
        """     
        pos_size = self.get_position_size(force_api_call=True)
      
        if pos_size == 0:
            return

        best_bid = self.best_bid
        best_ask = self.best_ask
        
        is_tp_full_size = False 
        is_sl_full_size = False   

        avg_entry = self.get_position_avg_price()     

        #sl
        sl_order = self.get_open_conditional_orders(type="stop")
        #logger.info(f"get open conditional orders:{sl_order}")
        if sl_order is not None:
            origQty = sl_order['size']
            orig_side = sl_order['side'] == "buy" if True else False
            if orig_side == False:
                origQty = -origQty            
            is_sl_full_size = origQty == -pos_size if True else False 

        sl_percent_long = self.get_sltp_values()['stop_long']
        sl_percent_short = self.get_sltp_values()['stop_short']
        use_perc = self.get_sltp_values()['use_perc']

        # sl execution logic
        if sl_percent_long > 0 and is_sl_full_size == False:
            if pos_size > 0:
                sl_price_long = round(avg_entry - (avg_entry*sl_percent_long), self.quote_rounding) if use_perc else  round(sl_percent_long * 100 , self.quote_rounding)
                if sl_order is not None:                             
                    self.cancel_all_conditional()
                    time.sleep(2)
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['stop_long_callback'])
                    #self.__amend_order(sl_order['clOrdID'], False, abs(pos_size), stop=sl_price_long)
                else:  
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['stop_long_callback'])
        if sl_percent_short > 0 and is_sl_full_size == False:
            if pos_size < 0:
                sl_price_short = round(avg_entry + (avg_entry*sl_percent_short), self.quote_rounding) if use_perc else round(sl_percent_short * 100, self.quote_rounding)
                if sl_order is not None:                                  
                    self.cancel_all_conditional()
                    time.sleep(2)
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['stop_short_callback'])
                    #self.__amend_order(sl_order['clOrdID'], True, abs(pos_size), stop=sl_price_short)
                else:  
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['stop_short_callback'])       

        # tp
        tp_order = self.get_open_order('TP')     
        
        if tp_order is not None:
            origQty = tp_order['remainingSize']
            is_tp_full_size = origQty == abs(pos_size) if True else False
            #pos_size =  pos_size - origQty                 
        
        tp_percent_long = self.get_sltp_values()['profit_long']
        tp_percent_short = self.get_sltp_values()['profit_short']    
             
        # tp execution logic                
        if tp_percent_long > 0 and is_tp_full_size == False:
            if pos_size > 0:                
                tp_price_long = round(avg_entry +(avg_entry*tp_percent_long), self.quote_rounding) if use_perc else round(tp_percent_long * 100, self.quote_rounding)
                if tp_price_long <= best_ask:
                    tp_price_long = best_ask 
                if tp_order is not None:
                    #time.sleep(2) 
                    self.cancel(id=tp_order['clientId'])  
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['profit_long_callback'])                                     
                    #self.__amend_order(tp_order['id'], False, abs(pos_size), limit=tp_price_long)
                else:               
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['profit_long_callback'])
        if tp_percent_short > 0 and is_tp_full_size == False:
            if pos_size < 0:                
                tp_price_short = round(avg_entry -(avg_entry*tp_percent_short), self.quote_rounding)  if use_perc else round(tp_percent_short * 100, self.quote_rounding)
                if tp_price_short >= best_bid:
                    tp_price_long = best_bid      
                if tp_order is not None: 
                    #time.sleep(2) 
                    self.cancel(id=tp_order['clientId'])  
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['profit_short_callback'])                
                    #self.__amend_order(tp_order['id'], True, abs(pos_size), limit=tp_price_short)
                else:
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True, allow_amend=False, callback=self.get_sltp_values()['profit_short_callback'])

    def fetch_ohlcv(self, bin_size, start_time, end_time, minute_granularity=False):
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
        bybit_bin_size_converted = bin_size_converter(fetch_bin_size)        

        #logger.info(f"fetching OHLCV data - {left_time}")    

        while True:   
            left_time_to_timestamp = int(datetime.timestamp(left_time))
            right_time_to_timestamp = int(datetime.timestamp(right_time))          
            if left_time > right_time:
                break
            source = retry(lambda: self.client.get_historical_prices(market=self.pair, resolution=bybit_bin_size_converted['seconds'],#bybit_bin_size_converted['seconds'],
                                                                            start_time=left_time_to_timestamp, end_time=right_time_to_timestamp, limit=1000))
            if len(source) == 0:
                break
            source_to_object_list =[]
           
            for s in source:                  
                timestamp_to_datetime_str = datetime.strptime(s['startTime'], '%Y-%m-%dT%H:%M:%S+00:00') + timedelta(seconds=0.01) 
                source_to_object_list.append({
                        "timestamp" : timestamp_to_datetime_str,
                        "high" : float(s['high']),
                        "low" : float(s['low']),
                        "open" : float(s['open']),
                        "close" : float(s['close']),
                        "volume" : float(s['volume'])
                    })           

            source = to_data_frame(source_to_object_list)
           
            data = pd.concat([data, source])    

            if right_time > source.iloc[-1].name + delta(fetch_bin_size):
                left_time = source.iloc[-1].name + delta(fetch_bin_size)
                time.sleep(2)
            else:
                break      
        
        return resample(data, bin_size, minute_granularity)        

    def security(self, bin_size, data=None):
        """
        Recalculate and obtain data of a timeframe higher than the current chart timeframe without looking into the furute that would cause undesired effects.
        """     
        if data == None:   
            timeframe_list = [allowed_range_minute_granularity[t][3] for t in self.bin_size] # minute count of a timeframe for sorting when sorting is needed 
            timeframe_list.sort(reverse=True)
            t = find_timeframe_string(timeframe_list[-1])     
            data = self.timeframe_data[t]      
            
        return resample(data, bin_size)[:-1]    

    def __update_ohlcv(self, action=None, new_data=None):
        """
        get and update OHLCV data and execute the strategy
        """     
        action = '1m' if self.minute_granularity else allowed_range[self.bin_size[0]][0]

        end_time = datetime.now(timezone.utc)  - timedelta(seconds=0.1) 
        start_time = end_time - self.ohlcv_len * delta(action)
       
        
        new_data = self.fetch_ohlcv(action, start_time, end_time)#[:-1]     

        if new_data.iloc[-1].name > datetime.now(timezone.utc):
            new_data = new_data[:-1]         
       
        dummy_data = to_data_frame([{
                        "timestamp": new_data.iloc[-1].name + timedelta(seconds=0.01),
                        "open":  new_data.iloc[-1]['close'],
                        "high":  new_data.iloc[-1]['close'],
                        "low" :  new_data.iloc[-1]['close'],
                        "close" : new_data.iloc[-1]['close'],
                        "volume": 0
                    }])
        
        if self.timeframe_data != None and self.last_new_data_timestamp != None:
            if new_data.iloc[-1].name == self.last_new_data_timestamp:                
                return
        self.last_new_data_timestamp = new_data.iloc[-1].name

        new_data = pd.concat([new_data, dummy_data])
        new_data = new_data[-2:]      
        #logger.info(f"new_data : {new_data}")        

        if self.timeframe_data is None:
            self.timeframe_data = {}
            for t in self.bin_size:              
                end_time = datetime.now(timezone.utc)
                start_time = end_time - self.ohlcv_len * delta(t)
                self.timeframe_data[t] = self.fetch_ohlcv(t, start_time, end_time)
                self.timeframe_info[t] = {
                                                    "allowed_range": allowed_range_minute_granularity[t][0] if self.minute_granularity else allowed_range[t][0], 
                                                    "ohlcv": self.timeframe_data[t][:-1], # Dataframe with closed candles                                                   
                                                    "last_action_time": None,#self.timeframe_data[t].iloc[-1].name, # Last strategy execution time
                                                    "last_candle": self.timeframe_data[t].iloc[-2].values,  # Store last complete candle
                                                    "partial_candle": self.timeframe_data[t].iloc[-1].values  # Store incomplete candle
                                                }
                # The last candle is an incomplete candle with timestamp in future                
                if self.timeframe_data[t].iloc[-1].name > end_time:
                    last_candle = self.timeframe_data[t].iloc[-1].values # Store last candle
                    self.timeframe_data[t] = self.timeframe_data[t][:-1] # Exclude last candle
                    self.timeframe_data[t].loc[end_time.replace(microsecond=0)] = last_candle #set last candle to end_time   

        # Timeframes to be updated
        timeframes_to_update = [allowed_range_minute_granularity[t][3] if self.timeframes_sorted != None else 
                                t for t in self.timeframe_info if self.timeframe_info[t]['allowed_range'] == action]        
        #logger.info(f"timeframes to update: {timeframes_to_update}")

        # Sorting timeframes that will be updated
        if self.timeframes_sorted == True:
            timeframes_to_update.sort(reverse=True)
        if self.timeframes_sorted == False:
            timeframes_to_update.sort(reverse=False)

        #logger.info(f"timefeames to update: {timeframes_to_update}")        

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

            #logger.info(f"{self.timeframe_info[t]['last_action_time']} : {self.timeframe_data[t].iloc[-1].name} : {re_sample_data.iloc[-1].name}")  

            if self.call_strat_on_start:
                if self.timeframe_info[t]["last_action_time"] is not None and \
                self.timeframe_info[t]["last_action_time"] == re_sample_data.iloc[-1].name:
                    continue
            else:   
                if self.timeframe_info[t]["last_action_time"] is None:
                    self.timeframe_info[t]["last_action_time"] = re_sample_data.iloc[-1].name
                    
                if self.timeframe_info[t]["last_action_time"] == re_sample_data.iloc[-1].name:
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
            #logger.info(f"{self.timeframe_info['5m']['partial_candle']}")                            
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

    def __on_update_ticker(self, action, ticker):
        """
        Update ticker data best bid and best ask
        """        
        #logger.info(f"ticker data {ticker}")
        #best bid and ask
        self.best_bid = ticker['bid']
        self.best_ask = ticker['ask']
        #last price
        self.market_price = ticker['last']

        if self.asset_rounding == None or self.quote_rounding == None:
            self.__init_client()
          
        if self.position_size == None:            
            self.get_position_size(force_api_call=True)
            
        #trail price update
        if self.get_position_size() > 0 and \
                self.market_price > self.get_trail_price():
            self.set_trail_price(self.market_price)
        if self.get_position_size() < 0 and \
                self.market_price < self.get_trail_price():
            self.set_trail_price(self.market_price)

        # # PnL calculation in %
        # self.percent_PnL = (self.market_price - self.entry_price) * 100 / self.entry_price 

    def __on_update_fills(self, action, fills):
        """
        Update fills of orders
        """
        self.last_fill = fills
        logger.info(f"last fill: {self.last_fill}")        
        #self.eval_sltp()    
        pos_size = self.get_position_size(force_api_call=True)
        logger.info(f"position size: {pos_size}")        

        message = f"""========= FILLS =============
                           {fills} 
                      ============================="""
        notify(message)

    def __on_update_order(self, action, order):
        """
        Update order status        
        """
        self.order_update = order
        # Evaluation of profit and loss
       
        logger.info(f"on update order:{self.order_update}")

        if self.is_sltp_active:
            self.eval_sltp()
        if self.is_exit_order_active:
            self.eval_exit()

    def on_update(self, bin_size, strategy):
        """
        Register the strategy function
        bind functions with webosocket data streams        
        :param strategy: strategy
        """       
        self.bin_size = bin_size
        self.strategy = strategy     

        if self.demo:
            logger.info(f"Sorry there is no testnet for FTX!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            return

        if len(self.bin_size) > 1:   
                self.minute_granularity=True  

        if self.minute_granularity==True and '1m' not in self.bin_size:
            self.bin_size.append('1m')      
     
        next_call=int(time.time()/60)*60

        self.update_ohlcv_timer = RepeatedTimer(60, self.__update_ohlcv, next_call)

        if self.is_running:            
            self.ws = FtxWs(account=self.account, pair=self.pair, test=self.demo)             
            self.ws.bind('ticker', self.__on_update_ticker)          
            self.ws.bind('orders', self.__on_update_order)
            self.ws.bind('fills', self.__on_update_fills)            
            # self.ob = OrderBook(self.ws)       

    def stop(self):
        """
        Stop the crawler
        """
        self.is_running = False
        self.ws.close()
        self.update_ohlcv_timer.stop()

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