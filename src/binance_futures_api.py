#!/usr/bin/env python

from urllib.parse import urlparse
import time, hashlib, hmac
import requests
from operator import itemgetter
from .exceptions import BinanceAPIException, BinanceRequestException, BinanceWithdrawException

class Client(object):

    API_URL = 'https://api.binance.{}/api'
    WITHDRAW_API_URL = 'https://api.binance.{}/wapi'
    MARGIN_API_URL = 'https://api.binance.{}/sapi'
    WEBSITE_URL = 'https://www.binance.{}'
    FUTURES_URL = 'https://fapi.binance.{}/fapi'
    PUBLIC_API_VERSION = 'v1'
    PRIVATE_API_VERSION = 'v3'
    WITHDRAW_API_VERSION = 'v3'
    MARGIN_API_VERSION = 'v1'
    FUTURES_API_VERSION = 'v1'
    FUTURES_API_VERSION_V2 = 'v2'


    SYMBOL_TYPE_SPOT = 'SPOT'

    ORDER_STATUS_NEW = 'NEW'
    ORDER_STATUS_PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    ORDER_STATUS_FILLED = 'FILLED'
    ORDER_STATUS_CANCELED = 'CANCELED'
    ORDER_STATUS_PENDING_CANCEL = 'PENDING_CANCEL'
    ORDER_STATUS_REJECTED = 'REJECTED'
    ORDER_STATUS_EXPIRED = 'EXPIRED'

    KLINE_INTERVAL_1MINUTE = '1m'
    KLINE_INTERVAL_3MINUTE = '3m'
    KLINE_INTERVAL_5MINUTE = '5m'
    KLINE_INTERVAL_15MINUTE = '15m'
    KLINE_INTERVAL_30MINUTE = '30m'
    KLINE_INTERVAL_1HOUR = '1h'
    KLINE_INTERVAL_2HOUR = '2h'
    KLINE_INTERVAL_4HOUR = '4h'
    KLINE_INTERVAL_6HOUR = '6h'
    KLINE_INTERVAL_8HOUR = '8h'
    KLINE_INTERVAL_12HOUR = '12h'
    KLINE_INTERVAL_1DAY = '1d'
    KLINE_INTERVAL_3DAY = '3d'
    KLINE_INTERVAL_1WEEK = '1w'
    KLINE_INTERVAL_1MONTH = '1M'

    SIDE_BUY = 'BUY'
    SIDE_SELL = 'SELL'

    ORDER_TYPE_LIMIT = 'LIMIT'
    ORDER_TYPE_MARKET = 'MARKET'
    ORDER_TYPE_STOP_LOSS = 'STOP_LOSS'
    ORDER_TYPE_STOP_LOSS_LIMIT = 'STOP_LOSS_LIMIT'
    ORDER_TYPE_TAKE_PROFIT = 'TAKE_PROFIT'
    ORDER_TYPE_TAKE_PROFIT_LIMIT = 'TAKE_PROFIT_LIMIT'
    ORDER_TYPE_LIMIT_MAKER = 'LIMIT_MAKER'

    TIME_IN_FORCE_GTC = 'GTC'  # Good till cancelled
    TIME_IN_FORCE_IOC = 'IOC'  # Immediate or cancel
    TIME_IN_FORCE_FOK = 'FOK'  # Fill or kill

    ORDER_RESP_TYPE_ACK = 'ACK'
    ORDER_RESP_TYPE_RESULT = 'RESULT'
    ORDER_RESP_TYPE_FULL = 'FULL'

    # For accessing the data returned by Client.aggregate_trades().
    AGG_ID = 'a'
    AGG_PRICE = 'p'
    AGG_QUANTITY = 'q'
    AGG_FIRST_TRADE_ID = 'f'
    AGG_LAST_TRADE_ID = 'l'
    AGG_TIME = 'T'
    AGG_BUYER_MAKES = 'm'
    AGG_BEST_MATCH = 'M'

    def __init__(self, api_key=None, api_secret=None, requests_params=None, tld='com'):
        """Binance API Client constructor
        :param api_key: Api Key
        :type api_key: str.
        :param api_secret: Api Secret
        :type api_secret: str.
        :param requests_params: optional - Dictionary of requests params to use for all calls
        :type requests_params: dict.
        """

        self.API_URL = self.API_URL.format(tld)
        self.WITHDRAW_API_URL = self.WITHDRAW_API_URL.format(tld)
        self.MARGIN_API_URL = self.MARGIN_API_URL.format(tld)
        self.WEBSITE_URL = self.WEBSITE_URL.format(tld)
        self.FUTURES_URL = self.FUTURES_URL.format(tld)

        self.API_KEY = api_key
        self.API_SECRET = api_secret
        self.session = self._init_session()
        self._requests_params = requests_params
        self.response = None

        # init DNS and SSL cert
        #self.ping()

    def _init_session(self):

        session = requests.session()
        session.headers.update({'Accept': 'application/json',
                                'User-Agent': 'binance/python',
                                'X-MBX-APIKEY': self.API_KEY})
        return session

    def _create_api_uri(self, path, signed=True, version=PUBLIC_API_VERSION):
        v = self.PRIVATE_API_VERSION if signed else version
        return self.API_URL + '/' + v + '/' + path

    def _create_withdraw_api_uri(self, path):
        return self.WITHDRAW_API_URL + '/' + self.WITHDRAW_API_VERSION + '/' + path

    def _create_margin_api_uri(self, path):
        return self.MARGIN_API_URL + '/' + self.MARGIN_API_VERSION + '/' + path

    def _create_website_uri(self, path):
        return self.WEBSITE_URL + '/' + path

    def _create_futures_api_uri(self, path, v2):
        if v2 == False:
            return self.FUTURES_URL + '/' + self.FUTURES_API_VERSION + '/' + path
        else:
            return self.FUTURES_URL + '/' + self.FUTURES_API_VERSION_V2 + '/' + path

    def _generate_signature(self, data):

        ordered_data = self._order_params(data)
        query_string = '&'.join(["{}={}".format(d[0], d[1]) for d in ordered_data])
        m = hmac.new(self.API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256)
        return m.hexdigest()

    def _order_params(self, data):
        """Convert params to list with signature as last element
        :param data:
        :return:
        """
        has_signature = False
        params = []
        for key, value in data.items():
            if key == 'signature':
                has_signature = True
            else:
                params.append((key, value))
        # sort parameters by key
        params.sort(key=itemgetter(0))
        if has_signature:
            params.append(('signature', data['signature']))
        return params

    def _request(self, method, uri, signed, force_params=False, **kwargs):

        # set default requests timeout
        kwargs['timeout'] = 10

        # add our global requests params
        if self._requests_params:
            kwargs.update(self._requests_params)

        data = kwargs.get('data', None)
        if data and isinstance(data, dict):
            kwargs['data'] = data

            # find any requests params passed and apply them
            if 'requests_params' in kwargs['data']:
                # merge requests params into kwargs
                kwargs.update(kwargs['data']['requests_params'])
                del(kwargs['data']['requests_params'])

        if signed:
            # generate signature
            kwargs['data']['timestamp'] = int(time.time() * 1000)
            kwargs['data']['signature'] = self._generate_signature(kwargs['data'])

        # sort get and post params to match signature order
        if data:
            # sort post params
            kwargs['data'] = self._order_params(kwargs['data'])
            # Remove any arguments with values of None.
            null_args = [i for i, (key, value) in enumerate(kwargs['data']) if value is None]
            for i in reversed(null_args):
                del kwargs['data'][i]

        # if get request assign data array to params value for requests lib
        if data and (method == 'get' or force_params):
            kwargs['params'] = '&'.join('%s=%s' % (data[0], data[1]) for data in kwargs['data'])
            del(kwargs['data'])

        self.response = getattr(self.session, method)(uri, **kwargs)
        return self._handle_response()

    def _request_api(self, method, path, signed=False, version=PUBLIC_API_VERSION, **kwargs):
        uri = self._create_api_uri(path, signed, version)

        return self._request(method, uri, signed, **kwargs)

    def _request_withdraw_api(self, method, path, signed=False, **kwargs):
        uri = self._create_withdraw_api_uri(path)

        return self._request(method, uri, signed, True, **kwargs)

    def _request_margin_api(self, method, path, signed=False, **kwargs):
        uri = self._create_margin_api_uri(path)

        return self._request(method, uri, signed, **kwargs)

    def _request_website(self, method, path, signed=False, **kwargs):
        uri = self._create_website_uri(path)

        return self._request(method, uri, signed, **kwargs)

    def _request_futures_api(self, method, path, signed=False, v2=False, **kwargs):
        uri = self._create_futures_api_uri(path, v2)

        return self._request(method, uri, signed, True, **kwargs)

    def _handle_response(self):
            """Internal helper for handling API responses from the Binance server.
            Raises the appropriate exceptions when necessary; otherwise, returns the
            response.
            """
            
            if not str(self.response.status_code).startswith('2'):
                raise BinanceAPIException(self.response)
            try:
                return self.response.json(),self.response
                
            except ValueError:
                raise BinanceRequestException('Invalid Response: %s' % self.response.text)

    def _get(self, path, signed=False, version=PUBLIC_API_VERSION, **kwargs):
        return self._request_futures_api('get', path, signed, **kwargs)

    def _post(self, path, signed=False, version=PUBLIC_API_VERSION, **kwargs):
        return self._request_futures_api('post', path, signed, **kwargs)

    def _put(self, path, signed=False, version=PUBLIC_API_VERSION, **kwargs):
        return self._request_futures_api('put', path, signed, **kwargs)

    def _delete(self, path, signed=False, version=PUBLIC_API_VERSION, **kwargs):
        return self._request_futures_api('delete', path, signed, **kwargs)
    
# User Stream Endpoints

    def stream_get_listen_key(self):
        """Start a new user data stream and return the listen key
        If a stream already exists it should return the same key.
        If the stream becomes invalid a new key is returned.
        Can be used to keep the user stream alive.
        https://github.com/binance-exchange/binance-official-api-docs/blob/master/rest-api.md#start-user-data-stream-user_stream
        :returns: API response
        .. code-block:: python
            {
                "listenKey": "pqia91ma19a5s61cv6a81va65sdf19v8a65a1a5s61cv6a81va65sdf19v8a65a1"
            }
        :raises: BinanceRequestException, BinanceAPIException
        """
        ret, res = self._post('listenKey', False, data={})
        return ret['listenKey']

    def stream_keepalive(self):#, listenKey):
        """PING a user data stream to prevent a time out.
        https://github.com/binance-exchange/binance-official-api-docs/blob/master/rest-api.md#keepalive-user-data-stream-user_stream
        :param listenKey: required
        :type listenKey: str
        :returns: API response
        .. code-block:: python
            {}
        :raises: BinanceRequestException, BinanceAPIException
        """
        # params = {
        #     'listenKey': listenKey
        # }
        return self._put('listenKey', False, data={})

        
# Exchange Endpoints

# Futures API

    def futures_ping(self):
        """Test connectivity to the Rest API
        https://binance-docs.github.io/apidocs/futures/en/#test-connectivity
        """
        return self._request_futures_api('get', 'ping')

    def futures_time(self):
        """Test connectivity to the Rest API and get the current server time.
        https://binance-docs.github.io/apidocs/futures/en/#check-server-time
        """
        return self._request_futures_api('get', 'time')

    def futures_exchange_info(self):
        """Current exchange trading rules and symbol information
        https://binance-docs.github.io/apidocs/futures/en/#exchange-information-market_data
        """
        return self._request_futures_api('get', 'exchangeInfo')

    def futures_order_book(self, **params):
        """Get the Order Book for the market
        https://binance-docs.github.io/apidocs/futures/en/#order-book-market_data
        """
        return self._request_futures_api('get', 'depth', data=params)

    def futures_recent_trades(self, **params):
        """Get recent trades (up to last 500).
        https://binance-docs.github.io/apidocs/futures/en/#recent-trades-list-market_data
        """
        return self._request_futures_api('get', 'trades', data=params)

    def futures_historical_trades(self, **params):
        """Get older market historical trades.
        https://binance-docs.github.io/apidocs/futures/en/#old-trades-lookup-market_data
        """
        return self._request_futures_api('get', 'historicalTrades', data=params)

    def futures_aggregate_trades(self, **params):
        """Get compressed, aggregate trades. Trades that fill at the time, from the same order, with the same
        price will have the quantity aggregated.
        https://binance-docs.github.io/apidocs/futures/en/#compressed-aggregate-trades-list-market_data
        """
        return self._request_futures_api('get', 'aggTrades', data=params)

    def futures_klines(self, **params):
        """Kline/candlestick bars for a symbol. Klines are uniquely identified by their open time.
        https://binance-docs.github.io/apidocs/futures/en/#kline-candlestick-data-market_data
        """
        return self._request_futures_api('get', 'klines', data=params)

    def futures_mark_price(self, **params):
        """Get Mark Price and Funding Rate
        https://binance-docs.github.io/apidocs/futures/en/#mark-price-market_data
        """
        return self._request_futures_api('get', 'premiumIndex', data=params)

    def futures_funding_rate(self, **params):
        """Get funding rate history
        https://binance-docs.github.io/apidocs/futures/en/#get-funding-rate-history-market_data
        """
        return self._request_futures_api('get', 'fundingRate', data=params)

    def futures_ticker(self, **params):
        """24 hour rolling window price change statistics.
        https://binance-docs.github.io/apidocs/futures/en/#24hr-ticker-price-change-statistics-market_data
        """
        return self._request_futures_api('get', 'ticker/24hr', data=params)

    def futures_symbol_ticker(self, **params):
        """Latest price for a symbol or symbols.
        https://binance-docs.github.io/apidocs/futures/en/#symbol-price-ticker-market_data
        """
        return self._request_futures_api('get', 'ticker/price', data=params)

    def futures_orderbook_ticker(self, **params):
        """Best price/qty on the order book for a symbol or symbols.
        https://binance-docs.github.io/apidocs/futures/en/#symbol-order-book-ticker-market_data
        """
        return self._request_futures_api('get', 'ticker/bookTicker', data=params)

    def futures_liquidation_orders(self, **params):
        """Get all liquidation orders
        https://binance-docs.github.io/apidocs/futures/en/#get-all-liquidation-orders-market_data
        """
        return self._request_futures_api('get', 'ticker/allForceOrders', data=params)

    def futures_open_interest(self, **params):
        """Get present open interest of a specific symbol.
        https://binance-docs.github.io/apidocs/futures/en/#open-interest-market_data
        """
        return self._request_futures_api('get', 'ticker/openInterest', data=params)

    def futures_leverage_bracket(self, **params):
        """Notional and Leverage Brackets
        https://binance-docs.github.io/apidocs/futures/en/#notional-and-leverage-brackets-market_data
        """
        return self._request_futures_api('get', 'ticker/leverageBracket', data=params)

    def transfer_history(self, **params):
        """Get future account transaction history list
        https://binance-docs.github.io/apidocs/futures/en/#new-future-account-transfer
        """
        return self._request_margin_api('get', 'futures/transfer', True, data=params)

    def futures_create_order(self, **params):
        """Send in a new order.
        https://binance-docs.github.io/apidocs/futures/en/#new-order-trade
        """
        return self._request_futures_api('post', 'order', True, data=params)

    def futures_get_order(self, **params):
        """Check an order's status.
        https://binance-docs.github.io/apidocs/futures/en/#query-order-user_data
        """
        return self._request_futures_api('get', 'order', True, data=params)

    def futures_get_open_orders(self, **params):
        """Get all open orders on a symbol.
        https://binance-docs.github.io/apidocs/futures/en/#current-open-orders-user_data
        """
        return self._request_futures_api('get', 'openOrders', True, data=params)

    def futures_get_all_orders(self, **params):
        """Get all futures account orders; active, canceled, or filled.
        https://binance-docs.github.io/apidocs/futures/en/#all-orders-user_data
        """
        return self._request_futures_api('get', 'allOrders', True, data=params)

    def futures_cancel_order(self, **params):
        """Cancel an active futures order.
        https://binance-docs.github.io/apidocs/futures/en/#cancel-order-trade
        """
        return self._request_futures_api('delete', 'order', True, data=params)

    def futures_cancel_all_open_orders(self, **params):
        """Cancel all open futures orders
        https://binance-docs.github.io/apidocs/futures/en/#cancel-all-open-orders-trade
        """
        return self._request_futures_api('delete', 'allOpenOrders', True, data=params)

    def futures_cancel_orders(self, **params):
        """Cancel multiple futures orders
        https://binance-docs.github.io/apidocs/futures/en/#cancel-multiple-orders-trade
        """
        return self._request_futures_api('delete', 'batchOrders', True, data=params)

    def futures_account_balance(self, **params):
        """Get futures account balance
        WARNING recommend to use v2 version
        https://binance-docs.github.io/apidocs/futures/en/#future-account-balance-user_data
        """
        return self._request_futures_api('get', 'balance', True, data=params)
    
    def futures_account_balance_v2(self, **params):
        """Get futures account balance v2
       https://binance-docs.github.io/apidocs/futures/en/#futures-account-balance-v2-user_data
        """
        return self._request_futures_api('get', 'balance', True, data=params, v2=True)

    def futures_account(self, **params):
        """Get current account information.
        WARNING recommend to use v2 version
        https://binance-docs.github.io/apidocs/futures/en/#account-information-user_data
        """
        return self._request_futures_api('get', 'account', True, data=params)

    def futures_account_v2(self, **params):
        """Get current account information v2
        https://binance-docs.github.io/apidocs/futures/en/#account-information-v2-user_data
        """
        return self._request_futures_api('get', 'account', True, data=params, v2=True)

    def futures_change_leverage(self, **params):
        """Change user's initial leverage of specific symbol market
        https://binance-docs.github.io/apidocs/futures/en/#change-initial-leverage-trade
        """
        return self._request_futures_api('post', 'leverage', True, data=params)

    def futures_change_margin_type(self, **params):
        """Change the margin type for a symbol
        https://binance-docs.github.io/apidocs/futures/en/#change-margin-type-trade
        """
        return self._request_futures_api('post', 'marginType', True, data=params)

    def futures_change_position_margin(self, **params):
        """Change the position margin for a symbol
        https://binance-docs.github.io/apidocs/futures/en/#modify-isolated-position-margin-trade
        """
        return self._request_futures_api('post', 'positionMargin', True, data=params)

    def futures_position_margin_history(self, **params):
        """Get position margin change history
        https://binance-docs.github.io/apidocs/futures/en/#get-postion-margin-change-history-trade
        """
        return self._request_futures_api('get', 'positionMargin/history', True, data=params)

    def futures_position_information(self, **params):
        """Get position information
        WARNING recommend to use v2 version
        https://binance-docs.github.io/apidocs/futures/en/#position-information-user_data
        """
        return self._request_futures_api('get', 'positionRisk', True, data=params)

    def futures_position_information_v2(self, **params):
        """Get position information v2
        https://binance-docs.github.io/apidocs/futures/en/#position-information-v2-user_data
        """
        return self._request_futures_api('get', 'positionRisk', True, data=params, v2=True)

    def futures_account_trades(self, **params):
        """Get trades for the authenticated account and symbol.
        https://binance-docs.github.io/apidocs/futures/en/#account-trade-list-user_data
        """
        return self._request_futures_api('get', 'userTrades', True, data=params)

    def futures_income_history(self, **params):
        """Get income history for authenticated account
        https://binance-docs.github.io/apidocs/futures/en/#get-income-history-user_data
        """
        return self._request_futures_api('get', 'income', True, data=params)