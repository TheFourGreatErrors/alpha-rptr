# coding: UTF-8
import hashlib
import hmac
import json
import os
import threading
import time
import traceback

import websocket
import requests
from pytz import UTC
from datetime import datetime, timedelta, timezone

from src import logger, to_data_frame, find_timeframe_string, bybit_allowed_range, bin_size_converter, notify
from src.config import config as conf
from src.monitor import Monitor


def generate_nonce():
    return int(round(time.time() * 1000))


class BybitWs:

    def __init__(self, account, pair, bin_size, spot=False, is_unified=False, test=False):
        """
        constructor
        """
        # Account
        self.account = account
        # Pair
        self.pair = pair.replace("-", "") if pair.endswith("PERP") else pair
        # Bin Size
        self.bin_size = bin_size
        # Spot
        self.spot = spot
        # Unified margin?
        self.unified_margin = is_unified      
        # testnet
        self.testnet = test     
        # Separate public websocket  
        self.ws = None
        # Public websoket thread
        self.wst = None 
        # Separate private websocket
        self.wsp = None      
        # Private websocket thread
        self.wspt = None   
        # Use healthchecks.io
        self.use_healthchecks = True
        # Last Heartbeat
        self.last_heartbeat = 0
        # condition that the bot runs on.
        self.is_running = True
        # Notification destination listener
        self.handlers = {}      
        
        # Endpoints    
        if self.spot:
            self.endpoint = 'wss://stream-testnet.bybit.com/v5/public/spot' \
                            if self.testnet else  'wss://stream.bybit.com/v5/public/spot'
            
        else:                      
            if self.pair.endswith("USDT") or self.pair.endswith("PERP"):                   
                self.endpoint = 'wss://stream-testnet.bybit.com/v5/public/linear' \
                                if self.testnet else 'wss://stream.bybit.com/v5/public/linear'   
            else:     
                # Inverse contracts UNIIFIED   
                # We have to treat the private ws connection as if it was a CONTRACT and not UNIFIED
                # since it uses the CONTRACT wallet           
                self.unified_margin = False
                self.endpoint = 'wss://stream-testnet.bybit.com/v5/public/inverse' \
                                if self.testnet else 'wss://stream.bybit.com/v5/public/inverse'
        
        self.endpoint_private = 'wss://stream-testnet.bybit.com/v5/private' \
                            if self.testnet else 'wss://stream.bybit.com/v5/private'        
        
        # public ws 
        self.__create_public()
        # private ws 
        self.__create_private()
        # Use Monitor to monitor Websocket pings
        self.monitor = Monitor()

        self.debug_log = False
        self.log_file = open(f"{self.account}.log", "w")
    
    def log(self, message):
        
        if self.debug_log:
            self.log_file.write(f"{datetime.now()} - {message}\n")
            self.log_file.flush()

    def __create_public(self):
        self.ws = websocket.WebSocketApp(self.endpoint,
                            on_open=self.__on_open_public,
                            on_message=self.__on_message,
                            on_error=self.__on_error,
                            on_pong=self.__on_pong_public)                             
        self.wst = threading.Thread(target=self.__start_public)
        self.wst.daemon = True
        self.wst.start()

    def __create_private(self):
        self.wsp = websocket.WebSocketApp(self.endpoint_private,
                            on_open=self.__on_open_private,
                            on_message=self.__on_message,
                            on_error=self.__on_error,
                            on_pong=self.__on_pong_private)                             
        self.wspt = threading.Thread(target=self.__start_private)
        self.wspt.daemon = True
        self.wspt.start()                       
        
    def __auth(self, ws):
        """
        authenticate
        """ 
        logger.info(f"Authenticating WebSocket")
        # API keys
        api_key =  conf['bybit_test_keys'][self.account]['API_KEY'] \
                    if self.testnet else conf['bybit_keys'][self.account]['API_KEY']       
        api_secret = conf['bybit_test_keys'][self.account]['SECRET_KEY'] \
                    if self.testnet else conf['bybit_keys'][self.account]['SECRET_KEY']   
        
        if len(api_key) and len(api_secret) == 0:           
            logger.info("WebSocket is not able to authenticate, make sure you added api key and secret to config.py") 
            
        # Generate expires.
        expires = str(int((time.time() + 1) * 1000))

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

    def __start_public(self):
        """
        start the public websocket.
        """
        self.ws.run_forever(
                                ping_interval=20, 
                                ping_timeout=15, 
                                )          
    
    def __start_private(self):
        """
        start the private websocket.
        """
        self.wsp.run_forever(
                                ping_interval=20, 
                                ping_timeout=15, 
                                )  

    def __on_open_public(self, ws):    
        klines = {}
        for t in self.bin_size: 
            klines["kline."+ bybit_allowed_range[t][0] +"." + self.pair] = True    
        klines = list(klines.keys())
        logger.info(f"WS klines: {klines}")   
        ws.send(
            json.dumps({
                'op': 'subscribe',
                'args': klines + [
                    #"publicTrade." + self.pair,
                    "tickers." + self.pair, 
                    "orderbook.1." + self.pair  # orderbook 1 level data is 10ms, 50 level data is 20ms, 200 is 100ms, 500 is 100ms
                ]
            })
        ) 

        def ws_monitor_callback(topic):
            logger.info(f"Monitor: *{topic}* Timed out! Closing!")
            try:
                self.ws.close()
            except Exception as e:
                logger.info(f"WS Monitor Callback Error: {e}")
                # public ws 

            self.__create_public()

        self.monitor.register_callback("public_ws", ws_monitor_callback, 120)
        
    def __on_open_private(self, ws):           
        self.__auth(ws)           
        ws.send(
            json.dumps({
                'op': 'subscribe',
                'args': [
                    "position", 
                    "execution", 
                    "order", 
                    "wallet"
                ]
            }) 
        )       
        
        def wsp_monitor_callback(topic):
            logger.info(f"Monitor: *{topic}* Timed out! Closing!")
            try:
                self.wsp.close()
            except Exception as e:
                logger.info(f"WSP Monitor Callback Error: {e}")
                # private ws
                
            self.__create_private()

        self.monitor.register_callback("private_ws", wsp_monitor_callback, 60)       
          
    def __on_error(self, ws, message):
        """
        On Error listener
        :param ws:
        :param message:
        """
        logger.error(f"Websocket On Error: {message}")
        logger.error(traceback.format_exc())

        notify(f"On Error: {message}")
        #notify(traceback.format_exc())

        #ws.close()

    def ping_ws(self):
        '''
        Pings the remote server on public websocket
        to keep it alive
        '''
        self.ws.send(json.dumps({'op': 'ping'}))

    def ping_wsp(self):
        '''
        Pings the remote server on public websocket
        to keep it alive
        '''
        if self.wsp is not None:
            self.wsp.send(json.dumps({"req_id": "private", 'op': 'ping'}))

    def __on_pong_public(self, ws, message):
        self.log(f"Received WS Pong")
        self.ping_ws()

    def __on_pong_private(self, ws, message):
        self.log(f"Received WSP Pong")
        self.ping_wsp()

    def __on_message(self, ws, message):
        """
        On Message listener
        :param ws:
        :param message:
        :return:
        """                
        try:
            obj = json.loads(message)      
            # logger.info(obj)
            if 'topic' in obj:
                if len(obj['data']) <= 0:
                    return
             
                table = obj['topic']
                action = obj['topic'] #obj['type']
                data = obj['data']  
                
                if table.startswith("trade"): # Tick Data, currently not used         
                    pass

                elif table.startswith("kline"):                    
                    
                    self.monitor.ping_topic("public_ws")

                    # Send a heartbeat to Healthchecks.io
                    if self.use_healthchecks:
                        current_minute = int(obj["ts"]/60000)
                        if self.last_heartbeat < current_minute:
                            # Send a heartbeat to Healthchecks.io
                            try:
                                requests.get(conf['healthchecks.io'][self.account]['websocket_heartbeat'])
                                #logger.info("WS Heart Beat sent!") 
                                self.last_heartbeat = current_minute
                            except Exception as e:
                                pass          

                    # final_candle_data = True if 'confirm' in data[0] and data[0]['confirm'] else False

                    # if not final_candle_data:                      
                    #     return
                    
                    timeframe = table[len('kline.'):-len('.'+self.pair)] 
                   
                    if timeframe.isdigit():                       
                        action = find_timeframe_string(int(timeframe))
                    else:
                        action = '1' + timeframe.lower()
             
                    data = [{
                        "timestamp" : data[0]['end'],
                        "high" : float(data[0]['high']),
                        "low" : float(data[0]['low']),
                        "open" : float(data[0]['open']),
                        "close" : float(data[0]['close']),
                        "volume" : float(data[0]['volume'])
                        }]
          
                    data[0]['timestamp'] = datetime.fromtimestamp(data[0]['timestamp']/1000, tz=timezone.utc)
                    self.__emit(action, action, to_data_frame(data))
                                           
                elif table.startswith("tickers"): 
                    #ignore delta messages as they may not contain all fields
                    self.__emit('instrument', table, data)  

                elif table.startswith("orderbook.1") or table.startswith("bookticker"):
                    self.__emit("bookticker", obj['type'], data)      

                elif 'position' in table:                            
                    self.__emit("position", action, data)                   

                elif table.startswith("execution"):       
                    data = data[0]            
                    self.__emit("execution", action, data)

                elif table.startswith("order"):                   
                    self.__emit("order", action, data)

                elif table.startswith("wallet"):            
                    self.__emit("wallet", action, data[0])                    

            elif "op" in obj :
                # logger.info(obj)
                if obj["op"] == "auth" and obj["success"]:
                    logger.info("WS Connection Successful")
                if (obj["op"] == "ping" or obj["op"] == "pong") and obj["req_id"] == "private":
                    self.monitor.ping_topic("private_ws")
                    self.log("WSP Keep Alive Received!")
                    # Send a heartbeat to Healthchecks.io when private ws does ping-pong
                    try:
                        requests.get(conf['healthchecks.io'][self.account]['listenkey_heartbeat'])
                        #logger.info("WS Keep Alive Received!") 
                    except Exception as e:
                        self.log(f"Healthcheck Error: {e}")
                        pass   

        except Exception as e:
            logger.error(f"On Message: {e}")
            logger.error(traceback.format_exc())
       
    def __emit(self, key, action, value):       
        """
        send data
        """
        if key in self.handlers:
            self.handlers[key](action, value)

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
        self.wsp.close()