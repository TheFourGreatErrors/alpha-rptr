# coding: UTF-8
import hashlib
import hmac
import json
import os
import threading
import time
import traceback
import urllib

import websocket
import requests
from pytz import UTC
from datetime import datetime, timedelta, timezone

from src import logger, to_data_frame, find_timeframe_string, allowed_range, bin_size_converter, notify
from src.config import config as conf


def generate_nonce():
    return int(round(time.time() * 1000))


class BybitWs:

    def __init__(self, account, pair, spot=False, test=False):
        """
        constructor
        """
        # Account
        self.account = account
        # Pair
        self.pair = pair.replace("-", "") if pair.endswith("PERP") else pair
        # Spot
        self.spot = spot
        # Unified margin?
        self.unified_margin = False
        # testnet
        self.testnet = test     
        # Separate private websocket
        self.wsp = None      
        # Use healthchecks.io
        self.use_healthcecks = True
        # Last Heartbeat
        self.last_heartbeat = 0
        # condition that the bot runs on.
        self.is_running = True
        # Notification destination listener
        self.handlers = {}      
        # Endpoints    
        if self.spot:
            self.endpoint = 'wss://stream-testnet.bybit.com/spot/public/v3' \
                            if self.testnet else  'wss://stream.bybit.com/spot/public/v3'
            self.endpoint_private = 'wss://stream-testnet.bybit.com/spot/private/v3' \
                            if self.testnet else 'wss://stream.bybit.com/spot/private/v3'
        else:
            if self.unified_margin:
                if self.pair.endswith("USDT"):
                    self.endpoint = 'wss://stream-testnet.bybit.com/contract/usdt/public/v3' \
                                    if self.testnet else 'wss://stream.bybit.com/contract/usdt/public/v3'
                    self.endpoint_private = 'wss://stream-testnet.bybit.com/unified/private/v3' \
                                    if self.testnet else 'wss://stream.bybit.com/unified/private/v3'
                if self.pair.endswith("PERP"):
                    self.endpoint = 'wss://stream-testnet.bybit.com/contract/usdc/public/v3' \
                                    if self.testnet else 'wss://stream.bybit.com/contract/usdc/public/v3'
                    self.endpoint_private = 'wss://stream-testnet.bybit.com/unified/private/v3' \
                                    if self.testnet else 'wss://stream.bybit.com/unified/private/v3'
            else:
                if self.pair.endswith("USDT"):
                    self.endpoint = 'wss://stream-testnet.bybit.com/contract/usdt/public/v3' \
                                    if self.testnet else 'wss://stream.bybit.com/contract/usdt/public/v3'
                    self.endpoint_private = 'wss://stream-testnet.bybit.com/contract/private/v3' \
                                    if self.testnet else 'wss://stream.bybit.com/contract/private/v3'
                elif self.pair.endswith("PERP"):
                    self.endpoint = 'wss://stream-testnet.bybit.com/contract/usdc/public/v3' \
                                    if self.testnet else 'wss://stream.bybit.com/contract/usdc/public/v3'
                    self.endpoint_private = 'wss://stream-testnet.bybit.com/trade/option/usdc/private/v1' \
                                    if self.testnet else 'wss://stream.bybit.com/trade/option/usdc/private/v1'
                else:
                    self.endpoint = 'wss://stream-testnet.bybit.com/contract/inverse/public/v3' \
                                    if self.testnet else 'wss://stream.bybit.com/contract/inverse/public/v3'
                    self.endpoint_private = 'wss://stream-testnet.bybit.com/contract/private/v3' \
                                    if self.testnet else 'wss://stream.bybit.com/contract/private/v3'           
        
        # public ws 
        self.ws = websocket.WebSocketApp(self.endpoint,
                            on_message=self.__on_message,
                            on_error=self.__on_error,
                            on_close=self.__on_close)                             
        self.wst = threading.Thread(target=self.__start_public)
        self.wst.daemon = True
        self.wst.start()
        self.ws.on_open = self.__on_open_public
        # private ws 
        self.wsp = websocket.WebSocketApp(self.endpoint_private,
                            on_message=self.__on_message,
                            on_error=self.__on_error,
                            on_close=self.__on_close)                             
        self.wspt = threading.Thread(target=self.__start_private)
        self.wspt.daemon = True
        self.wspt.start()                       
        self.wsp.on_open = self.__on_open_private
        self.__repeated_ping()

    def __auth(self, ws):
        """
        authenticate
        """ 
        logger.info(f"authenticating websocket")
        # API keys
        api_key =  conf['bybit_test_keys'][self.account]['API_KEY'] \
                    if self.testnet else conf['bybit_keys'][self.account]['API_KEY']       
        api_secret = conf['bybit_test_keys'][self.account]['SECRET_KEY'] \
                    if self.testnet else conf['bybit_keys'][self.account]['SECRET_KEY']   
        
        if len(api_key) and len(api_secret) == 0:           
            logger.info("WebSocket is not able to authenticate, make sure you added api key and secret to config.py") 
            
        # Generate expires.
        expires = str(int(time.time() * 50**3))

        # Generate signature.
        _val = 'GET/realtime' + expires
        signature = str(hmac.new(bytes(api_secret, 'utf-8'), 
            bytes(_val, 'utf-8'), digestmod='sha256').hexdigest())

        # Authenticate with API.
        ws.send(
            json.dumps({
                'op': 'auth',
                'args': [api_key, expires, signature]
            })
        )
    
    def ping(self):
        '''Pings the remote server to test the connection. The status of the
        connection can be monitored using ws.ping().
        '''
        self.ws.send(json.dumps({'op': 'ping'}))
        if self.wsp is not None:
            self.wsp.send(json.dumps({'op': 'ping'}))
    
    def __repeated_ping(self):
        """
        keep pinging so we minimize the chance of getting our connections closed
        """                      
        def loop_function():
            while self.is_running:
                try:          
                    self.ping()
                    time.sleep(19)
                except Exception as e:
                    logger.error(f"Keep Alive Error - {str(e)}")
                    #logger.error(traceback.format_exc())
                    notify(f"Keep Alive Error - {str(e)}")
                    #notify(traceback.format_exc())

        timer = threading.Timer(10, loop_function)
        timer.daemon = True        
        timer.start()        
    

    def __start_public(self):
        """
        start the public websocket.
        """
        while self.is_running:        
            self.ws.run_forever()            
    
    def __start_private(self):
        """
        start the private websocket.
        """
        while self.is_running:                    
            self.wsp.run_forever()      

    def __on_open_public(self, ws):        
        if self.spot:  
            ws.send(
                json.dumps({
                    'op': 'subscribe',
                    'args': ["kline.1m." + self.pair, "kline.5m." + self.pair, "kline.1h." + self.pair, "kline.1d." + self.pair, #"trade." + self.pair,
                            "tickers." + self.pair, "bookticker." + self.pair, "orderbook.40." + self.pair]
                }) 
            )    
        else:
           ws.send(
           json.dumps({
                'op': 'subscribe',
                'args': ["kline.1." + self.pair, "kline.5." + self.pair, "kline.60." + self.pair, "kline.D." + self.pair, #"publicTrade." + self.pair,
                        "tickers." + self.pair, "orderbook.1." + self.pair] # orderbook 1 level data is 10ms, 50 level data is 20ms, 200 is 100ms, 500 is 100ms
            })
        )    
    
    def __on_open_private(self, ws):        
        ws = self.wsp if self.wsp else ws    
        self.__auth(ws)      
        account = "unifiedAccount" if self.unified_margin else "contractAccount" 

        if self.spot:
             ws.send(
            json.dumps({
                    'op': 'subscribe',
                    'args': ["outboundAccountInfo", "stopOrder", "order", "ticketInfo"]
                }) 
            )            
        elif self.pair.endswith('PERP') and not self.unified_margin:
            ws.send(
            json.dumps({
                    'op': 'subscribe',
                    'args': ["user.openapi.perp.position", "user.openapi.perp.trade", "user.openapi.perp.order", "user.service"]
                }) 
            )         
        else:           
            ws.send(
            json.dumps({
                    'op': 'subscribe',
                    'args': ["user.position." + account, "user.execution." + account, "user.order." + account, "user.wallet."  + account]
                }) 
            )              
          
    def __on_error(self, ws, message):
        """
        On Error listener
        :param ws:
        :param message:
        """
        logger.error(message)
        logger.error(traceback.format_exc())

        notify(f"Error occurred. {message}")
        notify(traceback.format_exc())

    def __on_message(self, ws, message):
        """
        On Message listener
        :param ws:
        :param message:
        :return:
        """                
        try:
            obj = json.loads(message)      
     
            if 'topic' in obj:
                if len(obj['data']) <= 0:
                    return

                table = obj['topic']
                action = obj['topic'] #obj['type']
                data = obj['data']  

                data = data['result'] if table.startswith("user.openapi.") else data

                if table.startswith("trade"): # Tick Data, we dont currently use it            
                    pass

                elif table.startswith("kline"):                    
                    # if self.use_healthcecks:
                    current_minute = datetime.now().time().minute
                    if self.last_heartbeat != current_minute:
                        # Send a heartbeat to Healthchecks.io
                        try:
                            requests.get(conf['healthchecks.io'][self.account]['websocket_heartbeat'])
                            #logger.info("WS Heart Beat sent!") 
                            self.last_heartbeat = current_minute
                        except Exception as e:
                            pass          

                    kline = 'kline.'            
                    timeframe = table[len(kline):-len('.'+self.pair)] 
                   
                    if timeframe.isdigit():                       
                        action = find_timeframe_string(int(timeframe))
                    else:
                        action = '1' + timeframe.lower()
             
                    if self.spot:                                      
                        action = table[len(kline):-len('.' + self.pair)] 
                        data = [data]          
                        #bin_size_converted = timedelta(seconds=bin_size_converter(allowed_range[action][0])['seconds'])                    
                    data = [{
                        "timestamp" : data[0]['t' if self.spot else 'end'],
                        "high" : float(data[0]['h' if self.spot else 'high']),
                        "low" : float(data[0]['l' if self.spot else 'low']),
                        "open" : float(data[0]['o' if self.spot else 'open']),
                        "close" : float(data[0]['c' if self.spot else 'close']),
                        "volume" : float(data[0]['v' if self.spot else 'volume'])
                        }]
                   
                    if len(str(data[0]['timestamp'])) == 13:
                        data[0]['timestamp'] = data[0]['timestamp']  / 1000
          
                    data[0]['timestamp'] = datetime.fromtimestamp(data[0]['timestamp'], tz=timezone.utc) \
                                        + (timedelta(seconds=0.01) if self.spot else timedelta(seconds=0))   
                    self.__emit(action, action, to_data_frame([data[0]]))
                                           
                elif table.startswith("tickers"):
                    self.__emit('instrument', table, data)  

                elif table.startswith("orderbook.1") or table.startswith("bookticker"):
                    self.__emit("bookticker", obj['type'], data)      

                elif 'position' in table:                            
                    self.__emit("position", action, data)                   

                elif table.startswith(("user." if not self.spot else "") + "execution") \
                    or table.startswith("tickerInfo") or table == "user.openapi.perp.trade":                   
                    self.__emit("execution", action, data[0])

                elif table.startswith("user.order") \
                    or table == "user.openapi.perp.order" \
                    or table == "order" or table.startswith("stopOrder"):
                    self.__emit("order", action, data)

                elif table.startswith("outboundAccountInfo") \
                    or table.startswith("user.wallet") or table == "user.service":
                    self.__emit("wallet", action, data[0])                    

        except Exception as e:
            logger.error(e)
            logger.error(traceback.format_exc())
       
    def __emit(self, key, action, value):       
        """
        send data
        """
        if key in self.handlers:
            self.handlers[key](action, value)

    def __on_close(self, ws):
        """
        On Close Listener
        :param ws:
        """        
        if 'close' in self.handlers:
            self.handlers['close']()

        if self.is_running:
            logger.info(f"Websocket On Close: Restart")
            notify(f"Websocket On Close: Restart")

            time.sleep(60)
            self.ws = websocket.WebSocketApp(self.endpoint,
                                on_message=self.__on_message,
                                on_error=self.__on_error,
                                on_close=self.__on_close)                             
            self.wst = threading.Thread(target=self.__start_public)
            self.wst.daemon = True
            self.wst.start()
            self.ws.on_open = self.__on_open_public
            # private ws 
            self.wsp = websocket.WebSocketApp(self.endpoint_private,
                                on_message=self.__on_message,
                                on_error=self.__on_error,
                                on_close=self.__on_close)                             
            self.wspt = threading.Thread(target=self.__start_private)
            self.wspt.daemon = True
            self.wspt.start()                       
            self.wsp.on_open = self.__on_open_private

    def on_close(self, func):
        """
        on close fn
        :param func:
        """
        self.handlers['close'] = func

    def bind(self, key, func):
        """
        bind fn
        :param key:
        :param func:
        """ 
        self.handlers[key] = func

    def close(self):
        """
        close websocket
        """
        self.is_running = False
        self.ws.close()