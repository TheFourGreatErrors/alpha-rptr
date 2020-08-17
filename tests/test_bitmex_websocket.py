# coding: UTF-8
import time
import unittest

from src.bitmex_websocket import BitMexWs


class TestBitMexWs(unittest.TestCase):
    account = "bitmex"
    pair = "XBTUSD"

    wait = False

    def setUp(self):
        self.wait = True

    def complete(self):
        self.wait = False

    def wait_complete(self):
        i = 0
        while self.wait:
            if i > 5:
                raise Exception("waiting timeout")
                break
            i += 1
            time.sleep(1)

    def set_guard(self, guard):
        self.guard = guard

    def test_setup(self):
        ws = BitMexWs(account=self.account, pair=self.pair)
        ws.close()

    def test_subscribe_1m(self):
        ws = BitMexWs(account=self.account, pair=self.pair)

        def subscribe(x):
            print(x)
            self.complete()

        ws.bind('1m', subscribe)

        self.wait_complete()
        ws.close()

    def test_subscribe_5m(self):
        ws = BitMexWs(account=self.account, pair=self.pair)

        def subscribe(x):
            print(x)
            self.complete()

        ws.bind('5m', subscribe)

        self.wait_complete()
        ws.close()

    def test_subscribe_1h(self):
        ws = BitMexWs(account=self.account, pair=self.pair)

        def subscribe(x):
            print(x)
            self.complete()

        ws.bind('1h', subscribe)

        self.wait_complete()
        ws.close()

    def test_subscribe_1d(self):
        ws = BitMexWs(account=self.account, pair=self.pair)

        def subscribe(x):
            print(x)
            self.complete()

        ws.bind('1d', subscribe)

        self.wait_complete()
        ws.close()

    def test_subscribe_instrument(self):
        ws = BitMexWs(account=self.account, pair=self.pair)

        def subscribe(x):
            print(x)
            self.complete()

        ws.bind('instrument', subscribe)

        self.wait_complete()
        ws.close()

    def test_subscribe_margin(self):
        ws = BitMexWs(account=self.account, pair=self.pair)

        def subscribe(x):
            print(x)
            self.complete()

        ws.bind('margin', subscribe)

        self.wait_complete()
        ws.close()

    def test_subscribe_position(self):
        ws = BitMexWs(account=self.account, pair=self.pair)

        def subscribe(x):
            print(x)
            self.complete()

        ws.bind('position', subscribe)

        self.wait_complete()
        ws.close()

    def test_subscribe_wallet(self):
        ws = BitMexWs(account=self.account, pair=self.pair)

        def subscribe(x):
            print(x)
            self.complete()

        ws.bind('wallet', subscribe)

        self.wait_complete()
        ws.close()