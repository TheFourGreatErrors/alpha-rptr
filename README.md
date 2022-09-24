# alpha rptr

<img src="img/rptr.png" width="200">

A trading system for automated algorithmic trading on Binance Futures and BitMEX.  

The author is not responsible for any damage caused by this software. Be careful and test your strategy using very small sizes for some time to make sure it does what you expect it to do. 

## Features

- API and Websocket implementation for both Binance Futures and  BitMEX
- Supports all pairs
- Event-driven
- all types of orders supported including majority of parameters/combinations - if you miss any, you can request
- Supports custom strategies
- Backtesting
- Testnet for BitMEX and Binance Futures
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

### 2. Setting keys 

Set your API keys in `src / config.py` file.

```python
config = {
    "binance_keys": {
                    "binanceaccount1": {"API_KEY": "", "SECRET_KEY": ""},
                    "binanceaccount2": {"API_KEY": "", "SECRET_KEY": ""}
                    },
    "binance_test_keys": {
                    "binancetest1": {"API_KEY": "", "SECRET_KEY": ""},
                    "binancetest2": {"API_KEY": "", "SECRET_KEY": ""}
                    },
    "bitmex_keys": {
                    "bitmexaccount1": {"API_KEY": "", "SECRET_KEY": ""},
                    "bitmexaccount2": {"API_KEY": "", "SECRET_KEY": ""}
                    },
    "bitmex_test_keys": {
                    "bitmextest1": {"API_KEY": "", "SECRET_KEY": ""},
                    "bitmextest2": {"API_KEY": "", "SECRET_KEY": ""}
                    },
    "line_apikey": {"API_KEY": ""},
    "discord_webhooks": {
					"binanceaccount1": "",
					"binanceaccount2": ""
                    },
    "healthchecks.io": {
                    "binanceaccount1": {
                        "websocket_heartbeat": "",
                        "listenkey_heartbeat": ""
                    }
    }                       
}
```

If you want to send notifications to LINE or Discord, set LINE's API key and/or Discord webhooks - discord will be sending notifications based on the account you choose to trade with. #todo telegram 

## How to execute

```bash
$ python main.py --account binanceaccount1 --exchange binance --pair BTCUSDT --strategy Sample
 ```

By changing the values of `ACCOUNT` `EXCHANGE` `PAIR` `STRATEGY` you can switch accounts, exchanges, piars, strategies.

#### Case of using Channel Breakout on bitmex with bitmexaccount1 and XBTUSD pair

 ```bash
 $ python main.py --account bitmexaccount1 --exchange bitmex --pair XBTUSD --strategy Doten
 ```

## Mode
### 1. Production Trade Mode

```bash
$ python main.py --account binanceaccount1 --exchange binance --pair BTCUSDT --strategy Sample
```

### 2. Demo Trade Mode

It is possible to trade on BitMEX [testnet](https://testnet.bitmex.com/) and Binance Futures [testnet](https://testnet.binancefuture.com/en/futures/BTCUSDT)

```bash
$ python main.py --demo --account bitmexaccount1 --exchange bitmex --pair XBTUSD --strategy Sample
```

### 3. Back test Mode

```bash
$ python main.py --test --account binanceaccount1 --exchange binance --pair BTCUSDT --strategy Sample
```

### 4. Hyperopt Mode

```bash
$ python main.py --hyperopt --account binanceaccount1 --exchange binance --pair BTCUSDT --strategy Sample
```

### 5. Stub trade Mode

```bash
$ python main.py --stub --account binanceaccount1 --exchange binance --pair BTCUSDT --strategy Sample
```

## How to add a custom strategy

You can add a strategy by creating a new class in `src / strategy.py`.
Follow this example, which hopefully explains a lot of questions.

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

    def strategy(self, action, open, close, high, low, volume):    
        # this is your strategy function
        # use action argument for mutli timeframe implementation, since a timeframe string will be passed as `action`        
        # get lot or set your own value which will be used to size orders 
        # don't forget to round properly
        # careful default lot is about 20x your account size !!! (binance futures)
        lot = round(self.exchange.get_lot() / 20, 3)

        # Example of a callback function, which we can utilize for order execution etc.
        def entry_callback(avg_price=close[-1]):
            long = True if self.exchange.get_position_size() > 0 else False
            logger.info(f"{'Long' if long else 'Short'} Entry Order Successful")

        # if you are using minute granularity or multiple timeframes its important to use `action` as its going pass a timeframe string
        # this way you can separate functionality and use proper ohlcv timeframe data that get passed each time
        if action == '1m':
            #if you use minute_granularity you can make use of 1m timeframe for various operations
            pass
        if action == '15m':
            # indicator lengths
            fast_len = self.input('fast_len', int, 6)
            slow_len = self.input('slow_len', int, 18)

            # setting indicators, they usually take source and length as arguments
            sma1 = sma(close, fast_len)
            sma2 = sma(close, slow_len)

            # entry conditions
            long_entry_condition = crossover(sma1, sma2)
            short_entry_condition = crossunder(sma1, sma2)

            # setting a simple stop loss and profit target in % using built-in simple profit take and stop loss implementation 
            # which is placing the sl and tp automatically after entering a position
            self.exchange.sltp(profit_long=1.25, profit_short=1.25, stop_long=1, stop_short=1.1, round_decimals=0)

            # example of calculation of stop loss price 0.8% round on 2 decimals hardcoded inside this class
            # sl_long = round(close[-1] - close[-1]*0.8/100, 2)
            # sl_short = round(close[-1] - close[-1]*0.8/100, 2)
            
            # order execution logic
            if long_entry_condition:
                # entry - True means long for every other order other than entry use self.exchange.order() function
                self.exchange.entry("Long", True, lot, callback=entry_callback)
                # stop loss hardcoded inside this class
                #self.exchange.order("SLLong", False, lot, stop=sl_long, reduce_only=True, when=False)
                
            if short_entry_condition:
                # entry - False means short for every other order other than entry use self.exchange.order() function
                self.exchange.entry("Short", False, lot, callback=entry_callback)
                # stop loss hardcoded inside this class
                # self.exchange.order("SLShort", True, lot, stop=sl_short, reduce_only=True, when=False)
            
            # storing history for entry signals, you can store any variable this way to keep historical values
            self.isLongEntry.append(long_entry_condition)
            self.isShortEntry.append(short_entry_condition)

            # OHLCV and indicator data, you can access history using list index        
            # log indicator values 
            logger.info(f"sma1: {sma1[-1]}")
            logger.info(f"second last sma2: {sma2[-2]}")
            # log last candle OHLCV values
            logger.info(f"open: {open[-1]}")
            logger.info(f"high: {high[-1]}")
            logger.info(f"low: {low[-1]}")
            logger.info(f"close: {close[-1]}")
            logger.info(f"volume: {volume[-1]}")            
            # log history entry signals
            #logger.info(f"long entry signal history list: {self.isLongEntry}")
            #logger.info(f"short entry signal history list: {self.isShortEntry}")    
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

You can use this HTML5 Workbench by executing `python3 -m http.server 8000 --cgi` in the `html` folder and browsing to https://127.0.0.1:8000/ to view backtest results and access the library.

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
