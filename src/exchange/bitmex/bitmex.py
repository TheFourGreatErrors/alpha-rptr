# coding: UTF-8

import json
import math
#import os
import traceback
from datetime import datetime, timezone
import time
from decimal import Decimal

import pandas as pd
from bravado.exception import HTTPNotFound
from pytz import UTC

from src import (logger, retry, allowed_range,
                 allowed_range_minute_granularity,
                 find_timeframe_string, sync_obj_with_config,
                 to_data_frame, resample, delta,
                 FatalError, notify, ord_suffix)
from src.exchange.bitmex.bitmex_api import bitmex_api
from src.config import config as conf
from src.exchange_config import exchange_config
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
    # Call the strategy function on start. This can be useful if you don't want to wait for the candle to close
    # to trigger the strategy function. However, this can also be problematic for certain operations such as
    # sending orders or duplicates of orders that have already been sent, which were calculated based on closed
    # candle data that is no longer relevant. Be aware of these potential issues and make sure to handle them
    # appropriately in your strategy implementation.  
    call_strat_on_start = False

    def __init__(self, account, pair, demo=False, threading=True):
        """
        Constructor for BinanceFutures class.
        Args:
            account (str): The account identifier for Binance futures.
            pair (str): The trading pair for Binance futures.
            demo (bool, optional): Flag to use the testnet. Default is False.
            threading (bool, optional): Condition for setting the 'is_running' flag.
                Default is True to indicate the bot is running.
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
        # Best bid price
        self.best_bid_price = None
        # Best ask price
        self.best_ask_price = None 
        # Last strategy execution time
        self.last_action_time = None

        sync_obj_with_config(exchange_config['bitmex'], BitMex, self)

    def __init_client(self):
        """
        Initialization of the client for live trading on BitMEX exchange.
        """
        if self.private_client is not None and self.public_client is not None:
            return
       
        api_key =  conf['bitmex_test_keys'][self.account]['API_KEY'] \
                    if self.demo else conf['bitmex_keys'][self.account]['API_KEY']        
        api_secret = conf['bitmex_test_keys'][self.account]['SECRET_KEY'] \
                    if self.demo else conf['bitmex_keys'][self.account]['SECRET_KEY']

        self.private_client = bitmex_api(test=self.demo, api_key=api_key, api_secret=api_secret)
        self.public_client = bitmex_api(test=self.demo)

        if self.quote_rounding == None or self.asset_rounding == None:
            symbol = self.get_symbol_information()
            tick_size = symbol['tickSize'] * 2 if '5' in str(symbol['tickSize']) else symbol['tickSize'] 
            self.quote_asset = symbol['quoteCurrency']                                
            self.quote_rounding = abs(Decimal(str(tick_size))
                                      .as_tuple().exponent) if float(tick_size) < 1 else 0 
            self.base_asset = symbol['underlying'] 
            self.asset_rounding = abs(Decimal(str(symbol['lotSize']))
                                      .as_tuple().exponent) if float(symbol['lotSize']) < 1 else 0  
        
        self.sync()

        logger.info(f"Asset: {self.base_asset} Rounding: {self.asset_rounding} "\
                    f"- Quote: {self.quote_asset} Rounding: {self.quote_rounding}")
        
        logger.info(f"Position Size: {self.position_size:.3f} Entry Price: {self.entry_price:.2f}")
        
    def sync(self):
        """
        Synchronize BitMEX instance with the current position, position size,
          entry price, market price, margin best bid and best ask.
        """
        # Position
        self.position = self.get_position()
        # Position size
        self.position_size = self.get_position_size()
        # Entry price
        self.entry_price = self.get_position_avg_price()
        # Market price
        self.market_price = self.get_market_price()
        # Margin
        self.margin = self.get_margin()
        # Best bid price
        self.best_bid_price = self.ob.best_bid_price
        # Best ask price
        self.best_ask_price = self.ob.best_ask_price

    def now_time(self):
        """
        Get the current time in UTC timezone.
        """
        return datetime.now().astimezone(UTC)
        
    def get_retain_rate(self):
        """
        Get the maintenance margin rate.
        Returns:
            float: The maintenance margin rate (e.g., 0.004 represents 0.4%).
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
    
    def set_leverage(self, leverage=1):
        """
        set leverage, this will automaticall set your position to isolated margin
        :param  leverage: leverage
        :return:
        """
        self.__init_client()

        res = retry(lambda: self.private_client
                             .Position.Position_updateLeverage(symbol=self.pair, 
                                                               leverage=leverage).result())
       
        return res

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
        pos = self.get_position()#['avgEntryPrice']
      
        if pos is None or 'avgEntryPrice' not in pos:
            return 0
        else:
            return pos['avgEntryPrice']

    def get_market_price(self):
        """
        Get the current market price of the trading pair.
        Returns:
            float: The current market price.
        """
        self.__init_client()
        if self.market_price != 0:
            return self.market_price
        else:  # when the WebSocket cant get it
            self.market_price = retry(lambda: self.public_client
                                      .Instrument.Instrument_get(symbol=self.pair).result())[0]["lastPrice"]
            return self.market_price
        
    def get_symbol_information(self, symbol=None):
        """
        get latest symbol(trading pair) information
        :param symbol: if provided it will return information for the specific symbol otherwise,
                        otherwise it returns values for the pair currently traded 
        :return:
        """
        symbol = self.pair if symbol == None else symbol   
        try:     
            latest_symbol_information = retry(lambda: self.public_client.Instrument
                                              .Instrument_get(symbol=symbol).result())[0]
        except Exception  as e:        
            logger.info(f"An error occured: {e}")
            logger.info(f"Sorry couldnt retrieve information for symbol: {symbol}")
            return None
        
        return latest_symbol_information
        
    def get_trail_price(self):
        """
        Get Trail Price.
        Returns:
            float: Current trail price value.
        """
        return self.trail_price

    def set_trail_price(self, value):
        """
        Set the trail price to the specified value.
        Args:
            value (float): The value to set as the trail price.
        Returns:
            None
        """
        self.trail_price = value

    def get_commission(self):
        """
        Get the commission rate.
        Returns:
            float: The commission rate.
        """
        return 0.15 / 100

    def cancel_all(self):
        """
        Cancel all open orders for the trading pair.
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
        Close all positions for this trading pair.
        Args:
            callback (callable or None): Optional callback function to be called after positions are closed.
        Returns:
            None
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
        Cancel a specific order by id.
        Args:
            id (str): ID of the order to cancel.
        Returns:
            bool: True if the order was successfully cancelled, False otherwise.
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

    def __new_order(
            self,
            ord_id,
            side,
            ord_qty,
            limit=0,
            stop=0,
            post_only=False,
            reduce_only=False
    ):
        """
        Create an order.
        Args:
            ord_id (str): Order ID.
            side (str): Order side (Buy or Sell).
            ord_qty (float): Order quantity.
            limit (float): Limit price.
            stop (float): Stop price.
            post_only (bool): Whether the order is post-only.
            reduce_only (bool): Whether the order is reduce-only.
        Returns:
            None
        """   
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
    
    def amend_order(
            self, 
            ord_id, 
            ord_qty=0, 
            limit=0, 
            stop=0, 
            post_only=False
    ):
        """
        Amend an order with querying the order prior to verifying its existence and whether it's active or conditional.
        This function allows amending an existing order with the provided order ID.        
        Args:
            ord_id (str): Order ID to amend.
            ord_qty (float, optional): Order quantity. Default is 0.
            limit (float, optional): Limit price. Default is 0.
            stop (float, optional): Stop price. Default is 0.
            post_only (bool, optional): Whether the order is post-only. Default is False.
        Returns:
            None
        """
        order = self.get_open_order(id=ord_id)

        if order is None or len(order) == 0:
            logger.info(f"Cannot Find An Order to Amend Id: {ord_id}")
            return
        
        ord_id = order['clOrdID']

        self.__amend_order(ord_id=ord_id, side="", ord_qty=ord_qty,
                            limit=limit, stop=stop, post_only=post_only)       

    def __amend_order(
            self,
            ord_id,
            side,
            ord_qty,
            limit=0,
            stop=0,
            post_only=False
    ):
        """
        Amend an existing order.
        Args:
            ord_id (str): Order ID to amend.
            side (str): Order side (Buy or Sell).
            ord_qty (float): Order quantity.
            limit (float): Limit price.
            stop (float): Stop price.
            post_only (bool): Whether the order is post-only.
        Returns:
            None
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

    def entry(
            self,
            id,
            long,
            qty,
            limit=0,
            stop=0,
            post_only=False,
            reduce_only=False,
            allow_amend=False,
            when=True,
            round_decimals=None,
            callback=None
    ):
        """
        Places an entry order with various options, working as an equivalent to TradingView Pine script implementation:
        https://tradingview.com/study-script-reference/#fun_strategy{dot}entry

        When an order is placed in a market, it will typically open a position on a particular side (buy or sell). 
        However, if another entry order is sent while the position is still open, and it is on the opposite side, 
        the position will be reversed. This means that the current position will be closed out (effectively covering the existing position), 
        and a new position will be opened on the opposite side. In other words, 
        the order will close out the existing position and enter a new position in the opposite direction.
       
        It will not send the order if there is a position opened on the same side !!! 
        - for multiple entrie use `entry_pyramiding()` or regular `order()`

        Args:
            id (str): Order ID.
            long (bool): Long or Short position.
            qty (float): Quantity.
            limit (float, optional): Limit price. Default is 0.
            stop (float, optional): Stop price. Default is 0.
            post_only (bool, optional): Whether the order is post-only. Default is False.
            reduce_only (bool, optional): Reduce Only means that your existing position cannot be increased 
                                        only reduced by this order. Default is False.
            allow_amend (bool, optional): Allow amending existing orders. Default is False.
            when (bool, optional): Whether to execute the order or not - True for live trading. Default is True.
            round_decimals (int, optional): Number of decimals to round quantity. Default is None.
            callback (callable, optional): Optional callback function to be called after the order is placed. Default is None.
        Returns:
            None
        """     
        self.__init_client()

        if self.get_margin()['excessMargin'] <= 0 or qty <= 0:
            return
       
        if not when:
            return
       
        pos_size = self.get_position_size()

        if long and pos_size > 0:
            return
            
        if not long and pos_size < 0:            
            return
        
        ord_qty = qty + abs(pos_size)
        ord_qty = round(ord_qty, round_decimals if round_decimals != None else self.asset_rounding)

        self.order(id, long, ord_qty, limit, stop, post_only, reduce_only, allow_amend, when, callback)

    def entry_pyramiding(
            self,
            id,
            long,
            qty,
            limit=0,
            stop=0,
            post_only=False,
            reduce_only=False,
            cancel_all=False,
            pyramiding=2,
            allow_amend=False,
            when=True,
            round_decimals=None,
            callback=None
    ):
        """
        Places an entry order with pyramiding, allowing adding to a position in smaller chunks.
        The implementation is similar to TradingView Pine script:
        https://tradingview.com/study-script-reference/#fun_strategy{dot}entry

        Pyramiding in trading refers to adding to a position gradually,
        with the goal of increasing potential gains while reducing risk.
        In this function, the order quantity is adjusted based on the pyramiding value set by the user deviding it in smaller orders.
        Outside of order pyramiding functionality it behaves as a regular `entry()`.

        Args:
            id (str): Order ID.
            long (bool): Long or Short position.
            qty (float): Quantity.
            limit (float, optional): Limit price. Default is 0.
            stop (float, optional): Stop price. Default is 0.
            post_only (bool, optional): Whether the order is post-only. Default is False.
            reduce_only (bool, optional): Reduce Only means that your existing position cannot be increased 
                                        only reduced by this order. Default is False.
            cancel_all (bool, optional): Whether to cancel all open orders before sending the entry order. Default is False.
            pyramiding (int, optional): Number of entries you want in pyramiding. Default is 2.
            allow_amend (bool, optional): Allow amending existing orders. Default is False.
            when (bool, optional): Whether to execute the order or not - True for live trading. Default is True.
            round_decimals (int, optional): Number of decimals to round quantity. Default is None.
            callback (callable, optional): Optional callback function to be called after the order is placed. Default is None.
        Returns:
            None
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

        if (long and pos_size < 0) or (not long and pos_size > 0):
            ord_qty = qty + abs(pos_size)        
        else:
            ord_qty = qty  
        
        if (long and pos_size + qty > pyramiding*qty) or (not long and pos_size - qty < -pyramiding*qty):
            ord_qty = pyramiding*qty - abs(pos_size)
     
        # Make sure it doesnt spam small entries,
        # which in most cases would trigger risk management orders evaluation, you can make this less than 2% if needed  
        if ord_qty < ((pyramiding*qty) / 100) * 2:
            return          

        ord_qty = round(ord_qty, round_decimals if round_decimals != None else self.asset_rounding)

        self.order(id, long, ord_qty, limit, stop, post_only, reduce_only, allow_amend, when, callback)

    def order(
            self,
            id,
            long,
            qty,
            limit=0,
            stop=0,
            post_only=False,
            reduce_only=False,
            allow_amend=False,
            when=True,
            round_decimals=None,
            callback=None
    ):
        """
        Places an order with various options.

        Args:
            id (str): Order ID.
            long (bool): Long or Short position.
            qty (float): Quantity.
            limit (float, optional): Limit price. Default is 0.
            stop (float, optional): Stop limit. Default is 0.
            post_only (bool, optional): Whether the order is post-only. Default is False.
            reduce_only (bool, optional): Reduce Only means that your existing position cannot be increased 
                                        only reduced by this order by this order. Default is False.
            allow_amend (bool, optional): Allow amending existing orders. Default is False.
            when (bool, optional): Whether to execute the order or not - True for live trading. Default is True.
            round_decimals (int, optional): Number of decimals to round quantity. Default is None.
            callback (callable, optional): Optional callback function to be called after the order is placed. Default is None.
        Returns:
            None
        """
        self.__init_client()        
        
        if self.get_margin()['excessMargin'] <= 0 or qty <= 0:            
            return
        
        if not when:
            return
        
        side = "Buy" if long else "Sell"
        ord_qty = abs(round(qty, round_decimals if round_decimals != None else self.asset_rounding))                  

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
    
    def get_open_order_qty(self, id):
        """
        Returns the order quantity of the first open order that starts the given order ID.        
        Args:
            id (str): The ID of the order to search for.
        Returns:
            float: The quantity of the first open order or None if no matching order is found.
        """      
        order = self.get_open_order(id=id) 
        return None if order is None else order['leavesQty']

    def get_open_order(self, id):
        """
        Get open order by ID.        
        Args:
            id (str): Order ID for this pair.
        Returns:
            dict: Information about the first open order matching the provided ID or None if not found.
        """
        self.__init_client()
        open_orders = retry(lambda: self.private_client
                            .Order.Order_getOrders(filter=json.dumps({"symbol": self.pair, "open": True}))
                            .result())
        filtered_orders = [o for o in open_orders if o["clOrdID"].startswith(id)]
        if not filtered_orders:
            return None
        if len(filtered_orders) > 1:
            logger.info(f"Found more than 1 order starting with given id. Returning only the first one!")
        return filtered_orders[0]      
    
    def get_open_orders(self, id=None):
        """
        Get open orders.        
        Args:
            id (str, optional): If provided, it will return only those that start with the provided string.
        Returns:
            list: List of open orders or None if no matching orders are found.
        """
        self.__init_client()
        open_orders = retry(lambda: self.private_client
                            .Order.Order_getOrders(filter=json.dumps({"symbol": self.pair, "open": True}))
                            .result())        
        filtered_orders = [o for o in open_orders if o["clOrdID"].startswith(id)] if id else open_orders     
        return filtered_orders if filtered_orders else None

    def exit(self, profit=0, loss=0, trail_offset=0):
        """
        Profit-taking, stop loss, and trailing.
        If both stop loss and trailing offset are set, trailing_offset takes precedence.
        Args:
            profit (float, optional): Profit target value in %. Default is 0.S
            loss (float, optional): Stop loss value in %. Default is 0.
            trail_offset (float, optional): Trailing stop price. Default is 0.
        Returns:
            None
        """
        self.exit_order = {'profit': profit, 
                           'loss': loss, 
                           'trail_offset': trail_offset}
        
        self.is_exit_order_active = self.exit_order['profit'] > 0 \
                                    or self.exit_order['loss'] > 0 \
                                    or self.exit_order['trail_offset'] >  0     

    def sltp(
            self,
            profit_long=0,
            profit_short=0,
            stop_long=0,
            stop_short=0,
            eval_tp_next_candle=False,
            round_decimals=None,
            profit_long_callback=None,
            profit_short_callback=None,
            stop_long_callback=None,
            stop_short_callback=None
    ):
        """
        Implement a simple take profit and stop loss strategy. (Independent of exit())
        Sends a reduce-only stop-loss order upon entering a position.
        
        Args:
            profit_long (float, optional): Profit target value in % for longs. Default is 0.
            profit_short (float, optional): Profit target value in % for shorts. Default is 0.
            stop_long (float, optional): Stop loss value for long positions in %. Default is 0.
            stop_short (float, optional): Stop loss value for short positions in %. Default is 0.
            eval_tp_next_candle (bool, optional): Whether to evaluate the take profit on the next candle. Default is False.
            round_decimals (int, optional): Rounding decimals. Default is None.
            profit_long_callback (callable, optional): Callback function for long profit. Default is None.
            profit_short_callback (callable, optional): Callback function for short profit. Default is None.
            stop_long_callback (callable, optional): Callback function for long stop loss. Default is None.
            stop_short_callback (callable, optional): Callback function for short stop loss. Default is None.
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
        self.is_sltp_active = self.sltp_values['profit_long'] > 0 \
                                or self.sltp_values['profit_short'] > 0 \
                                or self.sltp_values['stop_long'] >  0 \
                                or self.sltp_values['stop_short'] > 0     
        
        if self.quote_rounding == None and round_decimals != None:
            self.quote_rounding = round_decimals

    def get_exit_order(self):
        """
        Get the profit take, stop loss, and trailing settings for the exit strategy.
        Returns:
            dict: Exit strategy settings.
        """
        return self.exit_order

    def get_sltp_values(self):
        """
        Get the values for the simple profit target and stop loss in percentage.
        Returns:
            dict: Simple profit target and stop loss values.
        """
        return self.sltp_values    

    def eval_exit(self):
        """
        Evaluate the profit target, stop loss, and trailing conditions for triggering an exit.
        """
        if self.get_position_size() == 0:
            return

        unrealised_pnl = self.get_position()['unrealisedPnl']

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
                0 < self.get_exit_order()['loss'] < abs(unrealised_pnl / 100000000):
            logger.info(f"Loss cut by stop loss: {self.get_exit_order()['loss']}")
            self.close_all(self.get_exit_order()['loss_callback'])

        # profit take
        if unrealised_pnl > 0 and \
                0 < self.get_exit_order()['profit'] < abs(unrealised_pnl / 100000000):
            logger.info(f"Take profit by stop profit: {self.get_exit_order()['profit']}")
            self.close_all(self.get_exit_order()['profit_callback'])
     
    def eval_sltp(self):
        """
        Evaluate and execute the simple take profit and stop loss implementation.
        - Sends a reduce-only stop loss order upon entering a position.
        - Requires setting values with sltp() prior.
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
                tp_price_long = round(avg_entry +(avg_entry*tp_percent_long), self.quote_rounding) 
                if tp_order is not None:
                    #time.sleep(2)                    
                    self.__amend_order(tp_order['clOrdID'], False, abs(pos_size), limit=tp_price_long)
                else:               
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True,
                                allow_amend=False, callback=self.get_sltp_values()['profit_long_callback'])
        if tp_percent_short > 0 and is_tp_full_size == False:
            if pos_size < 0:                
                tp_price_short = round(avg_entry -(avg_entry*tp_percent_short), self.quote_rounding)
                if tp_order is not None: 
                     #time.sleep(2)                   
                    self.__amend_order(tp_order['clOrdID'], True, abs(pos_size), limit=tp_price_short)
                else:
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True,
                                allow_amend=False, callback=self.get_sltp_values()['profit_short_callback'])
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
                sl_price_long = round(avg_entry - (avg_entry*sl_percent_long), self.quote_rounding)
                if sl_order is not None:                             
                    self.cancel(id=sl_order['clOrdID'])
                    time.sleep(2)
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True,
                                allow_amend=False, callback=self.get_sltp_values()['stop_long_callback'])
                    #self.__amend_order(sl_order['clOrdID'], False, abs(pos_size), stop=sl_price_long)
                else:  
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True,
                                allow_amend=False, callback=self.get_sltp_values()['stop_long_callback'])
        if sl_percent_short > 0 and is_sl_full_size == False:
            if pos_size < 0:
                sl_price_short = round(avg_entry + (avg_entry*sl_percent_short), self.quote_rounding)
                if sl_order is not None:                                  
                    self.cancel(id=sl_order['clOrdID'])
                    time.sleep(2)
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True,
                                allow_amend=False, callback=self.get_sltp_values()['stop_short_callback'])
                    #self.__amend_order(sl_order['clOrdID'], True, abs(pos_size), stop=sl_price_short)
                else:  
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True,
                                allow_amend=False, callback=self.get_sltp_values()['stop_short_callback'])

    def fetch_ohlcv(self, bin_size, start_time, end_time):
        """
        Fetch OHLCV data within the specified time range.

        Args:
            bin_size (str): Time frame to fetch (e.g., "1m", "1h", "1d").
            start_time (datetime): Start time of the data range.
            end_time (datetime): End time of the data range.

        Returns:
            pd.DataFrame: OHLCV data in the specified time frame.
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

    def security(self, bin_size, data=None):
        """
        Recalculate and obtain data of a timeframe higher than the current timeframe
        without looking into the future to avoid undesired effects.
        Args:
            bin_size (str): Time frame of the OHLCV data.
            data (pd.DataFrame): OHLCV data to be used for calculation. If None, use the current timeframe data.
        Returns:
            pd.DataFrame: OHLCV data resampled to the specified bin_size.
        """  
        if data == None:  # minute count of a timeframe for sorting when sorting is needed   
            timeframe_list = [allowed_range_minute_granularity[t][3] for t in self.bin_size]
            timeframe_list.sort(reverse=True)
            t = find_timeframe_string(timeframe_list[-1])     
            data = self.timeframe_data[t]      
            
        return resample(data, bin_size)[:-1]    
    
    def __update_ohlcv(self, action, new_data):
        """
        Update OHLCV (Open-High-Low-Close-Volume) data and execute the strategy.

        This function takes in new OHLCV data and updates the internal buffer for each specified timeframe.
        The function ensures that the data is correctly aligned with the timeframe and handles cases where
        the last candle is incomplete or contains data from the future.

        Args:
            action (str): The allowed range for updating the OHLCV data.
                        This could be a minute granularity (e.g., '1m', '5m', '15m') or a custom range.
            new_data (pd.DataFrame): New OHLCV data to be added. It should be a pandas DataFrame with
                                    a DatetimeIndex and columns for 'open', 'high', 'low', 'close', and 'volume'.
        Returns:
            None
        """         
        if self.timeframe_data is None:
            self.timeframe_data = {}
            for t in self.bin_size:                
                end_time = datetime.now(timezone.utc)
                start_time = end_time - self.ohlcv_len * delta(t)
                self.timeframe_data[t] = self.fetch_ohlcv(t, start_time, end_time)
                self.timeframe_info[t] = {
                            "allowed_range": allowed_range_minute_granularity[t][0]
                                            if self.minute_granularity else allowed_range[t][0], 
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
                #d1 = self.timeframe_data[t]
                # if len(d1) > 0:
                #     d2 = self.fetch_ohlcv(allowed_range[t][0],
                #                         d1.iloc[-1].name + delta(allowed_range[t][0]), end_time)

                #     self.timeframe_data[t] = pd.concat([d1, d2])               
                # else:
                #     self.timeframe_data[t] = d1                

                logger.info(f"Initial Buffer Fill - Last Candle: {self.timeframe_data[t].iloc[-1].name}")   
        #logger.info(f"{self.timeframe_data}") 

        # Timeframes to be updated
        timeframes_to_update = [allowed_range_minute_granularity[t][3] if self.timeframes_sorted != None 
                                else t for t in self.timeframe_info if self.timeframe_info[t]['allowed_range'] == action]        
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
            re_sample_data = resample(self.timeframe_data[t], 
                                      t, 
                                      minute_granularity=True if self.minute_granularity else False)
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
            self.timeframe_data[t] = pd.concat([re_sample_data.iloc[-1 * self.ohlcv_len:, :], 
                                                self.timeframe_data[t].iloc[[-1]]]) 
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
        Update the price of the instrument.

        This function is called when the instrument's price is updated. It keeps track of the current
        market price and checks if any trailing stop orders need to be updated based on the new price.

        Args:
            action (str): The action associated with the update (e.g., 'update', 'insert', 'delete').
            instrument (dict): The updated instrument data, typically containing the current market price.

        Returns:
            None
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
        Update wallet.

        Args:
            action (str): The action related to the update.
            wallet (dict): The updated wallet data.

        Returns:
            None
        """
        # Updates the wallet data by merging the current wallet data with the new data received
        self.wallet = {**self.wallet, **wallet} if self.wallet is not None else self.wallet

    def __on_update_order(self, action, order):
        """
        Update order status.

        Args:
            action (str): The action related to the update.
            order (dict): The updated order data containing the order status.

        Returns:
            None
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
        if self.is_exit_order_active:
            self.eval_exit()
        if self.is_sltp_active:
            self.eval_sltp()
        
    def __on_update_position(self, action, position):
        """
        Update position.

        This function is called when there is an update to the position. It filters the position data
        for the current trading pair and then checks if the position size has changed. If the position
        size has changed, it updates the trail price to the current market price. It also updates the
        internal position data and evaluates the profit and loss.

        Args:
            action (str): The action related to the update.
            position (dict): The updated position data containing position size, average entry price, etc.

        Returns:
            None
        """
        # Was the position size changed?
        is_update_pos_size = 'currentQty' in position \
                                and self.get_position()['currentQty'] != position['currentQty']

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
        if self.is_exit_order_active:
            self.eval_exit()
        if self.is_sltp_active:
            self.eval_sltp()

    def __on_update_margin(self, action, margin):
        """
        Update margin

        The function updates the 'margin' attribute with the new margin data. 
        It does this by merging the current margin data with the new data received to keep the margin information up-to-date.
        
        Args:
            action (str): The action related to the update. It indicates the type of update being received, such as "partial" or "update".
            margin (dict): The updated margin data, which contains information about the margin requirements and available margin balance.
        Returns:
            None
        """
        self.margin = {**self.margin, **margin} if self.margin is not None else self.margin

    def on_update(self, bin_size, strategy):
        """
        Register the strategy function and bind functions with WebSocket data streams.

        This function is used to set up the WebSocket connections for the specified bin sizes (timeframes)
        and register the provided strategy function to be executed on data updates. It also binds the
        necessary update functions to handle instrument, wallet, position, order, margin, and bookticker updates.

        Args:
            bin_size (list): List of bin sizes (timeframes) for which OHLCV data will be fetched and updated.
            strategy (function): The strategy function to be executed when OHLCV data is updated.

        Returns:
            None
        """       
        logger.info(f"pair: {self.pair}")  
        logger.info(f"timeframes: {bin_size}")  
        self.bin_size = bin_size
        self.strategy = strategy       

        if self.is_running:
            self.ws = BitMexWs(account=self.account, pair=self.pair, test=self.demo)
            
            #if len(self.bin_size) > 1:   
                #self.minute_granularity=True  

            #if self.minute_granularity==True and '1m' not in self.bin_size:
                #self.bin_size.append('1m')      

            #self.ws.bind('1m' if self.minute_granularity else allowed_range[bin_size[0]][0] \
                        #, self.__update_ohlcv)     

            if len(self.bin_size) > 0: 
                for t in self.bin_size:                                        
                    self.ws.bind(
                        allowed_range_minute_granularity[t][0] if self.minute_granularity else allowed_range[t][0],
                        self.__update_ohlcv
                        )                              
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
