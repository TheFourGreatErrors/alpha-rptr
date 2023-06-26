# coding: UTF-8

import base64
import logging
import os, tempfile
import time
import uuid
import threading
from datetime import timedelta

import numpy as np
import pandas as pd
from pandas import Series
import requests
from bravado.exception import HTTPError
#Install discord_webhook module 
from discord_webhook import DiscordWebhook, DiscordEmbed

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from src.config import config as conf
from src.exchange.binance_futures.exceptions import BinanceAPIException, BinanceRequestException


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


status_codes = [400, 401, 402, 403, 404, 429]


allowed_range = {
    "1m": ["1m", "1T", 1, 1], "2m":  ["1m", "2T", 2, 2], "3m":  ["1m", "3T", 3, 3],
    "4m": ["1m", "4T", 4, 4], "5m": ["1m", "5T", 5, 5], "6m": ["1m", "6T", 6, 6],
    "7m": ["1m", "7T", 7, 7], "8m": ["1m", "8T", 8, 8], "9m": ["1m", "9T", 9, 9],
    "10m": ["1m", "10T", 10, 10], "11m": ["1m", "11T", 11, 11],
    "15m": ["5m", "15T", 3, 15], "30m": ["5m", "30T", 6, 30], "45m": ["5m", "45T", 9, 45],
    "1h": ["1h", "1H", 1, 1], "2h":  ["1h", "2H", 2, 2],
    "3h": ["1h", "3H", 3, 3], "4h":  ["1h", "4H", 4, 4],
    "6h": ["1h", "6H", 6, 6], "12h": ["1h", "12H", 12, 12],
    "1d": ["1d", "1D", 1, 1], "3d": ["3d", "3D", 3, 3]
    # not support yet '1w', '2w', '1M'
}


allowed_range_minute_granularity = {
    "1m": ["1m", "1T", 1, 1], "2m":  ["1m", "2T", 2, 2], "3m":  ["1m", "3T", 3, 3],
    "4m": ["1m", "4T", 4, 4], "5m": ["1m", "5T", 5, 5], "6m": ["1m", "6T", 6, 6],
    "7m": ["1m", "7T", 7, 7], "8m": ["1m", "8T", 8, 8], "9m": ["1m", "9T", 9, 9],
    "10m": ["1m", "10T", 10, 10], "11m": ["1m", "11T", 11, 11],
    "15m": ["1m", "15T", 15, 15], "30m": ["1m", "30T", 30, 30], "45m": ["1m", "45T", 45, 45],
    "1h": ["1m", "60T", 60, 60], "2h":  ["1m", "120T", 120, 120],
    "3h": ["1m", "180T", 180, 180], "4h":  ["1m", "240T", 240, 240],
    "6h": ["1m", "360T", 360, 360], "12h": ["1m", "720T", 720, 720],
    "1d": ["1m", "1440T", 1440, 1440], "3d": ["1m", "4320T", 4320, 4320]
    # not support yet '1w', '2w', '1M'
}


def bin_size_converter(bin_size):
    """
    Converts a bin size string to a dictionary with "bin_size" and "seconds" keys.

    :param bin_size: A string representing the bin size, e.g. "1m", "2h", "1d".
    :return: A dictionary with "bin_size" and "seconds" keys.
    :raises ValueError: If the bin size is not recognized.
    """
    bin_sizes = {
        "1m": {"bin_size": "1", "seconds": 60},
        "3m": {"bin_size": "3", "seconds": 180},
        "5m": {"bin_size": "5", "seconds": 300},
        "15m": {"bin_size": "15", "seconds": 900},
        "30m": {"bin_size": "30", "seconds": 1800},
        "1h": {"bin_size": "60", "seconds": 3600},
        "2h": {"bin_size": "120", "seconds": 7200},
        "4h": {"bin_size": "240", "seconds": 14400},
        "6h": {"bin_size": "350", "seconds": 21600},
        "12h": {"bin_size": "720", "seconds": 43200},
        "1d": {"bin_size": "D", "seconds": 86400},
        "1w": {"bin_size": "W", "seconds": 604800},
    }

    if bin_size not in bin_sizes:
        raise ValueError("Unrecognized bin size: {}".format(bin_size))

    return bin_sizes[bin_size]


class RepeatedTimer(object):
  def __init__(self, interval, function, next_call=time.time(), *args, **kwargs):    
    self._timer = None
    self.interval = interval
    self.function = function
    self.args = args
    self.kwargs = kwargs
    self.is_running = False
    self.next_call = next_call #time.time()
    self.start()

  def _run(self):
    self.is_running = False
    self.start()
    self.function(*self.args, **self.kwargs)

  def start(self):    
    if not self.is_running:
      self.next_call += self.interval
      self._timer = threading.Timer(self.next_call - time.time(), self._run)
      self._timer.daemon = True
      self._timer.start()
      self.is_running = True

  def stop(self):
    self._timer.cancel()
    self.is_running = False


# https://stackoverflow.com/questions/3041986/apt-command-line-interface-like-yes-no-input
def query_yes_no(question, default="yes"):
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
            It must be "yes" (the default), "no" or None (meaning
            an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        logger.info(question + prompt)
        choice = input().lower()
        if default is not None and choice == "":
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            logger.info("Please respond with 'yes' or 'no' " "(or 'y' or 'n').\n")

# https://stackoverflow.com/questions/8299386/modifying-a-symlink-in-python/55742015#55742015
def symlink(target, link_name, overwrite=False):    
    """
    Create a symbolic link named link_name pointing to target.
    If link_name exists then FileExistsError is raised, unless overwrite=True.
    When trying to overwrite a directory, IsADirectoryError is raised.
    """

    if not overwrite:
        os.symlink(target, link_name)
        return

    # os.replace() may fail if files are on different filesystems
    link_dir = os.path.dirname(link_name)

    # Create link to target with temporary filename
    while True:
        temp_link_name = tempfile.mktemp(dir=link_dir)

        # os.* functions mimic as closely as possible system functions
        # The POSIX symlink() returns EEXIST if link_name already exists
        # https://pubs.opengroup.org/onlinepubs/9699919799/functions/symlink.html
        try:
            os.symlink(target, temp_link_name)
            break
        except FileExistsError:
            pass

    # Replace link_name with temp_link_name
    try:
        # Pre-empt os.replace on a directory with a nicer message
        if not os.path.islink(link_name) and os.path.isdir(link_name):
            raise IsADirectoryError(f"Cannot symlink over existing directory: '{link_name}'")
        os.replace(temp_link_name, link_name)
    except:
        if os.path.islink(temp_link_name):
            os.remove(temp_link_name)
        raise


class FatalError(Exception):
    pass


def sync_obj_with_config(config, obj, instance=None):
    """
    Synchronizes the attributes of an object with a dictionary of configuration values.

    Args:
        config (dict): A dictionary containing configuration values.
        obj (object): The object whose attributes should be updated.
        instance (object, optional): The instance of the object. Defaults to None.
    """
    for k,v in config.items():
        if k in dir(obj):               
            setattr(instance or obj, k, v)


def find_timeframe_string(timeframe_in_minutes):
    """
    finds and returns tf string based on minute count
    """
    for tf, value in allowed_range_minute_granularity.items(): 
        if value[3] == timeframe_in_minutes:
            return tf
            

def ord_suffix():
    return "_" + uuid.uuid4().hex[:15]


def load_data(file):
    """
    Read data from a file.
    """    
    source = pd.read_csv(file)
    # data_frame = pd.DataFrame({
    #     'timestamp': pd.to_datetime(source['timestamp']),
    #     'open': source['open'],
    #     'close': source['close'],
    #     'high': source['high'],
    #     'low': source['low'],
    #     'volume': source['volume']
    # })
    # data_frame = data_frame.set_index('timestamp')
    # return data_frame.tz_localize(None).tz_localize('UTC', level=0)
    return source


def delta(bin_size='1h', minute_granularity= False):
    if minute_granularity:
        return timedelta(minutes= allowed_range_minute_granularity[bin_size][3])
    elif bin_size.endswith('d'):
        return timedelta(days=allowed_range[bin_size][3])
    elif bin_size.endswith('h'):
        return timedelta(hours=allowed_range[bin_size][3])
    elif bin_size.endswith('m'):
        return timedelta(minutes=allowed_range[bin_size][3])


def validate_continuous(data, bin_size):    
    last_date = None
    for i in range(len(data)):
        index = data.iloc[-1 * (i + 1)].name
        if last_date is None:
            last_date = index
            continue
        if last_date - index != delta(bin_size):
            return False, index
        last_date = index
    return True, None


def verify_series(series: Series, min_length: int = None) -> Series:
    """
    If a Pandas Series and it meets the min_length of the indicator return it.
    """
    has_length = min_length is not None and isinstance(min_length, int)
    if series is not None and isinstance(series, Series):
        return None if has_length and series.size < min_length else series


def to_data_frame(data):    
    data_frame = pd.DataFrame(data, columns=["timestamp", "high", "low", "open", "close", "volume"])    
    data_frame = data_frame.set_index("timestamp")
    data_frame = data_frame.tz_localize(None).tz_localize('UTC', level=0)    
    return data_frame


def resample(data_frame, bin_size, minute_granularity=False, label="right", closed="right"):      
    resample_time = allowed_range_minute_granularity[bin_size][1] \
                    if minute_granularity else allowed_range[bin_size][1]
    return data_frame.resample(resample_time, label=label, closed=closed).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })   


def retry(func, count=5):
    err = None
    for i in range(count):
        try:           
            ret, res = func()            
            rate_limit = int(res.headers['X-RateLimit-Limit'])
            rate_remain = int(res.headers['X-RateLimit-Remaining'])
            if rate_remain < 10:
                time.sleep(5 * 60 * (1 + rate_limit - rate_remain) / rate_limit)
            return ret
        except HTTPError as error:
            status_code = error.status_code
            err = error
            if status_code >= 500:
                time.sleep(pow(2, i + 1))
                continue
            elif status_code in status_codes:
                raise FatalError(error)
    raise err


binance_errors_to_actions = {
    # APIError(code=-1021): Timestamp for this request is outside of the recvWindow.
    1021: "retry",
    # APIError(code=-1022): Signature for this request is not valid
    1022: "retry",
    # APIError(code=-5028): Timestamp for this request is outside of the ME recvWindow.
    5028: "retry",
    # APIError(code=-2021): Stop Order would immediately trigger.
    2021: "return",
    # APIError(code=-5021): Due to the order could not be filled immediately, the FOK order has been rejected. The order will not be recorded in the order history.
    5021: "return",
    # APIError(code=-5022): Due to the order could not be executed as maker, the Post Only order will be rejected. The order will not be recorded in the order history.
    5022: "return",
    # APIError(code=-2011): Unknown order sent.
    2011: "return"

}


def check_binance_error(code):
    try:
        return binance_errors_to_actions[abs(int(code))]
    except:
        return None


def retry_binance_futures(func, count=5):
    err = None
    for i in range(count):
        try:            
            ret, res = func()

            #res_header = res.headers['X-MBX-USED-WEIGHT-1M']                   
            rate_limit = int(res.headers['X-MBX-USED-WEIGHT-1M'])
            #todo finish retry limit and status codes
            
            # rate_remain = None
            # try:                
            #     rate_remain = int(res.headers['X-MBX-ORDER-COUNT-1M'])
            # except KeyError:             #             
            #     #return ret
            #     pass
            # if rate_remain is not None and rate_remain < 10:
            #     time.sleep(5 * 60 * (1 + rate_limit - rate_remain) / rate_limit)
            return ret
        except BinanceAPIException as error:
            logger.info(error)
            status_code = error.status_code
            err = error
            if status_code >= 500 or \
                check_binance_error(error.code) == "retry":
                time.sleep(pow(2, i + 1))
                logger.info(f"Retrying Request - Count: {i+1} - Status: {status_code} - Error: {error.code}")
                continue
            elif check_binance_error(error.code) == "return":
                break 
            elif status_code in status_codes or check_binance_error(error.code) == "error":
                raise FatalError(error)
        except BinanceRequestException as reqErr:
            logger.info(reqErr)
            time.sleep(pow(2, i + 1))
            logger.info(f"Retrying Request - Count: {i+1}")
            continue

    raise err


def retry_bybit(func, count=5):
    err = None
    for i in range(count):
        try:
            #logger.info(f"{func()}")
            ret = func()
            if 'result' in ret:
                ret = ret['result']

            #res_header = res.headers['X-MBX-USED-WEIGHT-1M']                   
            #rate_limit = int(res.headers['X-MBX-USED-WEIGHT-1M'])
            #todo finish retry limit and status codes
            
            # rate_remain = None
            # try:                
            #     rate_remain = int(res.headers['X-MBX-ORDER-COUNT-1M'])
            # except KeyError:             #             
            #     #return ret
            #     pass
            # if rate_remain is not None and rate_remain < 10:
            #     time.sleep(5 * 60 * (1 + rate_limit - rate_remain) / rate_limit)
            return ret
        except HTTPError as error:
            status_code = error.status_code
            err = error
            if status_code >= 500:
                time.sleep(pow(2, i + 1))
                continue
            elif status_code in status_codes:
                raise FatalError(error)
    raise err


def retry_ftx(func, count=5):
    err = None
    for i in range(count):
        try:        
            ret = func()
          
            if 'error' in ret:
                if ret['error'] == "Please retry request":
                    time.sleep(pow(2, i + 1))
                    continue
            return ret['result']
        except ConnectionError as error:            
            time.sleep(pow(2, i + 1))               
            continue
        except HTTPError as error:
            status_code = error.status_code
            err = error
            if status_code >= 500:
                time.sleep(pow(2, i + 1))
                continue               
            elif status_code in status_codes:
                raise FatalError(error)
    raise err


class Side:
    Long = "Long"
    Short = "Short"
    Close = "Close"
    Unknown = "Unknown"


def notify(message: object, fileName: object = None) -> object:

    try:
        webhook_url = conf["discord_webhooks"][conf["args"].account]

        if webhook_url is not None:       
            webhook = DiscordWebhook(url=webhook_url)
            embed = DiscordEmbed()
            embed.set_footer(text=message)
            embed.set_timestamp()
            webhook.add_embed(embed)
            response = webhook.execute()     
    except:
        pass   

    url = 'https://notify-api.line.me/api/notify'
    #api_key = os.environ.get('LINE_APIKEY')
    api_key = conf['line_apikey']['API_KEY']
    if api_key is None or len(api_key) == 0:
        return

    payload = {'message': message}
    headers = {'Authorization': 'Bearer ' + api_key}
    if fileName is None:
        try:
            requests.post(url, data=payload, headers=headers)
        except:
            pass
    else:
        try:
            files = {"imageFile": open(fileName, "rb")}
            requests.post(url, data=payload, headers=headers, files=files)
        except:
            pass

class InfluxDB():

    client = None #will be False if not configured
    writer = None #will be False if not configured

    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = super(InfluxDB, cls).__new__(cls)
        return cls.instance

    def __init__(self):
        try: 
            url = conf["influx_db"][conf["args"].account]["url"]
            token = conf["influx_db"][conf["args"].account]["token"]
            org = conf["influx_db"][conf["args"].account]["org"]
            self.client = InfluxDBClient(url=url, token=token, org=org)
            self.writer = self.client.write_api(write_options=SYNCHRONOUS)
        except Exception as e:
            self.client = False
            self.writer = False
            logger.info(e)
            pass

    def log(self, timestamp, measurement, fields, tags):

        if self.writer is not False:
            try:
                self.writer.write(bucket=conf["influx_db"][conf["args"].account]["bucket"],
                                record=[
                                    {
                                        "time": timestamp, #"2009-11-10T23:00:00Z"
                                        "measurement": measurement, #"my-type"
                                        "fields": fields, #kv pairs
                                        "tags": tags #kv pairs
                                    }
                                ])
            except Exception as e:
                logger.info(e)
                pass

        return

##############################################
# Implements logging metrics to InfluxDB
# 
# multiple related metrics can be logged together 
# with the given tags as part of the given collection
# 
# collection
# |
# |--- tags
#       |
#       |---metrics
#
# InfluxDB allows filtering by collection and tags
# 
# log_metrics to InfluxDB mapping:
#
# 1. collection -> measurement
# 2. metrics -> fields
# 3. tags -> tags
###############################################

def log_metrics(timestamp, collection, metrics={}, tags = {}):
    influx_db = InfluxDB()
    influx_db.log(timestamp, collection, metrics, tags)
    return