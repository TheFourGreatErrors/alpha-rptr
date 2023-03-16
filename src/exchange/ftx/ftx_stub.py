# coding: UTF-8

from src import logger
from src.exchange.ftx.ftx import Ftx


# stub (paper trading)
class FtxStub(Ftx):   
    # Positions in USDT?
    qty_in_usdt = False
    # Minute granularity
    minute_granularity = False
    # Enable log output
    enable_trade_log = True 
    # Default Balance (1000 USD)    
    balance = 1000
    # Default Leverage
    leverage = 1 

    def __init__(self, account, pair, demo=False, threading=True):
        """
        constructor
        :account:
        :pair:
        :param threading:
        """       
        Ftx.__init__(self, account, pair, threading=threading)
        # Pair
        self.pair = pair
        # Use testnet? - None is passed when using backtest mode
        self.demo = demo
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
        
    def get_lot(self):
        """
         Calculate the Lot
         :return:
         """
        return float( self.get_balance() * self.get_leverage() / self.get_market_price())

    def get_balance(self):
        """
        Get the Current Balance
        :return:
        """
        return self.balance

    def get_leverage(self):
        """
        Get the leverage
        :return:
        """
        return self.leverage

    def get_position_size(self):
        """
         Get the position size
         :return:
         """
        return self.position_size

    def get_position_avg_price(self):
        """
        Get the position avg price
        :return:
        """
        return self.position_avg_price

    def get_pnl(self):
        """
        get profit and loss calculation in %
        :return:
        """
        # PnL calculation in % 
        entry_price = self.get_position_avg_price()
        pnl = (self.market_price - entry_price) * 100 / entry_price
        return pnl        

    def cancel_all(self):
        """
        cancel the current orders
        """
        self.open_orders = []

    def close_all(self, callback=None):
        """
        close all current orders 
        """
        pos_size = self.position_size
        if pos_size == 0:
            return
        long = pos_size < 0 if True else False 
        ord_qty = abs(pos_size)
        self.commit("Close", long, ord_qty, self.get_market_price(), True, callback)
    
    def close_all_at_price(self, price, callback=None):
        """
        close the current position at price, for backtesting purposes its important to have a function that closes at given price
        :param price: price
        """
        pos_size = self.position_size
        if pos_size == 0:
            return
        long = pos_size < 0 if True else False 
        ord_qty = abs(pos_size)
        self.commit("Close", long, ord_qty, price, True, callback)

    def cancel(self, id):
        """
        cancel an order
        :param long: Long or short?
        :return success
        """
        self.open_orders = [o for o in self.open_orders if o["id"] != id]
        return True

    def entry(self, id, long, qty, limit=0, stop=0, post_only=False, when=True, round_decimals=None, callback=None):
        """
         I place an order. Equivalent function to pine's function.
         https://jp.tradingview.com/study-script-reference/#fun_strategy{dot}entry
        : param id: number of order
        : param long: long or short
        : param qty: order quantity
        : param limit: limit
        : param stop: stop limit
        : param post_only: post only
        : param when: Do you order?
        : return:
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
            self.open_orders.append({"id": id, "long": long, "qty": ord_qty, "limit": limit, "stop": stop, "post_only": post_only, "reduce_only": False, "callback": callback})
        else:
            self.commit(id, long, ord_qty, self.get_market_price(), True, callback)
            return
    
    def entry_pyramiding(self, id, long, qty, limit=0, stop=0, trailValue= 0, post_only=False, reduce_only=False, ioc=False, cancel_all=False, pyramiding=2,
                             when=True, round_decimals=None, callback=None):
        """
        Places an entry order, works as equivalent to tradingview pine script implementation with pyramiding        
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

        if limit > 0 or stop > 0:
            self.open_orders.append({"id": id, "long": long, "qty": ord_qty, "limit": limit, "stop": stop, "post_only": post_only, "reduce_only": False, "callback": callback})
        else:
            self.commit(id, long, ord_qty, self.get_market_price(), True, callback)
            return

    def order(self, id, long, qty, limit=0, stop=0, post_only=False, reduce_only=False, when=True, callback=None):
        """
        Places an order.         
        : param id: number of order
        : param long: long or short
        : param qty: order quantity
        : param limit: limit
        : param stop: stop limit
        : param post_only: post only
        : param reduce_only: reduce only
        : param when: Do you order?
        : return:
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
            self.open_orders.append({"id": id, "long": long, "qty": ord_qty, "limit": limit, "stop": stop, "post_only": post_only, "reduce_only": reduce_only, "callback": callback})
        else:
            self.commit(id, long, ord_qty, self.get_market_price(), True, callback)
            return

    def close_partial(self, id, ord_qty, limit=0, stop=0, trailValue=0, post_only=False, when=True, need_commission=True, callback=None):
        """
        """
        pos_size = self.get_position_size()

        if not when or pos_size == 0:
            return

        long = True if pos_size < 0 else False

        if abs(ord_qty) > abs(pos_size):
            ord_qty = pos_size

        if limit > 0 or stop > 0:
            self.open_orders.append({"id": id, "long": long, "qty": ord_qty, "limit": limit, "stop": stop, "post_only": post_only, "callback": callback})
        else:
            self.commit(id, long, abs(ord_qty), self.get_market_price(), True, callback)
            return

    def commit(self, id, long, qty, price, need_commission=False, callback=None):
        """         
         : param id: order number
         : param long: long or short
         : param qty: order quantity
         : param price: price
         : param need_commission: Does a fee arise?
        """
        self.order_count += 1

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
            self.order_log.write(f"{self.timestamp},{'BUY' if long else 'SELL'},{id if next_qty == 0 else 'Reversal'},{price:.2f},{-self.position_size if abs(next_qty) else order_qty:.2f},{self.position_avg_price:.2f},{0 if abs(next_qty) else self.position_size+order_qty:.2f},{profit:.2f},{self.get_balance():.2f},{self.drawdown:.2f}\n")
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
            self.order_log.write(f"{self.timestamp},{'BUY' if long else 'SELL'},{id},{price:.2f},{next_qty if abs(order_qty) > abs(next_qty) else order_qty:.2f},{self.position_avg_price:.2f},{self.position_size:.2f},{'-'},{self.get_balance():.2f},{self.drawdown:.2f}\n")
            self.order_log.flush()

            self.set_trail_price(price)

            if callback != None:
                callback()

    def eval_exit(self):
        """
        Evaluation of stop loss and profit target - different mechanism than sltp() and eval_sltp() 
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
            close_rate = ((price - self.get_position_avg_price()) / self.get_position_avg_price() - self.get_commission()) * self.get_leverage()
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
        evaluate simple profit target and stop loss        
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
    
    def on_update(self, bin_size, strategy):
        """
        Register function of strategy.
        :param strategy:
        """
        def __override_strategy(action, open, close, high, low, volume):
            new_open_orders = []

            self.OHLC = {
                        'open': open,
                        'high': high,
                        'low': low,
                        'close': close
                        }

            if self.get_position_size() > 0 and low[-1] > self.get_trail_price():
                self.set_trail_price(low[-1])
            if self.get_position_size() < 0 and high[-1] < self.get_trail_price():
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

                if reduce_only == True and (self.position_size == 0 or (long and self.get_position_size() > 0) or (not long and self.get_position_size() < 0)):
                    new_open_orders.append({"id": id, "long": long, "qty": qty, "limit": limit, "stop": 0, "post_only": post_only, "reduce_only": reduce_only, "callback": callback})
                    continue

                if limit > 0 and stop > 0 and (high[-1] >= stop >= low[-1]):
                        new_open_orders.append({"id": id, "long": long, "qty": qty, "limit": limit, "stop": 0, "post_only": post_only, "reduce_only": reduce_only, "callback": callback})
                        if(not self.minute_granularity):
                            logger.info("Simulating Stop-Limit orders on historical bars can be erroneous " +
                                        "as there is no way to guess intra-bar price movement. " +
                                        "Stop-Limit orders are converted into Limit orders once the stop is hit and evaluated in successive candles. " +
                                        "Switch on Minute Granularity for a more accurate simulation of Stop-limit orders.")
                        continue
                elif limit > 0:
                    if (long and low[-1] < limit) or (not long and high[-1] > limit):
                        self.commit(id, long, qty, limit, True, callback)
                        continue
                elif stop > 0:
                    if (high[-1] >= stop >= low[-1]):
                        self.commit(id, long, qty, stop, True, callback)
                        continue

                new_open_orders.append(order)

            self.open_orders = new_open_orders

            if self.is_exit_order_active:
                self.eval_exit()
            if self.is_sltp_active:
                self.eval_sltp()
                
            strategy(action, open, close, high, low, volume)            

        if self.demo == None:
            self.strategy = __override_strategy            
        else:
            Ftx.on_update(self, bin_size, __override_strategy)        