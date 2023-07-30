# coding: UTF-8

from src import logger, sync_obj_with_config
from src.exchange.binance_futures.binance_futures import BinanceFutures
from src.exchange.stub import Stub
from src.exchange_config import exchange_config


# Stub (paper trading)
class BinanceFuturesStub(Stub, BinanceFutures):       
    def __init__(self, account, pair, threading=True):
        """
        Constructor for BinanceFuturesStub class.        
        Args:
            account (str): The account identifier for the Binance futures.
            pair (str): The trading pair for the Binance futures.
            threading (bool, optional): Condition for setting the 'is_running' flag.
                Default is True to indicate the stub is running.
        """         
        # Call the constructor of the BinanceFutures parent class to initialize the instance.  
        BinanceFutures.__init__(self, account, pair, threading=threading)          
        # Call the constructor of the Stub parent class to initialize the instance. 
        Stub.__init__(self)
        
        # Pair
        self.pair = pair
        # Balance all time high
        self.balance_ath = self.balance
        # Current Pos Size
        self.position_size = 0
        # Flag to indicate if the stub is running (based on the 'threading' condition).
        # If threading is True, the stub is considered to be running; otherwise, it is considered stopped.
        self.is_running = threading

        sync_obj_with_config(exchange_config['binance_f'], BinanceFuturesStub, self)   

    def on_update(self, bin_size, strategy):
        """
        The method called when the 'on_update' function is called on an instance of 'YourExchangeNameStub'.
        Args:
            bin_size (list): The size of the bin for updating.
            strategy (function): The strategy function to be executed during the update.
        Returns:
            None
        """
        # A local function used to override the 'strategy' function behavior.
        # The 'Stub.override_strategy' is a decorator used to override the behavior of '__override_strategy'.
        # The '__get__' method is used to ensure that '__override_strategy' can access the instance variables.
        def __override_strategy(self, action, open, close, high, low, volume):
            strategy(action, open, close, high, low, volume)   

        # Bind the __override_strategy function to the instance
        self.__override_strategy = Stub.override_strategy(__override_strategy).__get__(self, BinanceFuturesStub)

        # Call the 'on_update' function of the 'BinanceFutures' class, passing 'bin_size' and the overridden '__override_strategy'.
        BinanceFutures.on_update(self, bin_size, self.__override_strategy)