# coding: UTF-8

import json
import math
import os
import traceback
from datetime import datetime, timezone
import time

import pandas as pd
from bravado.exception import HTTPNotFound
from pytz import UTC

from src import logger, retry, allowed_range, to_data_frame, \
    resample, delta, FatalError, notify, ord_suffix
from src.bitmex_api import bitmex_api
from src.config import config as conf
from src.bitmex_websocket import BitMexWs


# Class for production transaction
from src.orderbook import OrderBook


class BitMex:
    # Account
    account = ''
    # Pair
    pair = 'XBTUSD'
    # Wallet
    wallet = None
    # Price
    market_price = 0
    # Position
    position = None
    # Margin
    margin = None
    # Time Frame
    bin_size = '1h'
    # Client for private API
    private_client = None
    # Client for public API
    public_client = None
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
                    'stop_short': 0,
                    'eval_tp_next_candle': False
                    }        
    # Round decimals
    round_decimals = 0
    # Profit, Loss and Trail Offset
    exit_order = {'profit': 0, 'loss': 0, 'trail_offset': 0}
    # Trailing Stop
    trail_price = 0
    # Last strategy execution time
    last_action_time = None

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

    def close_all(self):
        """
        Close all positions for this pair
        """
        self.__init_client()
        order = retry(lambda: self.private_client.Order.Order_closePosition(symbol=self.pair).result())
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
        return True

    def __new_order(self, ord_id, side, ord_qty, limit=0, stop=0, post_only=False, reduce_only=False):
        """
        create an order
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

        self.order(id, long, ord_qty, limit, stop, post_only, reduce_only, when)

    def entry_pyramiding(self, id, long, qty, limit=0, stop=0, post_only=False, reduce_only=False, cancel_all=False, pyramiding=2, when=True):
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

        self.order(id, long, ord_qty, limit, stop, post_only, reduce_only, when)

    def order(self, id, long, qty, limit=0, stop=0, post_only=False, reduce_only=False, allow_amend=True, when=True):
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

    def sltp(self, profit_long=0, profit_short=0, stop_long=0, stop_short=0, eval_tp_next_candle=False, round_decimals=2):
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
                            'eval_tp_next_candle': eval_tp_next_candle
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
            elif self.get_position_size() < 0 and \
                    self.get_market_price() + self.get_exit_order()['trail_offset'] > self.get_trail_price():
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all()

        # stop loss
        if unrealised_pnl < 0 and \
                0 < self.get_exit_order()['loss'] < abs(unrealised_pnl / 100000000):
            logger.info(f"Loss cut by stop loss: {self.get_exit_order()['loss']}")
            self.close_all()

        # profit take
        if unrealised_pnl > 0 and \
                0 < self.get_exit_order()['profit'] < abs(unrealised_pnl / 100000000):
            logger.info(f"Take profit by stop profit: {self.get_exit_order()['profit']}")
            self.close_all()

       # simple TP implementation

    def eval_sltp(self):
        """
        evaluate simple profit target and stop loss
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
                    self.order("TP", False, abs(pos_size), limit=tp_price_long, reduce_only=True, allow_amend=False)
        if tp_percent_short > 0 and is_tp_full_size == False:
            if pos_size < 0:                
                tp_price_short = round(avg_entry -(avg_entry*tp_percent_short), self.round_decimals)
                if tp_order is not None: 
                     #time.sleep(2)                   
                    self.__amend_order(tp_order['clOrdID'], True, abs(pos_size), limit=tp_price_short)
                else:
                    self.order("TP", True, abs(pos_size), limit=tp_price_short, reduce_only=True, allow_amend=False)
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
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True, allow_amend=False)
                    #self.__amend_order(sl_order['clOrdID'], False, abs(pos_size), stop=sl_price_long)
                else:  
                    self.order("SL", False, abs(pos_size), stop=sl_price_long, reduce_only=True, allow_amend=False)
        if sl_percent_short > 0 and is_sl_full_size == False:
            if pos_size < 0:
                sl_price_short = round(avg_entry + (avg_entry*sl_percent_short), self.round_decimals)
                if sl_order is not None:                                  
                    self.cancel(id=sl_order['clOrdID'])
                    time.sleep(2)
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True, allow_amend=False)
                    #self.__amend_order(sl_order['clOrdID'], True, abs(pos_size), stop=sl_price_short)
                else:  
                    self.order("SL", True, abs(pos_size), stop=sl_price_short, reduce_only=True, allow_amend=False)

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
                                                                              count=500, partial=True).result())
            if len(source) == 0:
                break
            logger.info(f"fetching OHLCV data")
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
        get OHLCV data and execute the strategy
        """        
        if self.data is None:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - self.ohlcv_len * delta(self.bin_size)
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
            # Fatal Error
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
        self.bin_size = bin_size
        self.strategy = strategy
        if self.is_running:
            self.ws = BitMexWs(account=self.account, pair=self.pair, test=self.demo)
            self.ws.bind(allowed_range[bin_size][0], self.__update_ohlcv)
            self.ws.bind('instrument', self.__on_update_instrument)
            self.ws.bind('wallet', self.__on_update_wallet)
            self.ws.bind('position', self.__on_update_position)
            self.ws.bind('margin', self.__on_update_margin)
            self.ob = OrderBook(self.ws)
                        
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
