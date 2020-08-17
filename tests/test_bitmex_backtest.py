# coding: UTF-8

import datetime
import os
import tempfile
import unittest

from src import load_data
from src.bitmex_backtest import BitMexBackTest


class TestBitMexBackTest(unittest.TestCase):

    def test_download_data(self):
        bitmex = BitMexBackTest()
        end_time = datetime.datetime.now(datetime.timezone.utc)
        start_time = end_time - 200 * datetime.timedelta(hours=2)
        with tempfile.TemporaryDirectory() as dir:
            file = dir + "/tmp.csv"
            bitmex.download_data(file, '2h', start_time, end_time)
            assert os.path.exists(file)

    def test_load_file(self):
        bitmex = BitMexBackTest()
        end_time = datetime.datetime.now(datetime.timezone.utc)
        start_time = end_time - 5 * datetime.timedelta(hours=2)
        with tempfile.TemporaryDirectory() as dir:
            file = dir + "/tmp.csv"
            bitmex.download_data(file, '2h', start_time, end_time)
            data_frame = load_data(file)
            now = datetime.datetime.now(datetime.timezone.utc)
            assert data_frame.iloc[0].name < now