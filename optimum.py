### Sunflow Cryptobot ###
#
# Find optimal trigger price distance and profit percentage

# Load external libraries
import math, pandas as pd, pprint

# Load internal libraries
from loader import load_config
import defs

# Load config
config = load_config()

# Resample and create dataframe for optimizer
def resample_optimzer(prices, interval):

    # Debug
    debug = False
  
    # Convert the time and price data into a DataFrame
    df = pd.DataFrame(prices)
    
    # Convert the 'time' column to datetime format
    df['time'] = pd.to_datetime(df['time'], unit='ms')
    
    # Set the 'time' column as the index
    df.set_index('time', inplace=True)
    
    # Resample the data to the specified interval
    df_resampled = df['price'].resample(interval).last()
    
    # Drop any NaN values that may result from resampling
    df_resampled.dropna(inplace=True)

    # Remove the last row
    df_resampled = df_resampled.iloc[:-1]

    # Debug to stdout
    if debug:
        defs.announce("Debug: Resampled dataframe:")
        pprint.pprint(df_resampled)
        print()

    # Return dataframe
    return df_resampled

# Rebuild dataframe in two steps for speed reasons. First part is kept in cache, then we add the last one or two intervals. 
def build_df(optimizer, prices, interval):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]

    # Resample and create dataframe for the first time or get it from cache
    if optimizer['df'].empty:
        df = resample_optimzer(prices, interval)
    else:
        df = optimizer['df']
    
    # Get the timestamp of the last item in the dataframe in miliseconds
    last_timestamp = int(df.index[-1].timestamp() * 1000)
    
    # Which prices are not yet in the resampled data since last timestamp of dataframe
    prices_new = {
        'price': [price for price, time in zip(prices['price'], prices['time']) if time > last_timestamp],
        'time': [time for time in prices['time'] if time > last_timestamp]
    }

    # Create a dataframe from the new prices
    df_new         = pd.DataFrame(prices_new)
    df_new['time'] = pd.to_datetime(df_new['time'], unit='ms')
    df_new.set_index('time', inplace=True)

    # Debug to stdout
    if debug:
        defs.announce("Debug: Dataframes to be concatenated, first dataframe:")
        print(df)
        print()
        defs.announce("Debug: Dataframes to be concatenated, second dataframe:")        
        print(df_new)
        print()

    # Concatenate the cached and new dataframes
    df = pd.concat([df, df_new])

    # Resample again and drop empty rows
    df = df['price'].resample(interval).last()
    df.dropna(inplace=True)
    
    # Debug to stdout
    if debug:
        defs.announce("Debug: Concatenated dataframe:")
        print(df)
        print()

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))
    
    # Return dataframe
    return df

# Optimize based on volatility
def calc_volatility(optimizer, df, prices, distance, spread, profit, length=10):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]

    # Global error counter
    global df_errors, halt_sunflow
    
    # Initialize variables
    df_errors    = 0
    distance_new = distance
    spread_new   = spread
    profit_new   = profit
    success      = False
    
    try:
        # Debug
        if debug:
            defs.announce("Debug: Trying to optimize using volatility")

        # Calculate the log returns
        df = df.to_frame()
        df['log_return'] = df['price'].apply(lambda x: math.log(x)) - df['price'].shift(1).apply(lambda x: math.log(x))
        
        # Calculate the rolling volatility (standard deviation of log returns)
        df['volatility'] = df['log_return'].rolling(window=length).std() * math.sqrt(length)
        
        # Calculate the average volatility
        average_volatility = df['volatility'].mean()
        
        # Add a column for the deviation percentage from the average volatility
        df['volatility_deviation_pct'] = ((df['volatility'] - average_volatility) / average_volatility)
        
        # Drop the 'log_return' column if not needed
        df.drop(columns=['log_return'], inplace=True)
        
        # Debug to stdout
        if debug:
            defs.announce(f"Debug: Raw optimized volatility {df['volatility_deviation_pct'].iloc[-1]:.4f} %")
        
        # Get volatility deviation
        volatility   = df['volatility_deviation_pct'].iloc[-1] * optimizer['scaler']
        vol_stored   = volatility
        volatility   = min(volatility, optimizer['adj_max'] / 100)
        volatility   = max(volatility, optimizer['adj_min'] / 100)

        # Set new profit and trigger price distance
        profit_new   = profit * (1 + volatility)
        distance_new = (distance / profit) * profit_new
        
        # Set new spread distance
        if optimizer['spread_enabled']:
            spread_new = spread * (1 + volatility)

        # Debug to stdout
        if debug:
            defs.announce("Debug: Optimized full dataframe:")
            print(df)
            print()
            defs.announce(f"Age of database is: {stime - prices['time'][0]} ms")
            
        # Store the dataframe for future use, except for the last row
        optimizer['df'] = df.iloc[:-1]
        
    # In case of failure
    except Exception as e:
        
        # Count the errors and log
        df_errors  = df_errors + 1
        message = f"*** Error: Optimize failed: {e} ***"
        defs.log_error(message)
        
        # After three consecutive errors halt
        if df_errors > 2:
            halt_sunflow = True
        if speed: defs.announce(defs.report_exec(stime, "early return due to error"))    
        return distance, spread, profit
   
    # Reset error counter
    df_errors = 0
    
    # Report to stdout
    if volatility != 0:
        success = True
        defs.announce(f"Volatility {(volatility * 100):.4f} %, profit {profit_new:.4f} %, trigger price distance {distance_new:.4f} %, spread {spread_new:.4f} %")
    else:
        success = False
        defs.announce(f"Volatility {(vol_stored * 100):.4f} %, not between {(optimizer['adj_min']):.4f} % and {(optimizer['adj_max']):.4f} %")

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))
     
    # Return
    return distance_new, spread_new, profit_new, success
    
# Optimize profit percentage and default trigger price distance based on previous prices
def optimize(prices, profit, active_order, use_spread, optimizer):
       
    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]
    
    # Global error counter
    global df_errors, halt_sunflow
  
    # Initialize variables
    interval     = str(optimizer['interval']) + optimizer['delta']   # Interval used for indicator KPI (in our case historical volatility)
    distance     = optimizer['distance']    # Initial distance
    distance_new = optimizer['distance']    # New distance to be
    spread       = optimizer['spread']      # Initial spread
    spread_new   = optimizer['spread']      # New spread to be
    profit       = optimizer['profit']      # Initial profit
    profit_new   = optimizer['profit']      # New profit to be
    success      = False                    # Optimize possible

    # Optimize only on desired sides
    if active_order['side'] not in optimizer['sides']:
        defs.announce(f"Optimization not executed, active side {active_order['side']} is not in {optimizer['sides']}")
        if speed: defs.announce(defs.report_exec(stime, "early return to optimizaton issue"))
        return profit, active_order, use_spread, optimizer
    
    # Check if we can optimize
    if stime - prices['time'][0] < optimizer['limit_min']:
        defs.announce(f"Optimization not possible yet, missing {stime - prices['time'][0]} ms of price data")
        if speed: defs.announce(defs.report_exec(stime, "early return due to optimizaton issue"))
        return profit, active_order, use_spread, optimizer

    # Get the most recent dataframe
    df = build_df(optimizer, prices, interval)

    # Method used for optimization
    if optimizer['method'] == "Volatility":
        
        # Optimize based on volatility:
        result       = calc_volatility(optimizer, df, prices, distance, spread, profit, 10)
        distance_new = result[0]
        spread_new   = result[1]
        profit_temp  = result[2]
        success      = result[3]

    # Rework variables
    use_spread['distance']   = spread_new
    active_order['distance'] = distance_new
    profit_new               = profit_temp
    
    # Output to stdout
    if success:
        defs.announce(f"Spread: {spread:.4f} / {spread_new:.4f}, distance: {distance:.4f} / {distance_new:.4f}, profit: {profit:.4f} / {profit_new:.4f}")
    else:
        defs.announce("Not able to optimze data!")
        
  
    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return
    return profit_new, active_order, use_spread, optimizer
