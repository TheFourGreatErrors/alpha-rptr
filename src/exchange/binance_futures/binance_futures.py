# coding: UTF-8

#import json
import math
#import os
import traceback
from datetime import datetime, timezone
from inspect import signature
import time
import threading

import pandas as pd
from bravado.exception import HTTPNotFound
from pytz import UTC

from src import (logger, allowed_range, allowed_range_minute_granularity,
                 find_timeframe_string, to_data_frame, resample, delta,
                 FatalError, notify, log_metrics, ord_suffix, sync_obj_with_config)
from src import retry_binance_futures as retry
from src.config import config as conf
from src.exchange_config import exchange_config
from src.exchange.binance_futures.binance_futures_api import Client
from src.exchange.binance_futures.binance_futures_websocket import BinanceFuturesWs
from src.exchange.binance_futures.exceptions import BinanceAPIException, BinanceRequestException


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
            'interval': 0,
            'chaser': False, 
            'retry_maker': 100
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
            'trail_callbak': None,
            'split': 1,
            'interval': 0,
            'chaser': False, 
            'retry_maker': 100
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
        #  Bid quantity L1
        self.bid_quantity_L1 = None
        # Ask quantity L1
        self.ask_quantity_L1 = None
        # callback
        self.best_bid_ask_change_callback = {}

        sync_obj_with_config(exchange_config['binance_f'], BinanceFutures, self)

    def __init_client(self):
        """
        Initialization of the Binance futures client.
        """
        if self.client is not None:
            return        
        api_key = conf['binance_test_keys'][self.account]['API_KEY'] \
                    if self.demo else conf['binance_keys'][self.account]['API_KEY']        
        api_secret = conf['binance_test_keys'][self.account]['SECRET_KEY'] \
                    if self.demo else conf['binance_keys'][self.account]['SECRET_KEY']
        
        self.client = Client(api_key=api_key, api_secret=api_secret, testnet=self.demo)

        # If base_asset, asset_rounding, quote_asset, or quote_rounding are not set, fetch them from the exchange info
        if self.base_asset == None or self.asset_rounding == None or \
            self.quote_asset == None or self.quote_rounding == None:

            exchange_info =  retry(lambda: self.client.futures_exchange_info())
            symbols = exchange_info['symbols']
            symbol = [symbol for symbol in symbols if symbol.get('symbol')==self.pair]                 

            self.base_asset = symbol[0]['baseAsset']
            self.asset_rounding = symbol[0]['quantityPrecision'] 

            self.quote_asset = symbol[0]['quoteAsset']
            self.quote_rounding = symbol[0]['pricePrecision']      

        self.sync()  

        logger.info(f"Asset: {self.base_asset} Rounding: {self.asset_rounding} "\
                    f"- Quote: {self.quote_asset} Rounding: {self.quote_rounding}") 

        logger.info(f"Position Size: {self.position_size:.3f} Entry Price: {self.entry_price:.2f}")
        
    def sync(self):
        """
        Synchronize BinanceFutures instance with the current position, position size, entry price, market price, and margin.
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
    
    def now_time(self):
        """
        Get the current time in UTC timezone.
        Returns:
            datetime: The current time in UTC timezone.
        """
        return datetime.now().astimezone(UTC)
        
    def get_retain_rate(self):
        """
        Get the maintenance margin rate.
        Returns:
            float: The maintenance margin rate (e.g., 0.004 represents 0.4%).
        """
        return 0.004

    def get_lot(self, lot_leverage=1, only_available_balance=True, round_decimals=None):
        """        
        Calculate the lot size based on the provided lot_leverage.
        Args:
            lot_leverage (float, optional): The leverage to use for lot calculation.
                Set to None to automatically use your preset leverage.
            only_available_balance (bool, optional): Flag to use only the available balance
                for lot calculation. Default is True.
            round_decimals (int, optional): The number of decimals to round the calculated lot size.
                Set to None to use the asset_rounding as the default rounding.
        Returns:
            float: The calculated lot size.
        """
        if lot_leverage is None:
            lot_leverage = self.get_leverage()        

        balance = self.get_available_balance() if only_available_balance else self.get_balance() 
      
        if balance is None:
            logger.info(f"Can't Get Balance!")
            return balance

        return round((1 - self.get_retain_rate()) * balance
                      / (1 if self.qty_in_usdt else  self.get_market_price()) * lot_leverage,
                      round_decimals if round_decimals != None else self.asset_rounding)    

    def get_balance(self, asset=None):
        """
        Get the balance for the specified asset.
        Args:
            asset (str, optional): The asset for which to get the balance.
                If not provided, the quote asset will be used as the default.
        Returns:
            float: The balance for the specified asset.
        """
        self.__init_client()
        res = self.get_margin()

        asset = asset if asset else self.quote_asset
        
        if len(res) > 0:
            balances = [p for p in res if p["asset"] == asset]     
            if len(balances) > 0:      
                return float(balances[0]["balance"])
            else:
                logger.info(f"Couldnt find balance for asset: {asset}")                
        return None

    def get_available_balance(self, asset=None):
        """
        Get the available balance for the specified asset,
        considering that some might already be used as collateral for margin.
        Args:
            asset (str, optional): The asset for which to get the available balance.
                If not provided, the quote asset will be used as the default.
        Returns:
            float: The available balance for the specified asset.
        """
        self.__init_client()
        res = self.get_margin()

        asset = asset if asset else self.quote_asset
        
        if len(res) > 0:
            balances = [p for p in res if p["asset"] == asset]     
            if len(balances) > 0:            
                return float(balances[0]["availableBalance"])
            else:
                logger.info(f"Couldnt find available balance for asset: {asset}")               
        return None

    def get_margin(self):
        """
        Get the margin information.
        Returns:
            list: A list of dictionaries containing margin information for various assets.
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
        Get the current leverage.
        Returns:
            float: The current leverage.
        """
        self.__init_client()
        return float(self.get_position()["leverage"])
    

    def set_leverage(self, leverage, symbol=None):
        """
        Set the leverage for the specified symbol.
        Args:
            leverage (float): The leverage to set.
            symbol (str, optional): The symbol for which to set the leverage.
                If not provided, the default symbol (pair) of the instance will be used.
        Returns:
            None
        """
        self.__init_client()

        symbol = self.pair if symbol is None else symbol
        leverage = retry(lambda: self.client.futures_change_leverage(symbol=symbol, leverage=leverage)) 
        logger.info(f"Setting Leverage: {leverage}")
        #return self.get_leverage(symbol)

    def get_account_information(self):
        """
        Get account information about all types of margin balances, assets, and positions.
        https://binance-docs.github.io/apidocs/futures/en/#account-information-v2-user_data        
        Returns:
            dict: Account information as a dictionary.        
        """
        self.account_information = retry(lambda: self.client
                                .futures_account_v2())
        return self.account_information

    def get_position(self):
        """
        Get the current position information for the instance's trading pair.
        Returns:
            dict: Current position information as a dictionary.
        """
        self.__init_client()

        # Unfortunately we cannot rely just on the WebSocket updates
        # (for instance PnL) since binance is not pushing updates for the ACCOUNT_UPDATE stream often enough
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
        Get the current position size of the trading pair.
        Returns:
            float: The current position size.        
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
        Get the current market price of the trading pair.
        Returns:
            float: The current market price.        
        """
        self.__init_client()
        return float(self.get_position()['entryPrice'])

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
            self.market_price = float(retry(lambda: self.client
                                      .futures_symbol_ticker(symbol=self.pair))['price'])
            return self.market_price

    def get_pnl(self):
        """
        Calculate the profit and loss percentage for the current position.
        Returns:
            float: The profit and loss percentage.
        """
        # PnL calculation in %            
        pnl = self.get_profit()* 100/self.get_balance()
        return pnl   

    def get_profit(self, close=None, avg_entry_price=None, position_size=None, commission=None):
        """
        Calculate the profit of the current position.
        Args:
            close (float, optional): The current price. If not provided, the instance's market price is used.
            avg_entry_price (float, optional): The average entry price of the position.
                If not provided, the instance's entry price or the current position's entry price is used.
            position_size (float, optional): The current position size.
                If not provided, the instance's position size or the current position size is used.
            commission (float, optional): The applicable commission rate for this trading pair.
                If not provided, the instance's commission rate is used.
        Returns:
            float: The profit of the current position.
        """
        if close is None:
            close = self.market_price 
        if avg_entry_price is None:
            avg_entry_price = self.entry_price if self.entry_price != None else self.get_position_avg_price()
        if position_size is None:
            position_size = self.get_position_size()
        if commission is None:
            commission = self.get_commission()

        profit = 0
        close_rate = 0

        if position_size > 0:
            close_rate = ((close - avg_entry_price)/avg_entry_price) - commission                 
        elif (position_size < 0):
            close_rate = ((avg_entry_price - close)/avg_entry_price) - commission

        profit = round(abs(position_size)
                        * close_rate * (1 if self.qty_in_usdt else avg_entry_price), self.quote_rounding)

        return profit
        
    def get_trail_price(self):
        """
        Get the current trail price.
        Returns:
            float: The current trail price.
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
        return 0.08 / 100 # 2*0.04 fee

    def cancel_all(self):
        """
        Cancel all open orders for the trading pair.
        """
        self.__init_client()
        res = retry(lambda: self.client.futures_cancel_all_open_orders(symbol=self.pair))
        #for order in orders:
        logger.info(f"Cancel all open orders: {res}")    
        #self.callbacks = {}

    def close_all(self, callback=None, split=1, interval=0, chaser=False, retry_maker=100):
        """
        Close the open position for this trading pair using a market order.
        Args:
            callback (function, optional): A function to call once the underlying order is executed.
            split (int, optional): Number of orders to use for closing the position. Default is 1.
            interval (int, optional): Time interval between split orders. Default is 0.
            chaser (bool, optional): Refer to the order() function. Default is False.
            retry_maker (int, optional): Refer to the order() function. Default is 100.
        """
        self.__init_client()
        position_size = self.get_position_size()
        if position_size == 0:
            return

        side = False if position_size > 0 else True
        
        self.order("Close", side, abs(position_size), 
                   callback=callback, 
                   split=split, interval=interval, 
                   chaser=chaser, retry_maker=retry_maker)

    def cancel(self, id):
        """
        Cancel a specific order by ID.
        Args:
            id (int): The ID of the order to be canceled.
        Returns:
            bool: True if the order was successfully canceled, False otherwise.
        """
        self.__init_client()
        order = self.get_open_order(id)

        if order is None:
            return False

        try:
            retry(lambda: self.client.futures_cancel_order(symbol=self.pair,
                                                           origClientOrderId=order['clientOrderId']))
        except HTTPNotFound:
            return False
        logger.info(f"Cancel Order : (clientOrderId, type, side, quantity, price, stop) = "
                    f"({order['clientOrderId']}, {order['type']}, {order['side']}, {order['origQty']}, "
                    f"{order['price']}, {order['stopPrice']})")
        #self.callbacks.pop(order['clientOrderId'])
        return True

    def __new_order(
        self,
        ord_id,
        side,
        ord_qty,
        limit=0,
        stop=0,
        post_only=False,
        reduce_only=False,
        trailing_stop=0,
        activationPrice=0,
        workingType="CONTRACT_PRICE"
    ):
        """
        Create a new order (do not use directly).

        Args:
            ord_id (str): The order ID (user ID).
            side (str): 'Buy' for long position, 'Sell' for short position.
            ord_qty (float): The quantity to be traded.
            limit (float, optional): Limit price for the order. Defaults to 0.
            stop (float, optional): Stop price trigger for the order. Defaults to 0.
            post_only (bool, optional): If True, the order will be posted as a maker order. Defaults to False.
            reduce_only (bool, optional): If True, the order will only reduce the existing position, not increase it. Defaults to False.
            trailing_stop (float, optional): Binance futures built-in implementation of trailing stop in percentage. Defaults to 0.
            activationPrice (float, optional): Price that triggers Binance futures built-in trailing stop. Defaults to 0.
            workingType (str, optional): Price type to use, "CONTRACT_PRICE" by default. Defaults to "CONTRACT_PRICE".
        """
        #removes "+" from order suffix, because of the new regular expression rule for newClientOrderId updated as ^[\.A-Z\:/a-z0-9_-]{1,36}$ (2021-01-26)
        ord_id = ord_id.replace("+", "k") 

        reduce_only = "true" if reduce_only else "false"
        
        if  trailing_stop > 0 and activationPrice > 0:
            ord_type = "TRAILING_STOP_MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                           side=side, quantity=ord_qty, activationPrice=activationPrice,
                                                           callbackRate=trailing_stop, reduceOnly=reduce_only,
                                                           workingType=workingType))
        elif trailing_stop > 0:
            ord_type = "TRAILING_STOP_MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                            side=side, quantity=ord_qty, callbackRate=trailing_stop,
                                                            reduceOnly=reduce_only, workingType=workingType))
        elif limit > 0 and post_only:
            ord_type = "LIMIT"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                           side=side, quantity=ord_qty, price=limit,
                                                           timeInForce="GTX", reduceOnly=reduce_only))
        elif limit > 0 and stop > 0:
            ord_type = "STOP"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                           side=side, quantity=ord_qty, price=limit,
                                                           stopPrice=stop, reduceOnly=reduce_only,
                                                           workingType=workingType))
        elif limit > 0:   
            ord_type = "LIMIT"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                           side=side, quantity=ord_qty, price=limit, timeInForce="GTC",
                                                           reduceOnly=reduce_only))   
        elif stop > 0:
            ord_type = "STOP_MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                           side=side, quantity=ord_qty, stopPrice=stop,
                                                           reduceOnly=reduce_only, workingType=workingType))        
        elif post_only: # limit order with post only
            ord_type = "LIMIT"
                             
            limit = self.best_bid_price if side == "Buy" else self.best_ask_price                
            # New change coming. GTX and FOK orders will return
            # an error instead of EXPIRED update on WS when they dont
            # meet execution criteria. Release Date: Unknown
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                            side=side, quantity=ord_qty, price=limit,
                                                            timeInForce="GTX", reduceOnly=reduce_only))
        else:
            ord_type = "MARKET"
            retry(lambda: self.client.futures_create_order(symbol=self.pair, type=ord_type, newClientOrderId=ord_id,
                                                           side=side, quantity=ord_qty, reduceOnly=reduce_only))

        if self.enable_trade_log:
            logger.info(f"========= New Order ==============")
            logger.info(f"ID        : {ord_id}")
            logger.info(f"Type      : {ord_type}")
            logger.info(f"Side      : {side}")
            logger.info(f"Qty       : {ord_qty}")
            logger.info(f"Limit     : {limit}")
            logger.info(f"Stop      : {stop}")
            logger.info(f"Red. Only : {reduce_only}")
            logger.info(f"======================================")

            notify(f"New Order\nType: {ord_type}\nSide: {side}\nQty: {ord_qty}\nLimit: {limit}\nStop: {stop}\nRed. Only: {reduce_only}")

    # def __amend_order(self, ord_id, side, ord_qty, limit=0, stop=0, post_only=False):
        """
        Amend an order. (Currently not implemented due to Binance ecosystem limitations.)

        Args:
            ord_id (str): The order ID (user ID) to amend.
            side (str): The side of the order ('Buy' or 'Sell').
            ord_qty (float): The updated quantity for the order.
            limit (float, optional): The updated limit price for the order. Defaults to 0.
            stop (float, optional): The updated stop price trigger for the order. Defaults to 0.
            post_only (bool, optional): If True, the order will be posted as a maker order. Defaults to False.
        """
    # The function is currently not implemented due to limitations in the Binance ecosystem.
    # Code to amend the order would be implemented here if it were available.
    # TODO

    def entry(
        self,
        id,
        long,
        qty,
        limit=0,
        stop=0,
        trailing_stop=0, 
        activationPrice=0, 
        post_only=False,
        reduce_only=False,
        when=True,
        round_decimals=None,
        callback=None,
        workingType="CONTRACT_PRICE",
        split=1,
        interval=0,
        chaser=False,
        retry_maker=100
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
            id (str): Order ID (user ID).
            long (bool): True for a long position, False for a short position.
            qty (float): Quantity to be traded.
            limit (float, optional): Limit price for the order. Defaults to 0.
            stop (float, optional): Stop price trigger for the order. Defaults to 0.
            trailing_stop (float, optional): Binance futures built-in implementation of trailing stop in percentage. Defaults to 0.
            activationPrice (float, optional): Price that triggers Binance futures built-in trailing stop. Defaults to 0.
            post_only (bool, optional): If True, the order will be posted as a maker order. Defaults to False.
            reduce_only (bool, optional): If True, the order will only reduce the existing position, not increase it. Defaults to False.
            when (bool, optional): If True, the order is executed. Defaults to True.
            round_decimals (int, optional): Decimal places to round the order quantity. Automatic if left equal to None. Defaults to None.
            callback (function, optional): A callback function to execute after the order is filled. Defaults to None.
            workingType (str, optional): Price type to use, "CONTRACT_PRICE" by default. Defaults to "CONTRACT_PRICE".
            split (int, optional): Number of orders to split the quantity into (iceberg order). Defaults to 1.
            interval (int, optional): Interval between orders (iceberg order). Defaults to 0.
            chaser (bool, optional): If True, a chaser order is placed to follow the Best Bid/Ask (BBA) Price.
                As soon as BBA changes, the existing order is canceled, and a new one is placed at the new BBA for the remaining quantity. Defaults to False.
            retry_maker (int, optional): Number of times to retry placing a maker order if it fails. Defaults to 100.
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

        self.order(id, long, ord_qty, limit=limit, stop=stop, post_only=post_only, reduce_only=reduce_only,
                    trailing_stop=trailing_stop, activationPrice=activationPrice, when=when, callback=callback, 
                    workingType=workingType, split=split, interval=interval, chaser=chaser, retry_maker=retry_maker)

    def entry_pyramiding(
        self,
        id,
        long,
        qty,
        limit=0,
        stop=0,
        trailing_stop=0, 
        activationPrice=0, 
        post_only=False,
        reduce_only=False,
        cancel_all=False,
        pyramiding=2,
        when=True,
        round_decimals=None,
        callback=None,
        workingType="CONTRACT_PRICE",
        split=1,
        interval=0,
        chaser=False,
        retry_maker=100
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
            id (str): Order ID (user ID).
            long (bool): True for a long position, False for a short position.
            qty (float): Quantity to be traded.
            limit (float, optional): Limit price for the order. Defaults to 0.
            stop (float, optional): Stop price trigger for the order. Defaults to 0.
            trailing_stop (float, optional): Binance futures built-in implementation of trailing stop in percentage. Defaults to 0.
            activationPrice (float, optional): Price that triggers Binance futures built-in trailing stop. Defaults to 0.
            post_only (bool, optional): If True, the order will be posted as a maker order. Defaults to False.
            reduce_only (bool, optional): If True, the order will only reduce the existing position, not increase it. Defaults to False.
            cancel_all (bool, optional): If True, cancels all open orders before placing the entry order. Defaults to False.
            pyramiding (int, optional): Number of entries in the pyramiding strategy. Defaults to 2.
            when (bool, optional): If True, the order is executed. Defaults to True.
            round_decimals (int, optional): Decimal places to round the order quantity. Automatic if left equal to None. Defaults to None.
            callback (function, optional): A callback function to execute after the order is filled. Defaults to None.
            workingType (str, optional): Price type to use, "CONTRACT_PRICE" by default. Defaults to "CONTRACT_PRICE".
            split (int, optional): Number of orders to split the quantity into (iceberg order). Defaults to 1.
            interval (int, optional): Interval between orders (iceberg order). Defaults to 0.
            chaser (bool, optional): If True, a chaser order is placed to follow the Best Bid/Ask (BBA) Price.
                As soon as BBA changes, the existing order is canceled, and a new one is placed at the new BBA for the remaining quantity. Defaults to False.
            retry_maker (int, optional): Number of times to retry placing a maker order if it fails. Defaults to 100.
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
     
        # make sure it doesnt spam small entries, which in most cases would trigger risk management orders evaluation,
        # you can make this less than 2% if needed  
        if ord_qty < ((pyramiding*qty) / 100) * 2:
            return     

        ord_qty = round(ord_qty, round_decimals if round_decimals != None else self.asset_rounding)

        self.order(id, long, ord_qty, limit=limit, stop=stop, post_only=post_only, reduce_only=reduce_only,
                    trailing_stop=trailing_stop, activationPrice=activationPrice, when=when, callback=callback, 
                    workingType=workingType, split=split, interval=interval, chaser=chaser, retry_maker=retry_maker)

    def order(
        self,
        id,
        long,
        qty,
        limit=0, 
        stop=0, 
        post_only=False, 
        reduce_only=False,
        trailing_stop=0, 
        activationPrice=0, 
        when=True,
        round_decimals=None, 
        callback=None,
        workingType="CONTRACT_PRICE", 
        split=1, 
        interval=0,
        chaser=False,
        retry_maker=100
    ):
        """
        Places an entry order with various options.

        Args:
            id (str): Order ID (user ID).
            long (bool): True for a long position, False for a short position.
            qty (float): Quantity to be traded.
            limit (float, optional): Limit price for the order. Defaults to 0.
            stop (float, optional): Stop price trigger for the order. Defaults to 0.
            trailing_stop (float, optional): Binance futures built-in implementation of trailing stop in percentage. Defaults to 0.
            activationPrice (float, optional): Price that triggers Binance futures built-in trailing stop. Defaults to 0.
            post_only (bool, optional): If True, the order will be posted as a maker order. Defaults to False.
            reduce_only (bool, optional): If True, the order will only reduce the existing position, not increase it. Defaults to False.
            when (bool, optional): If True, the order is executed. Defaults to True.
            round_decimals (int, optional): Decimal places to round the order quantity. Automatic if left equal to None. Defaults to None.
            callback (function, optional): A callback function to execute after the order is filled. Defaults to None.
            workingType (str, optional): Price type to use, "CONTRACT_PRICE" by default. Defaults to "CONTRACT_PRICE".
            split (int, optional): Number of orders to split the quantity into (iceberg order). Defaults to 1.
            interval (int, optional): Interval between orders (iceberg order). Defaults to 0.
            chaser (bool, optional): If True, a chaser order is placed to follow the Best Bid/Ask (BBA) Price.
                As soon as BBA changes, the existing order is canceled, and a new one is placed at the new BBA for the remaining quantity. Defaults to False.
            retry_maker (int, optional): Number of times to retry placing a maker order if it fails. Defaults to 100.
        """
        self.__init_client()

        # if self.get_margin()['excessMargin'] <= 0 or qty <= 0:
        #     return

        if not when:
            return

        side = "BUY" if long else "SELL"
        ord_qty = abs(round(qty, round_decimals if round_decimals != None else self.asset_rounding))
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
                    exchange.order(sub_ord_id, long, s_ord_qty, limit=limit, stop=0, 
                                   post_only=post_only, reduce_only=reduce_only,
                                    trailing_stop=trailing_stop, activationPrice=activationPrice, 
                                    workingType=workingType, callback=sub_ord_callback)

            sub_ord_id = f"{id}_sub1"
            self.order(sub_ord_id, long, sub_ord_qty, limit=limit, stop=stop, 
                       post_only=post_only, reduce_only=reduce_only,
                        trailing_stop=trailing_stop, activationPrice=activationPrice, 
                        workingType=workingType, callback=split_order(1))
            return

        if chaser:

            exchange = self

            class Chaser:

                def __init__(self, 
                             order_id, 
                             long, qty, 
                             limit, stop, 
                             post_only, 
                             reduce_only, 
                             trailing_stop, 
                             activationPrice, 
                             callback, 
                             workingType):
                    self.order_id = order_id
                    self.long = long
                    self.qty = qty
                    # stop-market orders cannot be chased as they will
                    # be triggered and filled almost immediately
                    # with out any time for intervention.
                    # so converting them into stop-limit with limit=stop
                    self.limit = stop if stop != 0 and limit == 0 else limit
                    self.stop = stop
                    self.post_only = post_only #set to True for maker orders
                    self.reduce_only = reduce_only
                    self.callback = callback

                    self.callback_type = None
                    if callable(self.callback):                        
                        self.callback_type = True if len(signature(self.callback).parameters) > 0 else False

                    self.workingType = workingType

                    self.started = None
                    self.start_price = 0
                    self.count = 0
                    self.current_order_id = None
                    # if no limit price is set, set it to best bid/ask price
                    self.current_order_price = self.limit if self.limit != 0 else self.price()
                    # First order will be sent without post-only flag irrespective
                    # and post-only will be used once the order is triggered
                    self.order(retry_maker, 
                               self.sub_order_id(), 
                               self.long, self.qty, 
                               self.current_order_price, 
                               self.stop, self.post_only if self.stop==0 else False, 
                               self.reduce_only, 
                               self.workingType, 
                               self.on_order_update)     
                    
                    self.filled = {}
                    
                def sub_order_id(self):
                    return f"{self.order_id}_{self.count}"
                
                def filled_qty(self):
                    filled_qty = 0
                    for value in self.filled.values():
                        filled_qty += value[0]
                    
                    return round(filled_qty, exchange.asset_rounding)
                
                def remaining_qty(self):
                    return round(self.qty - self.filled_qty(), exchange.asset_rounding)
                
                def price(self):
                    return exchange.best_bid_price if self.long else exchange.best_ask_price 

                # Used to follow Bed Bid/Ask to chase 
                # limit orders at a specifid price.
                # The actual chaser starts once the limit price 
                # is crossed. Useful for TP orders.
                def limit_tracker(self, limit):

                    logger.info(f"Chaser: Limit Tracker Active: {self.order_id}")

                    #watch for best bid/ask price to cross limit price
                    limit_chaser = self
                    def tracker(best_bid_changed, best_ask_changed):

                        if (exchange.best_bid_price <= limit and limit_chaser.long) or \
                            (exchange.best_ask_price >= limit_chaser.limit and not limit_chaser.long):
                            limit_chaser.start()

                    exchange.add_ob_callback(self.order_id, tracker)                    

                def start(self):
                    self.started = True #started
                    self.start_price = self.price()
                    exchange.add_ob_callback(self.order_id, self.on_bid_ask_change)      
                    logger.info(f"Chaser Active: {self.order_id}")              

                def end(self):
                    exchange.remove_ob_callback(self.order_id)

                def avg_price(self, print_suborders=False):
                    order_value = 0
                    for key, value in self.filled.items():
                        if value[0] > 0:
                            if print_suborders:
                                logger.info(f"{key} - {value[0]} @ {value[1]}")
                            order_value += value[0]*value[1]
                    return round(order_value/self.qty, exchange.quote_rounding)

                def stats(self, status="FILLED"):
                    logger.info(f"Chaser Order Stats:")
                    logger.info(f"--------------------------------------")
                    logger.info(f"Order: {self.order_id} Status: {status}")
                    logger.info(f"Start Price: {self.start_price}")
                    logger.info(f"--------------------------------------")
                    avg_price = self.avg_price(True)
                    slippage = (avg_price - self.start_price if self.long else self.start_price - avg_price)/self.start_price
                    logger.info(f"--------------------------------------")
                    logger.info(f"Avg Price: {avg_price}")
                    logger.info(f"Slippage: {slippage*100:.2f}%")
                    logger.info(f"--------------------------------------")

                    log_metrics(datetime.utcnow(), "chaser", {
                        "side": "BUY" if self.long else "SELL",
                        "quantity": self.qty,
                        "start_price": self.start_price,
                        "avg_price": avg_price,
                        "slippage": round(slippage*100, 3)                        
                    },
                    {
                        "exchange": conf["args"].exchange,
                        "account": exchange.account,
                        "pair": exchange.pair,
                        "base_asset": exchange.base_asset,
                        "quote_asset": exchange.quote_asset,
                        "strategy": conf["args"].strategy
                    })

                def cancel(self):
                    self.started = False #canceled
                    if self.current_order_id is not None:
                        exchange.remove_ob_callback(self.order_id)
                        self.cancel_order(self.current_order_id)

                def cancel_order(self, id):
                    try:
                        exchange.cancel(id)
                    except BinanceAPIException as e:
                        error_code  = abs(int(e.code))
                        if (error_code == 2011):
                            logger.info("Chaser: Cancel Order: Unknown order. Already filled?")
                            return
                        raise e

                def order(self, retry, id, long, qty, limit, stop, post_only, reduce_only, workingType, callback):
                    # try fixed number of times
                    for x in range(retry):
                        try:  
                            exchange.order(id, long, qty, limit=limit, stop=stop, post_only=post_only, 
                                           reduce_only=reduce_only, workingType=workingType, callback=callback)
                            self.current_order_id = id
                            break
                        except BinanceAPIException as e:
                            error_code  = abs(int(e.code))
                            if x < (retry-1):
                                # Upcoming change:
                                # When placing order with timeInForce FOK or GTX(Post-only), 
                                # if the order can't meet execution criteria, order will get 
                                # rejected directly and receive error response, 
                                # no order_trade_update message in websocket. 
                                # The order can't be found in GET /fapi/v1/order or GET /fapi/v1/allOrders.
                                if (error_code == 5022):
                                    # limit > cmp for long order or vice versa
                                    # and would fail if its a post-only order
                                    # Solution: retry with limit set to best bid/ask
                                    time.sleep(1)
                                    ticker=exchange.get_orderbook_ticker()
                                    limit=float(ticker["bidPrice"] if long else ticker["askPrice"])
                                    continue
                                if (error_code == 2021):
                                    # stop < cmp for long order and vice versa
                                    # Will throw error that stop will be triggered immediately
                                    # Solution: retyr with stop = 0
                                    time.sleep(1)
                                    stop=0
                                    continue
                            raise e

                def on_bid_ask_change(self, best_bid_changed, best_ask_changed):

                    if (self.long and best_bid_changed) or (not self.long and best_ask_changed):
                        logger.info(f"Chaser: Price Changed - {self.price()}")

                        if self.current_order_id is not None :
                            exchange.remove_ob_callback(self.order_id)
                            self.cancel_order(self.current_order_id)
                            logger.info(f"Chaser: Cancel Order : {self.current_order_id} : Price Changed - {self.current_order_price} -> {self.price()}")
                            self.current_order_id = None
                        
                def on_order_update(self, order):
                    
                    #save filled qty
                    self.filled[order["id"]] = [order["filled"], order["avgprice"]]
                    
                    if order["status"] == "NEW":
                        logger.info(f"Chaser Event: Order Accepted - {order['id']}")
                        if self.started is None:
                            # market order - start chasing immediately
                            if self.stop == 0 and self.limit == 0:
                                self.start()
                            # limit order - start limit tracker
                            elif self.stop == 0 and self.limit != 0:
                                self.limit_tracker(self.limit)        
                        else:
                            # new sub-order - start ob chaser
                            exchange.add_ob_callback(self.order_id, self.on_bid_ask_change)

                    if self.stop != 0 and order["status"] == "TRIGGERED":
                        logger.info(f"Chaser Event: {order['id']} is Triggered @ {order['stop']}!")
                        if self.limit == self.stop:
                            # there was no limit set
                            self.start()
                        else:
                            self.limit_tracker(self.limit)
                        return

                    if order["status"] == "FILLED":
                        self.current_order_id = None
                        self.end()
                        self.stats(status=order["status"])
                        if self.callback_type is not None:
                            if self.callback_type:
                                order['id'] = self.order_id
                                order['filled'] = self.filled_qty()
                                order['qty'] = self.qty
                                order['limit'] = self.limit
                                order['stop'] = self.stop  
                                order['avgprice'] = self.avg_price()                              

                                self.callback(order)
                            else:
                                self.callback()

                    if order["status"] == "CANCELED" or order["status"] == "EXPIRED":
                        logger.info(f"Chaser Event: Order Cancelled: {order['id']} @ {order['limit']}")
                        if self.started is not True: #Chaser did not Cancel this order internally
                            self.end()
                            if self.callback_type is not None:
                                if self.callback_type:
                                    order['id'] = self.order_id
                                    order['filled'] = self.filled_qty()
                                    order['qty'] = self.qty
                                    order['limit'] = self.limit
                                    order['stop'] = self.stop     
                                    order['avgprice'] = self.avg_price()
                                    
                                    self.callback(order)
                        else:
                            self.current_order_id = None
                            self.current_order_price = self.price()
                            self.count += 1
                            self.order(retry_maker, 
                                       self.sub_order_id(), 
                                       self.long, 
                                       self.remaining_qty(), 
                                       self.current_order_price, 
                                       0, 
                                       self.post_only, 
                                       self.reduce_only, 
                                       self.workingType, 
                                       self.on_order_update)               
            
            # start the chaser
            return Chaser(id, long, qty, limit, stop, post_only, reduce_only, 
                          trailing_stop, activationPrice, callback, workingType)

        self.callbacks[ord_id] = callback

        if order is None:
            self.__new_order(ord_id, side, ord_qty, limit, stop, post_only, reduce_only,
                              trailing_stop, activationPrice, workingType)
        else:
            self.__new_order(ord_id, side, ord_qty, limit, stop, post_only, reduce_only,
                              trailing_stop, activationPrice, workingType)
            #self.__amend_order(ord_id, side, ord_qty, limit, stop, post_only)
            return    

    def get_open_order_qty(self, id):
        """
        Get the remaining quantity of an open order by its ID.
        Args:
            id (str): Order ID - Returns the quantity of the first order from the list of orders that matches the ID.
        Returns:
            float or None: Remaining order quantity if the order is found, None otherwise.
        """     
        order = self.get_open_order(id=id)        

        if order is None:
            return None
        
        order_qty = float(order['origQty']) - float(order['executedQty'])
        return order_qty

    def get_open_order(self, id):
        """
        Get an open order by its ID.
        Args:
            id (str): Order ID for this pair.
        Returns:
            dict or None: If multiple orders are found starting with the given ID, return only the first one. None if no matching order is found.
        """
        self.__init_client()
        open_orders = retry(lambda: self.client
                            .futures_get_open_orders(symbol=self.pair))                                   
        filtered_orders = [o for o in open_orders if o["clientOrderId"].startswith(id)]
        if not filtered_orders:
            return None
        if len(filtered_orders) > 1:
            logger.info(f"Found more than 1 order starting with given id. Returning only the first one!")
        return filtered_orders[0]      
    
    def get_open_orders(self, id=None):
        """
        Get a list of open orders.
        Args:
            id (str, optional): If provided, return only orders whose ID starts with the provided string.
        Returns:
            list or None: List of open orders that match the ID criteria, or None if no open orders are found.
        """
        self.__init_client()
        open_orders = retry(lambda: self.client
                            .futures_get_open_orders(symbol=self.pair))                                   
        filtered_orders = [o for o in open_orders if o["clientOrderId"].startswith(id)] if id else open_orders 
        return filtered_orders if filtered_orders else None

    def get_orderbook_ticker(self):
        """
        Get the ticker data for the order book.
        Returns:
            data: Ticker data for the order book.
        """
        orderbook_ticker = retry(lambda: self.client.futures_orderbook_ticker(symbol=self.pair))
        return orderbook_ticker

    def exit(
            self, 
            profit=0, 
            loss=0, 
            trail_offset=0, 
            profit_callback=None, 
            loss_callback=None, 
            trail_callback=None, 
            split=1, 
            interval=0,
            chaser=False,
            retry_maker=100
    ):
        """
        Define profit-taking, stop loss, and trailing settings for an exit strategy.(Independent of sltp())
        Args:
            profit (float): Profit percentage at which to trigger an exit.
            loss (float): Stop loss percentage at which to trigger an exit.
            trail_offset (float): Trailing stop price offset.
            profit_callback (function, optional): Callback function to call if the exit happens with a profit.
            loss_callback (function, optional): Callback function to call if the exit happens with a loss.
            trail_callback (function, optional): Callback function to call if a trailing exit happens.
            split (int): Number of orders to split the quantity into (iceberg order).
            interval (int): Interval between orders (iceberg order).
            chaser (bool): If True, use a chaser order to follow the Best Bid/Ask Price, updating the order whenever BBA changes.
            retry_maker (int): Number of times to retry placing a maker order if it fails.
        """
        self.exit_order = {
            'profit': profit, 
            'loss': loss, 
            'trail_offset': trail_offset, 
            'profit_callback': profit_callback,
            'loss_callback': loss_callback,
            'trail_callback': trail_callback,
            'split': split,
            'interval': interval,
            'chaser': chaser,
            'retry_maker': retry_maker
        }
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
            stop_short_callback=None, 
            workingType="CONTRACT_PRICE", 
            split=1, 
            interval = 0,
            chaser=False,
            retry_maker=100
            ):
        """
        Implement a simple take profit and stop loss strategy. (Independent of exit())
        Sends a reduce-only stop-loss order upon entering a position.

        Args:
            profit_long (float): Profit target value in percentage for long positions.
            profit_short (float): Profit target value in percentage for short positions.
            stop_long (float): Stop loss value in percentage for long positions.
            stop_short (float): Stop loss value in percentage for short positions.
            eval_tp_next_candle (bool): If True, evaluate the take profit condition at the next candle.
            round_decimals (int, optional): Round decimals.
            profit_long_callback (function, optional): Callback function to call if the take profit is triggered on a Long position.
            profit_short_callback (function, optional): Callback function to call if the take profit is triggered on a Short position.
            stop_long_callback (function, optional): Callback function to call if the stop loss is triggered on a Long position.
            stop_short_callback (function, optional): Callback function to call if the stop loss is triggered on a Short position.
            workingType (str): CONTRACT_PRICE or MARK_PRICE to use with the underlying stop order.
            split (int): Number of orders to split the quantity into (iceberg order).
            interval (int): Interval between orders (iceberg order).
            chaser (bool): If True, use a chaser order to follow the Best Bid/Ask Price, updating the order whenever BBA changes.
            retry_maker (int): Number of times to retry placing a maker order if it fails.
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
            'interval': interval,
            'chaser': chaser,
            'retry_maker': retry_maker
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

        unrealised_pnl = float(self.get_position()['unRealizedProfit'])

        # trail asset
        if self.get_exit_order()['trail_offset'] > 0 and self.get_trail_price() > 0:
            if self.get_position_size() > 0 and \
                    self.get_market_price() - self.get_exit_order()['trail_offset'] < self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all(self.get_exit_order()['trail_callback'],
                                self.get_exit_order()['split'], self.get_exit_order()['interval'],
                                self.get_exit_order()['chaser'], self.get_exit_order()['retry_maker'])
            elif self.get_position_size() < 0 and \
                    self.get_market_price() + self.get_exit_order()['trail_offset'] > self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all(self.get_exit_order()['trail_callback'],
                                self.get_exit_order()['split'], self.get_exit_order()['interval'],
                                self.get_exit_order()['chaser'], self.get_exit_order()['retry_maker'])

        #stop loss
        if unrealised_pnl < 0 and \
                0 < self.get_exit_order()['loss'] < abs(unrealised_pnl):
            logger.info(f"Loss cut by stop loss: {self.get_exit_order()['loss']}")
            self.close_all(self.get_exit_order()['loss_callback'],
                            self.get_exit_order()['split'], self.get_exit_order()['interval'],
                            self.get_exit_order()['chaser'], self.get_exit_order()['retry_maker'])

        # profit take
        if unrealised_pnl > 0 and \
                0 < self.get_exit_order()['profit'] < abs(unrealised_pnl):
            logger.info(f"Take profit by stop profit: {self.get_exit_order()['profit']}")
            self.close_all(self.get_exit_order()['profit_callback'],
                            self.get_exit_order()['split'], self.get_exit_order()['interval'],
                            self.get_exit_order()['chaser'], self.get_exit_order()['retry_maker'])

    # simple TP implementation

    def eval_sltp(self):
        """
        Evaluate and execute the simple take profit and stop loss implementation.
        - Sends a reduce-only stop loss order upon entering a position.
        - Requires setting values with sltp() prior.
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
                    time.sleep(1)                                         
                    self.cancel(id=tp_order['clientOrderId'])
                    time.sleep(1)
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True, 
                               callback=self.get_sltp_values()['profit_long_callback'], 
                               workingType=self.get_sltp_values()['sltp_working_type'],
                               split=self.get_sltp_values()['split'], 
                               interval=self.get_sltp_values()['interval'],
                               chaser=self.get_sltp_values()['chaser'],
                               retry_maker=self.get_sltp_values()['retry_maker'])
                else:               
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True, 
                               callback=self.get_sltp_values()['profit_long_callback'], 
                               workingType=self.get_sltp_values()['sltp_working_type'],
                               split=self.get_sltp_values()['split'], 
                               interval=self.get_sltp_values()['interval'],
                               chaser=self.get_sltp_values()['chaser'],
                               retry_maker=self.get_sltp_values()['retry_maker'])
        if tp_percent_short > 0 and is_tp_full_size == False:
            if pos_size < 0:                
                tp_price_short = round(avg_entry -(avg_entry*tp_percent_short), self.quote_rounding)
                if tp_order is not None:
                    time.sleep(1)                                                        
                    self.cancel(id=tp_order['clientOrderId'])
                    time.sleep(1)
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True, 
                               callback=self.get_sltp_values()['profit_short_callback'], 
                               workingType=self.get_sltp_values()['sltp_working_type'],
                               split=self.get_sltp_values()['split'], interval=self.get_sltp_values()['interval'],
                               chaser=self.get_sltp_values()['chaser'],
                               retry_maker=self.get_sltp_values()['retry_maker'])
                else:
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True, 
                               callback=self.get_sltp_values()['profit_short_callback'], 
                               workingType=self.get_sltp_values()['sltp_working_type'],
                               split=self.get_sltp_values()['split'], 
                               interval=self.get_sltp_values()['interval'],
                               chaser=self.get_sltp_values()['chaser'],
                               retry_maker=self.get_sltp_values()['retry_maker'])
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
                    time.sleep(1)                                    
                    self.cancel(id=sl_order['clientOrderId'])
                    time.sleep(1)
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True, 
                               callback=self.get_sltp_values()['stop_long_callback'], 
                               workingType=self.get_sltp_values()['sltp_working_type'], 
                               split=self.get_sltp_values()['split'], 
                               interval=self.get_sltp_values()['interval'],
                               chaser=self.get_sltp_values()['chaser'],
                               retry_maker=self.get_sltp_values()['retry_maker'])
                else:  
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True, 
                               callback=self.get_sltp_values()['stop_long_callback'], 
                               workingType=self.get_sltp_values()['sltp_working_type'],
                               split=self.get_sltp_values()['split'], 
                               interval=self.get_sltp_values()['interval'],
                               chaser=self.get_sltp_values()['chaser'],
                               retry_maker=self.get_sltp_values()['retry_maker'])
        if sl_percent_short > 0 and is_sl_full_size == False:
            if pos_size < 0:
                sl_price_short = round(avg_entry + (avg_entry*sl_percent_short), self.quote_rounding)
                if sl_order is not None: 
                    time.sleep(1)                                         
                    self.cancel(id=sl_order['clientOrderId'])
                    time.sleep(1)
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True, 
                               callback=self.get_sltp_values()['stop_short_callback'], 
                               workingType=self.get_sltp_values()['sltp_working_type'], 
                               split=self.get_sltp_values()['split'], 
                               interval=self.get_sltp_values()['interval'],
                               chaser=self.get_sltp_values()['chaser'],
                               retry_maker=self.get_sltp_values()['retry_maker']) 
                else:  
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True, 
                               callback=self.get_sltp_values()['stop_short_callback'], 
                               workingType=self.get_sltp_values()['sltp_working_type'],
                               split=self.get_sltp_values()['split'], 
                               interval=self.get_sltp_values()['interval'],
                               chaser=self.get_sltp_values()['chaser'],
                               retry_maker=self.get_sltp_values()['retry_maker'])                         
        
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
            if left_time > right_time:
                break
            
            left_time_to_timestamp = int(datetime.timestamp(left_time)*1000)
            right_time_to_timestamp = int(datetime.timestamp(right_time)*1000)   

            logger.info(f"fetching OHLCV data - {left_time}")         

            source = retry(lambda: self.client.futures_klines(symbol=self.pair, 
                                                              interval=fetch_bin_size,
                                                              startTime=left_time_to_timestamp, 
                                                              endTime=right_time_to_timestamp,
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
        # Binance can output wierd timestamps - Eg. 2021-05-25 16:04:59.999000+00:00
        # We need to round up to the nearest second for further processing
        new_data = new_data.rename(index={new_data.iloc[0].name: new_data.iloc[0].name.ceil(freq='1T')})               

        # If OHLCV data is not initialized, create and fetch data
        if self.timeframe_data is None:
            self.timeframe_data = {}            
            for t in self.bin_size:                              
                end_time = datetime.now(timezone.utc)
                start_time = end_time - self.ohlcv_len * delta(t)
                self.timeframe_data[t] = self.fetch_ohlcv(t, start_time, end_time)
                #logger.info(f"timeframe_data: {self.timeframe_data}") 

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

                logger.info(f"Initial Buffer Fill - Last Candle: {self.timeframe_data[t].iloc[-1].name}")   
        #logger.info(f"timeframe_data: {self.timeframe_data}") 

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
                notify(f"An error occurred. {e}")
                notify(traceback.format_exc())
   
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
        Update the wallet data.

        This function is called when there is an update to the wallet. It keeps track of the current wallet
        balance and other relevant information related to the trading account.

        Args:
            action (str): The action associated with the update (e.g., 'update', 'insert', 'delete').
            wallet (dict): The updated wallet data, typically containing balance and other related information.

        Returns:
            None
        """
        self.wallet = wallet #{**self.wallet, **wallet} if self.wallet is not None else self.wallet        
    
    def __on_update_order(self, action, order):
        """
        Update order status
        https://binance-docs.github.io/apidocs/futures/en/#event-order-update

        This function is called when there is an update to the status of an order. It handles various order
        events such as order creation, cancellation, filling, expiration, etc., and executes any registered
        callbacks associated with those events.

        Args:
            action (str): The action associated with the update (e.g., 'update', 'insert', 'delete').
            order (dict): The updated order data, typically containing information like order ID, type,
                        status, quantity, price, stop price, etc.

        Returns:
            None
        """
        order_info = {}

        # Normalize Order Info to canonical names
        order_info["id"]            = order['c']  # Client Order ID
        order_info["type"]          = order['o']  # LIMIT, MARKET, STOP, STOP_MARKET, TAKE_PROFIT, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET
        order_info["uses"]          = order['wt'] # CONTRACT_PRICE, MARK_PRICE (for stop orders)
        order_info["side"]          = order['S']  # BUY, SELL
        order_info["status"]        = order['X']  # NEW, CANCELED, EXPIRED, PARTIALLY_FILLED, FILLED
        order_info["timeinforce"]   = order['f']  # GTC, IOC, FOK, GTX
        order_info["qty"]           = float(order['q'])  # order quantity
        order_info["filled"]        = float(order['z'])  # filled quantity
        order_info["limit"]         = float(order['p'])  # limit price
        order_info["stop"]          = float(order['sp']) # stop price
        order_info["avgprice"]      = float(order['ap']) # average price
        order_info["reduceonly"]    = order['R'] # Reduce Only Order


        self.order_update = order_info

        order_log = False

        callback = self.callbacks.get(order['c'], None)
        all_updates = None
        if callable(callback):
            if len(signature(callback).parameters) > 0: # check if the callback accepts order argument
                all_updates = True # call the callback with order_info oject on all relevant updates from WS
            else:
                all_updates = False # call the callback without any arguements only once the order is filled

        # currently only these events will use callbacks
        if(order_info['status'] == "NEW"
           or order_info['status'] == "CANCELED" 
           or order_info['status'] == "EXPIRED" 
           or order_info['status'] == "PARTIALLY_FILLED" 
           or order_info['status'] == "FILLED"):
            
            if(order_info['status'] == "NEW"):
                if all_updates:
                    callback(order_info)    

            # If STOP PRICE is set for a GTC Order and filled quanitity is 0 then EXPIRED means TRIGGERED
            # When stop price is hit, the stop order expires and converts into a limit/market order
            if(order_info["stop"] > 0 
               and order_info["timeinforce"] == "GTC" 
               and order_info["filled"] == 0 
               and order_info['status'] == "EXPIRED"):
                
                order_info["status"] = "TRIGGERED" 
                
                order_log = True  
                if all_updates:
                    callback(order_info)    

            if(order_info['status'] == "CANCELED" or order_info['status'] == "EXPIRED"):
                
                order_log = True                  
                self.callbacks.pop(order['c'], None) # Removes the respective order callback 
                
                if all_updates:
                    callback(order_info) 
                
            #only after order is completely filled
            if order_info['status'] == "PARTIALLY_FILLED" or order_info['status'] == "FILLED":

                if self.order_update_log and order_info['status'] == "FILLED" and order_info["qty"] == order_info["filled"]:

                    order_log = True                    
                    self.callbacks.pop(order['c'], None)  # Removes the respective order callback 
                    
                if all_updates is True:
                    callback(order_info)
                elif all_updates is False and order_info['status'] == "FILLED":
                    callback()
        
        if order_log == True:
            logger.info(f"========= Order Update ==============")
            logger.info(f"ID     : {order_info['id']}") # Clinet Order ID
            logger.info(f"Type   : {order_info['type']}")
            logger.info(f"Uses   : {order_info['uses']}")
            logger.info(f"Side   : {order_info['side']}")
            logger.info(f"Status : {order_info['status']}")
            logger.info(f"TIF    : {order_info['timeinforce']}")
            logger.info(f"Qty    : {order_info['qty']}")
            logger.info(f"Filled : {order_info['filled']}")
            logger.info(f"Limit  : {order_info['limit']}")
            logger.info(f"Stop   : {order_info['stop']}")
            logger.info(f"APrice : {order_info['avgprice']}")
            logger.info(f"======================================")

        # Evaluation of profit and loss
        # self.eval_exit()
        # self.eval_sltp()
        
    def __on_update_position(self, action, position):
        """
        Update the position data.

        This function is called when there is an update to the position. It filters the position data
        for the current trading pair and then checks if the position size has changed. If the position
        size has changed, it updates the trail price to the current market price. It also updates the
        internal position data and evaluates the profit and loss.

        Args:
            action (str): The action associated with the update (e.g., 'update', 'insert', 'delete').
            position (list): List of position data, each containing information like entry price,
                            position amount, margin type, unrealized profit, etc.

        Returns:
            None
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
        if self.is_exit_order_active:
            self.eval_exit()
        if self.is_sltp_active:
            self.eval_sltp()

    def __on_update_margin(self, action, margin):
        """
        Update the margin data.

        This function is called when there is an update to the margin. It keeps track of the available
        balance and cross-wallet balance. It then calculates and logs the profit and loss percentage.
        The margin data is used for risk management and evaluating the overall account balance.

        Args:
            action (str): The action associated with the update (e.g., 'update', 'insert', 'delete').
            margin (dict): The updated margin data, typically containing balance and cross-wallet balance.

        Returns:
            None
        """
        if self.margin is not None:
            self.margin[0] = {
                                "asset": self.quote_asset,
                                "balance": float(margin['wb']),
                                "crossWalletBalance": float(margin['cw'])
                             }             
        else: self.get_margin() 

        balance = float(self.margin[0]['balance'])
        position_size = self.get_position_size()
        pnl = round(self.get_pnl())
        profit = self.get_profit()
        notify(f"Balance: {balance}\nPosition Size: {position_size}\nPnL: {profit:.2f}({pnl}%)")
        logger.info(f"Balance: {balance} Position Size: {position_size} PnL: {profit:.2f}({pnl}%)")     

        log_metrics(datetime.utcnow(), "margin", {
            "balance": balance,
            "margin": balance+profit,
            "profit": profit,
            "pnl": pnl
        },
        {
            "exchange": conf["args"].exchange,
            "account": self.account,
            "pair": self.pair,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "strategy": conf["args"].strategy
        })

    def add_ob_callback(self, id, callback):
        """
        Add a callback for order book changes.

        This function allows adding a callback function to be triggered when there are changes to the
        order book (best bid and best ask prices). The registered callbacks will be executed with
        arguments indicating whether the best bid and/or best ask prices have changed.

        Args:
            id (str): Identifier for the callback (usually an integer or string).
            callback (function): The callback function to be executed on order book changes.

        Returns:
            None
        """
        self.best_bid_ask_change_callback[id] = callback

    def remove_ob_callback(self, id):
        """
        Remove a previously added callback for order book changes.

        This function allows removing a callback function that was previously added using the
        'add_ob_callback' method. After removing the callback, it will no longer be triggered when there
        are changes to the order book (best bid and best ask prices).

        Args:
            id (str): Identifier for the callback to be removed (usually an integer or string).

        Returns:
            None
        """
        return self.best_bid_ask_change_callback.pop(id, None)

    def __on_update_bookticker(self, action, bookticker):
        """
        Update the best bid and best ask prices.

        This function is called when there is an update to the order book ticker. It updates the best
        bid and best ask prices and then triggers the registered callbacks for order book changes,
        passing information about whether the best bid and/or best ask prices have changed.

        Args:
            action (str): The action associated with the update (e.g., 'update', 'insert', 'delete').
            bookticker (dict): The updated order book ticker data, containing best bid and best ask prices.

        Returns:
            None
        """
        best_bid_changed = False

        if( self.best_bid_price != float(bookticker['b']) ):
            self.best_bid_price = float(bookticker['b'])
            best_bid_changed = True

        best_ask_changed = False            

        if (self.best_ask_price != float(bookticker['a']) ):
            self.best_ask_price = float(bookticker['a']) 
            best_ask_changed = True
            
        if best_bid_changed or best_ask_changed:
            for callback in self.best_bid_ask_change_callback.copy().values():
                if callable(callback):
                    callback(best_bid_changed, best_ask_changed)  

        self.bid_quantity_L1 = float(bookticker['B'])         
        self.ask_quantity_L1 = float(bookticker['A']) 
        #logger.info(f"best bid: {self.best_bid_price}          best_ask: {self.best_ask_price}           bq_L1: {self.bid_quantity_L1}           aq_L1: {self.ask_quantity_L1}")

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
                    self.ws.bind(
                        allowed_range_minute_granularity[t][0] if self.minute_granularity else allowed_range[t][0],
                        self.__update_ohlcv
                        )                              
            self.ws.bind('instrument', self.__on_update_instrument)
            self.ws.bind('wallet', self.__on_update_wallet)
            self.ws.bind('position', self.__on_update_position)
            self.ws.bind('order', self.__on_update_order)
            self.ws.bind('margin', self.__on_update_margin)
            self.ws.bind('bookticker', self.__on_update_bookticker)            
            #todo orderbook
            #self.ob = OrderBook(self.ws)

    def stop(self):
        """
        Stop the WebSocket data streams.

        This function stops the WebSocket data streams and closes the connection with the exchange.

        Returns:
            None
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