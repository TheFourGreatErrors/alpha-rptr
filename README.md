# alpha rptr

<img src="img/rptr.png" width="200">

## About

The Github repository features a trading system designed for automated algorithmic trading on Binance Futures, Bybit, BitMEX and FTX.

This trading system aims to offer an easy-to-use platform for users to test their trading strategies through backtesting and paper trading, as well as execute trades in live environments. With the goal of minimizing discrepancies between simulated and live trading results, the system allows for seamless transitions from backtesting to paper trading and finally to live trading. Additionally, users can expect minimal changes to their strategy code when transitioning from simulated to live trading.

While developing strategies, users are expected to have a basic understanding of trading and are not subject to many limitations. The system is designed around pre-defined events, such as market data updates, order updates, and trade executions, and provides various technical features, including advanced order types, and real-time position and order monitoring, to support the development and execution of trading strategies.

## Disclaimer

Please note that the author of this software is not liable for any losses, damages or other adverse consequences resulting from the use of this software. It is highly recommended that you exercise caution and thoroughly test your trading strategy using small sizes over an extended period of time to ensure that it performs as expected before deploying it with larger sums of money.

## Features

- API and Websocket implementation for all exchanges supported (Binance Futures, FTX, BitMEX)
- Supports all pairs
- Event-driven
- all types of orders supported including majority of parameters/combinations - if you miss any, you can request
- Supports custom strategies
- Backtesting
- Testnet for BitMEX and Binance Futures (FTX doesn't have a testnet)
- Stub trading (paper trading)
- TA-lib indicators, you can request an indicator if its missing
- Very easy strategy implementation, should be easy enough to migrate most pine script(tradingview) strategies - see Sample strategy
- Discord webhooks and Line notifications supported

## Implemented reference strategies

1. Channel Breakout
2. Cross SMA
3. RCI
4. Open Close Cross Strategy
5. Trading View Strategy (implemented but not supported in the current implementation via gmail) - maybe in the future todo tradingview webhooks implementation, until then this project is recommended for tradingview webhooks trading: https://github.com/CryptoMF/frostybot

It is not recommended to use these strategies for live trading, as they are here mostly just for reference.

## Requirements

- Python: 3.6.5

## How to install

### 1. Install packages

#### OSX

```bash
$ brew install ta-lib
$ git clone https://github.com/TheFourGreatErrors/alpha-rptr.git
$ cd alpha-rptr/
$ pip install -r requirements.txt
```

#### LINUX

```bash
$ wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
$ tar xvzf ta-lib-0.4.0-src.tar.gz
$ cd ta-lib/
$ ./configure --prefix=/usr
$ make
$ sudo make install
$ git clone https://github.com/TheFourGreatErrors/alpha-rptr.git
$ cd alpha-rptr/
$ pip install -r requirements.txt
```
**Disclaimer:** We are using a Python wrapper for the `TA-Lib` library, which provides a wide range of technical analysis functions for financial markets. It is important to note that the underlying TA-Lib library is written in C language. Therefore, in order to install and use this library, it needs to be properly compiled on your system. The Python wrapper allows these functions to be used from within Python code, but the installation process may require some technical knowledge. It is important to ensure that the C library is properly compiled prior to installation in order to avoid errors and ensure that the library functions correctly.

### 2. Setting keys 

The `src/config.py` file is where you can set your API keys and other configuration settings for the trading bot. Here's how to do it:
1. Open the config.py file in a text editor or IDE.
2. Look for the binance_keys section of the configuration dictionary. This is where you'll enter your Binance API keys.
3. Replace the empty string "" in the API_KEY and SECRET_KEY fields with your actual Binance API key and secret key, respectively. You can find your API keys by logging into your Binance account and navigating to the API Management page.
4. If you have additional Binance accounts or other exchanges, you can enter their API keys in the corresponding sections of the configuration dictionary.
5. Save the config.py file.

In addition to API keys, you can also set other configuration settings, such as webhook URLs for Discord and LINE, and health check parameters for monitoring the status of your accounts.

Note that you can also set up different trading profiles using the args_profile field, which allows you to specify different settings for different trading sessions. To use a specific profile, you can run the program with the --profile <profile name> flag.

When setting up your API keys, make sure to keep them secure and not share them with anyone.

```python
config = {
    "binance_keys": {
            "binanceaccount1": {"API_KEY": "", "SECRET_KEY": ""},
            "binanceaccount2": {"API_KEY": "", "SECRET_KEY": ""},
            # Examaple using environment variable
            "binanceaccount3": {"API_KEY": os.environ.get("BINANCE_API_KEY_3"), 
                                "SECRET_KEY": os.environ.get("BINANCE_SECRET_KEY_3")}
    },
    "binance_test_keys": {
            "binancetest1": {"API_KEY": "", "SECRET_KEY": ""},
            "binancetest2": {"API_KEY": "", "SECRET_KEY": ""}
    },
    "bybit_keys": {
            "bybitaccount1": {"API_KEY": "", "SECRET_KEY": ""},
            "bybitaccount2": {"API_KEY": "", "SECRET_KEY": ""}
    },
    "bybit_test_keys": {
            "bybittest1": {"API_KEY": "", "SECRET_KEY": ""},
            "bybittest2": {"API_KEY": "", "SECRET_KEY": ""}
    },
    "bitmex_keys": {
            "bitmexaccount1": {"API_KEY": "", "SECRET_KEY": ""},
            "bitmexaccount2": {"API_KEY": "", "SECRET_KEY": ""}
    },
    "bitmex_test_keys": {
            "bitmextest1":{"API_KEY": "", "SECRET_KEY": ""},
            "bitmextest2": {"API_KEY": "", "SECRET_KEY": ""}
    },
    "ftx_keys": {
            "ftxaccount1": {"API_KEY": "", "SECRET_KEY": ""},
            "ftxaccount2": {"API_KEY": "", "SECRET_KEY": ""},                    
    },  
    "line_apikey": {"API_KEY": ""},
    "discord_webhooks": {
            "binanceaccount1": "",
            "binanceaccount2": "",
            "bybitaccount1": "",
            "bybitaccount2": ""
    },
    "healthchecks.io": {
                    "binanceaccount1": {
                            "websocket_heartbeat": "",
                            "listenkey_heartbeat": ""
                    },
                    "bybitaccount1": {
                            "websocket_heartbeat": "",
                            "listenkey_heartbeat": ""
                    }
    },
    # To use Args profiles, add them here and run by using the flag --profile <your profile string>
    "args_profile": {"binanceaccount1_Sample_ethusdt": {"--test": False,
                                                        "--stub": False,
                                                        "--demo": False,
                                                        "--hyperopt": False,
                                                        "--spot": False,
                                                        "--account": "binanceaccount1",
                                                        "--exchange": "binance",
                                                        "--pair": "ETHUSDT",
                                                        "--strategy": "Sample",
                                                        "--session": None}}                                              
}
```

If you want to send notifications to LINE or Discord, set LINE's API key and/or Discord webhooks - discord will be sending notifications based on the account you choose to trade with. #todo telegram
 
### 3. Exchange config
 This is the configuration dictionary (found in `src/exchange_config.py`) for various exchanges including Binance, Bybit, Bitmex, and FTX. It contains the following parameters:
 ```py
 
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
              "warmup_tf": None}
```
 
## How to execute
 
 To use the trading bot, you need to run the main.py script with the appropriate parameters. Here's a breakdown of the available options:
- `--account`: Specifies the account to use for trading. This should match the name of a configuration file located in the config directory. For example, if you have a file called `binanceaccount1` in the config directory, you would use `--account binanceaccount1`.
- `--exchange`: Specifies the exchange to use. Currently, the bot supports Binance Futures, BitMEX, Bybit and FTX. Use `--exchange binance` to trade on Binance Futures or `--exchange bitmex` to trade on BitMEX.
- `--pair`: Specifies the trading pair to use. This should be a valid trading pair on the selected exchange. For example, `--pair BTCUSDT` would specify the Bitcoin/USDT pair on Binance Futures.
- `--strategy`: Specifies the trading strategy to use. This should match the name of a Python file located in the strategies directory. For example, if you have a file called `sample_strategy.py` in the strategies directory (case sensitive), you would use `--strategy sample_strategy`.
 
To execute the trading bot with the specified parameters, run the following command:
```bash
$ python main.py --account binanceaccount1 --exchange binance --pair BTCUSDT --strategy Sample
 ```
For example, if you want to use the Channel Breakout strategy on BitMEX with bitmexaccount1 and the XBTUSD pair, you would run the following command:

 ```bash
 $ python main.py --account bitmexaccount1 --exchange bitmex --pair XBTUSD --strategy Doten
 ```
 The bot also supports other modes of operation, such as backtesting, demo trading on testnet, hyperparameter optimization, and stub trading (paper trading). For more information on these modes and their respective options, run the following command:
```bash
$ python main.py --help
```

## Mode
### 1. Production Trade Mode
In this mode, the script will execute live trades on the Binance exchange for the specified trading account and trading pair using the specified strategy. To run the script in this mode, use the following command:
 
```bash
$ python main.py --account binanceaccount1 --exchange binance --pair BTCUSDT --strategy Sample
```

### 2. Demo Trade Mode
 In this mode, the script will execute demo trades on [BitMEX testnet](https://testnet.bitmex.com/), [Binance Futures testnet](https://testnet.binancefuture.com/en/futures/BTCUSDT) or [Bybit testnet](https://testnet.bybit.com/en-US/) for the specified trading account and trading pair using the specified strategy. To run the script in this mode, use the following command:

```bash
$ python main.py --demo --account bitmexaccount1 --exchange bitmex --pair XBTUSD --strategy Sample
```

### 3. Back test Mode
In this mode, the script will back test the specified strategy using historical data for the specified trading pair on the Binance exchange. To run the script in this mode, use the following command:
```bash
$ python main.py --test --account binanceaccount1 --exchange binance --pair BTCUSDT --strategy Sample
```

### 4. Hyperopt Mode
Back test Mode: In this mode, the script will back test the specified strategy using historical data for the specified trading pair on the Binance exchange. To run the script in this mode, use the following command:
```bash
$ python main.py --hyperopt --account binanceaccount1 --exchange binance --pair BTCUSDT --strategy Sample
```

### 5. Stub trade Mode (paper trading)
In this mode, the script will simulate trades on the Binance exchange for the specified trading account and trading pair using the specified strategy. No actual trades will be executed. To run the script in this mode, use the following command:
```bash
$ python main.py --stub --account binanceaccount1 --exchange binance --pair BTCUSDT --strategy Sample
```

## How to add a custom strategy

To add a new strategy to the trading bot, follow these steps:

- Create a new file in `src/strategies` folder with a name that is exactly the same as your strategy class name (case sensitive).
- Import necessary files, such as indicators, from other sample strategies or import your own.
- Define your strategy class in the new file.
- Implement your strategy logic inside the strategy method of your class.
- Use the self.exchange object to execute orders based on your strategy's signals.
- Optionally, define other methods that your strategy may need.   

This example should help you get started with adding your own strategies to the bot.

```python
# sample strategy
class Sample(Bot):
    def __init__(self): 
        # set time frame here       
        Bot.__init__(self, ['15m'])
        # initiate variables
        self.isLongEntry = []
        self.isShortEntry = []
        
    def options(self):
        return {}
    
    # Override this bot class function to set the length of historical candlestick data required for your indicators
    # In our case, the longest indicator we use requires 18(sma2) historical candle data values, so 100 is more than enough
    def ohlcv_len(self):
        return 100

    def strategy(self, action, open, close, high, low, volume):    
        # this is your strategy function
        # use action argument for mutli timeframe implementation, since a timeframe string will be passed as `action`        
        
        # Determine the lot size for your orders
        # You can set your own value or use your account balance, e.g. lot = self.exchange.get_balance()
        # Default lot is about 20 times your account size, so use with caution!
        lot = self.exchange.get_lot()
     
        # Example of a callback function, which can be used for order execution
        # For example, this function will log a message when a long or short entry order is successfully executed
        def entry_callback(avg_price=close[-1]):
            long = True if self.exchange.get_position_size() > 0 else False
            logger.info(f"{'Long' if long else 'Short'} Entry Order Successful")

        # if you are using minute granularity or multiple timeframes
        # its important to use `action` its going pass a timeframe string
        # This way, you can separate different operations and OHLCV timeframe data that gets passed each time
        if action == '1m':            
            # Perform operations on 1-minute timeframe data (if minute_granularity is used)            
            pass
        if action == '15m':
            # indicator lengths
            fast_len = self.input('fast_len', int, 6)
            slow_len = self.input('slow_len', int, 18)

            # Calculate the indicators using the OHLCV data and indicator lengths as arguments
            sma1 = sma(close, fast_len)
            sma2 = sma(close, slow_len)

            # Define the entry conditions for long and short positions
            long_entry_condition = crossover(sma1, sma2)
            short_entry_condition = crossunder(sma1, sma2)

            # Set a simple stop loss and profit target as percentages of entry price
            # Use the built-in `sltp` method to automatically place the stop loss and profit target after entering a position         
            self.exchange.sltp(profit_long=1.25, profit_short=1.25, stop_long=1, stop_short=1.1)
            
            # Execute orders based on entry conditions
            if long_entry_condition:
                # Enter a long position with the specified
                # lot, size and a callback function to be executed upon order execution
                # for non entry orders consider self.exchange.order() function
                self.exchange.entry("Long", True, lot, callback=entry_callback)                       
                
            if short_entry_condition:
                # Enter a short position with the specified 
                # lot, size and a callback function to be executed upon order execution
                # for non entry orders consider self.exchange.order() function
                self.exchange.entry("Short", False, lot, callback=entry_callback) 
            
           # Store historical entry signals, you can store any variable this way to keep historical values
            self.isLongEntry.append(long_entry_condition)
            self.isShortEntry.append(short_entry_condition)      
    
```

## Strategy Session Persistence

Sometime we might need to restart strategies with complex internal state and we might want to preserve this state between restarts.

For this a special provision has been provided by default in every strategy. You can define strategy variables that you want to persist inside the `init()` function of the strategy as `self.session.<whatever> = <whatever>` and these variables that are namespaced inside session will be optionally saved to a JSON file when the bot exits.

You can turn on session persistence by adding `--session <filename.json>` to the shell command used to start the bot. The bot then prompts you whether to load the session if one exists or will create one otherwise. You can choose to ignore the saved session and it will store the session afresh in the end.
    
## Advanced Session Usage:
    
Inside strategy you can manipulate Session before saving and loading by overriding `get_session()` and `set_session(session)` methods

Useful since persistence using json only supports basic types and you might have other types that you need to persist - overriding set_session and       get_session lets you manually handle the conversion from and to basic types.

## HTML5 Workbench for Backtests

<img src="img/HTML5Workbench.png" width="800">

A HTML5 Workbench with TradingView Lite (Open Source Version) widget based order visualization on top of Candle Stick data is available. It also displays a table with orders that can be sorted in many ways and clicking on any order date will auto-scroll that period into view.

A file called `orders.csv` file is generated after every backtest in the project root folder. And then at the end of each backtest `data.csv` from data folder and `orders.csv` from project root are symlinked into the new `html/data` directory along with the current strategy file.

Do not forget to refresh the page after each backtest for evaluating the results.

The workbench also helps you save to and retrieve backtests from the inbuilt library. A file called `backtests.db` is created inside `html` folder by the HTML Workbench and all your saved backtests are stored in it. Do not forget to back up this file.

You can use this HTML5 Workbench by executing `python3 -m http.server 8000 --cgi` in the `html` folder and browsing to http://127.0.0.1:8000/ to view backtest results and access the library.

## Dedicated discord server
This server is dedicated for bug reporting, feature requests and support.
https://discord.gg/ah3MGeN

## Support

if you find this software useful and want to support the development, please feel free to donate.

BTC address: 3MJsicsG6C4L7iZyVhEpVsBeEMUxLF3Qq2

ETH address: 0x24291B6F1e3e42D73280Dac54d7251482f5d4D99

DOGE adderess: DLWdyMihy6WTvUkdhiQm7HPCTais5QFRJQ

BNB address: bnb1kfmd03rzr7xekrrdmca92qyasv3kx2vfn7tzk6

Tether(BSC): 0x24291B6F1e3e42D73280Dac54d7251482f5d4D99

USDC(BSC): 0x24291B6F1e3e42D73280Dac54d7251482f5d4D99

SOL address: HARKcAFct9tc3L4E7vt2sDb2jkqBfZz1aaaPFBck5s6T

LTC address: LZo5Q7pabhYt5Zhpt9HC3eHDG3W5nZqGhU

XRP address: rLMGyMAhrDDAh3de2yhzDFwidbPPE7ifkt

MATIC address: 0x24291B6F1e3e42D73280Dac54d7251482f5d4D99
