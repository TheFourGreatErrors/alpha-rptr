# coding: UTF-8

import unittest
from datetime import datetime, timezone, timedelta

from src import delta, allowed_range
from src.bitmex import BitMex


class TestBitMex(unittest.TestCase):

    def test_fetch_ohlcv_5m(self):
        bitmex = BitMex(threading=False)
        end_time = datetime.now(timezone.utc)
        start_time = end_time - 5 * timedelta(minutes=5)
        source = bitmex.fetch_ohlcv('5m', start_time, end_time)
        assert len(source) > 1

    def test_fetch_ohlc_2h(self):
        bitmex = BitMex(threading=False)
        end_time = datetime.now(timezone.utc)
        start_time = end_time - 5 * timedelta(hours=2)
        source = bitmex.fetch_ohlcv('2h', start_time, end_time)
        assert len(source) > 1

    def test_fetch_ohlcv_11m(self):
        ohlcv_len = 100
        bin_size = '11m'
        bitmex = BitMex(threading=False)

        end_time = datetime.now(timezone.utc)
        start_time = end_time - ohlcv_len * delta(bin_size)
        d1 = bitmex.fetch_ohlcv(bin_size, start_time, end_time)
        print(f"{d1}")

    def test_entry_cancel(self):
        bitmex = BitMex()
        bitmex.demo = True

        # close current orders
        bitmex.close_all()

        price = bitmex.get_market_price()

        # TEST: CANCELLATION
        id = "Long"
        bitmex.entry(id, True, 1, limit=price-1000)
        assert bitmex.get_open_order(id) is not None
        bitmex.cancel(id)
        assert bitmex.get_open_order(id) is None

        # TEST: UPDATE ORDER
        id = "Long"
        bitmex.entry(id, True, 1, limit=price-1000)
        order = bitmex.get_open_order(id)
        assert order["orderQty"] == 1
        assert order["price"] == price-1000
        bitmex.entry(id, True, 2, limit=price-900)
        order = bitmex.get_open_order(id)
        assert order["orderQty"] == 2
        assert order["price"] == price-900
        bitmex.cancel(id)
        assert bitmex.get_open_order(id) is None

