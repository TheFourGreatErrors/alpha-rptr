# coding: UTF-8

import json
import math
import os
import traceback
from datetime import datetime, timezone, timedelta
from inspect import signature
import time
import threading
from decimal import Decimal

import numpy as np
import pandas as pd
from bravado.exception import HTTPNotFound
from pytz import UTC

from src import (logger, bin_size_converter, find_timeframe_string,
                 allowed_range_minute_granularity, allowed_range, parseFloat, sync_obj_with_config,
                 to_data_frame, resample, delta, FatalError, notify, log_metrics, ord_suffix)
from src import retry_bybit as retry
from pybit import unified_trading
#from pybit import spot as spot_http
from src.config import config as conf
from src.exchange_config import exchange_config
from src.exchange.bybit.bybit_websocket import BybitWs


#TODO
# orderbook class
#from src.exchange.bybit.bybit_orderbook import OrderBook


bybit_order_type_mapping = {
    "Market"    : "MARKET",
    "Limit"     : "LIMIT"
}


bybit_trigger_by_mapping = {
    "LastPrice"     : "CONTRACT_PRICE",
    "MarkPrice"     : "MARK_PRICE",
    "IndexPrice"    : "INDEX_PRICE",
    "UNKNOWN"       : "CONTRACT_PRICE",

    "CONTRACT_PRICE" : "LastPrice",
    "MARK_PRICE"     : "MarkPrice",
    "INDEX_PRICE"    : "IndexPrice"      
}


bybit_tif_mapping = {
    "GTC"           : "GTC",
    "IOC"           : "IOC",
    "FOK"           : "FOK",
    "PostOnly"      : "GTX"
}


bybit_order_status_mapping = {
    "Created"           : "CREATED",
    "New"               : "NEW",
    "Rejected"          : "REJECTED",
    "PartiallyFilled"   : "PARTIALLY_FILLED",
    "Filled"            : "FILLED",
    "PendingCancel"     : "PENDING_CANCEL",
    "Cancelled"         : "CANCELED",
    "Untriggered"       : "UNTRIGGERED",
    "Triggered"         : "TRIGGERED",
    "Deactivated"       : "DEACTIVATED",
    "Active"            : "ACTIVE"
}


class Bybit:
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
    call_strat_on_start = True

    def __init__(self, account, pair, demo=False, spot=False, threading=True):
        """
        Constructor for ByBit class.
        Args:
            account (str): The account identifier for Bybit.
            pair (str): The trading pair for ByBit.
            demo (bool, optional): Flag to use the testnet. Default is False.
            threading (bool, optional): Condition for setting the 'is_running' flag.
                Default is True to indicate the bot is running.
        """
        # Account
        self.account = account
        # Pair
        self.pair = (pair.replace("-", "") if pair.upper().endswith("PERP") else pair).upper()
        # Launch date
        self.launch_date = None
        # Spot market?
        self.spot = spot
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
        self.wallet = {}
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
        # Instrument
        self.instrument = {}
        # Bookticker
        self.bookticker = {}
        # Timeframe
        self.bin_size = ['1h'] 
        # Bybit client     
        self.client = None  
        # Price
        self.market_price = 0
        # Order update
        self.order_update = []
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
        # Best bid price
        self.best_bid_price = None
        # Best ask price
        self.best_ask_price = None 
        #  Bid quantity L1
        self.bid_quantity_L1 = None
        # Ask quantity L1
        self.ask_quantity_L1 = None
        # callback
        self.best_bid_ask_change_callback = {}

        # Bybit specific
        self.is_unified_account = None 
        self.account_type = 'UNIFIED' # 'UNIFIED'. 'CLASSIC'?, 'CONTRACT', 'SPOT' etc.
        self.category = None # 'linear', 'inverse', 'spot' etc.

        sync_obj_with_config(exchange_config['bybit'], Bybit, self)            

    def __init_client(self):
        """
        Initialization of the client for live trading on Bybit exchange.
        """
        if self.client is not None:
            return
        
        api_key = conf['bybit_test_keys'][self.account]['API_KEY'] \
                    if self.demo else conf['bybit_keys'][self.account]['API_KEY']        
        api_secret = conf['bybit_test_keys'][self.account]['SECRET_KEY'] \
                    if self.demo else conf['bybit_keys'][self.account]['SECRET_KEY']
        
        # Setting up the client
        self.client = unified_trading.HTTP(testnet=self.demo, api_key=api_key, api_secret=api_secret)

        # Get account type information
        self.is_unified_account = True if retry(lambda: self.client.get_account_info())['unifiedMarginStatus'] > 2 else False      
        
        if self.spot: 
            self.category = 'spot'            
        elif self.pair.endswith('USDT') or self.pair.endswith('PERP'):
            self.category = 'linear'       
        elif self.pair.endswith('USD'):
            self.category = 'inverse' 
        else:
            raise ValueError("Invalid or unsupported pair!")

        if self.quote_rounding == None or self.asset_rounding == None:      
            markets_list = retry(lambda: self.client.get_instruments_info(category=self.category))['list']
            market = [market for market in markets_list if market.get('symbol')==self.pair]            
            tick_size = float(market[0]['priceFilter']['tickSize']) * 2 \
                            if '5' in market[0]['priceFilter']['tickSize'] else market[0]['priceFilter']['tickSize']                        
            self.quote_asset = market[0]['quoteCoin']                                
            self.quote_rounding = abs(Decimal(str(tick_size)).as_tuple().exponent) if float(tick_size) < 1 else 0                
            self.base_asset = market[0]['baseCoin']  
            base_precision = 'basePrecision' if self.spot else 'qtyStep'
            self.asset_rounding = abs(Decimal(str(market[0]['lotSizeFilter'][base_precision])).as_tuple().exponent) \
                                    if float(market[0]['lotSizeFilter'][base_precision]) < 1 else 0
  
      
        logger.info(f"account type: {self.account_type}")
        logger.info(f"category: {self.category}")

        self.sync()

        logger.info(f"Asset: {self.base_asset} Rounding: {self.asset_rounding} "\
                    f"- Quote: {self.quote_asset} Rounding: {self.quote_rounding}")
         
        logger.info(f"Position Size: {self.position_size:.3f} Entry Price: {self.entry_price:.2f}")

    def sync(self):
        """
        Synchronize Bybit instance with the current position, position size, entry price and market price.
        """
        # Position
        if not self.spot:
            self.position = self.get_position()
        # Position size
        self.position_size = self.get_position_size()
        # Entry price
        self.entry_price = self.get_position_avg_price()
        # Market price
        self.market_price = self.get_market_price()
        # Margin
        # self.margin = self.get_margin()
        
    def now_time(self):
        """
        Get the current time in UTC timezone.
        """
        return datetime.now().astimezone(UTC)

    def get_launch_date(self):
        """
        Get the launch date of this pair
        Args:
            None
        Returns:
            datetime: The launch date of this pair
        """
        self.launch_date = datetime.fromisoformat("2020-01-01T00:00:00+00:00")
        return self.launch_date
        
    def get_retain_rate(self):
        """
        Get the maintenance margin rate.
        Returns:
            float: The maintenance margin rate (e.g., 0.004 represents 0.4%).
        """
        return 0.005
    
    def get_lot(self, lot_leverage=1, only_available_balance=True, round_decimals=None):
        """
        Calculate the lot size for the trade.
        Args:
            lot_leverage (int): The leverage to be used for the lot calculation. Use None to automatically use your preset leverage.
            only_available_balance (bool): If True, returns only the available balance (not used as collateral for margin).
            round_decimals (int): The number of decimals to round the calculated lot size.
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

    def get_balance(self, asset=None, return_available=False):
        """
        Get the balance for the specified asset.
        Args:
            asset (str): The asset to get the balance for. If not provided, the default balance asset is `self.quote_asset`.
            return_available (bool): If True, returns only the available balance (not used as collateral for margin).
        Returns:
            float: The balance for the specified asset.
        """
        self.__init_client()
        # Check if asset is not provided, and if margin balances are available.
        if asset is None and self.margin is not None:   
            balances = self.margin
        # If asset is specified, or margin balances are not available, get all balances.
        elif asset is not None:
            balances =  self.get_all_balances()
        else:
            # If asset is not specified and margin balances are not available, initialize and get all balances.
            self.margin = self.get_all_balances()
            balances = self.margin
       
        # Check if it's a spot account.
        if self.spot:             
            # Extract the balances for the specified asset or the default quote asset.
            balances = balances[0]['coin']
            asset = asset if asset else self.quote_asset

            # Find the balance entry for the specified asset.
            balance = [balance for balance in balances if balance.get('coin')==asset]           
            
            if len(balance) > 0:          
                # Calculate and return the available or total balance based on the 'return_available' flag.
                balance = float(balance[0]['walletBalance']) - float(balance[0]['locked'])  if return_available \
                            else float(balance[0]['walletBalance'])                      
                return balance             
            else:
                logger.info(f"Unable to find asset: {asset} in balances")
            
        # Check if the trading pair ends with specific strings.    
        elif self.pair.endswith('USDT') or self.pair.endswith('USD') or self.pair.endswith('PERP'):   

            if not asset:          
                # Calculate and return the available or total balance based on the 'return_available' flag.
                balance = (float(balances[0]['totalAvailableBalance']) \
                            if return_available else float(balances[0]['totalMarginBalance']))      
                return balance             
            elif asset:
                balances = balances[0]['coin']
                # Find the balance entry for the specified asset.
                balance =  [balance for balance in balances if balance.get('coin')==asset]
                balance = (float(balance[0]['walletBalance']) - float(balance[0]['locked']) \
                            if return_available else float(balance[0]['walletBalance']) ) \
                            if len(balance) > 0 else 0 #coin not found        
                return balance
            else:
                logger.info(f"Unable to find asset: {asset} in balances")           
        
    def get_available_balance(self, asset=None):
        """
        Get the available balance for the specified asset,
        considering that some might already be used as collateral for margin.
        Args:
            asset (str): The asset to get the available balance for. If not provided, the default balance asset is `self.quote_asset`.
        Returns:
            float: The available balance for the specified asset.        
        """
        self.__init_client()
       
        available_balance = self.get_balance(asset, return_available=True)
        return available_balance       

    def get_all_balances(self):
        """
        Get all balances.
        Returns:
            dict: A dictionary containing all balances.
        """
        self.__init_client()
       
        balances = retry(lambda: self.client.get_wallet_balance(accountType=self.account_type))['list']       
        return balances
    
    def set_leverage(self, leverage, symbol=None):
        """
        Set the leverage for the specified symbol.
        Args:
            leverage (int): The leverage value to be set.
            symbol (str): The symbol for which leverage should be set. If not provided, the default symbol is `self.pair`.
        Returns:
            None
        """
        self.__init_client()

        symbol = self.pair if symbol is None else symbol
        leverage = retry(lambda: self.client.set_leverage(symbol=symbol, category=self.category,
                                                            leverage=leverage,
                                                            buyLeverage=leverage,
                                                            sellLeverage=leverage)) 
        #return #self.get_leverage(symbol)

    def get_leverage(self, symbol=None):
        """
        Get the leverage for the specified symbol.
        Args:
            symbol (str): The symbol for which leverage should be retrieved. If not provided, the default symbol is `self.pair`.
        Returns:
            float: The leverage value for the specified symbol.
        """
        self.__init_client()

        symbol = self.pair if symbol is None else symbol
        return float(self.get_position()[0]["leverage"])

    def get_position(self, symbol=None, force_api_call=True):
        """
        Get the leverage for the specified symbol.
        Args:
            symbol (str): The symbol for which leverage should be retrieved. If not provided, the default symbol is `self.pair`.
        Returns:
            float: The leverage value for the specified symbol.
        """
        symbol = self.pair if symbol == None else symbol

        if self.spot:
            logger.info(f"Get Position Functionality Currently Not Supported For Spot")
            return      

        def get_position_api_call():           
            positions = retry(lambda: self.client
                                  .get_positions(symbol=symbol, category=self.category))['list']

            self.position = [p for p in positions if p['symbol'] == symbol]
            
            if self.position is None or len(self.position) == 0:
                self.position = [{'avgPrice': 0,
                                  'size': 0,
                                  'liqPrice': 0,
                                  'side': None}]   
                return None                          

            return self.position

        self.__init_client() 
       
        if self.position is not None and len(self.position) > 0 and not force_api_call:
            return self.position
        else:  # when the WebSocket cant get it or forcing the api call is needed
            position = get_position_api_call()       
            return position

    def get_position_size(self, force_api_call=True):
        """
        Get the position size.
        Args:
            force_api_call (bool): If True, force an API call to get the position.
        Returns:
            float: The position size.
        """
        self.__init_client()
        if self.spot: # Spot treats positions only as changes in balance from quote asset to base asset           
            position = self.get_balance(asset=self.base_asset) 
            position = 0 if position is None else position
            return float(position)

        position = self.get_position(force_api_call=force_api_call)

        if position is not None: # Positition size may return positive even when short !!!          
            position_size = float(position[0]['size'])           
            position_size = -position_size if position[0]['side'] == 'Sell' else position_size 
            return position_size  
        else:
            return 0

    def get_position_avg_price(self):
        """
        Get the average price of the current position.
        Returns:
            float: The average price of the current position.
        """
        self.__init_client()
        
        position = self.get_position()
        if position is None or len(position) == 0:
            return 0
        pos_avg_price = position[0]['avgPrice']       
        pos_avg_price = float(0 if pos_avg_price == "" else float(pos_avg_price)) 
        
        return pos_avg_price 

    def get_market_price(self):
        """
        Get the current market price.
        Returns:
            float: The current market price.
        """
        self.__init_client()
        if self.market_price != 0:
            return self.market_price
        else:  # when the WebSocket cant get it
            symbol_information = self.get_orderbook_ticker()
            if symbol_information is None:
                return 0               
            
            self.market_price = float(symbol_information['lastPrice'])             
            
            return self.market_price
    
    def get_pnl(self):
        """
        Get the profit and loss calculation in percentage.
        Returns:
            float: The profit and loss calculation in percentage.
        """
        # PnL calculation in %            
        pnl = self.get_profit()* 100/self.get_balance()
        return pnl   

    def get_profit(self, close=None, avg_entry_price=None, position_size=None, commission=None):
        """
        Get the profit for the current position.
        Args:
            close (float): The closing price.
            avg_entry_price (float): The average entry price. If not provided, it will be fetched from the current position.
            position_size (float): The position size. If not provided, it will be fetched from the current position.
            commission (float): The commission value.
        Returns:
            float: The profit for the current position.
        """
        if close is None:
            close = self.get_market_price() 
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
    
    def get_orderbook_ticker(self, symbol=None):
        """
        Get the latest symbol (trading pair) information.
        Args:
            symbol (str): If provided, it will return information for the specific symbol. Otherwise, it returns values for the pair currently traded.
        Returns:
            dict: A dictionary containing the latest symbol information.
        """
        symbol = self.pair if symbol == None else symbol   
        try:     
            ticker_information = retry(lambda: self.client.get_tickers(symbol=symbol, category=self.category))['list']
        except Exception  as e:        
            logger.info(f"An error occured: {e}")
            logger.info(f"Sorry couldnt retrieve information for symbol: {symbol}")
            return None
        
        if not ticker_information:
            return None

        ticker_information = ticker_information[0] # List to Dict

        ticker_information["askPrice"] = ticker_information["ask1Price"]
        ticker_information["askSize"] = ticker_information["ask1Size"]

        ticker_information["bidPrice"] = ticker_information["bid1Price"]
        ticker_information["bidSize"] = ticker_information["bid1Size"]
        
        return ticker_information
    
    def get_orderbook(self):
        """
        Get the orderbook L1, including the best bid and best ask prices and qantity.
        """
        self.__init_client()
        ob =  retry(lambda: self.client
                                      .get_orderbook(symbol=self.pair, category=self.category))
        self.best_bid_price = float(ob['b'][0])
        self.best_ask_price = float(ob['a'][0])
        self.bid_quantity_L1 = float(ob['b'][1])
        self.ask_quantity_L1 = float(ob['a'][1])
        
    def get_trail_price(self):
        """
        Get the trail price.
        Returns:
            float: The trail price.
        """
        return self.trail_price

    def set_trail_price(self, value):
        """
        Set the trail price.
        Args:
            value (float): The trail price value.
        Returns:
            None
        """
        self.trail_price = value

    def get_commission(self):
        """
        Get the commission.
        Returns:
            float: The commission value.
        """
        return 0.075 / 100    
    
    def cancel_all(self, only_active=False, only_conditional=False):
        """
        Cancel all orders for this pair.
        Args:
            only_active (bool): If True, cancel only active orders.
            only_conditional (bool): If True, cancel only conditional orders.
        """
        self.__init_client()
        
        res_active_orders = None
        res_conditional_orders = None

        if not only_conditional:
            res_active_orders = self.cancel_active_order(cancel_all=True)
            if res_active_orders:
                logger.info(f"Cancelled All Active Orders for {self.pair}")
            else:
                logger.info(f"No Active Orders to Cancel for {self.pair}")

        if not only_active:
            res_conditional_orders = self.cancel_conditional_order(cancel_all=True)
            if res_conditional_orders:
                logger.info(f"Cancelled All Conditional Orders for {self.pair}")
            else:
                logger.info(f"No Conditional Orders to Cancel for {self.pair}")

        if not res_active_orders and not res_conditional_orders:
            logger.info(f"No orders to cancel or an issue occurred for {self.pair}")

        #self.callbacks = {} 
    
    def close_all(self, 
                  spot_safety_catch=True, 
                  callback=None, 
                  split=1, interval=0, chaser=False, retry_maker=100,
                  limit_chase_init_delay=0.0001, chase_update_rate=0.05, limit_chase_interval=0):
        """
        Close open positions for this pair.
        Args:
            spot_safety_catch (bool): This is here to prevent you from accidentally dumping all your base assets 
                                      because spot treats positions as changes in balance of base asset and quote asset, 
                                      there is no open position status.
            callback: The callback function.
            split (int): The number of splits for large order quantities.
            interval (int): Time interval between split order executions (in milliseconds).
            limit_chase_init_delay (float): The initial delay for limit chase orders (in seconds).
            chase_update_rate (float): The rate of adjustment for the chase order price (0.05 means 5% adjustment on each update).
            limit_chase_interval (int): Greater than 0 starts limit chase order.
        """
        self.__init_client()
        position_size = self.get_position_size()
        if position_size == 0 or (spot_safety_catch and self.spot):
            return

        side = False if position_size > 0 else True

        def callback():
            position_size = self.get_position_size()
            if position_size == 0:
                logger.info(f"Closed {self.pair} position")
            else:
                logger.info(f"Failed to close all {self.pair} position, still {position_size} amount remaining")
        
        self.order("Close", side, abs(position_size), 
                   post_only=chaser or bool(limit_chase_interval), chaser=chaser, retry_maker=retry_maker,
                   limit_chase_init_delay=limit_chase_init_delay,
                   chase_update_rate=chase_update_rate, 
                   limit_chase_interval=limit_chase_interval, 
                   callback=callback, 
                   split=split, 
                   interval=interval)       

    def cancel(self, id):
        """
        Cancel a specific active order by its order ID.

        This function searches for active orders associated with the provided order ID (user ID) and attempts to cancel them.
        If multiple active orders are found, it cancels the first one.
        If no active orders are found, it logs a message and returns False.

        Args:
            order_id (str): The order ID (user ID) of the order to be canceled.

        Returns:
            bool: True if the order was successfully canceled; False otherwise.
        """
        self.__init_client()
    
        orders = self.get_open_orders(id, separate=True)            

        if orders is None:
            logger.info(f"Couldn't find an order of which id string starts with: {id}")
            return False              
          
        order_link_id = 'orderLinkId'       
        
        if len(orders['active_orders']) > 0:
            # Found an active order with the given user ID
            order = orders['active_orders'][0]
            res = self.cancel_active_order(user_id=order[order_link_id])
        elif len(orders['conditional_orders']):
            # Found a conditional order with the given user ID
            order = orders['conditional_orders'][0]
            # Attempt to cancel the first conditional order found using its order link ID
            res = self.cancel_conditional_order(user_id=order[order_link_id])
        else:
            res = False
        # Return the result of the cancellation (True/False)
        if res:
            return res

    def cancel_conditional_order(self, user_id=None, order_id=None, cancel_all=False):
        """
        Cancel a specific conditional order by order ID.

        This function cancels a specific conditional order by its order ID.
        To use this function, you need to provide the full order ID since
        it does not query orders and filter them prior to the cancellation.
        For convenience, you can also use `cancel()` for single order cancellation
        and `cancel_all()` for cancelling all conditional and active orders.

        Args:
            order_id (str): The internal ID of the order given by the exchange.
            user_id (str): Your user ID that you provided when sending the order.
            cancel_all (bool): Set to True to cancel all conditional orders for this pair.
        Returns:
            bool: True if the order was successfully cancelled; False otherwise.
        """
        if order_id == None and user_id == None and not cancel_all:
            logger.info(f"No id was provided, unable to cancel an order!")
            return False
        self.__init_client()  
               
        stop_order_id = order_id        

        cancel_conditional = self.client.cancel_all_orders if cancel_all else self.client.cancel_order

        res = retry(lambda: cancel_conditional(order_id=order_id, order_link_id=user_id, category=self.category, 
                                                orderId=order_id, orderLinkId=user_id,
                                                stop_order_id=stop_order_id, 
                                                symbol=self.pair, orderFilter='StopOrder'))      
        
        # TODO exception pybit.exceptions.InvalidRequestError: Order not exists or too late to repalce (ErrCode: 20001) (ErrTime: 22:40:43). etc...
        if cancel_all:
            if self.category == "spot":
                if res["success"] == "1":
                    return True
                else:
                    return False
            else:
                orders = res["list"] 
                if res["success"] == "1":
                    logger.info(f"Cancelled Orders: {orders}")
                    return True
                else:
                    return False
        else: #single order cancellation
            if res["orderId"] == order_id or res["orderLinkId"] == user_id:
                logger.info(f"Cancelled Order: {user_id}")
                return True
            else :
                return False
    
    def cancel_active_order(self, order_id=None, user_id=None, cancel_all=False):
        """
        Cancel a specific active order by order ID.

        This function cancels a specific active order by its order ID.
        To use this function, you need to provide the full order ID since
        it does not query orders and filter them prior to the cancellation.
        For convenience, you can also use `cancel()` and `cancel_all()`
        to handle single and all active order cancellations respectively.

        Args:
            order_id (str): The internal ID of the order given by the exchange.
            user_id (str): Your user ID that you provided when sending the order.
            cancel_all (bool): Set to True to cancel all active orders for this pair.
        Returns:
            bool: True if the order was successfully cancelled; False otherwise.
        """
        if order_id == None and user_id == None and not cancel_all:
            logger.info(f"No id was provided, unable to cancel an order!")
            return False
        self.__init_client()             
            
        cancel_active =  self.client.cancel_all_orders if cancel_all else self.client.cancel_order
        
        res =  retry(lambda: cancel_active(order_id=order_id, order_link_id=user_id,
                                 orderId=order_id, orderLinkId=user_id, category=self.category,
                                   symbol=self.pair, orderFilter='Order',
                                     orderTypes="LIMIT,LIMIT_MAKER"))
      
        # TODO exception pybit.exceptions.InvalidRequestError: Order not exists or too late to repalce (ErrCode: 20001) (ErrTime: 22:40:43). etc...
        if cancel_all:
            if self.category == "spot":
                if res["success"] == "1":
                    return True
                else:
                    return False
            else:
                orders = res["list"] 
                if res["success"] == "1":
                    logger.info(f"Cancelled Orders: {orders}")
                    return True
                else:
                    return False
        else: #single order cancellation
            if res["orderId"] == order_id or res["orderLinkId"] == user_id:
                logger.info(f"Cancelled Order: {user_id}")
                return True
            else :
                return False
        
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
        trigger_by='CONTRACT_PRICE'
    ):
        """
        Create an order.

        This function is used to create a new order with the given parameters.
        Depending on the provided parameters, different types of orders can be created:
        - Limit order
        - Stop-limit order
        - Market order
        - Limit chaser (for chasing the market price for limit orders)
        - Condition (conditional) order (only for non-spot markets)

        Args:
            ord_id (str): Order ID (user-defined identifier for the order).
            side (str): 'Buy' or 'Sell' to indicate the order side.
            ord_qty (float): Order quantity to be placed.
            limit (float, optional): Price for a limit order. Default is 0.
            stop (float, optional): Stop price for a stop-limit order. Default is 0.
            post_only (bool, optional): Set to True to create a post-only order. Default is False.
            reduce_only (bool, optional): Set to True to make this order reduce-only.
                This means it can only reduce an existing position and not increase it. Default is False. 
            trailing_stop (float, optional): Trailing stop price for a trailing stop-limit order. Default is 0. (use set_trading_stop() once in a position !!!)
            activationPrice (float, optional): Activation price for a stop-limit order with activation. Default is 0. (use set_trading_stop() once in a position !!!)
            trigger_by (str, optional): Determines the price to use for triggers (e.g., 'LastPrice', 'IndexPrice', etc.).
                Default is 'LastPrice'.

        Returns:
            None
        """         
        ord_qty = str(ord_qty) 
       
        base_price =  self.market_price 
                    #market_price + market_price / 100 * 1 if stop > market_price else market_price - market_price / 100 * 1 
        trig_dir = 1 if stop > base_price else 2
        timeInForce = 'GTC'
        trigger_by = bybit_trigger_by_mapping[trigger_by]
        cat = self.category   
       
        if limit > 0 and post_only:            
            ord_type = "Limit" 
            type = "LIMIT_MAKER" # Spot only
            orderFilter = "Order" # if self.pair.endswith('PERP') else None            
            limit = str(limit) #if self.pair.endswith('PERP') else limit                    
       
            res = retry(lambda: self.client
                                .place_order(symbol=self.pair, category=cat,
                                            order_type=ord_type, orderType=ord_type, type=type,
                                            order_link_id=ord_id, orderLinkId=ord_id, side=side, 
                                            qty=ord_qty, orderQty=ord_qty,
                                            price=limit, orderPrice=limit,
                                            reduce_only=reduce_only, reduceOnly=reduce_only,
                                            close_on_trigger=reduce_only,
                                            time_in_force='PostOnly', timeInForce='PostOnly',
                                            orderFilter=orderFilter, position_idx=0))                
        elif limit > 0 and stop > 0:
            ord_type = "Limit" #"StopLimit"
            #type = "LIMIT" #Spot only
            orderFilter = "StopOrder" # if self.pair.endswith('PERP') else None
            stop = str(stop) # if self.pair.endswith('PERP') else stop 
            limit = str(limit) # if self.pair.endswith('PERP') else limit 
            res = retry(lambda: self.client
                                .place_order(symbol=self.pair, category=cat,
                                            order_type=ord_type, orderType=ord_type,
                                            order_link_id=ord_id, orderLinkId=ord_id, side=side,
                                            qty=ord_qty, orderQty=ord_qty, price=limit, 
                                            stop_px=stop, triggerPrice=stop,
                                            orderPrice=limit, base_price=base_price, basePrice=base_price,
                                            reduce_only=reduce_only,  reduceOnly=reduce_only,
                                            close_on_trigger=reduce_only, triggerDirection=trig_dir,                                                                          
                                            time_in_force='GoodTillCancel', timeInForce=timeInForce,
                                            trigger_by=trigger_by, triggerBy=trigger_by,
                                            orderFilter=orderFilter, position_idx=0))
        elif limit > 0:
            ord_type = "Limit" 
            type = "LIMIT"
            orderFilter = "Order" # if self.pair.endswith('PERP') else None 
            limit = str(limit) # if self.pair.endswith('PERP') else limit          
            post_only=True, 
            res = retry(lambda: self.client
                                .place_order(symbol=self.pair, category=cat,
                                            order_type=ord_type, orderType=ord_type, type=type,
                                            order_link_id=ord_id, orderLinkId=ord_id, side=side,
                                            qty=ord_qty, orderQty=ord_qty, price=limit, orderPrice=limit,
                                            reduce_only=reduce_only, reduceOnly=reduce_only,
                                            close_on_trigger=reduce_only,
                                            time_in_force='GoodTillCancel', timeInForce=timeInForce,
                                            orderFilter=orderFilter, position_idx=0))
        elif stop > 0:
            ord_type = "Market" #"Stop"
            #type = "MARKET" #Spot only
            orderFilter = "StopOrder" # if self.pair.endswith('PERP') else None
            limit = str(limit) # if self.pair.endswith('PERP') else limit   
            stop = str(stop) # if self.pair.endswith('PERP') else stop    
            res = retry(lambda: self.client
                                .place_order(symbol=self.pair, category=cat,
                                            order_type=ord_type, orderType=ord_type,
                                            order_link_id=ord_id, orderLinkId=ord_id, side=side,
                                            qty=ord_qty, orderQty=ord_qty, stop_px=stop, triggerPrice=stop,
                                            reduce_only=reduce_only, reduceOnly=reduce_only,
                                            close_on_trigger=reduce_only, triggerDirection=trig_dir, 
                                            orderPrice=limit, base_price=str(base_price), basePrice=base_price,
                                            time_in_force='GoodTillCancel', timeInForce=timeInForce,
                                            trigger_by=trigger_by, triggerBy=trigger_by,
                                            orderFilter=orderFilter, position_idx=0))
        elif post_only:         
            limit = self.best_bid_price if side == "Buy" else self.best_ask_price
            ord_type = "Limit" 
            type = "LIMIT_MAKER" # Spot only
            orderFilter = "Order" # if self.pair.endswith('PERP') else None             
            limit = str(limit) # if self.pair.endswith('PERP') else limit 
           
            res = retry(lambda: self.client
                                .place_order(symbol=self.pair, category=cat,
                                            order_type=ord_type, orderType=ord_type, type=type,
                                            order_link_id=ord_id, orderLinkId=ord_id, side=side, 
                                            qty=ord_qty, orderQty=ord_qty,
                                            price=limit, orderPrice=limit,
                                            reduce_only=reduce_only, reduceOnly=reduce_only,
                                            close_on_trigger=reduce_only,
                                            time_in_force='PostOnly', timeInForce='PostOnly',
                                            orderFilter=orderFilter, position_idx=0))

        else:
            ord_type = "Market"
            type = "MARKET"
            orderFilter = "Order" # if self.pair.endswith('PERP') else None
            stop = str(stop) # if self.pair.endswith('PERP') else stop           
               
            res = retry(lambda: self.client
                                    .place_order(symbol=self.pair, category=cat,
                                                order_type=ord_type, type=type, orderType=ord_type,
                                                order_link_id=ord_id, orderLinkId=ord_id, side=side,
                                                qty=ord_qty, orderQty=ord_qty,
                                                reduce_only=reduce_only, reduceOnly=reduce_only,
                                                close_on_trigger=reduce_only,
                                                time_in_force='GoodTillCancel', timeInForce=timeInForce,
                                                orderFilter=orderFilter, position_idx=0))
                
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

    def amend_order(self, ord_id, ord_qty=0, limit=0, stop=0, query_orders=True, **kwargs):
        """
        Amend an order with querying the order prior to verifying its existence and whether it's active or conditional.

        This function allows amending an existing order with the provided order ID.
        It first queries the order to check if it exists and then amends the order if found.
        If no order is found or the order is not active, it logs a message and returns.

        Args:
            ord_id (str): The order ID to be amended. (orderLinkId - User customised order ID)
            ord_qty (float, optional): New order quantity (amend quantity). Default is 0 (no amendment).
            limit (float, optional): New limit price for a limit order. Default is 0 (no amendment).
            stop (float, optional): New stop price for a stop-limit order. Default is 0 (no amendment).
            **kwargs: Additional order parameters to amend (e.g. triggerBy etc.).
        Returns:
            None
        """        
        if self.spot:
            logger.info(f"Amending Orders Is Not Supported For Spot Yet.")
            return

        # Create a dictionary containing local variables (arguments) excluding 'self', 'ord_id', and 'kwargs'
        new_kwargs = {k: v  for k, v in locals().items() if v and k not in ('self', 'ord_id', 'kwargs')}
        # Check/Update if there are any additional keyword arguments (kwargs)        
        if kwargs:
            new_kwargs.update(kwargs)

        if query_orders:
            orders = self.get_open_orders(id=ord_id, separate=False)

            if not orders:
                logger.info(f"Cannot Find An Order to Amend Id: {ord_id}")
                return        
                    
            order_id_key = 'orderLinkId' 
        
            order = orders[0] 
            ord_id = order[order_id_key]                    
  
        res = self.__amend_order(ord_id, **new_kwargs)
           
    def __amend_order(self, ord_id, **kwargs):
        """
        Amend an existing order.

        This function is designed to amend an existing order based on the provided order ID.
        The order is verified for existence and whether it is an active order or a conditional order before amendment.

        Note:            
            - The keyword argument must be one of the following: 'limit' (to change the limit price), 'ord_qty'
            (to change the order quantity), or 'stop' (to change the stop price).

        Args:
            ord_id (str): The ID of the order to be amended.
            is_conditional (bool): Set to True if the order is conditional, False if it's active.
            **kwargs: Keyword arguments to be used for amending the order. Only one key-value pair should be provided,
                    representing the attribute to be amended and its new value.       
        Returns:
            dict or None: The response from the Bybit API if the order was successfully amended, or None otherwise.
        """    
        if len(kwargs) == 0:
            logger.info(f"No kwargs were provided.")
            return    
        
        kwargs_to_update = {}

        for k,v in kwargs.items():
            if k == 'limit':
                kwargs_to_update = {'price': str(v)}
            if k == 'ord_qty':
                kwargs_to_update = {'qty': str(v)}
            if k == 'stop':
                kwargs_to_update = {'triggerPrice':str(v)}

        kwargs.update(kwargs_to_update)

        res = None
 
        res = retry(lambda: self.client
                    .amend_order(symbol=self.pair, order_link_id=ord_id, category=self.category,
                                            orderLinkId=ord_id, 
                                            **kwargs))

        if self.enable_trade_log:
            logger.info(f"========= Amend Order ==============")
            logger.info(f"ID       : {ord_id}")            
            logger.info(f"======================================")
            notify(f"Amend Order\n ID       : {ord_id}")      

        if res:                
            logger.info(f"Modified Order with user_id: {ord_id}, response: {res}")
            return res         
        
    def set_trading_stop(self, **kwargs):
        """
        Set the take profit, stop loss or trailing stop for the position.
        """
        res = lambda: self.client.set_trading_stop(symbol=self.pair, category=self.category, **kwargs)  
        
    def entry(
        self,
        id,
        long,
        qty,
        limit=0,
        stop=0,
        post_only=False,
        reduce_only=False,
        when=True,
        round_decimals=None,
        callback=None,
        trigger_by='CONTRACT_PRICE',
        split=1,
        interval=0,
        chaser=False,
        retry_maker=100,
        limit_chase_init_delay=0.0001, 
        chase_update_rate=0.05, 
        limit_chase_interval=0
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
            id (str): Order id (identifier for the order).
            long (bool): Long or Short. Set to True for a long position, False for a short position.
            qty (float): Quantity. Quantity of the asset to buy/sell in the order.
            limit (float, optional): Limit price. Limit price for the order (if applicable, set to 0 for market orders).
            stop (float, optional): Stop limit. Stop price for the order (if applicable, set to 0 for non-stop orders).
            post_only (bool, optional): Post Only. Set to True to place the order as a post-only order (default is False).
            reduce_only (bool, optional): Reduce Only. Set to True if the order is intended to reduce the existing position, not increase it (default is False).
            when (bool, optional): When. Set to True to execute the order, False to skip execution (useful for testing).
            round_decimals (int, optional): Round Decimals. Number of decimals to round the order quantity (if not provided, it's rounded automatically).
            callback (callable, optional): Callback. A function to be called after the order is executed (optional).
            trigger_by (str, optional): Trigger By. Price to use for triggers (e.g., 'LastPrice', 'IndexPrice', etc.).
            split (int, optional): Split. For iceberg orders, set the number of order splits (default is 1, for non-iceberg orders).
            interval (int, optional): Interval. For iceberg orders, set the time interval between order splits (default is 0, for non-iceberg orders).
            limit_chase_init_delay (float, optional): Limit Chase Init Delay. Initial delay for limit order chasing (used when post_only is True and limit_chase_interval > 0).
            chase_update_rate (float, optional): Chase Update Rate. Sleep interval between price updates during limit order chasing.
            limit_chase_interval (int, optional): Limit Chase Interval. Minimum interval between each limit order update during chasing.
        Returns:
            None
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

        self.order(id, long, ord_qty, limit=limit, stop=stop, post_only=post_only, 
                   reduce_only=reduce_only, when=when, callback=callback, trigger_by=trigger_by, split=split, interval=interval, chaser=chaser, retry_maker=retry_maker,
                   limit_chase_init_delay=limit_chase_init_delay, chase_update_rate=chase_update_rate, limit_chase_interval=limit_chase_interval)

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
        when=True,
        round_decimals=None,
        callback=None,
        trigger_by='CONTRACT_PRICE',
        split=1,
        interval=0,
        chaser=False,
        retry_maker=100,
        limit_chase_init_delay=0.0001, 
        chase_update_rate=0.05, 
        limit_chase_interval=0
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
            id (str): Order id (identifier for the order).
            long (bool): Long or Short. Set to True for a long position, False for a short position.
            qty (float): Quantity. Quantity of the asset to buy/sell in the order.
            limit (float, optional): Limit price. Limit price for the order (if applicable, set to 0 for market orders).
            stop (float, optional): Stop limit. Stop price for the order (if applicable, set to 0 for non-stop orders).
            trailValue (float, optional): Trail Value. Trail value for trailing stop orders (default is 0).
            post_only (bool, optional): Post Only. Set to True to place the order as a post-only order (default is False).
            reduce_only (bool, optional): Reduce Only. Set to True if the order is intended to reduce the existing position, not increase it (default is False).
            cancel_all (bool, optional): Cancel All. Set to True to cancel all open orders before sending the entry order (default is False).
            pyramiding (int, optional): Pyramiding. Number of entries you want in pyramiding (default is 2).
            when (bool, optional): When. Set to True to execute the order, False to skip execution (useful for testing).
            round_decimals (int, optional): Round Decimals. Number of decimals to round the order quantity (if not provided, it's rounded automatically).
            callback (callable, optional): Callback. A function to be called after the order is executed (optional).
            trigger_by (str, optional): Trigger By. Price to use for triggers (e.g., 'LastPrice', 'IndexPrice', etc.).
            split (int, optional): Split. For iceberg orders, set the number of order splits (default is 1, for non-iceberg orders).
            interval (int, optional): Interval. For iceberg orders, set the time interval between order splits (default is 0, for non-iceberg orders).
            limit_chase_init_delay (float, optional): Limit Chase Init Delay. Initial delay for limit order chasing (used when post_only is True and limit_chase_interval > 0).
            chase_update_rate (float, optional): Chase Update Rate. Sleep interval between price updates during limit order chasing.
            limit_chase_interval (int, optional): Limit Chase Interval. Minimum interval between each limit order update during chasing.
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
     
        # make sure it doesnt spam small entries, which in most cases would trigger risk management orders evaluation,
        # you can make this less than 2% if needed  
        if ord_qty < ((pyramiding*qty) / 100) * 2:
            return       

        ord_qty = round(ord_qty, round_decimals if round_decimals != None else self.asset_rounding)

        self.order(id, long, ord_qty, limit=limit, stop=stop, post_only=post_only, 
                   reduce_only=reduce_only, when=when, callback=callback, trigger_by=trigger_by, split=split, interval=interval, chaser=chaser, retry_maker=retry_maker,
                   limit_chase_init_delay=limit_chase_init_delay, chase_update_rate=chase_update_rate, limit_chase_interval=limit_chase_interval)

    def order(
        self,
        id,
        long,
        qty,
        limit=0,
        stop=0,
        post_only=False,
        reduce_only=False,
        when=True,
        round_decimals=None,
        callback=None,
        trigger_by='CONTRACT_PRICE',
        split=1,
        interval=0, 
        chaser=False,
        retry_maker=100,
        limit_chase_init_delay=0.0001, 
        chase_update_rate=0.05, 
        limit_chase_interval=0
    ):
        """
        Places an order with various options.

        Args:
            id (str): Order id (identifier for the order).
            long (bool): Long or Short. Set to True for a long position, False for a short position.
            qty (float): Quantity. Quantity of the asset to buy/sell in the order.
            limit (float, optional): Limit price. Limit price for the order (if applicable, set to 0 for market orders).
            stop (float, optional): Stop limit. Stop price for the order (if applicable, set to 0 for non-stop orders).
            post_only (bool, optional): Post Only. Set to True to place the order as a post-only order (default is False).
            reduce_only (bool, optional): Reduce Only. Set to True if the order is intended to reduce the existing position, not increase it (default is False).
            when (bool, optional): When. Set to True to execute the order, False to skip execution (useful for testing).
            round_decimals (int, optional): Round Decimals. Number of decimals to round the order quantity (if not provided, it's rounded automatically).
            callback (callable, optional): Callback. A function to be called after the order is executed (optional).
            trigger_by (str, optional): Trigger By. Price to use for triggers (e.g., 'LastPrice', 'IndexPrice', etc.).
            split (int, optional): Split. For iceberg orders, set the number of order splits (default is 1, for non-iceberg orders).
            interval (int, optional): Interval. For iceberg orders, set the time interval between order splits (default is 0, for non-iceberg orders).
            limit_chase_init_delay (float, optional): Limit Chase Init Delay. Initial delay for limit order chasing (used when post_only is True and limit_chase_interval > 0).
            chase_update_rate (float, optional): Chase Update Rate. Sleep interval between price updates during limit order chasing.
            limit_chase_interval (int, optional): Limit Chase Interval. Minimum interval between each limit order update during chasing.
        Returns:
            None
        """
        self.__init_client()

        # if self.get_margin()['excessMargin'] <= 0 or qty <= 0:
        #     return

        # Check if the order execution is enabled.
        if not when:
            return
       
        side = "Buy" if long else "Sell" 
        ord_qty = abs(round(qty, round_decimals if round_decimals != None else self.asset_rounding))    

        # Construct the order ID for the main order or the suborders in case of iceberg orders.
        ord_id = id + ord_suffix() #if order is None else order["clientOrderId"]

        if split > 1:
            # Logic for splitting orders into suborders for iceberg orders.
            exchange = self
            sub_ord_qty = round(ord_qty/split, self.asset_rounding)
            
            class split_order:
                # Internal class to manage iceberg order suborders.    
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
                    exchange.order(sub_ord_id, long, s_ord_qty, limit, 0, post_only,
                                    reduce_only, trigger_by=trigger_by, callback=sub_ord_callback)

            sub_ord_id = f"{id}_sub1"
            self.order(sub_ord_id, long, sub_ord_qty, limit, stop, post_only,
                        reduce_only, trigger_by=trigger_by, callback=split_order(1))
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
                             callback, 
                             trigger_by):
                    self.order_id = order_id
                    self.long = long
                    self.qty = abs(qty)
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

                    self.trigger_by = trigger_by

                    self.filled = {}
                    self.started = None
                    self.start_price = self.limit if self.limit != 0 else 0
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
                               self.trigger_by, 
                               self.on_order_update)     
                    
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
                    logger.info(f"Chaser Active: {self.order_id} @ {self.start_price}")              

                def end(self):
                    exchange.remove_ob_callback(self.order_id)

                def avg_price(self, print_suborders=False):
                    order_value = 0
                    for key, value in self.filled.items():
                        if value[0] > 0:
                            if print_suborders:
                                logger.info(f"{key} - {value[0]} @ {value[1]}")
                            order_value += value[0]*value[1]
                    return round(order_value/self.qty if self.qty > 0 else 0, exchange.quote_rounding)

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
                    except Exception as e:
                        error_code  = abs(int(e.status_code))
                        if (error_code == 110001):
                            logger.info("Chaser: Cancel Order: Unknown order. Already filled?")
                            return
                        raise e

                def order(self, retry, id, long, qty, limit, stop, post_only, reduce_only, trigger_by, callback):
                    # try fixed number of times
                    for x in range(retry):
                        try:  
                            exchange.order(id, long, qty, limit=limit, stop=stop, post_only=post_only, 
                                           reduce_only=reduce_only, trigger_by=trigger_by, callback=callback)
                            self.current_order_id = id
                            break
                        except Exception as e:
                            #pybit.exceptions.InvalidRequestError: expect Rising, but trigger_price[419768000] <= current[419769000]??last (ErrCode: 10001) (ErrTime: 07:57:00).
                            error_code  = abs(int(e.status_code))
                            if x < (retry-1):
                                time.sleep(2)
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
                    self.filled[order["id"]] = [order["filled"], order["limit"]]
                    
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
                                       self.trigger_by, 
                                       self.on_order_update)
                    if order["status"] == "REJECTED":
                        logger.info(f"Chaser Event: Order Rejected: {order['id']} @ {order['limit']}")
                        # Bybit immediately rejects limit-maker orders if limit > BBA for longs and vice versa
                        if order["timeinforce"] == "GTX":
                            time.sleep(2)
                            self.current_order_id = None
                            self.limit = 0 #falling to market order with limit=BBA
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
                                       self.trigger_by, 
                                       self.on_order_update)                
            
            # start the chaser
            return Chaser(id, long, qty, limit, stop, post_only, reduce_only, 
                          callback, trigger_by)


        self.callbacks[ord_id] = callback
  
        self.__new_order(ord_id, side, ord_qty, limit=limit, stop=stop, post_only=post_only, reduce_only=reduce_only, trigger_by=trigger_by)


    def get_open_order_qty(self, id, only_active=False, only_conditional=False):
        """
        Returns the order quantity of the first open order that starts with the given order ID.
        Args:
            id (str): The ID of the order to search for.
            only_active (bool, optional): Return the quantity of active orders only (default is False).
            only_conditional (bool, optional): Return the quantity of conditional orders only (default is False).
        Returns:
            float: The quantity of the first open order or None if no matching order is found.
        """
        quantity_str = ["origQty", "qty"]#"leaves_qty", "leavesQty"]
        order = self.get_open_order(id=id,only_active=only_active, only_conditional=only_conditional)        
        
        order_qty = [] if order is None else [float(order[q]) for q in quantity_str if q in order]   
        return order_qty[0] if order_qty else None

    def get_open_order(self, id, only_active=False, only_conditional=False):
        """
        Returns the order of the first open order that starts with the given order ID.
        Args:
            id (str): Order id. Returns only the first order from the list of orders that matches the provided ID,
                    as it checks if the ID starts with the string passed as `id`.
            only_active (bool, optional): Return active orders only (default is False).
            only_conditional (bool, optional): Return conditional orders only (default is False).
        Returns:
            dict or None: The first open order that matches the given order ID,
                    or None if no matching order is found.
        """     
        orders = self.get_open_orders(id=id,only_active=only_active, only_conditional=only_conditional)
        return orders[0] if orders else None
    
    def get_open_orders(self, id=None, only_active= False, only_conditional=False, separate=False, symbol=None):
        """
        Get all orders or only all conditional orders or only all active orders.
        Args:
            id (str, optional): If provided, returns only orders that start with the provided string (default is None).
            only_active (bool, optional): Return only active orders (default is False).
            only_conditional (bool, optional): Return only conditional orders (default is False).
            separate (bool, optional): If True, returns a dictionary containing separate keys for active and conditional orders (default is False).
        Returns:
            list or dict or None: List of open orders if not separated, a dictionary containing separate keys for active and conditional orders if `separate=True`,
                                or None if no orders are found.
        """
        self.__init_client()

        symbol = self.pair if not symbol else symbol

        # exch_ord_id = 'orderId'
        user_id = 'orderLinkId'
        # Active orders include conditional orders in USDC perps for some reason  
        active_orders = retry(lambda: self.client.
                                get_open_orders(symbol= self.pair, category=self.category))['list'] # ['dataList' if self.pair.endswith('PERP') else 'data']          
        conditional_orders =retry(lambda: self.client.
                                    get_open_orders(symbol= self.pair, category=self.category, orderFiler='StopOrder'))['list'] \
                                if self.spot and self.is_unified_account else [order for order in active_orders if order['stopOrderType'] == 'Stop'] 
       
        orders = conditional_orders if only_conditional else active_orders if only_active else \
                                    {
                                    'active_orders': active_orders,
                                    'conditional_orders': conditional_orders
                                    } if separate else [*active_orders, *conditional_orders]
        
        if id is not None:
            if separate:
                orders = {
                    'active_orders': [order for order in orders['active_orders'] if order[user_id].startswith(id)],
                    'conditional_orders': [order for order in orders['conditional_orders'] if order[user_id].startswith(id)]
                }
            else:
                orders = [order for order in orders if order[user_id].startswith(id)] 

        if separate and (len(orders['active_orders']) > 0 or len(orders['conditional_orders']) > 0):
            return orders
        elif len(orders) > 0:                            
            return orders        
        else:
            return None

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
        Profit taking, stop loss, and trailing functionality.(Independent of sltp())
        Args:
            profit (float, optional): Profit target. Set the profit target value (default is 0).
            loss (float, optional): Stop loss. Set the stop loss value (default is 0).
            trail_offset (float, optional): Trailing stop price. Set the trailing stop offset (default is 0).
            profit_callback (callable, optional): Profit callback. A function to be called when the profit target is reached (default is None).
            loss_callback (callable, optional): Loss callback. A function to be called when the stop loss is triggered (default is None).
            trail_callback (callable, optional): Trailing callback. A function to be called when the trailing stop is triggered (default is None).
            split (int, optional): Split. For iceberg orders, set the number of order splits (default is 1, for non-iceberg orders).
            interval (int, optional): Interval. For iceberg orders, set the time interval between order splits (default is 0, for non-iceberg orders).
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
        trigger_by='CONTRACT_PRICE',
        split=1,
        interval = 0,
        chaser=False,
        retry_maker=100
    ):
        """
        Implement a simple take profit and stop loss strategy.(Independent of exit())
        Sends a reduce-only stop-loss order upon entering a position.
        Args:
            profit_long (float, optional): Profit target value in % for long positions (default is 0).
            profit_short (float, optional): Profit target value in % for short positions (default is 0).
            stop_long (float, optional): Stop-loss value for long positions in % (default is 0).
            stop_short (float, optional): Stop-loss value for short positions in % (default is 0).
            eval_tp_next_candle (bool, optional): Whether to evaluate the profit target at the next candle (default is False).
            round_decimals (int, optional): Round Decimals. Number of decimals to round the order quantity (if not provided, it's rounded automatically).
            profit_long_callback (callable, optional): Profit Long Callback. A function to be called when the long position's profit target is reached (default is None).
            profit_short_callback (callable, optional): Profit Short Callback. A function to be called when the short position's profit target is reached (default is None).
            stop_long_callback (callable, optional): Stop Long Callback. A function to be called when the stop-loss order for long position is triggered (default is None).
            stop_short_callback (callable, optional): Stop Short Callback. A function to be called when the stop-loss order for short position is triggered (default is None).
            trigger_by (str, optional): Trigger By. Price to use for triggers (e.g., 'LastPrice', 'IndexPrice', etc.).
            split (int, optional): Split. For iceberg orders, set the number of order splits (default is 1, for non-iceberg orders).
            interval (int, optional): Interval. For iceberg orders, set the time interval between order splits (default is 0, for non-iceberg orders).
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
            'trigger_by': trigger_by,
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

        unrealised_pnl = self.get_profit()#self.get_position()['unrealisedPnl']

        # trail asset
        if self.get_exit_order()['trail_offset'] > 0 and self.get_trail_price() > 0:
            if self.get_position_size() > 0 and \
                    self.get_market_price() - self.get_exit_order()['trail_offset'] < self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all(self.get_exit_order()['trail_callback'],
                                self.get_exit_order()['split'], self.get_exit_order()['interval'],
                                chaser=self.get_sltp_values()['chaser'],
                                retry_maker=self.get_sltp_values()['retry_maker'])                    
                            
            elif self.get_position_size() < 0 and \
                    self.get_market_price() + self.get_exit_order()['trail_offset'] > self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all(self.get_exit_order()['trail_callback'],
                                self.get_exit_order()['split'], self.get_exit_order()['interval'],
                                chaser=self.get_sltp_values()['chaser'],
                                retry_maker=self.get_sltp_values()['retry_maker'])                                

        #stop loss
        if unrealised_pnl < 0 and \
                0 < self.get_exit_order()['loss'] < abs(unrealised_pnl):
            logger.info(f"Loss cut by stop loss: {self.get_exit_order()['loss']}")
            self.close_all(self.get_exit_order()['loss_callback'],
                            self.get_exit_order()['split'], self.get_exit_order()['interval'],
                            chaser=self.get_sltp_values()['chaser'],
                            retry_maker=self.get_sltp_values()['retry_maker'])                            

        # profit take
        if unrealised_pnl > 0 and \
                0 < self.get_exit_order()['profit'] < abs(unrealised_pnl):
            logger.info(f"Take profit by stop profit: {self.get_exit_order()['profit']}")
            self.close_all(self.get_exit_order()['profit_callback'],
                            self.get_exit_order()['split'], self.get_exit_order()['interval'],
                            chaser=self.get_sltp_values()['chaser'],
                            retry_maker=self.get_sltp_values()['retry_maker'])                            

    def eval_sltp(self):
        """
        Evaluate and execute the simple take profit and stop loss implementation.
        - Sends a reduce-only stop loss order upon entering a position.
        - Requires setting values with sltp() prior.
        """
        pos_size = float(self.get_position_size())
        if pos_size == 0:
            return
        
        avg_entry = self.get_position_avg_price()

        is_tp_full_size = False 
        is_sl_full_size = False       

        # tp
        tp_order = self.get_open_order('TP')           

        if tp_order is not None:
            tp_id = tp_order['orderLinkId']    
            origQty = parseFloat(tp_order['qty'])
            orig_side = tp_order['side'] == "Buy"
            if orig_side == False:
                origQty = -origQty            
            is_tp_full_size = origQty == -pos_size             
        
        tp_percent_long = self.get_sltp_values()['profit_long']
        tp_percent_short = self.get_sltp_values()['profit_short']   

        # tp execution logic                
        if tp_percent_long > 0 and is_tp_full_size == False:
            if pos_size > 0:                
                tp_price_long = round(avg_entry +(avg_entry*tp_percent_long), self.quote_rounding) 
                if tp_order is not None:
                    #time.sleep(0.05)                                         
                    self.cancel(id=tp_id)
                    #time.sleep(0.05)
                self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True,
                            callback=self.get_sltp_values()['profit_long_callback'],
                            trigger_by=self.get_sltp_values()['trigger_by'], 
                            split=self.get_sltp_values()['split'],
                            interval=self.get_sltp_values()['interval'],
                            chaser=self.get_sltp_values()['chaser'],
                            retry_maker=self.get_sltp_values()['retry_maker']
                            )
                
        if tp_percent_short > 0 and is_tp_full_size == False:
            if pos_size < 0:                
                tp_price_short = round(avg_entry -(avg_entry*tp_percent_short), self.quote_rounding)
                if tp_order is not None:
                    #time.sleep(0.05)                                                        
                    self.cancel(id=tp_id)
                    #time.sleep(0.05)
                self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True,
                            callback=self.get_sltp_values()['profit_short_callback'], 
                            trigger_by=self.get_sltp_values()['trigger_by'], 
                            split=self.get_sltp_values()['split'], 
                            interval=self.get_sltp_values()['interval'],
                            chaser=self.get_sltp_values()['chaser'],
                            retry_maker=self.get_sltp_values()['retry_maker']
                            )
        # sl
        sl_order = self.get_open_order('SL')      
        if sl_order is not None:
            sl_id = sl_order['orderLinkId']
            origQty =  parseFloat(sl_order['qty'])
            orig_side = sl_order['side'] == "Buy"        
            if orig_side == False:
                origQty = -origQty            
            is_sl_full_size = origQty == -pos_size  

        sl_percent_long = self.get_sltp_values()['stop_long']
        sl_percent_short = self.get_sltp_values()['stop_short']

        # sl execution logic
        if sl_percent_long > 0 and is_sl_full_size == False:
            if pos_size > 0:
                sl_price_long = round(avg_entry - (avg_entry*sl_percent_long), self.quote_rounding)
                if sl_order is not None:
                    #time.sleep(0.05)                                    
                    self.cancel(id=sl_id)
                    #time.sleep(0.05)
                self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True,
                            callback=self.get_sltp_values()['stop_long_callback'], 
                            trigger_by=self.get_sltp_values()['trigger_by'],
                            split=self.get_sltp_values()['split'],
                            interval=self.get_sltp_values()['interval'],
                            chaser=self.get_sltp_values()['chaser'],
                            retry_maker=self.get_sltp_values()['retry_maker']
                            )
                
        if sl_percent_short > 0 and is_sl_full_size == False:
            if pos_size < 0:
                sl_price_short = round(avg_entry + (avg_entry*sl_percent_short), self.quote_rounding)
                if sl_order is not None: 
                    #time.sleep(0.05)                                         
                    self.cancel(id=sl_id)
                    #time.sleep(0.05)
                self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True,
                            callback=self.get_sltp_values()['stop_short_callback'], 
                            trigger_by=self.get_sltp_values()['trigger_by'],
                            split=self.get_sltp_values()['split'], 
                            interval=self.get_sltp_values()['interval'],
                            chaser=self.get_sltp_values()['chaser'],
                            retry_maker=self.get_sltp_values()['retry_maker']
                            )                  

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
        bybit_bin_size_converted = bin_size_converter(fetch_bin_size)        

        while True:
            # Convert to millisecond timestamps
            limit = 1000 # Limit for data size per page. [1, 1000]. Default: 200
            # Passed in reverse since we recieve a list that is `Sort in reverse by startTime`
            left_time_to_timestamp = int((left_time + delta(fetch_bin_size)) .timestamp() * 1000) 
            
            right_time_to_timestamp = int(left_time.timestamp() * 1000)

            if left_time > right_time:
                break

            logger.info(f"fetching OHLCV data - {left_time}")  

            source = retry(lambda: self.client
                           .get_kline(symbol=self.pair, category=self.category,
                                        interval= bybit_bin_size_converted['bin_size'], #end=left_time_to_timestamp,                                      
                                        start=right_time_to_timestamp, from_time=left_time_to_timestamp, limit=limit))['list']
                                                                      
            if len(source) == 0:
                break            

            source.reverse()
            source_to_object_list =[]            

            for s in source:
                timestamp =int(s[0])                
                source_to_object_list.append({                        
                    "timestamp" : (datetime.fromtimestamp(int(timestamp / 1000 if len(str(timestamp)) == 13 else timestamp)) 
                        + timedelta(seconds= + bybit_bin_size_converted['seconds']) - timedelta(seconds=0.01)).astimezone(UTC),
                    "high" : float(s[2]),
                    "low" : float(s[3]),
                    "open" : float(s[1]),
                    "close" : float(s[4]),
                    "volume" : float(s[5])
                    })

            source = to_data_frame(source_to_object_list)
   
            data = pd.concat([data, source])#.dropna()            

            if right_time > source.iloc[-1].name + delta(fetch_bin_size):              
                left_time = source.iloc[-1].name if source.iloc[-1].name  < right_time else right_time 
                time.sleep(0.2)
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
        if data == None: # minute count of a timeframe for sorting when sorting is needed   
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
        # Bybit can output wierd timestamps - Eg. 2021-05-25 16:04:59.999000+00:00
        # We need to round up to the nearest second for further processing
        new_data = new_data.rename(index={new_data.iloc[0].name: new_data.iloc[0].name.ceil(freq='1T')})           

        # If OHLCV data is not initialized, create and fetch data
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

                logger.info(f"Initial Buffer Fill - Last Candle: {self.timeframe_data[t].iloc[-1].name}")   
        #logger.info(f"timeframe_data: {self.timeframe_data}") 
        #         
        # Timeframes to be updated
        timeframes_to_update = [allowed_range_minute_granularity[t][3] if self.timeframes_sorted != None 
                                else t for t in self.timeframe_info if self.timeframe_info[t]['allowed_range'] == action]
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
            #self.timeframe_data[t] = pd.concat([self.timeframe_data[t], new_data]) 

            # exclude current candle data and store partial candle data
            re_sample_data = resample(self.timeframe_data[t], 
                                      t, 
                                      minute_granularity=True if self.minute_granularity else False)
            self.timeframe_info[t]['partial_candle'] = re_sample_data.iloc[-1].values # store partial candle data
            re_sample_data =re_sample_data[:-1]  # exclude current candle data

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
                    # Evaluation of profit and loss
                    if self.is_exit_order_active:
                        self.eval_exit()
                    if self.is_sltp_active:
                        self.eval_sltp()                   
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

    def __on_update_wallet(self, action, wallet):
        """
        Update wallet.
        Args:
            action (str): Action description (e.g., "update", "create", "delete", etc.).
            wallet (dict): Wallet information dictionary containing balance details.
        """
        self.wallet = {**self.wallet, **wallet}       
        
        balance = parseFloat(wallet["totalWalletBalance"], 0)
        position_size = self.get_position_size()
        pnl = parseFloat(wallet["totalPerpUPL"], 0)
        pnl_perc = pnl*100/balance

        message = f"Balance: {balance:.2f}\nPosition: {position_size:.3f}\nPnL: {pnl:.2f} ({pnl_perc:.2f}%)"
        logger.info(message)
        notify(message)
        
        log_metrics(datetime.utcnow(), "margin", {
            "balance": balance,
            "margin": balance+pnl,
            "profit": pnl,
            "pnl": pnl_perc
        },
        {
            "exchange": conf["args"].exchange,
            "account": self.account,
            "pair": self.pair,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "strategy": conf["args"].strategy
        })
        
    def __on_update_instrument(self, action, instrument):
        """
        Update instrument.
        Args:
            action (str): Action description (e.g., "update", "create", "delete", etc.).
            instrument (dict): Instrument information dictionary containing instrument details.
        """  
        if action not in self.instrument or len(self.instrument) == 0:
            self.instrument[action] = instrument
        
        self.instrument[action].update(instrument)
        #logger.info(f"self.instrument : {self.instrument}")
        
        self.market_price = float(self.instrument[action]['lastPrice'])
        
        if self.position_size == None or self.position_size == 0:
                return        
        # trail price update
        if self.position_size > 0 and \
                self.market_price > self.get_trail_price():
            self.set_trail_price(self.market_price)
        if self.position_size < 0 and \
                self.market_price < self.get_trail_price():
            self.set_trail_price(self.market_price)
        #Get PnL calculation in %
        if not self.spot:
            self.pnl = self.get_pnl() 

    def __on_update_fills(self, action, fills):
        """
        Update fills of orders.
        Args:
            action (str): Action description (e.g., "update", "create", "delete", etc.).
            fills (dict): Fill information dictionary containing details of the filled orders.
        """
        self.last_fill = fills
        #self.eval_sltp()    
        #pos_size = self.get_position_size(force_api_call=True)
        #logger.info(f"position size: {pos_size}")
        self.margin = None
        self.get_balance()
        
        message = f"""========= FILLS =============
                           {fills} 
                      ============================="""
        logger.info(f"{message}")
        #notify(message)
    
    def __on_update_order(self, action, orders):
        """
        Update order status.
        Args:
            action (str): Action description (e.g., "update", "create", "delete", etc.).
            orders (list): List of order information dictionaries containing details of updated orders.
        """
        orders = orders['result'] if 'result' in orders else orders        
        self.order_update.append(orders)              
        orders = [o for o in orders if o['s' if self.spot else 'symbol'] == self.pair]
        
        if len(orders) == 0:
            return
        for o in orders:
            if 'lastExecQty' not in o: # Some ws endpoints wont prvide us with this
                o['lastExecQty'] = None
            if 'rejectReason' not in o: # Some ws endpoints wont prvide us with this
                o['rejectReason'] = None
            if 'avgPrice' not in o: # Some ws endpoints wont prvide us with this
                o['avgPrice'] = None
            id = o['orderLinkId']
            side = o['side']      
            type = o['orderType']
            status = o['orderStatus']
            time_in_force = o['timeInForce']
            qty = float(o['qty'])
            filled_qty =float(o['cumExecQty'])
            limit = parseFloat(o['price'], 0)
            stop = parseFloat(o['triggerPrice'], 0)
            last_fill = parseFloat(o['lastExecQty'], 0)
            reject_reason = o['rejectReason']
            a_price = parseFloat(o['avgPrice'], 0)
            reduceOnly = o['reduceOnly']
            triggerBy = o["triggerBy"] if len(o["triggerBy"]) else "LastPrice"

            created_time = int(o["createdTime"])
            updated_time = int(o["updatedTime"])
            create_update_interval = updated_time - created_time

            if(time_in_force=="PostOnly" and status == "Cancelled" and create_update_interval < 25 and reject_reason == "EC_PostOnlyWillTakeLiquidity"):
                logger.info(f"Post Only Auto Cancelled/Rejected - {reject_reason}") # EC_PostOnlyWillTakeLiquidity
                status = "Rejected" # Bybit immediately rejects limit-maker orders if limit > BBA for longs and vice versa

            logger.info(f"Order: {o}")

            order_info = {}

            # Normalize Order Info to canonical names
            order_info["id"]            = id  # Client Order ID
            order_info["type"]          = bybit_order_type_mapping[type] # LIMIT, MARKET
            order_info["uses"]          = bybit_trigger_by_mapping[triggerBy] # CONTRACT_PRICE, MARK_PRICE, INDEX_PRICE (for stop orders)
            order_info["side"]          = side.upper()  # BUY, SELL
            order_info["status"]        = bybit_order_status_mapping[status]  # NEW, CANCELED, EXPIRED, PARTIALLY_FILLED, FILLED
            order_info["timeinforce"]   = bybit_tif_mapping[time_in_force]  # GTC, IOC, FOK, GTX (PostOnly)
            order_info["qty"]           = qty  # order quantity
            order_info["filled"]        = filled_qty  # filled quantity
            order_info["limit"]         = limit  # limit price
            order_info["stop"]          = stop # stop price
            order_info["avgprice"]      = a_price # average price
            order_info["reduceonly"]    = reduceOnly # Reduce Only Order

            #logger.info(f"Order Update: {order_info}")

            order_log = False

            callback = self.callbacks.get(id, None)
            all_updates = None
            if callable(callback):
                if len(signature(callback).parameters) > 0: # check if the callback accepts order argument
                    all_updates = True # call the callback with order_info oject on all relevant updates from WS
                else:
                    all_updates = False # call the callback without any arguements only once the order is filled

            # currently only these events will use callbacks
            if(order_info['status'] == "NEW"
            or order_info['status'] == "CANCELED" 
            or order_info['status'] == "REJECTED" 
            or order_info['status'] == "TRIGGERED" 
            or order_info['status'] == "PARTIALLY_FILLED" 
            or order_info['status'] == "FILLED"):
                
                if(order_info['status'] == "NEW"):
                    if all_updates:
                        callback(order_info)    

                # When stop price is hit, the stop order expires and converts into a limit/market order
                if(order_info["status"] == "TRIGGERED"):                    
                    
                    order_log = True  
                    if all_updates:
                        callback(order_info)    

                if(order_info['status'] == "CANCELED"):
                    
                    order_log = True                  
                    self.callbacks.pop(order_info['id'], None) # Removes the respective order callback 
                    
                    if all_updates:
                        callback(order_info) 
                
                if(order_info['status'] == "REJECTED"):

                    order_log = True
                    if all_updates:
                        callback(order_info)
                    
                #only after order is completely filled
                if order_info['status'] == "PARTIALLY_FILLED" or order_info['status'] == "FILLED":

                    if self.order_update_log and order_info['status'] == "FILLED" and order_info["qty"] == order_info["filled"]:

                        order_log = True                    
                        self.callbacks.pop(order_info['id'], None)  # Removes the respective order callback 
                        
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

            if order_info['status'] == "FILLED":
                # Evaluation of profit and loss
                if self.is_exit_order_active:
                    self.eval_exit()
                if self.is_sltp_active:
                    self.eval_sltp()    
        
    def __on_update_position(self, action, position):
        """
        Update position
        """         

        if len(position) > 0:
            position = [p for p in position if p["symbol"].startswith(self.pair)]   
            if len(position) == 0:
                # logger.info(f"Some other pair was traded!")
                return
        else:
            return         

        position[0]['size'] = parseFloat(position[0]['size'], 0)
        
        # Was the position size changed?
        is_update_pos_size = self.get_position_size() != position[0]['size']      

        # Reset trail to current price if position size changes
        if is_update_pos_size and position[0]['size'] != 0:
            self.set_trail_price(self.market_price)

        if is_update_pos_size:
            quote_asset_str = self.base_asset if self.category == 'inverse' else self.quote_asset
            message =   (f"Updated Position\n"
                        f"Price(entryPrice): {self.position[0]['avgPrice']} => {position[0]['entryPrice']}\n"
                        f"Qty(size): {self.position[0]['size'] * (-1 if self.position[0]['side'] == 'Sell' else 1)} => {position[0]['size'] * (-1 if position[0]['side'] == 'Sell' else 1)}\n"
                        f"liqPrice: {parseFloat(self.position[0]['liqPrice'])} => {parseFloat(position[0]['liqPrice'])}\n"
                        f"Balance: {self.get_balance()} {quote_asset_str}")
            logger.info(message)
            notify(message)       
        
        self.position[0]['avgPrice'] = float(position[0]['entryPrice'])
        self.position[0].update(position[0])
       
        self.position_size = parseFloat(self.position[0]['size'])
        self.entry_price = parseFloat(self.position[0]['avgPrice'])        
    
        # Evaluation of profit and loss, calling stop loss and take profit functions
        #self.eval_exit()
        #self.eval_sltp()

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
        Update best bid and best ask price and quantity.
        Args:
            action (str): Action description (e.g., "update", "create", "delete", etc.).
            bookticker (dict): Dictionary containing the updated book ticker data.
        """

        self.bookticker = {k:v for k,v in bookticker.items() if (k=='a' or k=='b') and len(v) > 0}       

        if 'b' in self.bookticker and 'a' in self.bookticker:
            
            best_bid_changed = False

            best_bid_price = float(self.bookticker['b'][0][0])
            if( self.best_bid_price != best_bid_price ):
                self.best_bid_price = best_bid_price
                best_bid_changed = True
            
            best_ask_changed = False

            best_ask_price = float(self.bookticker['a'][0][0])
            if (self.best_ask_price != best_ask_price ):
                self.best_ask_price = best_ask_price
                best_ask_changed = True

            
            if best_bid_changed or best_ask_changed:
                for callback in self.best_bid_ask_change_callback.copy().values():
                    if callable(callback):
                        callback(best_bid_changed, best_ask_changed)
            
            self.bid_quantity_L1 = float(self.bookticker['b'][0][1])          
            self.ask_quantity_L1 = float(self.bookticker['a'][0][1])
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
        self.bin_size = bin_size
        self.strategy = strategy
        logger.info(f"pair: {self.pair}")  
        logger.info(f"timeframes: {bin_size}")    

        if self.is_running:
            self.__init_client()
            self.ws = BybitWs(account=self.account, pair=self.pair, bin_size=self.bin_size, spot=self.spot, is_unified=self.is_unified_account, test=self.demo)

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
            #self.ws.bind("trade", self.__update_ohlcv) # tick data
            self.ws.bind('instrument', self.__on_update_instrument)
            self.ws.bind('wallet', self.__on_update_wallet)
            self.ws.bind('position', self.__on_update_position)
            self.ws.bind('bookticker', self.__on_update_bookticker)
            self.ws.bind('execution', self.__on_update_fills)
            self.ws.bind('order', self.__on_update_order)
            # TODO orderbook
            # self.ob = OrderBook(self.ws)        

    def stop(self):
        """
        Stop the WebSocket data streams.

        This function stops the WebSocket data streams and closes the connection with the exchange.

        Returns:
            None
        """
        self.stop_chaser_thread = True
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