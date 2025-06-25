### Sunflow Cryptobot ###
#
# Order functions

# Load external libraries
from loader import load_config
import pprint, requests

# Load internal libraries
import database, defs, deribit, distance, preload

# Load config
config = load_config()

# Get orderId from exchange order
def order_id(order):
    
    # Logic
    id = order['result']['order_id']
    return id

# Get order history
def history(orderId, orderLinkId, info):
    
    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]
        
    # Initialize variables
    data           = {}
    order          = {}
    order_received = False
    error_code     = 0


    ''' Load order state via get_order_state (order is presumably open) '''
    deribit.authenticate()
    message = defs.announce("session: /private/get_order_state")
    try:
        url     = config.api_url + "/private/get_order_state"
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type" : "application/json"
        }
        params = {
            "order_id": str(orderId)
        }
        response = requests.get(url, headers=headers, params=params)
        data     = response.json()
    except Exception as e:
        message = f"*** Error: Get order state for history failed: {e} ***"
        defs.log_error(message)

    # Check API rate limit and log data if possible
    if data:
        data = defs.rate_limit(data)
        defs.log_exchange(data, message)
        
    # Order response
    if response.status_code == 200:
        order          = data
        order_received = True


    ''' Load order state via get_order_state_label (order is presumably filled) '''
    deribit.authenticate()
    if not order_received:
        message = defs.announce("session: /private/get_order_state_by_label")
        try:
            url     = config.api_url + "/private/get_order_state_by_label"
            headers = {
                "Authorization": f"Bearer {config.access_token}",
                "Content-Type" : "application/json"
            }
            params = {
                "currency": str(info['quoteCoin']),
                "label"   : str(orderLinkId)
            }
            response = requests.get(url, headers=headers, params=params)
            data     = response.json()
        except Exception as e:
            message = f"*** Error: Get order state by label for history failed: {e} ***"
            defs.log_error(message)

        # Check API rate limit and log data if possible
        if data:
            data = defs.rate_limit(data)
            defs.log_exchange(data, message)        

        # Order response
        if response.status_code == 200:
            if data['result'] != []:
                data['result'] = data['result'][0]   # labels are not unique at Deribit, for Bybit they are
                order          = data
                order_received = True
            else:
                message = f"*** Warning S0012: Order disappeared from exchange ***\n>>> Message: Order ID is '{orderId}' and custom ID is '{orderLinkId}'"
                defs.log_error(message)
                error_code = 2
        else:
            message = f"*** Error: Failed to get order state: {response.status_code}, {response.text} ***"
            defs.log_error(message)
            error_code = 1

    # Debug to stdout
    if debug:
        defs.announce("Debug: Order history")
        pprint.pprint(order)
        print()

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return order
    return order, error_code

# Decode order from exchange to proper dictionary
def decode(order):
    
    # Debug
    debug = False
    
    # Debug to stdout
    if debug:
        defs.announce("Debug: Order before decode:")
        pprint.pprint(order)
        print()

    # Initialize variables
    transaction = {}
    result      = order['result']
    price       = result['price']

    # Map transaction
    transaction['createdTime']  = int(result['creation_timestamp'])                                         # Creation timestamp
    transaction['updatedTime']  = int(result['last_update_timestamp'])                                      # Last update timestamp
    transaction['orderId']      = result['order_id']                                                        # Order ID by exchange
    transaction['orderLinkId']  = result['label']                                                           # Custom ID by Sunflow
    transaction['symbol']       = result['instrument_name']                                                 # Symbol
    transaction['side']         = result['direction'].capitalize()                                          # Buy or Sell
    transaction['orderType']    = result['order_type'].capitalize()                                         # Order type: limit, market, stop_limit, stop_market
    transaction['orderStatus']  = result['order_state'].capitalize()                                        # Order state: open, filled, rejected, cancelled, untriggered
    transaction['price']        = price if price == 'market_price' else float(price)                        # Price in quote (USDT)
    transaction['avgPrice']     = float(result.get('average_price', 0))                                     # Average fill price in quote (USDT)
    transaction['qty']          = float(result['amount'])                                                   # Quantity in base (BTC)
    transaction['cumExecQty']   = float(result.get('filled_amount', 0))                                     # Cumulative executed quantity in base (BTC)
    transaction['cumExecValue'] = float(result.get('filled_amount', 0) * result.get('average_price', 0))    # Cumulative executed value
    transaction['cumExecFee']   = float(0)                                                                  # Cumulative executed fee
    transaction['triggerPrice'] = float(result['trigger_price'])                                            # Trigger price in quote (USDT)

    # Debug to stdout
    if debug:
        defs.announce("Debug: Order after decode:")
        pprint.pprint(transaction)
        print()

    # Return order
    return transaction

# Cancel an order at the exchange
def cancel(symbol, orderId, orderLinkId):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]

    # Debug to stdout
    if debug:
        defs.announce(f"Debug: Trying to cancel order with order ID {orderId} and/or custom ID {orderLinkId}")
    
    # Initialize variables
    data       = {}
    order      = {}
    error_code = 0
    exception  = ""
   
    # Cancel order
    deribit.authenticate()
    message = defs.announce("session: /private/cancel_by_label")
    try:
        url     = config.api_url + "/private/cancel_by_label"
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type" : "application/json"
        }
        params = {
            "label": str(orderLinkId)
        }
        response = requests.get(url, headers=headers, params=params)
        data     = response.json()
    except Exception as e:
        message = f"*** Error: Cancel by label failed: {e} ***"
        defs.announce(message)

    # Did the order exist
    if data['result'] == 0:
        error_code = 1
        
    # Check API rate limit and log data if possible
    if data:
        data = defs.rate_limit(data)
        defs.log_exchange(data, message)

    # Assign data to order
    order = data

    # Debug to stdout
    if debug:
        defs.announce("Debug: Cancelled order report")
        pprint.pprint(order)
        print()
        
    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return error code
    return error_code, exception    

# Turn an order from the exchange into a properly formatted transaction after placing or amending an order
# Only used by Bybit, not by Deribit
def transaction_from_order(order):

    # Initialize variables
    order_history = {}
    transaction   = {}
    result        = ()
    error_code    = 0

    # Get orderId first
    orderId       = order_id(order)

    # Get order history and status
    result        = history(orderId)
    order_history = result[0]
    error_code    = result[1] 

    # Check for status
    if error_code == 0:
        transaction = decode(order_history)

    # Return transaction
    return transaction, error_code

# Turn an order from the exchange into a properly formatted transaction after the order already exists
def transaction_from_id(orderId, orderLinkId, info):

    # Initialize variables
    result        = ()
    
    # Do logic
    result        = history(orderId, orderLinkId, info)
    order_history = result[0]
    error_code    = result[1]
    transaction   = decode(order_history)

    # Return transaction
    return transaction, error_code

# Initialize active order for initial buy or sell
def set_trigger(spot, active_order, info):

    # Debug
    defs.announce(f"Trigger price distance {active_order['fluctuation']:.4f} % and price {defs.format_number(spot, info['tickSize'])} {info['quoteCoin']}")

    # Check side buy or sell
    if active_order['side'] == "Buy":
        active_order['qty']     = info['minBuyBase']
        active_order['trigger'] = defs.round_number(spot * (1 + (active_order['fluctuation'] / 100)), info['tickSize'], "up")
    else:
        active_order['trigger'] = defs.round_number(spot * (1 - (active_order['fluctuation'] / 100)), info['tickSize'], "down")
        
    # Set initial trigger price so we can remember
    active_order['trigger_ini'] = active_order['trigger']

    # Return active_order
    return active_order

# Check if we can sell based on price limit
def sell_matrix(spot, use_pricelimit, pricelimit_advice, info):
    
    # Initialize variables
    message = ""
    pricelimit_advice['sell_result'] = True
    
    # Check sell price for price limits
    if use_pricelimit['enabled']:
        
        # Check minimum sell price for price limit
        if use_pricelimit['min_sell_enabled']:
            if spot > use_pricelimit['min_sell']:
                pricelimit_advice['sell_result'] = True
            else:
                pricelimit_advice['sell_result'] = False
                message = f"price {spot} {info['quoteCoin']} is lower than minimum sell price "
                message = message + f"{defs.format_number(use_pricelimit['min_sell'], info['tickSize'])} {info['quoteCoin']}"

        # Check maximum sell price for price limit
        if use_pricelimit['max_sell_enabled']:
            if spot < use_pricelimit['max_sell']:
                pricelimit_advice['sell_result'] = True
            else:
                pricelimit_advice['sell_result'] = False
                message = f"price {spot} {info['quoteCoin']} is higher than maximum sell price "
                message = message + f"{defs.format_number(use_pricelimit['max_sell'], info['tickSize'])} {info['quoteCoin']}"

    # Return modified price limit
    return pricelimit_advice, message    

# What orders and how much can we sell with profit
def check_sell(spot, profit, active_order, all_buys, use_pricelimit, pricelimit_advice, info):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]

    # Initialize variables
    qty       = 0
    counter   = 0
    message   = ""
    rise_to   = ""
    nearest   = []
    distance  = active_order['distance']
    pre_sell  = False
    can_sell  = False
    all_sells = []
    result    = ()
    
    # Check sell price limit
    result            = sell_matrix(spot, use_pricelimit, pricelimit_advice, info)
    pricelimit_advice = result[0]
    message           = result[1]
    
    # Walk through buy database and find profitable buys
    for transaction in all_buys:

        # Only walk through closed buy orders
        if transaction['status'] == 'Closed':
                    
            # Check if a transaction is profitable
            profitable_price = transaction['avgPrice'] * (1 + ((profit + distance) / 100))
            nearest.append(profitable_price - spot)
            if spot >= profitable_price:
                qty = qty + transaction['cumExecQty']
                all_sells.append(transaction)
                counter = counter + 1
    
    # Adjust quantity to exchange regulations
    qty = defs.round_number(qty, info['basePrecision'], "down")
    
    # Do we have order to sell
    if all_sells and qty > 0:
        pre_sell = True

    # We have orders to sell, and sell price limit is not blocking 
    if pre_sell and pricelimit_advice['sell_result']:
        can_sell = True
        defs.announce(f"Trying to sell {counter} orders for a total of {defs.format_number(qty, info['basePrecision'])} {info['baseCoin']}")
    else:
        if nearest:
            rise_to = f"{defs.format_number(min(nearest), info['tickSize'])} {info['quoteCoin']}"

    # We have orders to sell, but sell price limit is blocking
    if pre_sell and not pricelimit_advice['sell_result']:
        message = f"We could sell {counter} orders, but " + message
        defs.announce(message)        

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return data
    return all_sells, qty, can_sell, rise_to
        
# New buy order
def buy(symbol, spot, compounding, active_order, all_buys, prices, info):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]
    
    # Initialize variables
    data             = {}
    order            = {}
    error_code       = 0
    result           = ()
    response_message = ""
    response_skip    = False   

    # Output to stdout
    defs.announce("*** BUY BUY BUY! ***")

    # Recalculate minimum values
    info = preload.calc_info(info, spot, config.multiplier, compounding)

    # Initialize active_order
    active_order['side']     = "Buy"
    active_order['active']   = True
    active_order['start']    = spot
    active_order['previous'] = spot
    active_order['current']  = spot
    active_order['linkid']   = deribit.custom_id()
    
    # Determine distance of trigger price
    active_order = distance.calculate(active_order, prices)

    # Initialize trigger price
    active_order = set_trigger(spot, active_order, info)  

    # Place buy order
    deribit.authenticate()
    message = defs.announce("session: /private/buy")
    try:
        url     = config.api_url + "/private/buy"
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type" : "application/json"
        }
        params = {
            "instrument_name": symbol,
            "amount"         : float(active_order['qty']),
            "type"           : "stop_market",
            "label"          : str(active_order['linkid']),
            "trigger"        : "index_price",
            "trigger_price"  : float(active_order['trigger'])
        }
        response = requests.get(url, headers=headers, params=params)
        data     = response.json()
    except Exception as e:
        
        # Buy order failed, log, reset active_order and return
        message = f"*** Warning S0007a: Buy order failed when placing, trailing stopped! ***\n>>> Message: {e}"
        defs.log_error(message)
        active_order['active'] = False
        if speed: defs.announce(defs.report_exec(stime))    
        return active_order, all_buys, info
        
    # Review response for errors
    result  = deribit.check_response(data)
    response_message = result[1]
    response_skip    = result[2]

    # Check response for errors
    if not response_skip:
        if response_message == "order_not_found" or response_message == "already_closed":
            error_code = 1
        elif response_message == "trigger_price_too_high":
            error_code = 11
        elif response_message == "trigger_price_too_low":
            error_code = 12
        else:
            # Any other error
            error_code = 100

    # Take action based on response
    if error_code != 0:

        # Buy order failed, log, reset active_order and return
        message = f"*** Warning S0007b: Buy order failed when placing, trailing stopped! ***\n>>> Message: {response_message}"
        defs.log_error(message)
        active_order['active'] = False
        if speed: defs.announce(defs.report_exec(stime))    
        return active_order, all_buys, info

    # Check API rate limit and log data if possible
    if data:
        data = defs.rate_limit(data)
        defs.log_exchange(data, message)

    # Get order ID, custom ID is already assigned at initialize
    active_order['orderid'] = data['result']['order']['order_id']

    # Report to stdout
    message = f"Buy order opened for {defs.format_number(active_order['qty'], info['basePrecision'])} {info['baseCoin']} "
    message = message + f"at trigger price {defs.format_number(active_order['trigger'], info['tickSize'])} {info['quoteCoin']} "
    message = message + f"with order ID '{active_order['orderid']}'"
    if debug: message = message + f" and custom ID '{active_order['linkid']}'"
    defs.announce(message, True)

    # Prepare for Deribit decode
    order = deribit.prep_decode(data)
      
    # Get the transaction
    transaction = decode(order)   
            
    # Change the status of the transaction
    transaction['status'] = "Open"

    # Store the transaction in the database buys file
    all_buys = database.register_buy(transaction, all_buys, info)
    defs.announce(f"Registered buy order in database {config.dbase_file}")

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return trailing order and new buy order database
    return active_order, all_buys, info
    
# New sell order
def sell(symbol, spot, active_order, prices, info):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]

    # Initialize variables
    data             = {}
    error_code       = 0
    result           = ()
    response_message = ""
    response_skip    = False

    # Output to stdout
    defs.announce("*** SELL SELL SELL! ***")

    # Initialize active_order
    active_order['side']     = "Sell"
    active_order['active']   = True
    active_order['start']    = spot
    active_order['previous'] = spot
    active_order['current']  = spot
    active_order['linkid']   = deribit.custom_id()    
  
    # Determine distance of trigger price
    active_order = distance.calculate(active_order, prices)

    # Initialize trigger price
    active_order = set_trigger(spot, active_order, info)

    # Place sell order
    deribit.authenticate()
    message = defs.announce("session: /private/sell")
    try:
        url     = config.api_url + "/private/sell"
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type" : "application/json"
        }
        params = {
            "instrument_name": symbol,
            "amount"         : float(active_order['qty']),
            "type"           : "stop_market",
            "label"          : str(active_order['linkid']),
            "trigger"        : "index_price",
            "trigger_price"  : float(active_order['trigger'])
        }
        response = requests.get(url, headers=headers, params=params)
        data     = response.json()
    except Exception as e:

        # Sell order failed, log, reset active_order and return
        message = f"*** Warning S0008a: Sell order failed due to error, trailing stopped! ***\n>>> Message: {e}"
        defs.log_error(message)
        active_order['active'] = False
        if speed: defs.announce(defs.report_exec(stime))        
        return active_order

    # Review response for errors
    result   = deribit.check_response(data)
    response_message = result[1]
    response_skip    = result[2]

    # Check response for errors
    if not response_skip:
        if response_message == "order_not_found" or response_message == "already_closed":
            error_code = 1
        elif response_message == "trigger_price_too_high":
            error_code = 11
        elif response_message == "trigger_price_too_low":
            error_code = 12
        else:
            # Any other error
            error_code = 100

    # Take action based on response
    if error_code != 0:

        # Sell order failed, log, reset active_order and return
        message = f"*** Warning S0008b: Sell order failed when placing, trailing stopped! ***\n>>> Message: {response_message}"
        defs.log_error(message)
        active_order['active'] = False
        if speed: defs.announce(defs.report_exec(stime))    
        return active_order
        
    # Check API rate limit and log data if possible
    if data:
        data = defs.rate_limit(data)
        defs.log_exchange(data, message)
    
    # Get order ID, custom ID is already assigned at initialize
    active_order['orderid'] = data['result']['order']['order_id']
    
    # Output to stdout
    message = f"Sell order opened for {defs.format_number(active_order['qty'], info['basePrecision'])} {info['baseCoin']} "
    message = message + f"at trigger price {defs.format_number(active_order['trigger'], info['tickSize'])} {info['quoteCoin']} "
    message = message + f"with order ID '{active_order['orderid']}'"
    if debug: message = message + f" and custom ID '{active_order['linkid']}'"
    defs.announce(message, True)

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))
   
    # Return data
    return active_order

# Get wallet
def get_wallet(coins):

    # Debug
    debug = False

    # Initialize variables
    data   = {}
    wallet = {}

    # Get wallet
    deribit.authenticate()    
    message = defs.announce("session: private/get_account_summary")
    try:
        url     = config.api_url + "/private/get_account_summary"
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type" : "application/json"
        }
        params = {
            "currency": str(coins)
        }
        response = requests.get(url, headers=headers, params=params)
        data     = response.json()
    except Exception as e:
        message = f"*** Error: Get account summary for wallet failed: {e} ***"
        defs.log_error(message)
        
    # Check API rate limit and log data if possible
    if data:
        data = defs.rate_limit(data)
        defs.log_exchange(data, message)        

    # Assign to wallet
    wallet = data

    # Debug to stdout
    if debug:
        defs.announce("Debug: Wallet information:")
        pprint.pprint(wallet)

    # Return wallet
    return wallet

# Handle equity requests safely
def equity_safe(equity):
    
    # Do logic
    if equity:
        equity = float(equity)
    else:
        equity = float(0)
    
    # Return equity
    return equity

# Rebalances the database vs exchange by removing orders with the highest price
def rebalance(all_buys, info):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]

    # Initialize variables
    wallet         = ()
    equity_wallet  = 0
    equity_dbase   = 0
    equity_diff    = 0
    equity_remind  = 0
    equity_lost    = 0
    dbase_changed = False

    # Debug to stdout
    if debug:
        defs.announce("Debug: Trying to rebalance buys database with exchange data")

    # Get wallet for base coin
    wallet = get_wallet(info['baseCoin'])
    
    # Get equity from wallet for basecoin
    equity_wallet = equity_safe(wallet['result']['balance'])
  
    # Get equity from all buys for basecoin
    equity_dbase  = float(sum(order['cumExecQty'] for order in all_buys))
    equity_remind = float(equity_dbase)
    equity_diff   = equity_wallet - equity_dbase

    # Debug to stdout
    if debug:
        defs.announce(f"Debug: Before rebalance equity on exchange: {equity_wallet} {info['baseCoin']}")
        defs.announce(f"Debug: Before rebalance equity in database: {equity_dbase} {info['baseCoin']}")

    # Selling more than we have
    while equity_dbase > equity_wallet:
        
        # Database changed
        dbase_changed = True
        
        # Find the item with the highest avgPrice
        highest_avg_price_item = max(all_buys, key=lambda x: x['avgPrice'])

        # Remove this item from the list
        all_buys.remove(highest_avg_price_item)
        
        # Recalculate all buys
        equity_dbase = sum(order['cumExecQty'] for order in all_buys)    

    # Debug to stdout
    if debug:
        defs.announce(f"Debug: After rebalance equity on exchange: {equity_wallet} {info['baseCoin']}")
        defs.announce(f"Debug: After rebalance equity in database: {equity_dbase} {info['baseCoin']}")

    # Save new database
    if dbase_changed:
        equity_lost = equity_remind - equity_dbase
        defs.announce(f"Rebalanced buys database with exchange data and lost {defs.format_number(equity_lost, info['basePrecision'])} {info['baseCoin']}")
        database.save(all_buys, info)
    
    # Report to stdout
    defs.announce(f"Difference between exchange and database is {defs.format_number(equity_diff, info['basePrecision'])} {info['baseCoin']}")

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return all buys
    return all_buys

# Report wallet info to stdout
def report_wallet(spot, all_buys, info):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]

    # Initialize variables
    message_1 = ""
    message_2 = ""
    result    = ()

    # Get order count and quantity
    result        = database.order_count(all_buys, info)
    base_database = result[1]
      
    # Get wallet for base and quote coin
    base_exchange  = equity_safe(get_wallet(info['baseCoin'])['result']['balance'])
    quote_exchange = equity_safe(get_wallet(info['quoteCoin'])['result']['balance'])
   
    # Calculate values
    bot    = base_exchange * spot + quote_exchange    # Bot value in quote according to exchange
    lost   = base_exchange - base_database            # Lost due to inconsistancies
    
    # Create messsage
    message_1 = f"Bot value is {defs.format_number(bot, info['quotePrecision'])} {info['quoteCoin']} "
    message_1 = message_1 + f"({defs.format_number(base_exchange, info['basePrecision'])} {info['baseCoin']} / {defs.format_number(quote_exchange, info['quotePrecision'])} {info['quoteCoin']})"    
    message_2 = f"Database has {defs.format_number(base_database, info['basePrecision'])} {info['baseCoin']} and "
    message_2 = message_2 + f"{defs.format_number(lost, info['basePrecision'])} {info['baseCoin']} is out of sync"
          
    # Output to stdout
    defs.announce(message_1, True, 1)
    defs.announce(message_2)

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))
 
    # Return total equity and quote
    return bot, base_exchange, quote_exchange, base_database, lost
