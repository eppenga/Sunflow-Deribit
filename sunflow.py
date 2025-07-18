### Sunflow Cryptobot ###
#
# File that drives it all! 

# Load external libraries
from time import sleep
from pathlib import Path
import asyncio, argparse, importlib, json, pprint, sys, traceback, websockets
import pandas as pd

# Load internal libraries
import database, defs, deribit, optimum, orders, preload, trailing

# Parse command line arguments
parser = argparse.ArgumentParser(description="Run the Sunflow Cryptobot with a specified config.")
parser.add_argument('-c', '--config', default='config.py', help='Specify the config file (with .py extension).')
args = parser.parse_args()

# Resolve config file path
config_path = Path(args.config).resolve()
if not config_path.exists():
    print(f"Config file not found at {config_path}, aborting...\n")
    sys.exit()

# Dynamically load the config module
sys.path.append(str(config_path.parent))
config_module_name = config_path.stem
config = importlib.import_module(config_module_name)


### Initialize variables ###

# Set default values
debug                                = config.debug                                # Debug
symbol                               = config.symbol                               # Symbol bot used for trading
klines                               = {}                                          # Klines for symbol
intervals                            = {}                                          # Klines intervals
intervals[0]                         = 0                                           # Average of all active intervals
intervals[1]                         = config.interval_1                           # Klines timeframe interval 1
intervals[2]                         = config.interval_2                           # Klines timeframe interval 2
intervals[3]                         = config.interval_3                           # Klines timeframe interval 3
limit                                = config.limit                                # Number of klines downloaded, used for calculcating technical indicators
trades                               = {}                                          # Trades for symbol
ticker                               = {}                                          # Ticker data, including lastPrice and time
info                                 = {}                                          # Instrument info on symbol
spot                                 = 0                                           # Spot price, always equal to lastPrice
profit                               = config.profit                               # Minimum profit percentage
depth                                = config.depth                                # Depth in percentages used to calculate market depth from orderbook
multiplier                           = config.multiplier                           # Multiply minimum order quantity by this
prices                               = {}                                          # Last {limit} prices based on ticker
depth_data                           = {}                                          # Depth buy and sell percentage indexed by time

# Optimize profit and trigger price distance
optimizer                            = {}                                          # Profit and trigger price distance optimizer
optimizer['enabled']                 = config.optimizer_enabled                    # Try to optimize the minimum profit and distance percentage
optimizer['spread_enabled']          = config.optimizer_spread                     # If optimizer is active, also optimize spread
optimizer['sides']                   = config.optimizer_sides                      # If optimizer is active, optimize both buy and sell, or only sell
optimizer['method']                  = config.optimizer_method                     # Method used to optimize distance, profit and / or spread
optimizer['profit']                  = config.profit                               # Initial profit percentage when Sunflow started, will never change
optimizer['distance']                = config.distance                             # Initial trigger price distance percentage when Sunflow started, will never change
optimizer['spread']                  = config.spread_distance                      # Initial minimum spread in percentages when Sunflow started, will never change
optimizer['interval']                = config.optimizer_interval                   # Interval used for indicator KPI
optimizer['delta']                   = config.optimizer_delta                      # Delta used for indicator KPI
optimizer['limit_min']               = config.optimizer_limit_min                  # Minimum miliseconds of spot price data
optimizer['limit_max']               = config.optimizer_limit_max                  # Maximum miliseconds of spot price data
optimizer['adj_min']                 = config.optimizer_adj_min                    # Minimum adjustment
optimizer['adj_max']                 = config.optimizer_adj_max                    # Maximum adjustment
optimizer['scaler']                  = config.optimizer_scaler                     # Scales the final optimizer value by multiplying by this value
optimizer['df']                      = pd.DataFrame()                              # Dataframe is empty at start

# Minimum spread between historical buy orders
use_spread                           = {}                                          # Spread
use_spread['enabled']                = config.spread_enabled                       # Use spread as buy trigger
use_spread['distance']               = config.spread_distance                      # Minimum spread in percentages

# Technical indicators
use_indicators                       = {}                                          # Technical indicators
use_indicators['enabled']            = config.indicators_enabled                   # Use technical indicators as buy trigger
use_indicators['minimum']            = config.indicators_minimum                   # Minimum advice value
use_indicators['maximum']            = config.indicators_maximum                   # Maximum advice value

# Orderbook
use_orderbook                        = {}                                          # Orderbook
use_orderbook['enabled']             = config.orderbook_enabled                    # Use orderbook as buy trigger
use_orderbook['minimum']             = config.orderbook_minimum                    # Minimum orderbook buy percentage
use_orderbook['maximum']             = config.orderbook_maximum                    # Maximum orderbook buy percentage
use_orderbook['average']             = config.orderbook_average                    # Average out orderbook depth data or use last data point
use_orderbook['limit']               = config.orderbook_limit                      # Number of orderbook data elements to keep in database
use_orderbook['timeframe']           = config.orderbook_timeframe                  # Timeframe for averaging out

# Trade
use_trade                            = {}
use_trade['enabled']                 = config.trade_enabled                        # Use realtime trades as buy trigger
use_trade['minimum']                 = config.trade_minimum                        # Minimum trade buy ratio percentage
use_trade['maximum']                 = config.trade_maximum                        # Maximum trade buy ratio percentage
use_trade['limit']                   = config.trade_limit                          # Number of trade orders to keep in database
use_trade['timeframe']               = config.trade_timeframe                      # Timeframe in ms to collect realtime trades

# Price limits
use_pricelimit                       = {}                                          # Use pricelimits to prevent buy or sell
use_pricelimit['enabled']            = config.pricelimit_enabled                   # Set pricelimits functionality
use_pricelimit['max_buy_enabled']    = False                                       # Set pricelimits maximum buy price toggle  
use_pricelimit['min_sell_enabled']   = False                                       # Set pricelimits minimum sell price toggle
use_pricelimit['max_sell_enabled']   = False                                       # Set pricelimits maximum sell price toggle
use_pricelimit['max_buy']            = config.pricelimit_max_buy                   # Maximum buy price 
use_pricelimit['min_sell']           = config.pricelimit_min_sell                  # Minimum sell price
use_pricelimit['max_sell']           = config.pricelimit_max_sell                  # Maximum sell price
if config.pricelimit_max_buy > 0     : use_pricelimit['max_buy_enabled'] = True    # Maximum buy price enabled
if config.pricelimit_min_sell > 0    : use_pricelimit['min_sell_enabled'] = True   # Minimum sell price enabled
if config.pricelimit_max_sell > 0    : use_pricelimit['max_sell_enabled'] = True   # Maximum sell price enabled

# Trailing order
active_order                         = {}                                          # Trailing order data
active_order['side']                 = ""                                          # Trailing Buy or Sell
active_order['active']               = False                                       # Trailing order active or not
active_order['start']                = 0                                           # Start price when trailing order began     
active_order['previous']             = 0                                           # Previous price
active_order['current']              = 0                                           # Current price
active_order['wiggle']               = config.wiggle                               # Method to use to calculate trigger price distance
active_order['distance']             = config.distance                             # Trigger price distance percentage when set to default
active_order['distance_ini']         = config.distance                             # Keep initial distance always stored
active_order['fluctuation']          = config.distance                             # Trigger price distance percentage when set to wiggle
active_order['wave']                 = config.distance                             # Trigger price distance percentage when set to wave
active_order['orderid']              = 0                                           # Order ID
active_order['linkid']               = 0                                           # Link ID (label)
active_order['trigger']              = 0                                           # Trigger price for order
active_order['trigger_new']          = 0                                           # New trigger price when trailing 
active_order['trigger_ini']          = 0                                           # Initial trigger price when trailing
active_order['qty']                  = 0                                           # Order quantity
active_order['qty_new']              = 0                                           # New order quantity when trailing

# Databases for buy and sell orders
all_buys                             = {}                                          # All buys retreived from database file buy orders
all_sells                            = {}                                          # Sell order linked to database with all buys orders

# Websockets to use
ws_kline                             = False                                       # Initialize ws_kline
ws_orderbook                         = False                                       # Initialize ws_orderbook
ws_trade                             = False                                       # Initialize ws_trade
if config.indicators_enabled         : ws_kline     = True                         # Use klines websocket
if config.orderbook_enabled          : ws_orderbook = True                         # Use orderbook websocket
if config.trade_enabled              : ws_trade     = True                         # Use trade websocker

# Initialize indicator advice variable
if not config.indicators_enabled:
    intervals[1] = 0
    intervals[2] = 0
    intervals[3] = 0

# Initialize indicators advice variable
indicators_advice                    = {}
indicators_advice[intervals[0]]      = {'result': False, 'value': 0, 'level': 'Neutral', 'filled': False}   # Average advice of all active intervals
indicators_advice[intervals[1]]      = {'result': False, 'value': 0, 'level': 'Neutral', 'filled': False}   # Advice for interval 1
indicators_advice[intervals[2]]      = {'result': False, 'value': 0, 'level': 'Neutral', 'filled': False}   # Advice for interval 2
indicators_advice[intervals[3]]      = {'result': False, 'value': 0, 'level': 'Neutral', 'filled': False}   # Advice for interval 3

# Initialize orderbook advice variable
orderbook_advice                     = {}
orderbook_advice['buy_perc']         = 0
orderbook_advice['sell_perc']        = 0
orderbook_advice['result']           = False

# Initialize trade advice variable
trade_advice                         = {}
trade_advice['buy_ratio']            = 0
trade_advice['sell_ratio']           = 0
trade_advice['result']               = False

# Initialize pricelimit advice variable
pricelimit_advice                    = {}
pricelimit_advice['buy_result']      = False
pricelimit_advice['sell_result']     = False

# Initialize trades variable
trades                               = {'time': [], 'side': [], 'size': [], 'price': []}

# Initialize depth variable
depth_data                           = {'time': [], 'buy_perc': [], 'sell_perc': []}

# Compounding
compounding                          = {}
compounding['enabled']               = config.compounding_enabled
compounding['start']                 = config.compounding_start
compounding['now']                   = config.compounding_start

# Locking handle_ticker function to prevent race conditions
lock_ticker                          = {}
lock_ticker['time']                  = defs.now_utc()[4]
lock_ticker['delay']                 = 5000
lock_ticker['enabled']               = False

# Uptime ping
uptime_ping                          = {}
uptime_ping['time']                  = defs.now_utc()[4]
uptime_ping['record']                = defs.now_utc()[4]
uptime_ping['delay']                 = 10000
uptime_ping['expire']                = 1000000
uptime_ping['enabled']               = True

# Periodic tasks
periodic                             = {}
periodic['time']                     = defs.now_utc()[4]
periodic['delay']                    = 3600000
periodic['enabled']                  = True

# Channel handlers
channel_handlers                     = {}


### Functions ###

# Handle messages to keep tickers up to date
def handle_ticker(message):
    
    # Debug and speed
    debug = False
    speed = False
    stime = defs.now_utc()[4]
       
    # Errors are not reported within websocket
    try:
   
        # Declare some variables global
        global spot, ticker, profit, active_order, all_buys, all_sells, prices, indicators_advice, lock_ticker, use_spread, optimizer, compounding, uptime_ping, info

        # Initialize variables
        ticker              = {}
        result              = ()
        current_time        = defs.now_utc()[4]
        lock_ticker['time'] = current_time
        
        # Decoded message and get latest ticker
        ticker['time']      = int(message['params']['data']['timestamp'])
        ticker['lastPrice'] = float(message['params']['data']['price'])
        ticker['lastPrice'] = defs.round_number(ticker['lastPrice'], info['tickSize'])   # Deribit does not deliver prices occording to tickSize via websocket!

        # Popup new price
        prices['time'].append(ticker['time'])
        prices['price'].append(ticker['lastPrice'])
        
        # Remove last price if necessary
        if current_time - prices['time'][0] > optimizer['limit_max']:
            prices['time'].pop(0)
            prices['price'].pop(0)

        # Show incoming message
        if debug: defs.announce(f"*** Incoming ticker with price {ticker['lastPrice']} {info['baseCoin']}, simulated = {ticker['simulated']} ***")

        # Prevent race conditions
        if lock_ticker['enabled']:
            spot = ticker['lastPrice']
            defs.announce("Function is busy, Sunflow will catch up with next tick")
            if speed: defs.announce(defs.report_exec(stime, "function busy"))
            return
        
        # Lock handle_ticker function
        lock_ticker['enabled'] = True

        # Run trailing if active
        if active_order['active']:
            active_order['current'] = ticker['lastPrice']
            result       = trailing.trail(symbol, ticker['lastPrice'], compounding, active_order, info, all_buys, all_sells, prices)
            active_order = result[0]
            all_buys     = result[1]
            compounding  = result[2]
            info         = result[3]
         
        # Has price changed, then run all kinds of actions
        if spot != ticker['lastPrice']:

            # Store new spot price
            new_spot = ticker['lastPrice']

            # Optimize profit and distance percentages
            if optimizer['enabled']:
                result       = optimum.optimize(prices, profit, active_order, use_spread, optimizer)
                profit       = result[0]
                active_order = result[1]
                use_spread   = result[2]
                optimizer    = result[3]

            # Check if and how much we can sell
            result                  = orders.check_sell(new_spot, profit, active_order, all_buys, use_pricelimit, pricelimit_advice, info)
            all_sells_new           = result[0]
            active_order['qty_new'] = result[1]
            can_sell                = result[2]
            rise_to                 = result[3]

            # Reset uptime notice
            uptime_ping['time']   = current_time
            uptime_ping['record'] = current_time            

            # Output to stdout "Price went up/down from ..."
            message = defs.report_ticker(spot, new_spot, rise_to, active_order, all_buys, info)
            defs.announce(message)
            
            # If trailing buy is already running while we can sell
            if active_order['active'] and active_order['side'] == "Buy" and can_sell:
                
                # Output to stdout and Apprise
                defs.announce("*** Warning: Buying while selling is possible, trying to cancel buy order! ***", True, 1)
                
                # Cancel trailing buy, remove from all_buys database
                active_order['active'] = False
                result                 = orders.cancel(symbol, active_order['orderid'], active_order['linkid'])
                error_code             = result[0]
                
                if error_code == 0:
                    # Situation normal, just remove the order
                    defs.announce("Buy order cancelled successfully", True, 1)
                    all_buys = database.remove(active_order['orderid'], all_buys, info)

                if error_code == 1:
                    # Trailing buy was bought
                    defs.announce("Buy order could not be cancelled, closing trailing buy", True, 1)
                    result       = trailing.close_trail(active_order, all_buys, all_sells, spot, info)
                    active_order = result[0]
                    all_buys     = result[1]
                    all_sells    = result[2]
                    
                if error_code == 100:
                    # Something went very wrong
                    defs.log_error(result[1])
                
            # Initiate sell
            if not active_order['active'] and can_sell:
                # There is no old quantity on first sell
                active_order['qty'] = active_order['qty_new']
                # Fill all_sells for the first time
                all_sells = all_sells_new                
                # Place the first sell order
                active_order = orders.sell(symbol, new_spot, active_order, prices, info)
              
            # Amend existing sell trailing order if required
            if active_order['active'] and active_order['side'] == "Sell":

                # Only amend order if the quantity to be sold has changed
                if active_order['qty_new'] != active_order['qty'] and active_order['qty_new'] > 0:

                    # Amend order quantity
                    result        = trailing.aqs_helper(symbol, active_order, info, all_sells, all_sells_new)
                    active_order  = result[0]
                    all_sells     = result[1]
                    all_sells_new = result[2]

            # Work as a true gridbot when only spread is used
            if use_spread['enabled'] and not use_indicators['enabled'] and not active_order['active']:
                active_order = buy_matrix(new_spot, active_order, all_buys, intervals[1])

    # Report error
    except Exception as e:
        tb_info = traceback.extract_tb(e.__traceback__)
        frame_summary = tb_info[-1]
        filename = frame_summary.filename
        line = frame_summary.lineno
        defs.announce(f"*** Warning: Exception in {filename} on line {line}: {e} ***")

    # Always set new spot price and unlock function
    spot = ticker['lastPrice']
    lock_ticker['enabled'] = False
    
    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))
    
    # Close function
    return

def handle_kline_1(message):
    handle_kline(message, intervals[1])
    return

def handle_kline_2(message):
    handle_kline(message, intervals[2])
    return

def handle_kline_3(message):
    handle_kline(message, intervals[3])
    return

# Handle messages to keep klines up to date
def handle_kline(message, interval):

    # Debug and speed
    debug = False
    speed = False
    stime = defs.now_utc()[4]

    # Errors are not reported within websocket
    try:

        # Declare some variables global
        global klines, active_order, all_buys, indicators_advice

        # Initialize variables
        kline = {}
     
        # Show incoming message
        if debug: defs.announce(f"*** Incoming kline with interval {interval}m ***")

        # Decode message and get latest kline
        kline['time']     =   int(message['params']['data']['tick'])
        kline['open']     = float(message['params']['data']['open'])
        kline['high']     = float(message['params']['data']['high'])
        kline['low']      = float(message['params']['data']['low'])
        kline['close']    = float(message['params']['data']['close'])
        kline['volume']   = float(message['params']['data']['volume'])
        kline['turnover'] = float(message['params']['data']['cost'])

        # Check if the number of klines and add in
        klines_count = len(klines[interval]['close'])
        if klines_count != limit:
            klines[interval] = preload.get_klines(symbol, interval, limit)
        klines[interval] = defs.add_kline(kline, klines[interval])
        defs.announce(f"Added {interval}m interval onto existing {klines_count} klines")
        
        # Run buy matrix
        active_order = buy_matrix(spot, active_order, all_buys, interval)

    # Report error
    except Exception as e:
        tb_info = traceback.extract_tb(e.__traceback__)
        frame_summary = tb_info[-1]
        filename = frame_summary.filename
        line = frame_summary.lineno
        defs.announce(f"*** Warning: Exception in {filename} on line {line}: {e} ***")

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))
    
    # Close function
    return

# Handle messages to keep orderbook up to date
def handle_orderbook(message):
    
    # To be implemented for Deribit
    pass
    return
    
    # Debug and speed
    debug_1 = False    # Show orderbook
    debug_2 = False    # Show buy and sell depth percentages
    speed   = False
    stime   = defs.now_utc()[4]

    # Errors are not reported within websocket
    try:

        # Declare some variables global
        global orderbook_advice, depth_data
        
        # Initialize variables
        total_buy_within_depth  = 0
        total_sell_within_depth = 0
          
        # Show incoming message
        if debug: defs.announce("*** Incoming orderbook ***")
        
        # Recalculate depth to numerical value
        depthN = ((2 * depth) / 100) * spot
        
        # Extracting bid (buy) and ask (sell) arrays
        bids = message['data']['b']
        asks = message['data']['a']

        # Calculate total buy quantity within depth
        for bid in bids:
            price, quantity = float(bid[0]), float(bid[1])
            if (spot - depthN) <= price <= spot:
                total_buy_within_depth += quantity

        # Calculate total sell quantity within depth
        for ask in asks:
            price, quantity = float(ask[0]), float(ask[1])
            if spot <= price <= (spot + depthN):
                total_sell_within_depth += quantity

        # Calculate total quantity (buy + sell)
        total_quantity_within_depth = total_buy_within_depth + total_sell_within_depth

        # Calculate percentages
        buy_percentage  = (total_buy_within_depth / total_quantity_within_depth) * 100 if total_quantity_within_depth > 0 else 0
        sell_percentage = (total_sell_within_depth / total_quantity_within_depth) * 100 if total_quantity_within_depth > 0 else 0

        # Output the stdout
        if debug_1:        
            defs.announce("Orderbook")
            print(f"Spot price        : {spot}")
            print(f"Lower depth       : {spot - depth}")
            print(f"Upper depth       : {spot + depth}\n")

            print(f"Total Buy quantity : {total_buy_within_depth}")
            print(f"Total Sell quantity: {total_sell_within_depth}")
            print(f"Total quantity     : {total_quantity_within_depth}\n")

            print(f"Buy within depth  : {buy_percentage:.2f} %")
            print(f"Sell within depth : {sell_percentage:.2f} %")

        # Announce message only if it changed and debug
        if debug_2:
            if (buy_percentage != orderbook_advice['buy_perc']) or (sell_percentage != orderbook_advice['sell_perc']):
                message = f"Orderbook information (Buy / Sell | Depth): {buy_percentage:.2f} % / {sell_percentage:.2f} % | {depth} % "
                defs.announce(message)
        
        # Popup new depth data
        depth_data['time'].append(defs.now_utc()[4])
        depth_data['buy_perc'].append(buy_percentage)
        depth_data['sell_perc'].append(sell_percentage)
        if len(depth_data['time']) > use_orderbook['limit']:
            depth_data['time'].pop(0)
            depth_data['buy_perc'].pop(0)        
            depth_data['sell_perc'].pop(0)

        # Get average buy and sell percentage for timeframe
        new_buy_percentage  = buy_percentage
        new_sell_percentage = sell_percentage
        if use_orderbook['average']:
            result              = defs.average_depth(depth_data, use_orderbook, buy_percentage, sell_percentage)
            new_buy_percentage  = result[0]
            new_sell_percentage = result[1]
        
        # Set orderbook_advice
        orderbook_advice['buy_perc']  = new_buy_percentage
        orderbook_advice['sell_perc'] = new_sell_percentage

    # Report error
    except Exception as e:
        tb_info = traceback.extract_tb(e.__traceback__)
        frame_summary = tb_info[-1]
        filename = frame_summary.filename
        line = frame_summary.lineno
        defs.announce(f"*** Warning: Exception in {filename} on line {line}: {e} ***")
    
    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Close function
    return

# Handle messages to keep trades up to date
def handle_trade(message):

    # To be implemented for Deribit
    pass
    return
    
    # Debug
    debug_1 = False   # Show incoming trade
    debug_2 = False   # Show datapoints
    speed   = False
    stime   = defs.now_utc()[4]
   
    # Errors are not reported within websocket
    try:

        # Declare some variables global
        global trade_advice, trades
        
        # Initialize variables
        result     = ()
        datapoints = {}
        compare    = {'time': [], 'side': [], 'size': [], 'price': []}

        # Show incoming message
        if debug_1: 
            defs.announce("*** Incoming trade ***")
            print(f"{message}\n")
                        
        # Combine the trades
        for trade in message['data']:
            trades['time'].append(trade['T'])      # T: Timestamp
            trades['side'].append(trade['S'])      # S: Side
            trades['size'].append(trade['v'])      # v: Trade size
            trades['price'].append(trade['p'])     # p: Trade price
    
        # Limit number of trades
        if len(trades['time']) > use_trade['limit']:
            trades['time']  = trades['time'][-use_trade['limit']:]
            trades['side']  = trades['side'][-use_trade['limit']:]
            trades['size']  = trades['size'][-use_trade['limit']:]
            trades['price'] = trades['price'][-use_trade['limit']:]
    
        # Number of trades to use for timeframe
        number = defs.get_index_number(trades, use_trade['timeframe'], use_trade['limit'])
        compare['time']  = trades['time'][-number:]
        compare['side']  = trades['side'][-number:]
        compare['size']  = trades['size'][-number:]
        compare['price'] = trades['price'][-number:]        
    
        # Get trade_advice
        result = defs.calculate_total_values(compare)        
        trade_advice['buy_ratio']  = result[3]
        trade_advice['sell_ratio'] = result[4]
        
        # Validate data
        datapoints['trade']   = len(trades['time'])
        datapoints['compare'] = len(compare['time'])
        datapoints['limit']   = use_trade['limit']
        if (datapoints['compare'] >= datapoints['trade']) and (datapoints['trade'] >= datapoints['limit']):
            defs.announce("*** Warning: Increase trade_limit variable in config file! ***", True, 1)
        
        # Debug
        if debug_2:
            message = f"There are {datapoints['trade']} / {datapoints['limit']} data points, "
            message = message + f"using the last {datapoints['compare']} points and "
            message = message + f"buy ratio is {trade_advice['buy_ratio']:.2f} %"
            defs.announce(message)
    
    # Report error
    except Exception as e:
        tb_info = traceback.extract_tb(e.__traceback__)
        frame_summary = tb_info[-1]
        filename = frame_summary.filename
        line = frame_summary.lineno
        defs.announce(f"*** Error: Failure in {filename} on line {line}: {e} ***")
       
    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Close function
    return

# Check if we can buy the based on signals
def buy_matrix(spot, active_order, all_buys, interval):

    # Declare some variables global
    global indicators_advice, orderbook_advice, trade_advice, pricelimit_advice, info
    
    # Initialize variables
    can_buy       = False
    spread_advice = {}
    result        = ()
    speed         = False
    stime         = defs.now_utc()[4]
              
    # Only initiate buy and do complex calculations when not already trailing
    if not active_order['active']:
        
        # Get buy advice
        result            = defs.advice_buy(indicators_advice, orderbook_advice, trade_advice, pricelimit_advice, use_indicators, use_spread, use_orderbook, use_trade, use_pricelimit, spot, klines, all_buys, interval)
        indicators_advice = result[0]
        spread_advice     = result[1]
        orderbook_advice  = result[2]
        trade_advice      = result[3]
        pricelimit_advice = result[4]
                    
        # Get buy decission and report
        result            = defs.decide_buy(indicators_advice, use_indicators, spread_advice, use_spread, orderbook_advice, use_orderbook, trade_advice, use_trade, pricelimit_advice, use_pricelimit, interval, intervals, info)
        can_buy           = result[0]
        message           = result[1]
        indicators_advice = result[2]
        defs.announce(message)

        # Determine distance of trigger price and execute buy decission
        if can_buy:
            result       = orders.buy(symbol, spot, compounding, active_order, all_buys, prices, info)
            active_order = result[0]
            all_buys     = result[1]
            info         = result[2]
    
    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return active_order
    return active_order

# Prechecks to see if we can start sunflow
def prechecks():
    
    # Declare some variables global
    global symbol
    
    # Initialize variables
    goahead = True
    
    # Do checks
    if intervals[3] != 0 and intervals[2] == 0:
        goahead = False
        defs.announce("Interval 2 must be set if you use interval 3 for confirmation!")
        
    if not use_spread['enabled'] and not use_indicators['enabled']:
        goahead = False
        defs.announce("Need at least either Technical Indicators enabled or Spread to determine buy action!")
    
    if compounding['enabled'] and not config.wallet_report:
        goahead = False
        defs.announce("When compounding set wallet_report to True to use compounding!")
    
    # Return result
    return goahead


### Start main program ###

## Check if we can start
if not prechecks():
    defs.announce("*** NO START ***", True, 1)
    exit()


## Display welcome screen
print("\n*************************")
print("*** Sunflow Cryptobot ***")
print("*************************\n")
print(f"Symbol    : {symbol}")
if use_indicators['enabled']:
    print(f"Interval 1: {intervals[1]}m")
    print(f"Interval 2: {intervals[2]}m")
    print(f"Interval 3: {intervals[3]}m")
if use_spread['enabled']:
    print(f"Spread    : {use_spread['distance']} %")
print(f"Profit    : {profit} %")
print(f"Limit     : {limit}\n")


## Preload all requirements
print("\n*** Preloading ***\n")
preload.check_files()
if intervals[1] !=0  : klines[intervals[1]] = preload.get_klines(symbol, intervals[1], limit)
if intervals[2] !=0  : klines[intervals[2]] = preload.get_klines(symbol, intervals[2], limit)
if intervals[3] !=0  : klines[intervals[3]] = preload.get_klines(symbol, intervals[3], limit)
ticker               = preload.get_ticker(symbol)
spot                 = ticker['lastPrice']
info                 = preload.get_info(symbol, spot, multiplier, compounding)
deribit.authenticate()
all_buys             = database.load(config.dbase_file, info)
all_buys             = preload.check_orders(all_buys, info)
prices               = preload.get_prices(symbol, 1, 1000)

# Preload optimizer and load prices
if optimizer['enabled']:

    # Get historical prices and combine with current prices
    prices_old   = preload.get_prices(symbol, optimizer['interval'], 1000)
    prices       = preload.combine_prices(prices_old, prices)
    
    # Calulcate optimized data
    result       = optimum.optimize(prices, profit, active_order, use_spread, optimizer)
    profit       = result[0]
    active_order = result[1]
    use_spread   = result[2]
    optimizer    = result[3]

# Preload database inconsistencies
if config.database_rebalance:
    all_buys = orders.rebalance(all_buys, info)

# Preload wallet, quote and base currency to stdout
if config.wallet_report:
    wallet_data        = orders.report_wallet(spot, all_buys, info)
    compounding['now'] = wallet_data[0]

# Preload compounding
if compounding['enabled']:
    info = defs.calc_compounding(info, spot, compounding)


## TESTS ##
print("\n*** Preloading report ***")

print("\n** Ticker **")
print(f"Symbol    : {ticker['symbol']}")
print(f"Last price: {ticker['lastPrice']} {info['quoteCoin']}")
print(f"Updated   : {ticker['time']} ms")

print("\n** Spot **")
print(f"Spot price: {spot} {info['quoteCoin']}")

print("\n** Info **")
print("Instrument information:")
pprint.pprint(info)

#print("\n** Klines **")
#pprint.pprint(klines)

print("\n** Deribit **")
print(f"Authentication successful, expiration at Unix epoch {config.token_expiration} ms")
if config.wallet_report:
    print("\n** Wallet **")
    print(f"Total bot value : {wallet_data[0]} {info['quoteCoin']}")
    print(f"Quote (exchange): {wallet_data[2]} {info['quoteCoin']}")
    print(f"Base (exchange) : {wallet_data[1]} {info['baseCoin']}")
    print(f"Base (database) : {wallet_data[3]} {info['baseCoin']}")
    print(f"Out of sync     : {wallet_data[4]} {info['baseCoin']}")

#exit()


## Announce start
print("\n*** Starting ***\n")
if config.timeutc_std:
    time_output = defs.now_utc()[0] + " UTC time"
else:
    time_output = defs.now_utc()[5] + " " + config.timezone_str + " time"
defs.announce(f"Sunflow started at {time_output}", True, 1)


### Periodic tasks ###

# Run tasks periodically
def periodic_tasks(current_time):
    
    # Debug
    debug = False
    
    # Pass
    pass
    
    # Return
    return

# Run tasks periodically
def ping_message(current_time):
    
    # Debug
    debug = False

    # Initialize variables
    expire        = uptime_ping['expire']
    delay_ping    = current_time - uptime_ping['time']
    delay_tickers = current_time - uptime_ping['record']
    
    # Check for to little action
    if delay_tickers > expire:
        message = f"*** Error S0015: Ping, last ticker update of {delay_tickers} ms ago is larger than {expire} ms maximum! ***"
        defs.log_error(message)

    # Output to stdout
    if uptime_ping['enabled']:
        if delay_ping == delay_tickers:
            defs.announce(f"Ping, {delay_ping} ms since last message and ticker update")
        else:
            defs.announce(f"Ping, {delay_ping} ms since last message and last ticker update was {delay_tickers} ms ago")
    
    # Return
    return

### Websockets ###

# Create subscription message based on intervals
def create_subscription_message(symbol, intervals):
       
    # Define channels
    channels = ["deribit_price_index." + symbol.lower()]
    channel_handlers["deribit_price_index." + symbol.lower()] = handle_ticker
    
    if intervals[1] != 0:
        channels.append(f"chart.trades.{symbol.upper()}.{intervals[1]}")
        channel_handlers[f"chart.trades.{symbol.upper()}.{intervals[1]}"] = handle_kline_1
    
    if intervals[2] != 0:
        channels.append(f"chart.trades.{symbol.upper()}.{intervals[2]}")
        channel_handlers[f"chart.trades.{symbol.upper()}.{intervals[2]}"] = handle_kline_2

    if intervals[3] != 0:
        channels.append(f"chart.trades.{symbol.upper()}.{intervals[3]}")
        channel_handlers[f"chart.trades.{symbol.upper()}.{intervals[3]}"] = handle_kline_3
  
    subscription_message = {
        "jsonrpc": "2.0",
        "id": 3600,
        "method": "public/subscribe",
        "params": {
            "channels": channels
        }
    }
    
    # Create subscription message
    return subscription_message

# Connect to websocket
async def connect_websocket():
    while not defs.halt_sunflow:
        try:
            websocket = await websockets.connect(config.api_ws)
            defs.announce("Connected to exchange websocket")
            return websocket
        except Exception as e:
            message = f"*** Error S0003: Exchange websocket error ***\n>>> Message: {e}"
            defs.log_error(message)            
            defs.announce("Reconnecting to exchange in 5 seconds...")
            await asyncio.sleep(5)

# Heartbeat
async def send_heartbeat(websocket, interval=30):
    while websocket.open and not defs.halt_sunflow:
        try:
            await websocket.ping()
            defs.announce("Websocket heartbeat sent to exchange")
        except Exception as e:
            message = f"*** Warning S0004: Warning sending heartbeat to exchange ***\n>>> Message: {e}"
            defs.log_error(message)
            break
        await asyncio.sleep(interval)

# Simulated ticker
def simulated_ticker():
    
    # Create message
    message = {
        'params': {
            'data': {
                'timestamp': defs.now_utc()[4],
                'price': str(spot),
                'simulated': True
            }
        }
    }
    
    # Return ticker message
    return message

# Call API
async def call_api(symbol, intervals):
    while not defs.halt_sunflow:
        websocket = await connect_websocket()
        if websocket and not defs.halt_sunflow:

            # Create subscription message
            subscription_message = create_subscription_message(symbol, intervals)

            # Subscribe to all channels
            await websocket.send(json.dumps(subscription_message))
            defs.announce(f"Subscribed to channels: {', '.join(subscription_message['params']['channels'])}")
            
            # Send heartbeat
            asyncio.create_task(send_heartbeat(websocket))
            
            # Get data from exchange
            while websocket.open and not defs.halt_sunflow:
                try:
                    current_time = defs.now_utc()[4]
                    #simulated    = simulated_ticker()      # *** CHECK *** How to fix simulated tickers??
                    
                    # Uptime ping
                    if current_time - uptime_ping['time'] > uptime_ping['delay']:
                        ping_message(current_time)
                        uptime_ping['time'] = current_time

                    # Periodic tasks
                    if current_time - periodic['time'] > periodic['delay']:
                        periodic_tasks(current_time)
                        periodic['time'] = current_time

                    # Get response                    
                    response      = await websocket.recv()
                    response_data = json.loads(response)
                    channel       = response_data.get('params', {}).get('channel')

                    # Dispatch to appropriate handler based on channel
                    if channel and channel in channel_handlers:
                        channel_handlers[channel](response_data)
                    else:
                        defs.announce(f"Unhandled message from channel {channel}, this might occur at start")

                # Reconnect on connection close
                except websockets.exceptions.ConnectionClosed as e:
                    message = f"*** Warning S0005: Exchange websocket connection closed ***\n>>> Message: {e}"
                    defs.log_error(message)
                    break
                
                # Reconnect on anything else
                except Exception as e:
                    message = f"*** Error S0006: Exchange websocket error ***\n>>> Message: {e}"
                    defs.log_error(message)
                    break

        # Wait before reconnecting
        defs.announce("Reconnecting to exchange in 5 seconds...")
        await asyncio.sleep(5)

# Run continuously
if __name__ == "__main__" and not defs.halt_sunflow:
    async def main():
        await call_api(symbol, intervals)

    # Execute main
    asyncio.run(main())


### Say goodbye ###
if config.timeutc_std:
    time_output = defs.now_utc()[0] + " UTC time"
else:
    time_output = defs.now_utc()[5] + " " + config.timezone_str + " time"
defs.announce(f"*** Sunflow terminated at {time_output} ***", True, 1)
