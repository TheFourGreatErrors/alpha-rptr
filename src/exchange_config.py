exchange_config = {
    "binance_f":{"qty_in_usdt": False,
                 "minute_granularity": False,
                 "timeframes_sorted": True, # True for higher first, False for lower first and None when off 
                 "enable_trade_log": True,
                 "order_update_log": True,
                 "ohlcv_len": 100,
                 # Call the strategy function on start. This can be useful if you don't want to wait for the candle to close
                 # to trigger the strategy function. However, this can also be problematic for certain operations such as
                 # sending orders or duplicates of orders that have already been sent, which were calculated based on closed
                 # candle data that is no longer relevant. Be aware of these potential issues and make sure to handle them
                 # appropriately in your strategy implementation. 
                 "call_strat_on_start": False,
                # ==== Papertrading And Backtest Class Config ====
                 "balance": 1000,
                 "leverage": 1,
                 "update_data": True,
                 "check_candles_flag": True,
                 "days": 1200,
                 "search_oldest": 10, # Search for the oldest historical data, integer for increments in days, False or 0 to turn it off
                 # Warmup timeframe - used for loading warmup candles for indicators when minute granularity is need
                 # highest tf, if None its going to find it automatically based on highest tf and ohlcv_len
                 "warmup_tf": None}, 
    "bybit": {"qty_in_usdt": False,
              "minute_granularity": False,
              "timeframes_sorted": True, # True for higher first, False for lower first and None when off 
              "enable_trade_log": True,
              "order_update_log": True,
              "ohlcv_len": 100, 
              "call_strat_on_start": False,
             # ==== Papertrading And Backtest Class Config ====
              "balance": 1000,
              "leverage": 1,
              "update_data": True,
              "check_candles_flag": True,
              "days": 1200,
              "search_oldest": 10, # Search for the oldest historical data, integer for increments in days, False or 0 to turn it off
              "warmup_tf": None}, 
    "bitmex": {"qty_in_usdt": False,
              "minute_granularity": False,
              "timeframes_sorted": True, # True for higher first, False for lower first and None when off 
              "enable_trade_log": True,
              "order_update_log": True,
              "ohlcv_len": 100, 
              "call_strat_on_start": False,
             # ==== Papertrading And Backtest Class Config ====
              "balance": 1000,
              "leverage": 1,
              "update_data": True,
              "check_candles_flag": True,
              "days": 1200,
              "search_oldest": 10, # Search for the oldest historical data, integer for increments in days, False or 0 to turn it off
              "warmup_tf": None}, 
    "ftx": {"qty_in_usdt": False,
              "minute_granularity": False,
              "timeframes_sorted": True, # True for higher first, False for lower first and None when off 
              "enable_trade_log": True,
              "order_update_log": True,
              "ohlcv_len": 100, 
              "call_strat_on_start": False,
             # ==== Papertrading And Backtest Class Config ====
              "balance": 1000,
              "leverage": 1,
              "update_data": True,
              "check_candles_flag": True,
              "days": 1200,
              "warmup_tf": None} 
}