### Sunflow Cryptobot ###
#
# Preload ticker, klines, instrument info and other data

# Load external libraries
from loader import load_config
import os, requests, pprint

# Load internal libraries
import database, defs, orders

# Load config
config = load_config()

# Preload ticker
def get_ticker(symbol):

    # Debug
    debug = False

    # Initialize variables
    data   = {}
    ticker = {'time': 0, 'symbol': symbol, 'lastPrice': 0}
   
    # Load ticker via normal session
    message = defs.announce("session: /public/ticker")
    try:
        url    = config.api_url + "/public/ticker"
        params = {
            'instrument_name': str(symbol)
        }
        response = requests.get(url, params=params)
        data     = response.json()
    except Exception as e:
        defs.log_error(e)
  
    # Check API rate limit and log data if possible
    if data:
        data = defs.rate_limit(data)
        defs.log_exchange(data, message)
   
    # Transform ticker into required format
    ticker['time']      = int(data['result']['timestamp'])
    ticker['symbol']    = data['result']['instrument_name']
    ticker['lastPrice'] = float(data['result']['last_price'])
    
    # Output to stdout
    defs.announce(f"Initial ticker price set to {ticker['lastPrice']} {ticker['symbol']} via exchange")
    
    # Debug to stdout
    if debug:
        defs.announce("Debug: Ticker data:")
        pprint.pprint(ticker)
        print()
       
    # Return ticker
    return ticker

# Preload klines
def get_klines(symbol, interval, limit):
   
    # Debug
    debug = False
    
    # Initialize variables
    amount_klines   = 0
    data            = {}
    klines          = {'time': [], 'open': [], 'high': [], 'low': [], 'close': [], 'volume': [], 'turnover': []}
    end_timestamp   = defs.now_utc()[4]
    start_timestamp = end_timestamp - (interval * (limit - 1) * 60 * 1000)

    # Load klines via normal session
    message = defs.announce("session: /public/get_tradingview_chart_data")
    try:
        url    = config.api_url + "/public/get_tradingview_chart_data"
        params = {
            'instrument_name': str(symbol),
            'start_timestamp': int(start_timestamp),
            'end_timestamp'  : int(end_timestamp),
            'resolution'     : str(interval)
        }
              
        response = requests.get(url, params=params)
        data     = response.json()
    except Exception as e:
        defs.log_error(e)

    # Check API rate limit and log data if possible
    if data:
        data = defs.rate_limit(data)
        defs.log_exchange(data, message)
       
    # Transform klines into required format
    for i in range(len(data['result']['ticks'])):
        klines['time'].append(int(data['result']['ticks'][i]))        # Time
        klines['open'].append(float(data['result']['open'][i]))       # Open prices
        klines['high'].append(float(data['result']['high'][i]))       # High prices
        klines['low'].append(float(data['result']['low'][i]))         # Low prices
        klines['close'].append(float(data['result']['close'][i]))     # Close prices
        klines['volume'].append(float(data['result']['volume'][i]))   # Volume
        klines['turnover'].append(float(data['result']['cost'][i]))   # Turnover

    # Check response from exchange
    amount_klines = len(klines['time'])
    if amount_klines != limit:
        defs.announce(f"*** Error: Tried to load {limit} klines, but exchange only provided {amount_klines} ***")
        defs.log_error("Insufficient klines provided by exchange")
      
    # Output to stdout
    defs.announce(f"Initial {limit} klines with {interval}m interval loaded from exchange")
    
    # Debug to stdout
    if debug:
        defs.announce(f"Debug: Prefilled klines with interval {interval}m")
        defs.announce(f"Time : {klines['time']}")
        defs.announce(f"Open : {klines['open']}")
        defs.announce(f"High : {klines['high']}")
        defs.announce(f"Low  : {klines['low']}")
        defs.announce(f"Close: {klines['close']}")
    
    # return klines
    return klines

# Preload prices
def get_prices(symbol, interval, limit):

    # Debug
    debug = False
       
    # Initialize prices
    prices = {'time': [], 'price': []}

    # Get kline with the lowest interval (1 minute)
    kline_prices = get_klines(symbol, interval, limit)
    prices       = {
        'time' : kline_prices['time'],
        'price': kline_prices['close']
    }

    # Report to stdout
    defs.announce(f"Initial {limit} prices with {interval}m interval extracted from klines")

    # Return prices
    return prices

# Combine two lists of prices
def combine_prices(prices_1, prices_2):
    
    # Combine and sort by 'time'
    prices = sorted(zip(prices_1['time'] + prices_2['time'], prices_1['price'] + prices_2['price']))

    # Use a dictionary to remove duplicates, keeping the first occurrence of each 'time'
    unique_prices = {}
    for t, p in prices:
        if t not in unique_prices:
            unique_prices[t] = p

    # Separate into 'time' and 'price' lists
    combined_prices = {
        'time': list(unique_prices.keys()),
        'price': list(unique_prices.values())
    }
    
    # Return combined list
    return combined_prices

# Calculations required for info
def calc_info(info, spot, multiplier, compounding):

    # Debug
    debug = False
    
    # Initialize variables
    add_up            = 1.0
    compounding_ratio = 1.0

    # Calculate minimum order value, add up and round up to prevent strange errors
    minimumQty = info['minOrderQty'] * add_up             # Base asset (BTC)
    minimumAmt = info['minOrderQty'] * add_up * spot      # Quote asset (USDT)
    
    # Do compounding if enabled
    if compounding['enabled']:
        
        # Only compound if when profitable
        if compounding['now'] > compounding['start']:
            compounding_ratio = compounding['now'] / compounding['start']

    # Round correctly, adjust for multiplier and compounding
    info['minBuyBase']  = defs.round_number(minimumQty * multiplier * compounding_ratio, info['basePrecision'], "up")
    info['minBuyQuote'] = defs.round_number(minimumAmt * multiplier * compounding_ratio, info['quotePrecision'], "up")

    # Debug to stdout
    if debug:
        defs.announce(f"Debug: Minimum order in base is {info['minBuyBase']} {info['baseCoin']} and in quote is {info['minBuyQuote']} {info['quoteCoin']}")

    # Return instrument info
    return info

# Preload instrument info
def get_info(symbol, spot, multiplier, compounding):

    # Debug
    debug = False
    
    # Initialize variables
    data = {}
    info = {}

    # Load instrument info via normal session
    message  = defs.announce("session: /public/get_instrument")
    try:
        url    = config.api_url + "/public/get_instrument"
        params = {
            'instrument_name': str(symbol)
        }
        response = requests.get(url, params=params)
        data     = response.json()
    except Exception as e:
        defs.log_error(e)

    # Check API rate limit and log data if possible
    if data:
        data = defs.rate_limit(data)
        defs.log_exchange(data, message)

    # Transform instrument info intro required format
    info['time']           = defs.now_utc()[4]                              # Time of last instrument update
    info['symbol']         = data['result']['instrument_name']              # Symbol
    info['baseCoin']       = data['result']['base_currency']                # Base asset, in case of BTCUSDT it is BTC 
    info['quoteCoin']      = data['result']['quote_currency']               # Quote asset, in case of BTCUSDT it is USDT
    info['status']         = data['result']['is_active']                    # Is the symbol trading?
    info['basePrecision']  = float(data['result']['contract_size'])         # Decimal precision of base asset (BTC) 
    info['quotePrecision'] = float(data['result']['tick_size'])             # Decimal precision of quote asset (USDT)
    info['minOrderQty']    = float(data['result']['min_trade_amount'])      # Minimum order quantity in base asset (BTC)
    info['maxOrderQty']    = float('inf')                                   # Maximum order quantity in base asset (BTC)
    info['minOrderAmt']    = None                                           # Minimum order quantity in quote asset (USDT)
    info['maxOrderAmt']    = float('inf')                                   # Maximum order quantity in quote asset (USDT)
    info['tickSize']       = float(data['result']['tick_size'])             # Smallest possible price increment of base asset (USDT)

    # Calculate additional values
    data = calc_info(info, spot, multiplier, compounding)
    
    # Add info
    info['minBuyBase']     = data['minBuyBase']                            # Minimum buy value in Base Asset (possibly corrected for multiplier and compounding!)
    info['minBuyQuote']    = data['minBuyQuote']                           # Minimum buy value in Quote Asset (possibly corrected for multiplier and compounding!)

    # Debug to stdout
    if debug:
        defs.announce("Debug: Instrument info")
        pprint.pprint(info)
        print()
  
    # Return instrument info
    return info
    
# Create empty files for check_files
def create_file(create_file, content=""):
        
    # Does the file exist and if not create a file    
    if not os.path.exists(create_file):
        with open(create_file, 'a') as file:
            if content:
                file.write(content)
            else:
                pass

    # Return
    return

# Check if necessary files exists
def check_files():
        
    # Does the data folder exist
    if not os.path.exists(config.data_folder):
        os.makedirs(config.data_folder)
    
    # Headers for files
    revenue_header = "UTCTime,createdTime,orderId,orderLinkId,side,symbol,baseCoin,quoteCoin,orderType,orderStatus,avgPrice,qty,triggerStart,triggerEnd,cumExecFee,cumExecQty,cumExecValue,revenue\n"
    
    # Does the buy orders database exist
    create_file(config.dbase_file)                      # Buy orders database
    create_file(config.error_file)                      # Errors log file
    create_file(config.exchange_file)                   # Exchange log file
    create_file(config.revenue_file, revenue_header)    # Revenue log file
    
    defs.announce("All folders and files checked")
    
# Check orders in database if they still exist
def check_orders(transactions, info):
    
    # Initialize variables
    message          = ""
    all_buys         = []
    transaction      = {}
    temp_transaction = {}
    quick            = config.quick_check

    # Output to stdout
    defs.announce("Checking all orders on exchange")

    # Loop through all buys
    for transaction in transactions:

        # Check orders
        if quick:
            # Only check order on exchange if status is not Closed
            defs.announce(f"Checking order from database with order ID {transaction['orderId']} and custom ID {transaction['orderLinkId']}")
            temp_transaction = transaction
            if transaction['status'] != "Closed":
                defs.announce("Performing an additional check on order status via exchange")
                temp_transaction = orders.transaction_from_id(transaction['orderId'], transaction['orderLinkId'], info)
        else:
            # Check all order on exchange regardless of status
            defs.announce(f"Checking order on exchange: {transaction['orderId']}, {transaction['orderLinkId']}")
            temp_transaction = orders.transaction_from_id(transaction['orderId'], transaction['orderLinkId'], info)

        # Assign status, if not filled just disregard
        if "Filled" in temp_transaction['orderStatus']:
            temp_transaction['status'] = "Closed"
            all_buys.append(temp_transaction)
        
    # Save refreshed database
    database.save(all_buys, info)
    
    # Return correct database
    return all_buys 
