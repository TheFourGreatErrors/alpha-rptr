# coding: UTF-8

from src import logger
from src.bitmex import BitMex

# stub trading
class BitMexStub(BitMex):
    # Pair
    pair = 'XBTUSD'
    # Default Balance (0.1BTC)
    balance = 0.1 * 100000000
    # Default Leverage
    leverage = 1
    # Current Pos Size
    position_size = 0
    # Current AVG Price
    position_avg_price = 0
    # Current Order Count
    order_count = 0
    # Current Winning Count
    win_count = 0
    # Current Lose Count
    lose_count = 0
    # Win Profit
    win_profit = 0
    # Lose Loss
    lose_loss = 0
    # Max Loss Rate
    max_draw_down = 0
    # max drawdown for the session
    max_draw_down_session = 0
    # max drawdown session %
    max_draw_down_session_perc = 0
    # orders
    open_orders = []

    def __init__(self, account, pair, threading=True):
        """
        constructor
        :account:
        :pair:
        :param threading:
        """
        self.pair = pair
        BitMex.__init__(self, account, pair, threading=threading)
        self.balance_ath = self.balance

    def get_lot(self):
        """
         Calculate the Lot
         :return:
         """
        return int((1 - self.get_retain_rate()) * self.get_balance() / 100000000 * self.get_leverage() * self.get_market_price())

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

    def cancel_all(self):
        """
        cancel the current orders
        """
        self.open_orders = []

    def close_all(self):
        """
        close the current orders
        """
        pos_size = self.position_size
        if pos_size == 0:
            return
        long = pos_size < 0
        ord_qty = abs(pos_size)
        self.commit(id, long, ord_qty, self.get_market_price(), True)
    
    def close_all_at_price(self, price):
        """
        close the current position at price, for backtesting purposes its important to have a function that closes at given price
        :param price: price
        """
        pos_size = self.position_size
        if pos_size == 0:
            return
        long = pos_size < 0 if True else False 
        ord_qty = abs(pos_size)
        self.commit(id, long, ord_qty, price, True)

    def cancel(self, id):
        """
        cancel an order
        :param long: Long or short?
        :return success
        """
        self.open_orders = [o for o in self.open_orders if o["id"] != id]
        return True

    def entry(self, id, long, qty, limit=0, stop=0, post_only=False, when=True):
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

        if limit > 0 or stop > 0:
            self.open_orders.append({"id": id, "long": long, "qty": ord_qty, "limit": limit, "stop": stop, "post_only": post_only})
        else:
            self.commit(id, long, ord_qty, self.get_market_price(), True)
            return

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
            ord_qty = (pyramiding*qty) - abs(pos_size)

        if not long and (pos_size - qty < -(pyramiding*qty)):
            ord_qty = (pyramiding*qty) - abs(pos_size)
        # make sure it doesnt spam small entries, which in most cases would trigger risk management orders evaluation, you can make this less than 2% if needed  
        if ord_qty < ((pyramiding*qty) / 100) * 2:
            return

        if limit > 0 or stop > 0:
            self.open_orders.append({"id": id, "long": long, "qty": ord_qty, "limit": limit, "stop": stop, "post_only": post_only})
        else:
            self.commit(id, long, ord_qty, self.get_market_price(), True)
            return

    def commit(self, id, long, qty, price, need_commission=False):
        """
         Promise.
         : param id: order number
         : param long: long or short
         : param qty: order quantity
         : param price: price
         : param need_commission: Does a fee arise?
        """
        self.order_count += 1

        order_qty = qty if long else -qty
        next_qty = self.get_position_size() + order_qty
        commission = self.get_commission() if need_commission else 0.0

        if (self.get_position_size() > 0 >= order_qty) or (self.get_position_size() < 0 < order_qty):
            if self.get_position_avg_price() > price:
                close_rate = ((self.get_position_avg_price() - price) / price - commission) * self.get_leverage()
                profit = -1 * self.get_position_size() * close_rate
            else:
                close_rate = ((price - self.get_position_avg_price()) / self.get_position_avg_price() - commission) * self.get_leverage()
                profit = self.get_position_size() * close_rate

            if profit > 0:
                self.win_profit += profit/self.get_market_price()*100000000
                self.win_count += 1
            else:
                self.lose_loss += -1 * profit/self.get_market_price()*100000000
                self.lose_count += 1
                if close_rate > self.max_draw_down:
                    self.max_draw_down = close_rate

            self.balance += profit/self.get_market_price()*100000000
            
            if self.balance_ath < self.balance:
                    self.balance_ath = self.balance
            if self.balance_ath > self.balance:
                if self.max_draw_down_session is 0:
                    self.max_draw_down_session = self.balance_ath - self.balance 
                    self.max_draw_down_session_perc = (self.balance_ath - self.balance) / self.balance_ath * 100  
                else:
                    if self.max_draw_down_session < self.balance_ath - self.balance:
                        self.max_draw_down_session = self.balance_ath - self.balance 
                        self.max_draw_down_session_perc = (self.balance_ath - self.balance) / self.balance_ath * 100                         

            if self.enable_trade_log:
                logger.info(f"========= Close Position =============")
                logger.info(f"TRADE COUNT   : {self.order_count}")
                logger.info(f"POSITION SIZE : {self.position_size}")
                logger.info(f"ENTRY PRICE   : {self.position_avg_price}")
                logger.info(f"EXIT PRICE    : {price}")
                logger.info(f"PROFIT        : {profit}")
                logger.info(f"BALANCE       : {self.get_balance()}")
                #logger.info(f"WIN RATE      : {0 if self.order_count == 0 else self.win_count/self.order_count*100} %")
                logger.info(f"WIN RATE      : {0 if self.order_count == 0 else self.win_count/(self.win_count + self.lose_count)*100} %")
                logger.info(f"PROFIT FACTOR : {self.win_profit if self.lose_loss == 0 else self.win_profit/self.lose_loss}")
                logger.info(f"MAX DRAW DOWN : {self.max_draw_down * 100}")
                logger.info(f"MAX DRAW DOWN SESSION : {round(self.max_draw_down_session, 4)} or {round(self.max_draw_down_session_perc, 2)}%")
                logger.info(f"======================================")

        if next_qty != 0:
            if self.enable_trade_log:
                logger.info(f"********* Create Position ************")
                logger.info(f"TIME          : {self.now_time()}")
                logger.info(f"PRICE         : {price}")
                logger.info(f"TRADE COUNT   : {self.order_count}")
                logger.info(f"ID            : {id}")
                logger.info(f"POSITION SIZE : {qty}")
                logger.info(f"**************************************")               
            if long and self.position_size < next_qty:
                self.position_avg_price = (self.position_avg_price * self.position_size + price * qty) /  next_qty 
            elif not long and self.position_size > next_qty:
                self.position_avg_price = (self.position_avg_price * self.position_size - price * qty) /  next_qty
            else:
                 self.position_avg_price = price
            self.position_size = next_qty
            logger.info(f"**********{next_qty}") 
              
           
            self.set_trail_price(price)
        else:
            self.position_size = 0
            self.position_avg_price = 0

    def eval_exit(self):
        """
        Evaluation of accuracy, loss-cutting strategy
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
                self.close_all()
            elif self.get_position_size() < 0 and \
                    price + trail_offset > trail_price:
                logger.info(f"Loss cut by trailing stop: {self.get_exit_order()['trail_offset']}")
                self.close_all()

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
            self.close_all()

        # If profit is set
        if unrealised_pnl > 0 and \
                0 < self.get_exit_order()['profit'] < abs(unrealised_pnl):
            logger.info(f"Take profit by stop profit: {self.get_exit_order()['profit']}")
            self.close_all()

    def on_update(self, bin_size, strategy):
        """
        Register function of strategy.
        :param strategy:
        """
        def __override_strategy(open, close, high, low, volume):
            new_open_orders = []

            if self.get_position_size() > 0 and low[-1] > self.get_trail_price():
                self.set_trail_price(low[-1])
            if self.get_position_size() < 0 and high[-1] < self.get_trail_price():
                self.set_trail_price(high[-1])

            for _, order in enumerate(self.open_orders):
                id = order["id"]
                long = order["long"]
                qty = order["qty"]
                limit = order["limit"]
                stop = order["stop"]
                post_only = order["post_only"]

                if limit > 0 and stop > 0:
                    if (long and high[-1] > stop and close[-1] < limit) or (not long and low[-1] < stop and close[-1] > limit):
                        self.commit(id, long, qty, limit, False)
                        continue
                    elif (long and high[-1] > stop) or (not long and low[-1] < stop):
                        new_open_orders.append({"id": id, "long": long, "qty": qty, "limit": limit, "stop": 0})
                        continue
                elif limit > 0:
                    if (long and low[-1] < limit) or (not long and high[-1] > limit):
                        self.commit(id, long, qty, limit, False)
                        continue
                elif stop > 0:
                    if (long and high[-1] > stop) or (not long and low[-1] < stop):
                        self.commit(id, long, qty, stop, False)
                        continue

                new_open_orders.append(order)

            self.open_orders = new_open_orders
            strategy(open, close, high, low, volume)
            self.eval_exit()

        BitMex.on_update(self, bin_size, __override_strategy)
