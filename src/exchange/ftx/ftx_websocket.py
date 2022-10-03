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
from datetime import datetime
import pandas as pd

from src import logger, to_data_frame, notify
from src.config import config as conf


def generate_nonce():
    return int(round(time.time() * 1000))


class FtxWs:    
    # testnet    
    testnet = False
    # condition that the bot runs on.
    is_running = True
    # Notification destination listener
    handlers = {}
    
    def __init__(self, account, pair, test=False):
        """
        constructor
        """
        self.account = account
        self.pair = pair
        self.testnet = test   
        if self.account == "None":
            self.subaccount = None
        else:
            self.subaccount = self.account     
        
        if test:            
            domain = ''
        else:            
            domain = 'wss://ftx.com/ws/'               
  
        self.endpoint = domain
        self.ws = websocket.WebSocketApp(self.endpoint,
                            on_message=self.__on_message,
                            on_error=self.__on_error,
                            on_close=self.__on_close)                             
        self.wst = threading.Thread(target=self.__start)
        self.wst.daemon = True
        self.wst.start()            
        self.ws.on_open = self.subscribe_all 

    def __auth(self, ws):
        """
        authenticate
        """ 
        logger.info(f"authenticating ws")
        # API keys
        api_key =  conf['ftx_keys'][self.account]['API_KEY'] if self.testnet else conf['ftx_keys'][self.account]['API_KEY']       
        api_secret = conf['ftx_keys'][self.account]['SECRET_KEY'] if self.testnet else conf['ftx_keys'][self.account]['SECRET_KEY']   
        
        ts = int(time.time() * 1000)        

        # Authenticate with API.
        self.ws.send(
            json.dumps({
                'op': 'login',
                'args': {
                    'key': api_key,
                    'sign': hmac.new(
                                    api_secret.encode(), f'{ts}websocket_login'.encode(), 'sha256').hexdigest(),
                    'time': ts,
                    'subaccount': self.subaccount
                }                
            })
        )        

    def __start(self):
        """
        start the websocket.
        """
        while self.is_running:           
            self.ws.run_forever()   

    #public channels   
    def subscribe_all(self, ws):
        self.__auth(self.ws) 
        ws.send(
           json.dumps({
                'op': 'subscribe',                
                'channel': 'trades',
                'market': self.pair
            }) 
        )  

        ws.send(
           json.dumps({
                'op': 'subscribe',                
                'channel': 'ticker',
                'market': self.pair
            }) 
        )          

        ws.send(
           json.dumps({
                'op': 'subscribe',                
                'channel': 'orderbook',
                'market': self.pair
            }) 
        )                      
        ws.send(
           json.dumps({
                'op': 'subscribe',                
                'channel': 'fills'                
            }) 
        )          
        ws.send(
           json.dumps({
                'op': 'subscribe',                
                'channel': 'orders'                
            }) 
        )                                                                              

    def subscribe_ticker(self, ws):
       
        ws.send(
           json.dumps({
                'op': 'subscribe',                
                'channel': 'ticker',
                'market': self.pair
            }) 
        ) 

    def subscribe_trades(self, ws):
        
        ws.send(
           json.dumps({
                'op': 'subscribe',                
                'channel': 'trades',
                'market': self.pair
            }) 
        )                   

    def subscribe_orderbook(self, ws):
         
        ws.send(
           json.dumps({
                'op': 'subscribe',                
                'channel': 'orderbook',
                'market': self.pair
            }) 
        )    

    # Private Channels   
    def subscribe_fills(self, ws):
        self.__auth(self.ws)  
        ws.send(
          json.dumps({
                'op': 'subscribe',                
                'channel': 'fills'                
            }) 
        )                   

    def subscribe_orders(self, ws):
        self.__auth(self.ws)  
        ws.send(
           json.dumps({
                'op': 'subscribe',                
                'channel': 'trades'                
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
      
            if 'channel' in obj:
                if 'data' not in obj:
                    return

                table = obj['channel']
                action = obj['type']
                data = obj['data']            

                if table.startswith("klineV2"): 
                                
                    data = [{
                        "timestamp" : data[0]['end'],
                        "high" : data[0]['high'],
                        "low" : data[0]['low'],
                        "open" : data[0]['open'],
                        "close" : data[0]['close'],
                        "volume" : data[0]['volume']
                    }]
                    data[0]['timestamp'] = datetime.fromtimestamp(data[0]['timestamp']).strftime('%Y-%m-%dT%H:%M:%S')
                    data[0]['timestamp'] = datetime.strptime(data[0]['timestamp'],'%Y-%m-%dT%H:%M:%S')                                             
                   
                    self.__emit(table, action, to_data_frame([data[0]]))  

                elif table.startswith("ticker"):
                    self.__emit(table, action, data)             

                elif table.startswith("orders"):
                    self.__emit(table, action, data)
                    

                elif table.startswith("fills"):
                    self.__emit(table, action, data)
                    
                elif table.startswith("orderBookL2"):
                    self.__emit(table, action, data)

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
            logger.info("Websocket restart")
            notify(f"Websocket restart")

            self.ws = websocket.WebSocketApp(self.endpoint,
                            on_message=self.__on_message,
                            on_error=self.__on_error,
                            on_close=self.__on_close)                             
            self.wst = threading.Thread(target=self.__start)
            self.wst.daemon = True
            self.wst.start()            
            self.ws.on_open = self.subscribe_all 

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
        kline = 'klineV2'

        if self.pair.endswith('USDT'):
            kline = 'candle'

        # if key == 'trade':
        #     self.handlers["trade"] = func
        # if key == 'ticker':
        #     self.handlers["ticker"] = func
        if key == 'fills':
             self.handlers["fills"] = func
        if key == 'orders':
             self.handlers["orders"] = func
        if key == '1h':
            self.handlers[kline + '.60.' + self.pair] = func
        if key == '1d':
            self.handlers[kline + '.D.' + self.pair] = func
        if key == 'instrument':
            self.handlers['instrument_info.100ms.' + self.pair] = func
        if key == 'margin':
            self.handlers['margin'] = func
        if key == 'position':
            self.handlers['position'] = func
        if key == 'wallet':
            self.handlers['wallet'] = func
        if key == 'orderBookL2':
            self.handlers['orderBookL2'] = func
        else:
            self.handlers[key] = func

    def close(self):
        """
        close websocket
        """
        self.is_running = False
        self.ws.close()    