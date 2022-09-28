# coding: UTF-8

#import json
import math
#import os
import traceback
from datetime import datetime, timezone
import time
import threading

import pandas as pd
from bravado.exception import HTTPNotFound
from pytz import UTC

from src import logger, allowed_range, allowed_range_minute_granularity, \
    find_timeframe_string, to_data_frame, resample, delta, FatalError, notify, ord_suffix
from src import retry_binance_futures as retry
from src.config import config as conf
from src.exchange.binance_futures.binance_futures_api import Client
from src.exchange.binance_futures.binance_futures_websocket import BinanceFuturesWs


class BinanceFutures:   
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
    # Call strategy function on start, this can be useful when you dont want to wait for the candle to close to trigger the strategy function
    # this also can be problematic for certain operations like sending orders(or duplicates of orders that were already sent) calculated based on closed candle data that are no longer relevant etc.    
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
        self.base_asset = None
	    # Asset Rounding
        self.asset_rounding = None
	    # Quote Asset
        self.quote_asset = None
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
        # Binance futures client     
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
                        'stop_short_callback': None,
						'split': 1,
						'interval': 0
                        }         
         # Profit, Loss and Trail Offset
        self.exit_order = {
                        'profit': 0, 
                        'loss': 0, 
                        'trail_offset': 0, 
                        'profit_callback': None,
                        'loss_callback': None,
                        'trail_callbak': None,
						'split': 1,
						'interval': 0
                        }
        # Trailing Stop
        self.trail_price = 0   
        # Order callbacks
        self.callbacks = {}    
        # best bid price
        self.best_bid_price = None
        # best ask price
        self.best_ask_price = None 
        
    def __init_client(self):
        """
        initialization of client
        """
        if self.client is not None:
            return        
        api_key = conf['binance_test_keys'][self.account]['API_KEY'] if self.demo else conf['binance_keys'][self.account]['API_KEY']        
        api_secret = conf['binance_test_keys'][self.account]['SECRET_KEY'] if self.demo else conf['binance_keys'][self.account]['SECRET_KEY']
        
        self.client = Client(api_key=api_key, api_secret=api_secret, testnet=self.demo)

        if self.base_asset == None or self.asset_rounding == None or \
            self.quote_asset == None or self.quote_rounding == None:

            exchange_info =  retry(lambda: self.client.futures_exchange_info())
            symbols = exchange_info['symbols']
            symbol = [symbol for symbol in symbols if symbol.get('symbol')==self.pair]                 

            self.base_asset = symbol[0]['baseAsset']
            self.asset_rounding = symbol[0]['quantityPrecision'] 

            self.quote_asset = symbol[0]['quoteAsset']
            self.quote_rounding = symbol[0]['pricePrecision']      

            logger.info(f"Asset: {self.base_asset} Rounding: {self.asset_rounding} - Quote: {self.quote_asset} Rounding: {self.quote_rounding}")      
        
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
        get leverage
        :return:  
        """         
        return 20

    def get_lot(self, round_decimals=None):
        """        
        lot calculation
        :param round_decimals: round decimals
        :return:
        """
        account_information = self.get_account_information()        
        return round(float(account_information['totalMarginBalance']) / self.get_market_price() * self.lot_leverage(),
                 round_decimals if round_decimals != None else self.asset_rounding)    

    def get_balance(self):
        """
        get balance
        :return:
        """
        self.__init_client()
        ret = self.get_margin()

        if len(ret) > 0:
            balances = [p for p in ret if p["asset"] == self.quote_asset]            
            return float(balances[0]["balance"])
        else: return None

    def get_available_balance(self):
        """
        get available balance
        :return:
        """
        self.__init_client()
        ret = self.get_margin()

        if len(ret) > 0:
            balances = [p for p in ret if p["asset"] == self.quote_asset]            
            return float(balances[0]["availableBalance"])
        else: return None

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
            self.position = [p for p in ret if p["symbol"] == self.pair]            
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
            self.market_price = float(retry(lambda: self.client
                                      .futures_symbol_ticker(symbol=self.pair))['price'])
            return self.market_price

    def get_pnl(self):
        """
        get profit and loss calculation in %
        :return:
        """
        # PnL calculation in %            
        pnl = (self.market_price - self.entry_price) * 100 / self.entry_price
        return pnl        
        
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
        return 0.08 / 100 # 2*0.04 fee

    def cancel_all(self):
        """
        cancel all orders
        """
        self.__init_client()
        res = retry(lambda: self.client.futures_cancel_all_open_orders(symbol=self.pair))
        #for order in orders:
        logger.info(f"Cancel all open orders: {res}")    
        self.callbacks = {}

    def close_all(self, callback=None, split=1, interval=0):
        """
        market close open position for this pair
        """
        self.__init_client()
        position_size = self.get_position_size()
        if position_size == 0:
            return

        side = False if position_size > 0 else True
        
        self.order("Close", side, abs(position_size), callback=callback, split=split, interval=interval)
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
        self.callbacks.pop(order['clientOrderId'])
        return True

    def __new_order(self, ord_id, side, ord_qty, limit=0, stop=0, post_only=False, reduce_only=False, trailing_stop=0, activationPrice=0, workingType="CONTRACT_PRICE"):
        """
        create an order
        """
        #removes "+" from order suffix, because of the new regular expression rule for newClientOrderId updated as ^[\.A-Z\:/a-z0-9_-]{1,36}$ (2021-01-26)
        ord_id = ord_id.replace("+", "k") 
        
        if  trailing_stop > 0 and activationPrice > 0:
            ord_type = "TRAILING_STOP_MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, activationPrice=activationPrice,
                                                              callbackRate=trailing_stop, workingType=workingType))
        elif trailing_stop > 0:
            ord_type = "TRAILING_STOP_MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, callbackRate=trailing_stop, workingType=workingType))
        elif limit > 0 and post_only:
            ord_type = "LIMIT"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, price=limit,
                                                              timeInForce="GTX"))
        elif limit > 0 and stop > 0 and reduce_only:
            ord_type = "STOP"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, price=limit,
                                                              stopPrice=stop, reduceOnly="true", workingType=workingType))
        elif limit > 0 and reduce_only:
            ord_type = "LIMIT"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, price=limit,
                                                              reduceOnly="true", timeInForce="GTC"))
        elif limit > 0 and stop > 0:
            ord_type = "STOP"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, price=limit,
                                                              stopPrice=stop, workingType=workingType))
        elif limit > 0:   
            ord_type = "LIMIT"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, price=limit, timeInForce="GTC"))
        elif stop > 0 and reduce_only:
            ord_type = "STOP_MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, stopPrice=stop,
                                                              reduceOnly="true", workingType=workingType))        
        elif stop > 0:
            ord_type = "STOP_MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                              side=side, quantity=ord_qty, stopPrice=stop, workingType=workingType))        
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

    def entry(self, id, long, qty, limit=0, stop=0, post_only=False, reduce_only=False, when=True, round_decimals=None,
                 callback=None, workingType="CONTRACT_PRICE", split=1, interval=0):
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

        ord_qty = abs(qty) + abs(pos_size)
        ord_qty = round(ord_qty, round_decimals if round_decimals != None else self.asset_rounding)

        trailing_stop=0
        activationPrice=0

        self.order(id, long, ord_qty, limit, stop, post_only, reduce_only, trailing_stop, activationPrice, when, callback, workingType, split, interval)

    def entry_pyramiding(self, id, long, qty, limit=0, stop=0, trailValue= 0, post_only=False, reduce_only=False, cancel_all=False, pyramiding=2, when=True, round_decimals=None,
                             callback=None, workingType="CONTRACT_PRICE", split=1, interval=0):
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

        trailing_stop = 0
        activationPrice = 0

        ord_qty = round(ord_qty, round_decimals if round_decimals != None else self.asset_rounding)

        self.order(id, long, ord_qty, limit, stop, post_only, reduce_only, trailing_stop, activationPrice, when, callback, workingType, split, interval)

    def order(self, id, long, qty, limit=0, stop=0, post_only=False, reduce_only=False, trailing_stop=0, activationPrice=0, when=True,
                 callback=None, workingType="CONTRACT_PRICE", split=1, interval=0):
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
        ord_qty = abs(qty)
        logger.info(f"ord_qty: {ord_qty}")

        order = self.get_open_order(id)
        ord_id = id + ord_suffix() #if order is None else order["clientOrderId"]

        if split > 1:

            exchange = self
            sub_ord_qty = round(ord_qty/split, self.asset_rounding)
            
            class split_order:

                def __init__(self,count):
                    self.count = count

                def __call__(self):
                    logger.info(f"Split Order - Filled - {self.count}/{split}")
                    threading.Timer(interval, self.next_order).start()

                def next_order(self):  

                    sub_ord_id = f"{id}_sub{self.count+1}"                  

                    #last sub order
                    if(self.count == split-1):     
                        #remaining quantity                   
                        s_ord_qty = round(ord_qty - sub_ord_qty*(split-1), exchange.asset_rounding)
                        def final_callback():
                            logger.info(F"Order ID - {id} - All Suborders filled!")
                            if callable(callback):
                                callback() #call original callback
                        sub_ord_callback = final_callback 
                    else:
                        s_ord_qty = sub_ord_qty
                        sub_ord_callback = type(self)(self.count+1)
                    
                    # Override stop for subsequent sub orders
                    exchange.order(sub_ord_id, long, s_ord_qty, limit, 0, post_only, reduce_only, trailing_stop, activationPrice, workingType=workingType, callback=sub_ord_callback)

            sub_ord_id = f"{id}_sub1"
            self.order(sub_ord_id, long, sub_ord_qty, limit, stop, post_only, reduce_only, trailing_stop, activationPrice, workingType=workingType, callback=split_order(1))
            return

        self.callbacks[ord_id] = callback

        if order is None:
            self.__new_order(ord_id, side, ord_qty, limit, stop, post_only, reduce_only, trailing_stop, activationPrice, workingType)
        else:
            self.__new_order(ord_id, side, ord_qty, limit, stop, post_only, reduce_only, trailing_stop, activationPrice, workingType)
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

    def exit(self, profit=0, loss=0, trail_offset=0, profit_callback=None, loss_callback=None, trail_callback=None, split=1, interval=0):
        """
        profit taking and stop loss and trailing, if both stop loss and trailing offset are set trailing_offset takes precedence
        :param profit: Profit (specified in ticks)
        :param loss: Stop loss (specified in ticks)
        :param trail_offset: Trailing stop price (specified in ticks)
        """
        self.exit_order = {
                            'profit': profit, 
                            'loss': loss, 
                            'trail_offset': trail_offset, 
                            'profit_callback': profit_callback,
                            'loss_callback': loss_callback,
                            'trail_callback': trail_callback,
                            'split': split,
                            'interval': interval
                            }

    def sltp(self, profit_long=0, profit_short=0, stop_long=0, stop_short=0, eval_tp_next_candle=False, round_decimals=None,
                 profit_long_callback=None, profit_short_callback=None, stop_long_callback=None, stop_short_callback=None, workingType="CONTRACT_PRICE", split=1, interval = 0):
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
                            'stop_short_callback': stop_short_callback,
                            'sltp_working_type': workingType,
                            'split': split,
                            'interval': interval
                            } 
        if self.quote_rounding == None and round_decimals != None:
            self.quote_rounding = round_decimals

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
                self.close_all(self.get_exit_order()['trail_callback'], self.get_exit_order()['split'], self.get_exit_order()['interval'])
            elif self.get_position_size() < 0 and \
                    self.get_market_price() + self.get_exit_order()['trail_offset'] > self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all(self.get_exit_order()['trail_callback'], self.get_exit_order()['split'], self.get_exit_order()['interval'])

        #stop loss
        if unrealised_pnl < 0 and \
                0 < self.get_exit_order()['loss'] < abs(unrealised_pnl):
            logger.info(f"Loss cut by stop loss: {self.get_exit_order()['loss']}")
            self.close_all(self.get_exit_order()['loss_callback'], self.get_exit_order()['split'], self.get_exit_order()['interval'])

        # profit take
        if unrealised_pnl > 0 and \
                0 < self.get_exit_order()['profit'] < abs(unrealised_pnl):
            logger.info(f"Take profit by stop profit: {self.get_exit_order()['profit']}")
            self.close_all(self.get_exit_order()['profit_callback'], self.get_exit_order()['split'], self.get_exit_order()['interval'])

    # simple TP implementation

    def eval_sltp(self):
        """
        Simple take profit and stop loss implementation, which sends a reduce only stop loss order upon entering a position.
        - requires setting values with sltp() prior
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
            is_tp_full_size = origQty == abs(pos_size) if True else False
            #pos_size =  pos_size - origQty                 
        
        tp_percent_long = self.get_sltp_values()['profit_long']
        tp_percent_short = self.get_sltp_values()['profit_short']   

        avg_entry = self.get_position_avg_price()

        # tp execution logic                
        if tp_percent_long > 0 and is_tp_full_size == False:
            if pos_size > 0:                
                tp_price_long = round(avg_entry +(avg_entry*tp_percent_long), self.quote_rounding) 
                if tp_order is not None:
                    time.sleep(2)                                         
                    self.cancel(id=tp_order['clientOrderId'])
                    time.sleep(2)
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True, callback=self.get_sltp_values()['profit_long_callback'], workingType=self.get_sltp_values()['sltp_working_type'], \
                        split=self.get_sltp_values()['split'], interval=self.get_sltp_values()['interval'])
                else:               
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True, callback=self.get_sltp_values()['profit_long_callback'], workingType=self.get_sltp_values()['sltp_working_type'], \
                        split=self.get_sltp_values()['split'], interval=self.get_sltp_values()['interval'])
        if tp_percent_short > 0 and is_tp_full_size == False:
            if pos_size < 0:                
                tp_price_short = round(avg_entry -(avg_entry*tp_percent_short), self.quote_rounding)
                if tp_order is not None:
                    time.sleep(2)                                                        
                    self.cancel(id=tp_order['clientOrderId'])
                    time.sleep(2)
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True, callback=self.get_sltp_values()['profit_short_callback'], workingType=self.get_sltp_values()['sltp_working_type'], \
                        split=self.get_sltp_values()['split'], interval=self.get_sltp_values()['interval'])
                else:
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True, callback=self.get_sltp_values()['profit_short_callback'], workingType=self.get_sltp_values()['sltp_working_type'], \
                        split=self.get_sltp_values()['split'], interval=self.get_sltp_values()['interval'])
        #sl
        sl_order = self.get_open_order('SL')
        if sl_order is not None:
            origQty = float(sl_order['origQty'])
            orig_side = sl_order['side'] == "BUY" if True else False
            if orig_side == False:
                origQty = -origQty            
            is_sl_full_size = origQty == -pos_size if True else False     

        sl_percent_long = self.get_sltp_values()['stop_long']
        sl_percent_short = self.get_sltp_values()['stop_short']

        # sl execution logic
        if sl_percent_long > 0 and is_sl_full_size == False:
            if pos_size > 0:
                sl_price_long = round(avg_entry - (avg_entry*sl_percent_long), self.quote_rounding)
                if sl_order is not None:
                    time.sleep(2)                                    
                    self.cancel(id=sl_order['clientOrderId'])
                    time.sleep(2)
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True, callback=self.get_sltp_values()['stop_long_callback'], workingType=self.get_sltp_values()['sltp_working_type'], \
                        split=self.get_sltp_values()['split'], interval=self.get_sltp_values()['interval'])
                else:  
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True, callback=self.get_sltp_values()['stop_long_callback'], workingType=self.get_sltp_values()['sltp_working_type'], \
                        split=self.get_sltp_values()['split'], interval=self.get_sltp_values()['interval'])
        if sl_percent_short > 0 and is_sl_full_size == False:
            if pos_size < 0:
                sl_price_short = round(avg_entry + (avg_entry*sl_percent_short), self.quote_rounding)
                if sl_order is not None: 
                    time.sleep(2)                                         
                    self.cancel(id=sl_order['clientOrderId'])
                    time.sleep(2)
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True, callback=self.get_sltp_values()['stop_short_callback'], workingType=self.get_sltp_values()['sltp_working_type'], \
                        split=self.get_sltp_values()['split'], interval=self.get_sltp_values()['interval']) 
                else:  
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True, callback=self.get_sltp_values()['stop_short_callback'], workingType=self.get_sltp_values()['sltp_working_type'], \
                        split=self.get_sltp_values()['split'], interval=self.get_sltp_values()['interval'])                         
        
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

            logger.info(f"fetching OHLCV data - {left_time}")         

            source = retry(lambda: self.client.futures_klines(symbol=self.pair, interval=fetch_bin_size,
                                                                              startTime=left_time_to_timestamp, endTime=right_time_to_timestamp,
                                                                              limit=1500))
            if len(source) == 0:
                break
            
            source_to_object_list =[]
           
            for s in source:   
                timestamp_to_datetime = datetime.fromtimestamp(s[6]/1000).astimezone(UTC)               
                source_to_object_list.append({
                        "timestamp" : timestamp_to_datetime,
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

    def security(self, bin_size, data=None):
        """
        Recalculate and obtain different time frame data
        """     
        if data == None:   
            timeframe_list = []

            for t in self.bin_size:               
                    # append minute count of a timeframe for sorting when sorting is needed
                    timeframe_list.append(allowed_range_minute_granularity[t][3]) 
            timeframe_list.sort(reverse=True)
            t = find_timeframe_string(timeframe_list[-1])     
            data = self.timeframe_data[t]      
            return resample(data, bin_size)[:-1]   
        else:        
            return resample(data, bin_size)[:-1]    

    def __update_ohlcv(self, action, new_data):
        """
        get and update OHLCV data and execute the strategy
        """        
        # Binance can output wierd timestamps - Eg. 2021-05-25 16:04:59.999000+00:00
        # We need to round up to the nearest second for further processing
        new_data = new_data.rename(index={new_data.iloc[0].name: new_data.iloc[0].name.ceil(freq='1T')})               

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
            #Get PnL calculation in %
            self.pnl = self.get_pnl() 

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

        if(order['X'] == "CANCELED" or order['X'] == "EXPIRED"):
            #If stop price is set for a GTC Order and filled quanitity is 0 then EXPIRED means TRIGGERED
            if(float(order['sp']) > 0 and order['f'] == "GTC" and float(order['z']) == 0 and order['X'] == "EXPIRED"):
                logger.info(f"========= Order Update ==============")
                logger.info(f"ID     : {order['c']}") # Clinet Order ID
                logger.info(f"Type   : {order['o']}")
                logger.info(f"Uses   : {order['wt']}")
                logger.info(f"Side   : {order['S']}")
                logger.info(f"Status : TRIGGERED")
                logger.info(f"TIF    : {order['f']}")
                logger.info(f"Qty    : {order['q']}")
                logger.info(f"Filled : {order['z']}")
                logger.info(f"Limit  : {order['p']}")
                logger.info(f"Stop   : {order['sp']}")
                logger.info(f"APrice : {order['ap']}")
                logger.info(f"======================================")
            else:
                logger.info(f"========= Order Update ==============")
                logger.info(f"ID     : {order['c']}") # Clinet Order ID
                logger.info(f"Type   : {order['o']}")
                logger.info(f"Uses   : {order['wt']}")
                logger.info(f"Side   : {order['S']}")
                logger.info(f"Status : {order['X']}")
                logger.info(f"TIF    : {order['f']}")
                logger.info(f"Qty    : {order['q']}")
                logger.info(f"Filled : {order['z']}")
                logger.info(f"Limit  : {order['p']}")
                logger.info(f"Stop   : {order['sp']}")
                logger.info(f"APrice : {order['ap']}")
                logger.info(f"======================================")
                self.callbacks.pop(order['c'], None)

        #only after order if completely filled
        if(self.order_update_log and float(order['q']) == float(order['z'])): 
            logger.info(f"========= Order Update ==============")
            logger.info(f"ID     : {order['c']}") # Clinet Order ID
            logger.info(f"Type   : {order['o']}")
            logger.info(f"Uses   : {order['wt']}")
            logger.info(f"Side   : {order['S']}")
            logger.info(f"Status : {order['X']}")
            logger.info(f"Qty    : {order['q']}")
            logger.info(f"Filled : {order['z']}")
            logger.info(f"Limit  : {order['p']}")
            logger.info(f"Stop   : {order['sp']}")
            logger.info(f"APrice : {order['ap']}")
            logger.info(f"======================================")

            # Call the respective order callback
            callback = self.callbacks.pop(order['c'], None)  # Removes the respective order callback and returns it
            if callable(callback):
                callback()

        # Evaluation of profit and loss
        # self.eval_exit()
        # self.eval_sltp()
        
    def __on_update_position(self, action, position):
        """
        Update position
        """    

        if len(position) > 0:
            position = [p for p in position if p["s"].startswith(self.pair)]   
            if len(position) == 0:
                # logger.info(f"Some other pair was traded!")
                return
        else:
            return         
            
        # Was the position size changed?
        is_update_pos_size = self.get_position_size() != float(position[0]['pa'])        

        # Reset trail to current price if position size changes
        if is_update_pos_size and float(position[0]['pa']) != 0:
            self.set_trail_price(self.market_price)
        
        if is_update_pos_size:
            logger.info(f"Updated Position\n"
                        f"Price: {self.position[0]['entryPrice']} => {position[0]['ep']}\n"
                        f"Qty: {self.position[0]['positionAmt']} => {position[0]['pa']}\n"
                        f"Balance: {self.get_balance()} {self.quote_asset}")
            notify(f"Updated Position\n"
                   f"Price: {self.position[0]['entryPrice']} => {position[0]['ep']}\n"
                   f"Qty: {self.position[0]['positionAmt']} => {position[0]['pa']}\n"
                   f"Balance: {self.get_balance()} {self.quote_asset}")
       
        self.position[0] = {
                            "entryPrice": position[0]['ep'],
                            "marginType": position[0]['mt'],                            
                            "positionAmt":  position[0]['pa'], 
                            "symbol": position[0]['s'], 
                            "unRealizedProfit":  position[0]['up'], 
                            "positionSide": position[0]['ps'],
                            } if self.position is not None else self.position[0]

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
                                "asset": self.quote_asset,
                                "balance": float(margin['wb']),
                                "crossWalletBalance": float(margin['cw'])
                             }             
        else: self.get_margin() 
        notify(f"Balance: {self.margin[0]['balance']}")
        logger.info(f"Balance: {self.margin[0]['balance']} Cross Balance: {self.margin[0]['crossWalletBalance']}")     

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
        logger.info(f"timeframes: {bin_size}")      
        self.bin_size = bin_size
        self.strategy = strategy             

        if self.is_running:
            klines = set()
            if len(self.bin_size) > 0: 
                for t in self.bin_size: 
                    klines.add(allowed_range_minute_granularity[t][0]) if self.minute_granularity else klines.add(allowed_range[t][0])
            self.ws = BinanceFuturesWs(account=self.account, pair=self.pair, bin_size=sorted(klines), test=self.demo)

            #if len(self.bin_size) > 1:   
                #self.minute_granularity=True  

            #if self.minute_granularity==True and '1m' not in self.bin_size:
                #self.bin_size.append('1m')      

            #self.ws.bind('1m' if self.minute_granularity else allowed_range[bin_size[0]][0] \
                        #, self.__update_ohlcv)     

            if len(self.bin_size) > 0: 
                for t in self.bin_size:                                        
                    self.ws.bind(allowed_range_minute_granularity[t][0] if self.minute_granularity else allowed_range[t][0] \
                        , self.__update_ohlcv)                              
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
