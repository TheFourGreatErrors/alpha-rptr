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
from pytz import UTC

from src import logger, to_data_frame, notify
from src.config import config as conf
from src.exchange.binance_futures.binance_futures_api import Client


def generate_nonce():
    return int(round(time.time() * 1000))


def get_listenkey(api_key, api_secret, testnet): 
    client = Client(api_key=api_key, api_secret=api_secret, testnet=testnet)
    listenKey = client.stream_get_listen_key()
    return listenKey


class BinanceFuturesWs:    

    def __init__(self, account, pair, test=False):
        """
        constructor
        """
        # Account
        self.account = account
        # Pair
        self.pair = pair.lower()
        # testnet
        self.testnet = test
        # domain
        domain = None
        # Use healthchecks.io
        self.use_healthcecks = False
        # Last Heartbeat
        self.last_heartbeat = 0
        # condition that the bot runs on.
        self.is_running = True
        # Notification destination listener
        self.handlers = {}
        # listen key
        self.listenKey = None
        # API keys
        self.api_key = conf['binance_test_keys'][self.account]['API_KEY'] if self.testnet else conf['binance_keys'][self.account]['API_KEY']
        self.api_secret = conf['binance_test_keys'][self.account]['SECRET_KEY'] if self.testnet else conf['binance_keys'][self.account]['SECRET_KEY']        
        if test:
            self.domain = 'stream.binancefuture.com'
        else:
            self.domain = 'fstream.binance.com'
        self.__get_auth_user_data_streams()
        self.endpoint = 'wss://' + self.domain + '/stream?streams=' + self.listenKey + '/' + self.pair + '@ticker/' + self.pair + '@kline_1m/' \
                        + self.pair + '@kline_5m/' + self.pair + '@kline_30m/' \
                        + self.pair + '@kline_1h/'  + self.pair + '@kline_1d/' + self.pair + '@kline_1w/' \
                        + self.pair + '@depth20@100ms/' + self.pair + '@bookTicker'
        self.ws = websocket.WebSocketApp(self.endpoint,
                             on_message=self.__on_message,
                             on_error=self.__on_error,
                             on_close=self.__on_close)                             
                             
        self.wst = threading.Thread(target=self.__start)
        self.wst.daemon = True
        self.wst.start()
        self.__keep_alive_user_datastream(self.listenKey)
   
    def __get_auth_user_data_streams(self):
        """
        authenticate user data streams
        """        
        if len(self.api_key) > 0 and len(self.api_secret):
            self.listenKey = get_listenkey(self.api_key, self.api_secret, testnet=self.testnet) 
        else:
            logger.info("WebSocket is not able to get listenKey for user data streams") 

    def __start(self):
        """
        start the websocket.
        """
        self.ws.run_forever()
    
    def __keep_alive_user_datastream(self, listenKey):
        """
        keep alive user data stream, needs to ping every 60m
        """              
        client = Client(self.api_key, self.api_secret, self.testnet)
        def loop_function():
            while self.is_running:
                try:
                    # retries 10 times over 486secs
                    # before raising error/exception
                    # check binance_futures_api.py line 113
                    # for implementation details

                    #client.stream_keepalive()
                    listenKey = client.stream_get_listen_key() 
                    
                    if self.listenKey != listenKey:
                        logger.info("listenKey Changed!")
                        notify("listenKey Changed!")
                        self.listenKey = listenKey
                        self.ws.close()

                    # Send a heartbeat to Healthchecks.io
                    if self.use_healthcecks:
                        try:
                            requests.get(conf['healthchecks.io'][self.account]['listenkey_heartbeat'])
                            #logger.info("Listen Key Heart Beat sent!") 
                        except Exception as e:
                            pass

                    time.sleep(600)
                except Exception as e:
                    logger.error(f"Keep Alive Error - {str(e)}")
                    #logger.error(traceback.format_exc())

                    notify(f"Keep Alive Error - {str(e)}")
                    #notify(traceback.format_exc())

        timer = threading.Timer(10, loop_function)
        timer.daemon = True
        if listenKey is not None:  
            timer.start()            
        else: 
            self.__get_auth_user_data_streams()
            timer.start() 
          
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
            
            
            if 'e' in obj['data']:                
                e = obj['data']['e']
                action = ""                
                datas = obj['data']                
                
                if e.startswith("kline"):
                    if self.use_healthcecks:
                        current_minute = datetime.now().time().minute
                        if self.last_heartbeat != current_minute:
                            # Send a heartbeat to Healthchecks.io
                            try:
                                requests.get(conf['healthchecks.io'][self.account]['websocket_heartbeat'])
                                #logger.info("WS Heart Beat sent!") 
                                self.last_heartbeat = current_minute
                            except Exception as e:
                                pass
                    data = [{
                        "timestamp" : datas['k']['T'],
                        "high" : float(datas['k']['h']),
                        "low" : float(datas['k']['l']),
                        "open" : float(datas['k']['o']),
                        "close" : float(datas['k']['c']),
                        "volume" : float(datas['k']['v'])
                    }]                     
                    data[0]['timestamp'] = datetime.fromtimestamp(data[0]['timestamp']/1000).astimezone(UTC)                                        
                    self.__emit(obj['data']['k']['i'], obj['data']['k']['i'], to_data_frame([data[0]]))                    
                elif e.startswith("24hrTicker"):
                    self.__emit(e, action, datas)               

                elif e.startswith("ACCOUNT_UPDATE"):
                    self.__emit(e, action, datas['a']['P'])
                    self.__emit('wallet', action, datas['a']['B'][0])
                    self.__emit('margin', action, datas['a']['B'][0])                  
                    
                # todo  ORDER_TRADE_UPDATE
                elif e.startswith("ORDER_TRADE_UPDATE"):
                    self.__emit(e, action, datas['o'])
                #todo orderbook stream
                # elif table.startswith(""):
                #     self.__emit(e, action, data)
                elif e.startswith("listenKeyExpired"):
                    self.__emit('close', action, datas)                    
                    self.__get_auth_user_data_streams()
                    logger.info(f"listenKeyExpired!!!")
                    #self.__on_close(ws)
                    self.ws.close()

            elif not 'e' in obj['data']:
                e = 'IndividualSymbolBookTickerStreams'
                action = ''
                data = obj['data']
                #logger.info(f"{data}")
                self.__emit(e, action, data)

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
            self.endpoint = 'wss://' + self.domain + '/stream?streams=' + self.listenKey + '/' + self.pair + '@ticker/' + self.pair + '@kline_1m/' \
                    + self.pair + '@kline_5m/' + self.pair + '@kline_30m/' \
                    + self.pair + '@kline_1h/'  + self.pair + '@kline_1d/' + self.pair + '@kline_1w/' \
                    + self.pair + '@depth20@100ms/' + self.pair + '@bookTicker'
        
            self.ws = websocket.WebSocketApp(self.endpoint,
                                 on_message=self.__on_message,
                                 on_error=self.__on_error,
                                 on_close=self.__on_close)                                 
                                 
            self.wst = threading.Thread(target=self.__start)
            self.wst.daemon = True
            self.wst.start()

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
        if key == '1m':
            self.handlers['1m'] = func
        if key == '5m':
            self.handlers['5m'] = func
        if key == '1h':
            self.handlers['1h'] = func
        if key == '1d':
            self.handlers['1d'] = func
        if key == 'instrument':
            self.handlers['24hrTicker'] = func
        if key == 'margin':
            self.handlers['margin'] = func
        if key == 'position':
            self.handlers['ACCOUNT_UPDATE'] = func
        if key == 'order':
            self.handlers['ORDER_TRADE_UPDATE'] = func
        if key == 'wallet':
            self.handlers['wallet'] = func
        if key == 'IndividualSymbolBookTickerStreams':
            self.handlers['IndividualSymbolBookTickerStreams'] = func
        if key == 'orderBookL2':
            self.handlers['orderBookL2'] = func

    def close(self):
        """
        close websocket
        """
        self.is_running = False
        self.ws.close()
