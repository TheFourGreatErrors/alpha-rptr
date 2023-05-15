# coding: UTF-8

import math
from collections.abc import Iterable

import numpy as np
from numpy import nan as npNaN
import pandas as pd
from pandas import Series
import talib

from src import verify_series


def first(l=[]):
    return l[0]


def last(l=[]):
    return l[-1]


def highest(source, period):
    return pd.Series(source).rolling(period).max().values


def lowest(source, period):
    return pd.Series(source).rolling(period).min().values


def med_price(high, low):
    """
    also found in tradingview as hl2 source
    """
    return talib.MEDPRICE(high, low)


def avg_price(open, high, low, close):
    """
    also found in tradingview as ohlc4 source
    """
    return talib.AVGPRICE(open, high, low, close)

def typ_price(high,low,close):
    """
    typical price, also found in tradingview as hlc3 source
    """
    return talib.TYPPRICE(high, low, close)


def MAX(close, period):
    return talib.MAX(close, period)


def highestbars(source, length):
    """
    Highest value offset for a given number of bars back.
    Returns offset to the highest bar.
    """    
    source = source[-length:]
    offset = abs(length - 1 - np.argmax(source))

    return offset


def lowestbars(source, length):
    """
    Lowest value offset for a given number of bars back.
    Returns offset to the lowest bar.
    """    
    source = source[-length:]
    offset = abs(length - 1 - np.argmin(source))

    return offset


def tr(high, low, close):
    """
    true range
    """
    return talib.TRANGE(high, low, close)


def atr(high, low, close, period):
    """
    average true range
    """
    return talib.ATR(high, low, close, period)


def stdev(source, period):
    return pd.Series(source).rolling(period).std().values


def stddev(source, period, nbdev=1):
    """
    talib stdev
    """
    return talib.STDDEV(source, timeperiod=period, nbdev=nbdev)


def sma(source, period):
    return pd.Series(source).rolling(period).mean().values


def ema(source, period):
    return talib.EMA(np.array(source), period)


def double_ema(src, length):
    ema_val = ema(src, length)
    return 2 * ema_val - ema(ema_val, length)


def triple_ema(src, length):
    ema_val = ema(src, length)
    return 3 * (ema_val - ema(ema_val, length)) + ema(ema(ema_val, length), length)


def wma(src, length):
    return talib.WMA(src, length)


def ewma(data, alpha):
    """
    Calculate Exponentially Weighted Moving Average (EWMA) using Pandas.
    Args:
        data (list or numpy array): Input data for calculating EWMA.
        alpha (float): Smoothing factor for EWMA.
    Returns:
        list: List containing the calculated EWMA values.
    """
    ewma_series = pd.Series(data).ewm(alpha=alpha).mean()
    ewma_list = ewma_series.tolist()
    return ewma_list


def vwap(high, low, volume):
    average_price = volume * (high + low) / 2
    return average_price.sum() / volume.sum()


def ssma(src, length):
    return pd.Series(src).ewm(alpha=1.0 / length).mean().values.flatten()


def hull(src, length):
    return wma(2 * wma(src, length / 2) - wma(src, length), round(np.sqrt(length)))


def bbands(source, timeperiod=5, nbdevup=2, nbdevdn=2, matype=0):
    return talib.BBANDS(source, timeperiod, nbdevup, nbdevdn, matype)


def macd(close, fastperiod=12, slowperiod=26, signalperiod=9):
    return talib.MACD(close, fastperiod, slowperiod, signalperiod)


def adx(high, low, close, period=14):
    return talib.ADX(high, low, close, period)


def di_plus(high, low, close, period=14):
    return talib.PLUS_DI(high, low, close, period)


def di_minus(high, low, close, period=14):
    return talib.MINUS_DI(high, low, close, period)


def rsi(close, period=14):
    return talib.RSI(close, period)


def rsx(source, length=None, drift=None, offset=None):
    """
    Indicator: Relative Strength Xtra (inspired by Jurik RSX)
    """
    # Validate arguments
    length = int(length) if length and length > 0 else 14
    source = pd.Series(source)
    source = verify_series(source, length)
    #drift = get_drift(drift)
    #offset = get_offset(offset)

    if source is None: return

    # variables
    vC, v1C = 0, 0
    v4, v8, v10, v14, v18, v20 = 0, 0, 0, 0, 0, 0

    f0, f8, f10, f18, f20, f28, f30, f38 = 0, 0, 0, 0, 0, 0, 0, 0
    f40, f48, f50, f58, f60, f68, f70, f78 = 0, 0, 0, 0, 0, 0, 0, 0
    f80, f88, f90 = 0, 0, 0

    # Calculate Result
    m = source.size
    result = [npNaN for _ in range(0, length - 1)] + [0]
    for i in range(length, m):
        if f90 == 0:
            f90 = 1.0
            f0 = 0.0
            if length - 1.0 >= 5:
                f88 = length - 1.0
            else:
                f88 = 5.0
            f8 = 100.0 * source.iloc[i]
            f18 = 3.0 / (length + 2.0)
            f20 = 1.0 - f18
        else:
            if f88 <= f90:
                f90 = f88 + 1
            else:
                f90 = f90 + 1
            f10 = f8
            f8 = 100 * source.iloc[i]
            v8 = f8 - f10
            f28 = f20 * f28 + f18 * v8
            f30 = f18 * f28 + f20 * f30
            vC = 1.5 * f28 - 0.5 * f30
            f38 = f20 * f38 + f18 * vC
            f40 = f18 * f38 + f20 * f40
            v10 = 1.5 * f38 - 0.5 * f40
            f48 = f20 * f48 + f18 * v10
            f50 = f18 * f48 + f20 * f50
            v14 = 1.5 * f48 - 0.5 * f50
            f58 = f20 * f58 + f18 * abs(v8)
            f60 = f18 * f58 + f20 * f60
            v18 = 1.5 * f58 - 0.5 * f60
            f68 = f20 * f68 + f18 * v18
            f70 = f18 * f68 + f20 * f70
            v1C = 1.5 * f68 - 0.5 * f70
            f78 = f20 * f78 + f18 * v1C
            f80 = f18 * f78 + f20 * f80
            v20 = 1.5 * f78 - 0.5 * f80

            if f88 >= f90 and f8 != f10:
                f0 = 1.0
            if f88 == f90 and f0 == 0.0:
                f90 = 0.0

        if f88 < f90 and v20 > 0.0000000001:
            v4 = (v14 / v20 + 1.0) * 50.0
            if v4 > 100.0:
                v4 = 100.0
            if v4 < 0.0:
                v4 = 0.0
        else:
            v4 = 50.0
        result.append(v4)
    rsx = Series(result, index=source.index)

    # Offset
    if offset != 0 and offset != None:
        rsx = rsx.shift(offset)
    
    return rsx


def cci(high, low, close, period):
    return talib.CCI(high,low, close, period)


def sar(high, low, acceleration=0, maximum=0):
    return talib.SAR(high, low, acceleration, maximum)


def sarext(high, low, startvalue=0, offsetonreverse=0,
           accelerationinitlong=0.02, accelerationlong=0.02, accelerationmaxlong=0.2,
           accelerationinitshort=0.02, accelerationshort=0.02, accelerationmaxshort=0.2):
    """
    Parabolic SAR - Extended
    """
    return abs(talib.SAREXT(high, low, startvalue, offsetonreverse,
                        accelerationinitlong, accelerationlong, accelerationmaxlong,
                        accelerationinitshort, accelerationshort, accelerationmaxshort))


def crossover(a, b):
    return a[-2] < b[-2] and a[-1] > b[-1]


def crossunder(a, b):
    return a[-2] > b[-2] and a[-1] < b[-1]


def ord(seq, sort_seq, idx, itv):
    p = seq[idx]
    for i in range(0, itv):
        if p >= sort_seq[i]:
            return i + 1


def d(src, itv):
    sort_src = np.sort(src)[::-1]
    sum = 0.0
    for i in range(0, itv):
        sum += pow((i + 1) - ord(src, sort_src, i, itv), 2)
    return sum


def rci(src, itv):
    reversed_src = src[::-1]
    ret = [(1.0 - 6.0 * d(reversed_src[i:i + itv], itv) / (itv * (itv * itv - 1.0))) * 100.0
           for i in range(2)]
    return ret[::-1]


def vix(close, low, pd=23, bbl=23, mult=1.9, lb=88, ph=0.85, pl=1.01):
    hst = highest(close, pd)
    wvf = (hst - low) / hst * 100
    s_dev = mult * stdev(wvf, bbl)
    mid_line = sma(wvf, bbl)
    lower_band = mid_line - s_dev
    upper_band = mid_line + s_dev

    range_high = (highest(wvf, lb)) * ph
    range_low = (lowest(wvf, lb)) * pl

    green_hist = [wvf[-i] >= upper_band[-i] or wvf[-i] >= range_high[-i] for i in range(8)][::-1]
    red_hist = [wvf[-i] <= lower_band[-i] or wvf[-i] <= range_low[-i] for i in range(8)][::-1]

    return green_hist, red_hist


def supertrend(high, low, close, length=None, multiplier=None, offset=None):
    """
    Indicator: Supertrend
    """
    # Validate Arguments
    length = int(length) if length and length > 0 else 7
    multiplier = float(multiplier) if multiplier and multiplier > 0 else 3.0
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    high = verify_series(high, length)
    low = verify_series(low, length)
    close = verify_series(close, length)
    #offset = get_offset(offset)

    if high is None or low is None or close is None: return

    # Calculate Results
    m = close.size
    dir_, trend = [1] * m, [0] * m
    long, short = [npNaN] * m, [npNaN] * m

    hl2_ = med_price(high, low)
    matr = multiplier * atr(high, low, close, length)
    upperband = hl2_ + matr
    lowerband = hl2_ - matr

    for i in range(1, m):
        if close.iloc[i] > upperband.iloc[i - 1]:
            dir_[i] = 1
        elif close.iloc[i] < lowerband.iloc[i - 1]:
            dir_[i] = -1
        else:
            dir_[i] = dir_[i - 1]
            if dir_[i] > 0 and lowerband.iloc[i] < lowerband.iloc[i - 1]:
                lowerband.iloc[i] = lowerband.iloc[i - 1]
            if dir_[i] < 0 and upperband.iloc[i] > upperband.iloc[i - 1]:
                upperband.iloc[i] = upperband.iloc[i - 1]

        if dir_[i] > 0:
            trend[i] = long[i] = lowerband.iloc[i]
        else:
            trend[i] = short[i] = upperband.iloc[i]

    # Prepare DataFrame to return
    _props = f"_{length}_{multiplier}"
    df = pd.DataFrame({
            f"SUPERT": trend,
            f"SUPERTd": dir_,
            f"SUPERTl": long,
            f"SUPERTs": short,
        }, index=close.index)

    df.name = f"SUPERT{_props}"
    df.category = "overlap"

    # Apply offset if needed
    if offset != 0 and offset != None:
        df = df.shift(offset)    

    return df


def tv_supertrend(high, low, close, length=14, multiplier=3):
    
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    
    # calculate ATR
    price_diffs = [high - low, 
                   high - close.shift(), 
                   low - close.shift()]
    true_range = pd.concat(price_diffs, axis=1)
    true_range = true_range.abs().max(axis=1)
    true_range[0] = (high[0] + low[0])/2
    # default ATR calculation in supertrend indicator
    atr = true_range.ewm(alpha=1/length,min_periods=length,ignore_na=True,adjust=False).mean() 
    # atr = sma(true_range, length)

    atr.fillna(0, inplace=True)

    # HL2 is simply the average of high and low prices
    hl2 = (high + low) / 2
    # upperband and lowerband calculation
    # notice that final bands are set to be equal to the respective bands
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)

    # initialize Supertrend column to 1
    dir = [np.NaN] * close.size
    trend = [np.NaN] * close.size
    
    for i in range(1, len(close)):
        curr, prev = i, i-1
        
        #lowerBand := lowerBand > prevLowerBand or close[1] < prevLowerBand ? lowerBand : prevLowerBand
        lowerband[curr] = lowerband[curr] if \
            lowerband[curr] > lowerband[prev] or close[prev] < lowerband[prev] \
                else lowerband[prev]

        #upperBand := upperBand < prevUpperBand or close[1] > prevUpperBand ? upperBand : prevUpperBand
        upperband[curr] = upperband[curr] if \
            upperband[curr] < upperband[prev] or close[prev] > upperband[prev] \
                else upperband[prev]

        if np.isnan(atr[prev]):
            dir[curr] = -1
        elif trend[prev] == upperband[prev]:
            dir[curr] = 1 if close[curr] > upperband[curr] else -1
        else:
            dir[curr] = -1 if close[curr] < lowerband[curr] else 1

        trend[curr] = lowerband[curr] if dir[curr] == 1 else upperband[curr]

    return pd.DataFrame({
        f"SUPERT": trend,
        f"SUPERTd": dir,
        f"SUPERTl": lowerband,
        f"SUPERTs": upperband,
    }, index=close.index)


def donchian(high, low, lower_length=None, upper_length=None, offset=None, **kwargs):
    """
    Indicator: Donchian Channels (DC)
    """
    # Validate arguments
    high = pd.Series(high)
    low = pd.Series(low)

    lower_length = int(lower_length) if lower_length and lower_length > 0 else 20
    upper_length = int(upper_length) if upper_length and upper_length > 0 else 20
    lower_min_periods = int(kwargs["lower_min_periods"]) if "lower_min_periods" in kwargs and kwargs["lower_min_periods"] is not None else lower_length
    upper_min_periods = int(kwargs["upper_min_periods"]) if "upper_min_periods" in kwargs and kwargs["upper_min_periods"] is not None else upper_length
    _length = max(lower_length, lower_min_periods, upper_length, upper_min_periods)
    high = verify_series(high, _length)
    low = verify_series(low, _length)
    #offset = get_offset(offset)

    if high is None or low is None: return

    # Calculate Result
    lower = low.rolling(lower_length, min_periods=lower_min_periods).min()
    upper = high.rolling(upper_length, min_periods=upper_min_periods).max()
    mid = 0.5 * (lower + upper)    

    # Offset
    if offset != 0 and offset != None:
        lower = lower.shift(offset)
        mid = mid.shift(offset)
        upper = upper.shift(offset)

    # Name and Categorize it
    lower.name = f"DCL" #_{lower_length}_{upper_length}"
    mid.name = f"DCM" #_{lower_length}_{upper_length}"
    upper.name = f"DCU" #_{lower_length}_{upper_length}"
    mid.category = upper.category = lower.category = "volatility"

    # Prepare DataFrame to return
    data = {lower.name: lower, mid.name: mid, upper.name: upper}
    dcdf = pd.DataFrame(data)
    dcdf.name = f"DC_{lower_length}_{upper_length}"
    dcdf.category = mid.category

    return dcdf


def hurst_exponent(data):
    """Calculate the Hurst exponent using the R/S method.    
    Args: 
        data (numpy.ndarray or list): The input time series data.    
    Returns: 
        float: The calculated Hurst exponent.
    """
    data = np.asarray(data)
    n = len(data)
    rs = np.zeros((len(data)//2, 2))
    
    for i in range(1, n//2 + 1):
        cumsum = np.cumsum(data - np.mean(data))
        rs[i-1, 0] = np.max(cumsum[:i]) - np.min(cumsum[:i])
        rs[i-1, 1] = np.std(data)
    
    avg_rs = np.mean(rs[:, 0] / rs[:, 1])
    
    return np.log2(avg_rs)


def lyapunov_exponent(data, dt):  
    """
    Calculate the Lyapunov exponent for a given time series data.
    Parameters:
        data: Time series data of the dynamical system.
        dt (float): Time step between consecutive state vectors.
    Returns: 
        float: The Lyapunov exponent.
    """
    data = data if isinstance(data[0], Iterable) else [data]
    #n = np.shape(data)[0]  # Length of data
    #d = np.shape(data)[1] if len(np.shape(data)) > 1 else 1  # Dimensionality of data 
    n = len(data)
    d = len(data[0])   
    epsilon = 1e-8  # small constant to avoid division by zero

    # Initialize the Lyapunov sum
    sum_lyapunov = 0.0

    for i in range(n):
        x = data[i]

        # Initialize the tangent vector
        v = np.zeros(d)
        v[0] = 1.0

        # Integrate the tangent vector
        for j in range(d):
            x_forward = data[(i + j) % n]
            x_backward = data[(i - j) % n]

            forward_difference = x_forward - x
            backward_difference = x - x_backward

            norm_forward = np.linalg.norm(forward_difference) + epsilon
            norm_backward = np.linalg.norm(backward_difference) + epsilon

            v += np.log(norm_forward / norm_backward) * backward_difference / norm_backward

            # Orthogonalize the tangent vector
            v -= np.dot(v, x) * x / np.dot(x, x)

        # Calculate the local Lyapunov exponent
        sum_lyapunov += np.log(np.linalg.norm(v) + epsilon) / dt

    # Calculate the average Lyapunov exponent
    average_lyapunov = sum_lyapunov / n

    return average_lyapunov


def detrended_fluctuation_analysis(data, window_sizes):
    """
    Perform Detrended Fluctuation Analysis (DFA) on the given data.    
    Parameters:
        data: 1-D array or list containing the data.
        window_sizes: List of window sizes (list of integers).    
    Returns:
        List of tuples (window_size, fluctuation) representing the detrended fluctuation values.
    """
    # Convert data to a numpy array
    data = np.asarray(data)
    
    # Calculate the cumulative sum of the data
    cumulative_sum = np.cumsum(data - np.mean(data))
    
    # Initialize a list to store the fluctuation values
    fluctuation = []
    
    # Iterate over the window sizes
    for window_size in window_sizes:
        # Check if the window size is greater than the length of the data
        if window_size > len(data):
            continue
        
        # Calculate the number of windows
        num_windows = len(data) // window_size
        
        # Initialize lists to store the local trends and local detrended data
        local_trends = []
        local_detrended_data = []
        
        # Iterate over the windows
        for i in range(num_windows):
            # Get the data points within the current window
            window_data = cumulative_sum[i*window_size : (i+1)*window_size]
            
            # Fit a least-squares polynomial to the data points
            polynomial = np.polyfit(np.arange(window_size), window_data, 1)
            
            # Calculate the local trend
            local_trend = np.polyval(polynomial, np.arange(window_size))
            local_trends.extend(local_trend)
            
            # Calculate the local detrended data
            local_detrended_data.extend(window_data - local_trend)
        
        # Convert the local trends and local detrended data to numpy arrays
        local_trends = np.asarray(local_trends)
        local_detrended_data = np.asarray(local_detrended_data)
        
        # Calculate the root mean square of the local detrended data
        rms = np.sqrt(np.mean(local_detrended_data**2))
        
        # Calculate the fluctuation as a function of the window size
        fluctuation.append((window_size, rms))
    
    return fluctuation


def psd(sig, fs):
    """
    Compute the Power Spectral Density (PSD) of a given signal.
    Parameters:
        sig (array-like): Input signal.
        fs (float): Sampling frequency of the signal.
    Returns:
        f (array-like): Frequency values.
        psd (array-like): Power Spectral Density values.
    """
    f, psd = scipy.welch(sig, fs=fs, nperseg=len(sig))
    return f, psd


def autocorrelation(data):
    n = len(data)
    mean = np.mean(data)
    autocorr = np.correlate(data - mean, data - mean, mode='full')
    autocorr /= autocorr[n - 1]
    return autocorr[n - 1:]


def shannon_entropy(probabilities):
    """
    Calculates the Shannon entropy of a probability distribution.
    Args: 
        probabilities (list): List of probabilities.
    Returns: 
        float: Shannon entropy value.
    """
    entropy = 0
    for probability in probabilities:
        if probability > 0:
            entropy -= probability * math.log2(probability)
    return entropy


def brownian_motion(timesteps, dt, initial_position=0, drift=0, volatility=1):
    """Simulates a Brownian motion path.
    Args:
        timesteps (int): Number of time steps to simulate.
        dt (float): Time step size.
        initial_position (float, optional): Initial position of the Brownian motion. Defaults to 0.
        drift (float, optional): Drift parameter. Defaults to 0.
        volatility (float, optional): Volatility parameter. Defaults to 1.
    Returns:
        numpy.ndarray: Array of simulated positions.
    """
    num_dimensions = 1  # We simulate a 1-dimensional Brownian motion

    # Calculate the number of increments
    num_increments = int(timesteps / dt)

    # Generate random normal increments
    increments = np.random.normal(loc=0, scale=np.sqrt(dt), size=(num_increments, num_dimensions))

    # Calculate the cumulative sum of the increments
    path = np.cumsum(increments, axis=0)

    # Add drift and volatility
    path = drift * dt + volatility * path

    # Add initial position
    path = initial_position + path

    return path


def brownian_bridge(timesteps, dt, initial_value, final_value):
    """Simulates a Brownian bridge path.
    Args:
        timesteps (int): Number of time steps to simulate.
        dt (float): Time step size.
        initial_value (float): Initial value of the bridge.
        final_value (float): Final value of the bridge.
    Returns:
        numpy.ndarray: Array of simulated values.
    """
    num_dimensions = 1  # We simulate a 1-dimensional process

    # Calculate the number of increments
    num_increments = int(timesteps / dt)

    # Generate random normal increments
    increments = np.random.normal(loc=0, scale=np.sqrt(dt), size=(num_increments, num_dimensions))

    # Calculate the cumulative sum of the increments
    path = np.cumsum(increments, axis=0)

    # Scale the path to match the initial and final values
    path = initial_value + path * ((final_value - initial_value) / path[-1])

    return path    


def bessel_process(timesteps, dt, initial_value):
    """Simulates a Bessel process path.
    Args:
        timesteps (int): Number of time steps to simulate.
        dt (float): Time step size.
        initial_value (float): Initial value of the process.
    Returns:
        numpy.ndarray: Array of simulated values.
    """
    num_dimensions = 1  # We simulate a 1-dimensional process

    # Calculate the number of increments
    num_increments = int(timesteps / dt)

    # Generate random normal increments
    increments = np.random.normal(loc=0, scale=np.sqrt(dt), size=(num_increments, num_dimensions))

    # Calculate the cumulative sum of the increments
    path = np.cumsum(increments, axis=0)

    # Apply the Bessel process transformation
    path = np.sqrt(initial_value**2 + 2 * np.cumsum(path, axis=0))

    return path


def ornstein_uhlenbeck_process(timesteps, dt, mean_reversion, volatility, initial_value):
    """Simulates an Ornstein-Uhlenbeck process.
    Args:
        timesteps (int): Number of time steps to simulate.
        dt (float): Time step size.
        mean_reversion (float): Mean reversion rate.
        volatility (float): Volatility parameter.
        initial_value (float): Initial value of the process.
    Returns:
        numpy.ndarray: Array of simulated values.
    """
    num_dimensions = 1  # We simulate a 1-dimensional process

    # Calculate the number of increments
    num_increments = int(timesteps / dt)

    # Generate random normal increments
    increments = np.random.normal(loc=0, scale=np.sqrt(dt), size=(num_increments, num_dimensions))

    # Calculate the cumulative sum of the increments
    path = np.cumsum(increments, axis=0)

    # Apply the Ornstein-Uhlenbeck process transformation
    path = initial_value + mean_reversion * path + volatility * np.sqrt(dt) * np.random.normal(loc=0, scale=1, size=(num_increments, num_dimensions))

    return path


def cir_process(timesteps, dt, mean_reversion, volatility, long_term_mean, initial_value):
    """Simulates a Cox-Ingersoll-Ross (CIR) process.
    Args:
        timesteps (int): Number of time steps to simulate.
        dt (float): Time step size.
        mean_reversion (float): Mean reversion rate.
        volatility (float): Volatility parameter.
        long_term_mean (float): Long-term mean value of the process.
        initial_value (float): Initial value of the process.
    Returns:
        numpy.ndarray: Array of simulated values.
    """
    num_dimensions = 1  # We simulate a 1-dimensional process

    # Calculate the number of increments
    num_increments = int(timesteps / dt)

    # Generate random normal increments
    increments = np.random.normal(loc=0, scale=np.sqrt(dt), size=(num_increments, num_dimensions))

    # Calculate the cumulative sum of the increments
    path = np.cumsum(increments, axis=0)

    # Apply the CIR process transformation
    path = initial_value + mean_reversion * (long_term_mean - path) * dt + volatility * np.sqrt(np.abs(path) * dt) * np.random.normal(loc=0, scale=1, size=(num_increments, num_dimensions))

    return path


def heston_model(timesteps, dt, initial_price, mean_reversion, long_term_volatility, volatility_of_volatility, correlation, initial_volatility):
    """Simulates a stock price path using the Heston model.
    Args:
        timesteps (int): Number of time steps to simulate.
        dt (float): Time step size.
        initial_price (float): Initial price of the stock.
        mean_reversion (float): Mean reversion rate of the volatility.
        long_term_volatility (float): Long-term volatility of the stock.
        volatility_of_volatility (float): Volatility of the volatility.
        correlation (float): Correlation between the stock and volatility.
        initial_volatility (float): Initial volatility value.
    Returns:
        numpy.ndarray: Array of simulated stock prices.
    """
    num_dimensions = 2  # We simulate a 2-dimensional process (stock price and volatility)

    # Calculate the number of increments
    num_increments = int(timesteps / dt)

    # Generate random normal increments
    increments = np.random.normal(loc=0, scale=np.sqrt(dt), size=(num_increments, num_dimensions))

    # Initialize arrays to store the paths
    stock_path = np.zeros(num_increments + 1)
    volatility_path = np.zeros(num_increments + 1)
    stock_path[0] = initial_price
    volatility_path[0] = initial_volatility

    for i in range(num_increments):
        # Calculate the volatility at time step i
        volatility = volatility_path[i] + mean_reversion * (long_term_volatility - volatility_path[i]) * dt + \
                     volatility_of_volatility * np.sqrt(volatility_path[i]) * increments[i, 1]

        # Calculate the stock price at time step i+1
        stock_path[i+1] = stock_path[i] + correlation * volatility_path[i] * increments[i, 0] + \
                          np.sqrt(1 - correlation**2) * np.sqrt(volatility_path[i]) * increments[i, 1]

        # Update the volatility path
        volatility_path[i+1] = volatility

    return stock_path


def jump_diffusion_model(timesteps, dt, initial_price, mean_return, volatility, jump_intensity, jump_mean, jump_std):
    """Simulates a stock price path using the Jump Diffusion model.
    Args:
        timesteps (int): Number of time steps to simulate.
        dt (float): Time step size.
        initial_price (float): Initial price of the stock.
        mean_return (float): Mean return rate.
        volatility (float): Volatility of the stock.
        jump_intensity (float): Intensity of the jumps.
        jump_mean (float): Mean of the jump sizes.
        jump_std (float): Standard deviation of the jump sizes.
    Returns:
        numpy.ndarray: Array of simulated stock prices.
    """
    num_dimensions = 1  # We simulate a 1-dimensional process

    # Calculate the number of increments
    num_increments = int(timesteps / dt)

    # Generate random normal increments
    increments = np.random.normal(loc=0, scale=np.sqrt(dt), size=(num_increments, num_dimensions))

    # Generate Poisson-distributed jump occurrences
    jump_occurrences = np.random.poisson(lam=jump_intensity * dt, size=num_increments)

    # Initialize array to store the paths
    path = np.zeros(num_increments + 1)
    path[0] = initial_price

    for i in range(num_increments):
        # Calculate the drift component
        drift = mean_return * dt

        # Calculate the diffusion component
        diffusion = volatility * increments[i]

        # Calculate the jump component
        jump = jump_occurrences[i] * np.random.normal(loc=jump_mean, scale=jump_std)

        # Calculate the stock price at time step i+1
        path[i+1] = path[i] + drift + diffusion + jump

    return path


def is_under(src, value, p):
    for i in range(p, -1, -1):
        if src[-i - 1] > value:
            return False
    return True


def is_over(src, value, p):
    for i in range(p, -1, -1):
        if src[-i - 1] < value:
            return False
    return True


def sharpe_ratio(returns, risk_free_rate):
    """
    Calculates the Sharpe ratio given a list of returns.
    Args:
        returns (list or array-like): List of decimal returns.
        risk_free_rate (float): Risk-free rate of return.
    Returns:
        float: Sharpe ratio.
    """
    returns = np.array(returns)  # Convert the list of returns to a NumPy array
    excess_returns = returns - risk_free_rate
    std_dev = np.std(returns)
    sharpe_ratio = np.mean(excess_returns) / std_dev
    return sharpe_ratio