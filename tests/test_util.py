# coding: UTF-8

import datetime
import os
import unittest

from src import to_data_frame, validate_continuous, load_data, ord_suffix


class TestUtil(unittest.TestCase):

    def test_to_data_frame(self):
        data = {'timestamp': datetime.datetime(2018, 6, 8, 23, 56), 'symbol': 'XBTUSD', 'open': 7625.5, 'high': 7625.5, 'low': 7625, 'close': 7625, 'trades': 66, 'volume': 645499, 'vwap': 7625.4385, 'lastSize': 2001, 'turnover': 8465106620, 'homeNotional': 84.6510662, 'foreignNotional': 645499}
        data_frame = to_data_frame([data])
        now = datetime.datetime.now(datetime.timezone.utc)
        assert data_frame.iloc[0].name < now

    def test_validate_continuous(self):
        file = os.path.join(os.path.dirname(__file__), "./ohlc/discontinuous.csv")
        data = load_data(file)
        assert not validate_continuous(data, '5m')[0]

        file = os.path.join(os.path.dirname(__file__), "./ohlc/continuous.csv")
        data = load_data(file)
        assert validate_continuous(data, '5m')[0]

    def test_order_suffix(self):
        suffix = ord_suffix()
        print(suffix)
        assert len(suffix) > 0