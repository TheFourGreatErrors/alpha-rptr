# coding: UTF-8
from src import logger


# stub (paper trading)
class Stub():   
    # Positions in USDT?
    qty_in_usdt = False
    # Minute granularity
    minute_granularity = False
    # Enable log output
    enable_trade_log = True 
    # Default Balance (1000 USDT)    
    balance = 1000
    # Default Leverage
    leverage = 1 

    def __init__(self):   
        # Balance all time high
        self.balance_ath = self.balance
        # Current Pos Size
        self.position_size = 0
        # Current AVG Price
        self.position_avg_price = 0
        # Current Order Count
        self.order_count = 0
        # Current Winning Count
        self.win_count = 0
        # Current Lose Count
        self.lose_count = 0
        # Win Profit
        self.win_profit = 0
        # Lose Loss
        self.lose_loss = 0
        #Drawdown from peak
        self.drawdown = 0
        # Max Loss Rate
        self.max_draw_down = 0
        # max drawdown for the session
        self.max_draw_down_session = 0
        # max drawdown session %
        self.max_draw_down_session_perc = 0
        # orders
        self.open_orders = []
        # Warmup long and short entry lists for tp_next_candle option for sltp()
        self.isLongEntry = [False, False]
        self.isShortEntry = [False,False]               

        self.order_log = open("orders.csv", "w")
        self.order_log.write("time,type,id,price,quantity,av_price,position,pnl,balance,drawdown\n") #header        

    def get_lot(self, **kwargs):
        """
        Calculate the position size (lot) based on the current balance and leverage.

        This function calculates the position size (lot) based on the current balance and leverage set in the trading account.
        Since this is a stub class for backtesting and paper trading purposes, it uses the historical balance and leverage.

        Returns:
            float: The calculated position size (lot).
        """
        return float(self.get_balance() * self.get_leverage() / self.get_market_price())

    def get_balance(self, **kwargs):
        """
        Get the current balance of the trading account.

        This function retrieves the current balance from the stub trading account for pepr trading and backtesting purposes.

        Returns:
            float: The current balance in the base currency.
        """
        return self.balance
    
    def set_leverage(self, leverage, **kwargs):
        """
        Set the leverage for the trading account.

        This function sets the leverage to be used for trading in the stub trading account.

        Args:
            leverage (float): The leverage value to be set.

        Returns:
            None
        """
        self.leverage = leverage

    def get_leverage(self, **kwargs):
        """
        Get the leverage used for the trading account.

        This function retrieves the leverage value currently set in the stub trading account.

        Returns:
            float: The current leverage value.
        """
        return self.leverage

    def get_position_size(self, **kwargs):
        """
        Get the current position size.

        This function retrieves the current position size (quantity) for the trading pair in the stub trading account.        

        Returns:
            float: The current position size (quantity).
        """
        return self.position_size

    def get_position_avg_price(self):
        """
        Get the average price of the current position.

        This function retrieves the average price of the current position for the trading pair in the stub trading account.       

        Returns:
            float: The average price of the current position.
        """
        return self.position_avg_price

    def get_pnl(self):
        """
        Calculate the profit and loss (PnL) percentage for the current position.

        This function calculates the profit and loss percentage for the current position based on the entry price
        and the current market price in the stub trading account.

        Returns:
            float: The profit and loss percentage for the current position.
        """

        # PnL calculation in % 
        entry_price = self.get_position_avg_price()
        pnl = (self.market_price - entry_price) * 100 / entry_price
        return pnl        

    def cancel_all(self):
        """
        Cancel all the current orders.

        This function cancels all the open orders associated with the stub trading account for backtesting purposes.

        Returns:
            None
        """
        self.open_orders = []

    def close_all(self, post_only=False, callback=None, chaser=False, **kwargs):
        """
        Close all the current positions.

        This function closes all the current positions for the trading pair in the stub trading account.
        It submits a closing order with the corresponding order quantity to flatten the position.

        Args:
            callback (function, optional): A callback function to be executed on order completion.
            chaser (bool, optional): If True, the order will be submitted as a trailing stop order (not applicable in backtesting).

        Returns:
            None
        """
        pos_size = self.position_size
        if pos_size == 0:
            return
        long = pos_size < 0
        ord_qty = abs(pos_size)
        self.commit("Close", long, ord_qty, self.get_market_price(), True, False, callback)
    
    def close_all_at_price(self, price, callback=None, chaser=False):
        """
        Close the current position at the specified price.

        This function submits a closing order to close the current position at the specified price in the stub trading account.
        This is particularly useful for backtesting purposes to simulate closing positions at certain prices.

        Args:
            price (float): The price at which the position should be closed.
            callback (function, optional): A callback function to be executed on order completion.
            chaser (bool, optional): If True, the order will be submitted as a trailing stop order (not applicable in backtesting).

        Returns:
            None
        """
        pos_size = self.position_size
        if pos_size == 0:
            return
        long = pos_size < 0 if True else False 
        ord_qty = abs(pos_size)
        self.commit("Close", long, ord_qty, price, True, False, callback)

    def cancel(self, id, **kwargs):
        """
        Cancel a specific order by ID(starts with) from the stub trading account.

        Args:
            id (str): The ID of the order to be canceled.

        Returns:
            bool: True if the order was successfully canceled, False otherwise.
        """
        # Query for an order starting with given id
        order_to_cancel = self.get_open_order(id)

        if order_to_cancel is None:
            return False

        self.open_orders.remove(order_to_cancel)
        return True

    def get_open_order(self, id, **kwargs):
        """
        Get an open order by its ID.

        Args:
            id (str): Order ID for this pair.
            
        Returns:
            dict or None: If multiple orders are found starting with the given ID, return only the first one. None if no matching order is found.
        """        
        open_orders = self.open_orders                           
        filtered_orders = [o for o in open_orders if o["id"].startswith(id)]
        if not filtered_orders:
            return None
        if len(filtered_orders) > 1:
            logger.info(f"Found more than 1 order starting with given id. Returning only the first one!")
        return filtered_orders[0]  
    
    def get_open_orders(self, id=None, **kwargs):
        """
        Get a list of open orders.

        Args:
            id (str, optional): If provided, return only orders whose ID starts with the provided string.

        Returns:
            list or None: List of open orders that match the ID criteria, or None if no open orders are found.
        """        
        open_orders = self.open_orders         
        if not id:
            return self.open_orders                      
        filtered_orders = [o for o in open_orders if o["id"].startswith(id)] if id else open_orders 
        return filtered_orders if filtered_orders else None
    
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
        callback=None, 
        workingType="CONTRACT_PRICE",
        split=1, 
        interval=0,
        chaser=False,
        retry_maker=100,
        **kwargs
    ):
        """
        Place an order.

        This function places an order for the trading pair with the given parameters in the stub trading account.
        For backtesting and paper trading purposes, the order is simulated without actually executing it on an exchange.

        Args:
            id (str): The order ID.
            long (bool): True if it's a long order, False for a short order.
            qty (float): The order quantity.
            limit (float, optional): The limit price for a limit order. Defaults to 0.
            stop (float, optional): The stop price for a stop-limit order. Defaults to 0.
            post_only (bool, optional): True if the order should be post-only. Defaults to False.
            reduce_only (bool, optional): True if the order should be reduce-only. Defaults to False.
            when (bool, optional): Set to True to execute the order. Defaults to True.
            callback (function, optional): A callback function to be executed on order completion.
            workingType (str, optional): The working type for the order. Defaults to "CONTRACT_PRICE".
            split (int, optional): The number of splits for iceberg orders. Defaults to 1.
            interval (int, optional): The interval for time-weighted average price orders. Defaults to 0.
            chaser (bool, optional): If True, the order will be submitted as a trailing stop order (not applicable in backtesting and paper trading).
            retry_maker (int, optional): The number of retries for maker orders. Defaults to 100.

        Returns:
            None
        """
        if not when:
            return

        pos_size = self.get_position_size()
        ord_qty = abs(qty)

        if reduce_only \
            and \
            ((pos_size > 0 and (long == True or ord_qty > abs(pos_size))) \
            or \
            (pos_size < 0 and (long == False or ord_qty > abs(pos_size)))):
            return

        self.cancel(id)

        if limit > 0 or stop > 0:
            self.open_orders.append({"id": id, 
                                     "long": long, 
                                     "qty": ord_qty, 
                                     "limit": limit, 
                                     "stop": stop, 
                                     "post_only": post_only, 
                                     "reduce_only": reduce_only, 
                                     "callback": callback})
        else:
            self.commit(id, long, ord_qty, self.get_market_price(), True,  reduce_only, callback)
            return

    def close_partial(
        self, 
        id, 
        ord_qty, 
        limit=0, 
        stop=0, 
        trailValue=0, 
        post_only=False, 
        when=True, 
        need_commission=True, 
        reduce_only=False,
        callback=None, 
        workingType="CONTRACT_PRICE",
        split=1, 
        interval=0,
        chaser=False,
        retry_maker=100,
        **kwargs
    ):
        """
        Close a partial position.

        This function closes a part of the current position for the trading pair in the stub trading account.
        It submits a closing order with the specified order quantity to partially reduce the position.
        """
        pos_size = self.get_position_size()

        if not when or pos_size == 0:
            return

        long = True if pos_size < 0 else False

        if abs(ord_qty) > abs(pos_size):
            ord_qty = pos_size

        if limit > 0 or stop > 0:
            self.open_orders.append({"id": id, 
                                     "long": long, 
                                     "qty": ord_qty, 
                                     "limit": limit, 
                                     "stop": stop, 
                                     "post_only": post_only,
                                     "callback": callback})
        else:
            self.commit(id, long, abs(ord_qty), self.get_market_price(), True, reduce_only, callback)
            return

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
        workingType="CONTRACT_PRICE",
        split=1, 
        interval=0,
        chaser=False,
        retry_maker=100,
        **kwargs
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
            id (str): The order ID.
            long (bool): True if it's a long order, False for a short order.
            qty (float): The order quantity.
            limit (float, optional): The limit price for a limit order. Defaults to 0.
            stop (float, optional): The stop price for a stop-limit order. Defaults to 0.
            post_only (bool, optional): True if the order should be post-only. Defaults to False.
            when (bool, optional): Set to True to execute the order. Defaults to True.
            round_decimals (int, optional): The number of decimals to round the order quantity. Defaults to None.
            callback (function, optional): A callback function to be executed on order completion (not applicable in backtesting and paper trading).
            workingType (str, optional): The working type for the order. Defaults to "CONTRACT_PRICE".
            split (int, optional): The number of splits for iceberg orders. Defaults to 1.
            interval (int, optional): The interval for time-weighted average price orders. Defaults to 0.
            chaser (bool, optional): If True, the order will be submitted as a trailing stop order (not applicable in backtesting and paper trading).
            retry_maker (int, optional): The number of retries for maker orders. Defaults to 100.
            **kwargs: Additional arguments (if needed).

        Returns:
            None
        """
        if not when:
            return

        pos_size = self.get_position_size()

        if long and pos_size > 0:
            return

        if not long and pos_size < 0:
            return

        self.cancel(id)
        ord_qty = qty + abs(pos_size)
        ord_qty = round(ord_qty, round_decimals if round_decimals != None else self.asset_rounding)

        if limit > 0 or stop > 0:
            self.open_orders.append({"id": id, 
                                     "long": long, 
                                     "qty": ord_qty, 
                                     "limit": limit, 
                                     "stop": stop, 
                                     "post_only": post_only, 
                                     "reduce_only": False, 
                                     "callback": callback})
        else:
            self.commit(id, long, ord_qty, self.get_market_price(), True, False, callback)
            return
    
    def entry_pyramiding(
        self, 
        id, 
        long, 
        qty, 
        limit=0, 
        stop=0, 
        trailValue= 0, 
        post_only=False, 
        reduce_only=False, 
        ioc=False, 
        cancel_all=False, 
        pyramiding=2, 
        when=True,
        round_decimals=None,
        callback=None, 
        workingType="CONTRACT_PRICE",
        split=1, 
        interval=0,
        chaser=False,
        retry_maker=100,
        **kwargs
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
            pyramiding (int, optional): The number of entries to be placed with pyramiding. Defaults to 2.
            + other Args the same as `entry()`
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
     
        # make sure it doesnt spam small entries, 
        # which in most cases would trigger risk management orders evaluation, you can make this less than 2% if needed  
        if ord_qty < ((pyramiding*qty) / 100) * 2:
            return       

        ord_qty = round(ord_qty, round_decimals if round_decimals != None else self.asset_rounding)

        if limit > 0 or stop > 0:
            self.open_orders.append({"id": id, 
                                     "long": long, 
                                     "qty": ord_qty, 
                                     "limit": limit, 
                                     "stop": stop, 
                                     "post_only": post_only, 
                                     "reduce_only": False, 
                                     "callback": callback})
        else:
            self.commit(id, long, ord_qty, self.get_market_price(), True, reduce_only, callback)
            return

    def commit(
        self, 
        id, 
        long, 
        qty, 
        price, 
        need_commission=False, 
        reduce_only=False,
        callback=None            
    ):        
        """         
        Commits a trade order.

        This function commits a trade order for the trading pair in the stub trading account.
        It updates the position size, average entry price, profit and loss, and other relevant account metrics.

        Parameters:
            id (str): Order id.
            long (bool): Indicates whether the order is long (True) or short (False).
            qty (float): Order quantity.
            price (float): Price of the order.
            need_commission (bool, optional): Indicates if a commission fee arises. Defaults to False.
            reduce_only (bool, optional): Indicates if the order is reduce-only. Defaults to False.
            callback (function, optional): Callback function to execute after the order is committed. Defaults to None.

        Returns:
            None
        """
        self.order_count += 1

        qty = abs(self.get_position_size()) if abs(qty) > abs(self.get_position_size()) and reduce_only == True else abs(qty)
        order_qty = qty if long else -qty

        if self.get_position_size()*order_qty > 0:
            next_qty = self.get_position_size() + order_qty
        else:
            if abs(order_qty) > abs(self.get_position_size()):
                next_qty = self.get_position_size() + order_qty
            else:
                next_qty = 0

        commission = self.get_commission() if need_commission else 0.0

        if (self.get_position_size() > 0 >= order_qty) or (self.get_position_size() < 0 < order_qty):            
            closing_qty = -order_qty if abs(order_qty) < abs(self.get_position_size()) else self.get_position_size()
            if self.get_position_size() >= 0:
                close_rate = ((price - self.get_position_avg_price())/self.get_position_avg_price()) - commission                 
            else:
                close_rate = ((self.get_position_avg_price() - price)/self.get_position_avg_price()) - commission

            profit = abs(closing_qty) * close_rate * (1 if self.qty_in_usdt else self.get_position_avg_price())

            if profit > 0:
                self.win_profit += profit #* self.get_market_price() 
                self.win_count += 1                
            else:
                self.lose_loss += -1 * profit #* self.get_market_price() 
                self.lose_count += 1
                if close_rate*self.leverage < self.max_draw_down:
                    self.max_draw_down = close_rate*self.leverage

            self.balance += profit #* self.get_market_price() / 100

            if self.balance_ath < self.balance:
                    self.balance_ath = self.balance
            if self.balance_ath > self.balance:
                if self.max_draw_down_session is 0:
                    self.max_draw_down_session = self.balance_ath - self.balance
                    self.max_draw_down_session_perc = (self.balance_ath - self.balance) / self.balance_ath * 100
                else:
                    if self.max_draw_down_session_perc < (self.balance_ath - self.balance) / self.balance_ath * 100: #if self.max_draw_down_session < self.balance_ath - self.balance:
                        self.max_draw_down_session = self.balance_ath - self.balance
                        self.max_draw_down_session_perc = (self.balance_ath - self.balance) / self.balance_ath * 100

            self.drawdown = (self.balance_ath - self.balance) / self.balance_ath * 100

            # self.order_log.write("time,type,id,price,quantity,av_price,position,pnl,balance,drawdown\n") #header
            self.order_log.write(
                f"{self.timestamp},{'BUY' if long else 'SELL'},{id if next_qty == 0 else 'Reversal'},"\
                f"{price},{-self.position_size if abs(next_qty) else order_qty},{self.position_avg_price},"
                f"{0 if abs(next_qty) else self.position_size+order_qty},{profit:.2f},{self.get_balance():.2f},{self.drawdown:.2f}\n"
                )
            self.order_log.flush()

            self.position_size = self.get_position_size() + order_qty    

            if self.enable_trade_log:
                logger.info(f"========= Close Position =============")
                logger.info(f"ID            : {id if next_qty == 0 else 'Reversal'}")
                logger.info(f"TIME          : {self.timestamp}")
                logger.info(f"TRADE COUNT   : {self.order_count}")
                logger.info(f"POSITION SIZE : {self.position_size}")
                logger.info(f"ENTRY PRICE   : {self.position_avg_price}")
                logger.info(f"EXIT PRICE    : {price}")
                logger.info(f"PROFIT        : {profit}")
                logger.info(f"BALANCE       : {self.get_balance()}")
                #logger.info(f"WIN RATE      : {0 if self.order_count == 0 else self.win_count/self.order_count*100} %")
                logger.info(f"WIN RATE      : {0 if self.order_count == 0 else self.win_count/(self.win_count + self.lose_count)*100} %")
                logger.info(f"PROFIT FACTOR : {self.win_profit if self.lose_loss == 0 else self.win_profit/self.lose_loss}")
                logger.info(f"MAX DRAW DOWN : {abs(self.max_draw_down) * 100:.2f}%")
                logger.info(f"MAX DRAW DOWN SESSION : {round(self.max_draw_down_session, 4)} or {round(self.max_draw_down_session_perc, 2)}%")
                logger.info(f"======================================")

            if next_qty == 0 and callback != None:
                callback()

        if next_qty != 0:
            if self.enable_trade_log:
                logger.info(f"********* Create Position ************")
                logger.info(f"TIME          : {self.timestamp}")
                logger.info(f"PRICE         : {price}")
                logger.info(f"TRADE COUNT   : {self.order_count}")
                logger.info(f"ID            : {id}")
                logger.info(f"POSITION SIZE : {order_qty if next_qty * self.position_size > 0 else next_qty}")
                logger.info(f"**************************************")   

            if long and 0 < self.position_size < next_qty:
                self.position_avg_price = (self.position_avg_price * self.position_size + price * qty) /  next_qty 
            elif not long and 0 > self.position_size > next_qty:
                self.position_avg_price = (self.position_avg_price * self.position_size - price * qty) /  next_qty
            else:
                 self.position_avg_price = price
            self.position_size = next_qty
            logger.info(f"//////// Current Position ////////////")
            logger.info(f"current position size: {next_qty} at avg. price: {self.position_avg_price}")

            # self.order_log.write("time,type,id,price,quantity,av_price,position,pnl,balance,drawdown\n") #header
            self.order_log.write(f"{self.timestamp},{'BUY' if long else 'SELL'},{id},{price},"
                                 f"{next_qty if abs(order_qty) > abs(next_qty) else order_qty},"
                                 f"{self.position_avg_price},{self.position_size},{'-'},"
                                 f"{self.get_balance():.2f},{self.drawdown:.2f}\n")
            self.order_log.flush()

            self.set_trail_price(price)

            if callback != None:
                callback()

    def eval_exit(self):
        """
        Evaluate exit conditions.

        This function evaluates the exit conditions for the current position in the stub trading account.
        It checks if the position should be closed based on trailing stop loss or take profit levels.

        Returns:
            None
        """
        if self.get_position_size() == 0:
            return

        price = self.get_market_price()

        # trail asset
        if self.get_exit_order()['trail_offset'] > 0 and self.get_trail_price() > 0:
            trail_offset = self.get_exit_order()['trail_offset']
            trail_price = self.get_trail_price()
            if self.get_position_size() > 0 and \
                    price - trail_offset < trail_price:
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all(self.get_exit_order()['trail_callback'])
            elif self.get_position_size() < 0 and \
                    price + trail_offset > trail_price:
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all(self.get_exit_order()['trail_callback'])

        if self.get_position_avg_price() > price:
            close_rate = ((self.get_position_avg_price() - price) / price - self.get_commission()) * self.get_leverage()
            unrealised_pnl = -1 * self.get_position_size() * close_rate
        else:
            close_rate = ((price - self.get_position_avg_price())
                           / self.get_position_avg_price() - self.get_commission()) * self.get_leverage()
            unrealised_pnl = self.get_position_size() * close_rate

        # If loss is set
        if unrealised_pnl < 0 and \
                0 < self.get_exit_order()['loss'] < abs(unrealised_pnl):
            logger.info(f"Loss cut by stop loss: {self.get_exit_order()['loss']}")
            self.close_all(self.get_exit_order()['loss_callback'])

        # If profit is set
        if unrealised_pnl > 0 and \
                0 < self.get_exit_order()['profit'] < abs(unrealised_pnl):
            logger.info(f"Take profit by stop profit: {self.get_exit_order()['profit']}")
            self.close_all(self.get_exit_order()['profit_callback'])

    def eval_sltp(self):
        """
        Evaluate stop loss and take profit.

        This function evaluates the stop loss and take profit levels for the current position in the stub trading account.
        It checks if the position should be closed based on the specified stop loss and take profit percentages.

        Returns:
            None
        """
        pos_size = self.get_position_size()
        if pos_size == 0:
            return

        best_bid = self.market_price
        best_ask = self.market_price        
        tp_percent_long = self.get_sltp_values()['profit_long']
        tp_percent_short = self.get_sltp_values()['profit_short']   

        avg_entry = self.get_position_avg_price() 
        
        #sl   
        sl_percent_long = self.get_sltp_values()['stop_long']
        sl_percent_short = self.get_sltp_values()['stop_short']         

        # sl execution logic
        if sl_percent_long > 0:
            if pos_size > 0:
                sl_price_long = round(avg_entry - (avg_entry*sl_percent_long), self.quote_rounding)
                if self.OHLC['low'][-1] <= sl_price_long:               
                    self.close_all_at_price(sl_price_long, self.get_sltp_values()['stop_long_callback']) 
        if sl_percent_short > 0:
            if pos_size < 0:
                sl_price_short = round(avg_entry + (avg_entry*sl_percent_short), self.quote_rounding)
                if self.OHLC['high'][-1] >= sl_price_short:                 
                    self.close_all_at_price(sl_price_short, self.get_sltp_values()['stop_short_callback'])    

        # eval_tp_next_candle
        if (self.isLongEntry[-1] == True and self.isLongEntry[-2] == False and self.get_sltp_values()['eval_tp_next_candle']) or \
            (self.isShortEntry[-1] == True and self.isShortEntry[-2] == False and self.get_sltp_values()['eval_tp_next_candle']):
            return
        
        # tp execution logic                
        if tp_percent_long > 0:
            if pos_size > 0:                
                tp_price_long = round(avg_entry +(avg_entry*tp_percent_long), self.quote_rounding) 
                if tp_price_long <= best_ask and self.get_sltp_values()['eval_tp_next_candle'] == True and  \
                    (self.isLongEntry[-1] == False and self.isLongEntry[-2] == True and self.isLongEntry[-3] == False):
                    tp_price_long = best_ask
                if self.OHLC['high'][-1] >= tp_price_long:               
                    self.close_all_at_price(tp_price_long, self.get_sltp_values()['profit_long_callback'])
        if tp_percent_short > 0:
            if pos_size < 0:                
                tp_price_short = round(avg_entry -(avg_entry*tp_percent_short), self.quote_rounding)
                if tp_price_short >= best_bid and self.get_sltp_values()['eval_tp_next_candle'] == True and  \
                    (self.isShortEntry[-1] == False and self.isShortEntry[-2] == True and self.isShortEntry[-3] == False):
                    tp_price_short = best_bid
                if self.OHLC['low'][-1] <= tp_price_short:               
                    self.close_all_at_price(tp_price_short, self.get_sltp_values()['profit_short_callback'])  

    @staticmethod
    def override_strategy(strategy):       
        """
        A decorator to override the behavior of a target function with the provided custom strategy.
            args:
                strategy(function): the function to be overridden.
            return:
               The wrapped function that will use the custom strategy before and after calling the original function.
        """
         # The wrapper function that will replace the original function.
        def wrapper(self, action, open, close, high, low, volume):           
            new_open_orders = []
            pos_size = self.get_position_size()
            trail_price = self.get_trail_price()
            
            self.OHLC = {'open': open,
                        'high': high,
                        'low': low,
                        'close': close}

            if pos_size > 0 and low[-1] > trail_price:
                self.set_trail_price(low[-1])
            if pos_size < 0 and high[-1] < trail_price:
                self.set_trail_price(high[-1])

            index=0

            while(True):
                
                if index < len(self.open_orders):
                    order = self.open_orders[index]
                    index += 1
                else:
                    break

                id = order["id"]
                long = order["long"]
                qty = order["qty"]
                limit = order["limit"]
                stop = order["stop"]
                post_only = order["post_only"]
                reduce_only = order["reduce_only"]
                callback = order["callback"]

                if reduce_only == True and (self.position_size == 0
                                            or (long and pos_size > 0)
                                            or (not long and pos_size < 0)):
                    new_open_orders.append({"id": id, 
                                            "long": long, 
                                            "qty": qty, 
                                            "limit": limit, 
                                            "stop": 0, 
                                            "post_only": post_only, 
                                            "reduce_only": reduce_only, 
                                            "callback": callback})
                    continue

                if limit > 0 and stop > 0 and (high[-1] >= stop >= low[-1]):
                        new_open_orders.append({"id": id, 
                                                "long": long, 
                                                "qty": qty, 
                                                "limit": limit, 
                                                "stop": 0, 
                                                "post_only": post_only, 
                                                "reduce_only": reduce_only, 
                                                "callback": callback})
                        if not self.minute_granularity:
                            logger.info("Simulating Stop-Limit orders on historical bars can be erroneous " +
                                        "as there is no way to guess intra-bar price movement. " +
                                        "Stop-Limit orders are coverted into Limit orders " +
                                        "once the stop is hit and evaluated in successive candles. " +
                                        "Switch on Minute Granularity for a more accurate simulation of Stop-limit orders.")
                        continue
                elif limit > 0:
                    if (long and low[-1] < limit) or (not long and high[-1] > limit):
                        self.commit(id, long, qty, limit, True, reduce_only, callback)
                        continue
                elif stop > 0:
                    if (high[-1] >= stop >= low[-1]):
                        self.commit(id, long, qty, stop, True, reduce_only, callback)
                        continue

                new_open_orders.append(order)

            self.open_orders = new_open_orders

            if self.is_exit_order_active:
                self.eval_exit()

            if self.is_sltp_active:            
                self.eval_sltp()

            return strategy(self, action, open, close, high, low, volume)    
        return wrapper