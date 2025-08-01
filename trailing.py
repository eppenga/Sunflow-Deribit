### Sunflow Cryptobot ###
#
# Traling buy and sell

# Load external libraries
import pprint, requests, threading

# Load internal libraries
from loader import load_config
import database, defs, deribit, distance, orders

# Load config
config = load_config()

# Initialize stuck variable
stuck             = {}
stuck['check']    = True
stuck['time']     = defs.now_utc()[4]
stuck['interval'] = 20000
   
# Check if we can do trailing buy or sell
def check_order(symbol, spot, compounding, active_order, all_buys, all_sells, info):

    # Debug and speed
    debug = False
    speed = False
    stime = defs.now_utc()[4]
    
    # Declare stuck variable global
    global stuck
    
    # Initialize variables
    result         = ()
    type_check     = ""
    do_check_order = False

    # Has current price crossed trigger price
    if active_order['side'] == "Sell":
        if active_order['current'] <= active_order['trigger']:
            type_check     = "a regular"
            do_check_order = True
    else:
        if active_order['current'] >= active_order['trigger']:
            type_check     = "a regular"
            do_check_order = True

    # Check every interval, sometimes orders get stuck
    current_time = defs.now_utc()[4]
    if stuck['check']:
        stuck['check'] = False
        stuck['time']  = defs.now_utc()[4]
    if current_time - stuck['time'] > stuck['interval']:
        type_check = "an additional"
        do_check_order = True

    # Current price crossed trigger price
    if do_check_order:

        # Report to stdout
        message = f"Performing {type_check} check on {active_order['side'].lower()} order with order ID '{active_order['orderid']}'"
        if debug: message = message + f" and custom ID '{active_order['linkid']}'"
        defs.announce(message)

        # Reset stuck
        stuck['check'] = True
        
        # Has trailing endend, check if order does still exist
        result       = orders.transaction_from_id(active_order['orderid'], active_order['linkid'], info)
        order        = result[0]
        error_code   = result[1]
        
        # Check if order does not exist anymore (Deribit sometimes loses orders)
        if error_code == 2:

            # Reset trailing order
            active_order['active'] = False
            # Remove order from exchange
            orders.cancel(symbol, active_order['orderid'], active_order['linkid'])
            # Rebalance to be safe
            all_buys = orders.rebalance(all_buys, info)
            # Remove order from all buys
            if active_order['side'] == "Buy":
                all_buys = database.remove(active_order['orderid'], all_buys, info)
            
        # Check if trailing order is filled, if so reset counters and close trailing process
        if order['orderStatus'] == "Filled":
            
            # Prepare message for stdout and Apprise
            defs.announce(f"Trailing {active_order['side'].lower()}: *** Order has been filled! ***")
            message_1 = f"{active_order['side']} order closed for {defs.format_number(active_order['qty'], info['basePrecision'])} {info['baseCoin']} "
            message_1 = message_1 + f"at trigger price {defs.format_number(active_order['trigger'], info['tickSize'])} {info['quoteCoin']}"
            
            # Close trailing process
            result       = close_trail(active_order, all_buys, all_sells, spot, info)
            active_order = result[0]
            all_buys     = result[1]
            all_sells    = result[2]
            transaction  = result[3]
            revenue      = result[4]
        
            # Fill in average price and report message
            if active_order['side'] == "Buy":
                message_1 = message_1 + f" and fill price {defs.format_number(transaction['avgPrice'], info['tickSize'])} {info['quoteCoin']}"
            else:
                message_1 = message_1 + f", fill price {defs.format_number(transaction['avgPrice'], info['tickSize'])} {info['quoteCoin']} "
                message_1 = message_1 + f"and profit {defs.format_number(revenue, info['quotePrecision'])} {info['quoteCoin']}"
                message_2 = f"sold {defs.format_number(active_order['qty'], info['basePrecision'])} {info['baseCoin']}, "
                message_2 = message_2 + f"profit is {defs.format_number(revenue, info['quotePrecision'])} {info['quoteCoin']}"
                # Send message to group 2
                defs.announce(message_2, False, 0, True, 1)
            
            # Send message to group 1
            defs.announce(message_1, True, 1)

            # Report wallet, quote and base currency to stdout and adjust compounding (task)
            def report_wallet_task():
                compounding['now'] = orders.report_wallet(spot, all_buys, info)[0]
            
            # Report wallet, quote and base currency to stdout and adjust compounding (threaded or not)
            threaded = False    # For Deribit we do not threat
            if config.wallet_report:
                if threaded:
                    wallet_thread = threading.Thread(target=report_wallet_task)
                    wallet_thread.start()
                else:
                    compounding['now'] = orders.report_wallet(spot, all_buys, info)[0]
                            
            # Report compounding, only possible when wallet reporting is active, see config file
            if compounding['enabled']:
                info = defs.calc_compounding(info, spot, compounding)
                
            # Report to revenue log file
            if config.revenue_log:
                defs.log_revenue(active_order, transaction, revenue, info, config.revenue_log_sides, config.revenue_log_extend)
            
        # Check if symbol is spiking
        else:
            result       = check_spike(symbol, spot, active_order, order, all_buys, info)
            active_order = result[0]
            all_buys     = result[1]

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return modified data
    return active_order, all_buys, compounding, info

# Checks if the trailing error spiked
def check_spike(symbol, spot, active_order, order, all_buys, info):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]

    # Initialize variables
    error_code = 0

    # Check if the order spiked
    if active_order['side'] == "Sell":

        # Did it spike and was forgotten when selling
        if order['triggerPrice'] > spot:
            defs.announce("*** Warning: Sell order spiked, cancelling current order! ***", True, 1)
            # Reset trailing sell
            active_order['active'] = False
            # Remove order from exchange
            orders.cancel(symbol, active_order['orderid'], active_order['linkid'])
            # Rebalance to be safe
            all_buys = orders.rebalance(all_buys, info)

    else:

        # Did it spike and was forgotten when buying
        if order['triggerPrice'] < spot:
            defs.announce("*** Warning:  Buy order spiked, cancelling current order! ***", True, 1)
            # Reset trailing buy
            active_order['active'] = False
            # Remove order from all buys
            all_buys = database.remove(active_order['orderid'], all_buys, info)
            # Remove order from exchange
            orders.cancel(symbol, active_order['orderid'], active_order['linkid'])
            # Rebalance to be safe
            all_buys = orders.rebalance(all_buys, info)
    
    if error_code == 1:
        defs.announce(f"Order ID '{active_order['orderid']}' and custom ID '{active_order['linkid']}' spiked, but order was not found at exchange!", True, 1)

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))
    
    # Return data
    return active_order, all_buys

# Calculate revenue from sell
def calculate_revenue(transaction, all_sells, spot, info):
    
    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]
    
    # Initialize variables
    sells         = 0
    buys          = 0
    revenue       = 0
    fees          = {}
    fees['buy']   = 0
    fees['sell']  = 0
    fees['total'] = 0
    
    # Logic
    sells         = transaction['cumExecValue']
    buys          = sum(item['cumExecValue'] for item in all_sells)
    fees['buy']   = sum(item['cumExecFee'] for item in all_sells) * spot
    fees['sell']  = transaction['cumExecFee']
    fees['total'] = fees['buy'] + fees['sell']
    revenue       = sells - buys - fees['total']
    
    # Output to stdout for debug
    if debug:
        message = f"Debug: Total sells {sells} {info['quoteCoin']}, buys {buys} {info['quoteCoin']}, "
        message = message + f"buy fees {fees['buy']} {info['quoteCoin']}, sell fees {fees['sell']} {info['quoteCoin']}, total fees {fees['total']} {info['quoteCoin']}, "
        message = message + f"giving a profit of {defs.format_number(revenue, info['quotePrecision'])} {info['quoteCoin']}"
        defs.announce(message)

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))
    
    # Return revenue
    return revenue
    
# Trailing order does not exist anymore, close it
def close_trail(active_order, all_buys, all_sells, spot, info):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]
    
    # Initialize variables
    revenue = 0
    
    # Make active_order inactive
    active_order['active'] = False
    
    # Close the transaction on either buy or sell trailing order
    transaction = orders.transaction_from_id(active_order['orderid'], active_order['linkid'], info)[0]
    transaction['status'] = "Closed"
    if debug:
        defs.announce(f"Debug: {active_order['side']} order")
        pprint.pprint(transaction)
        print()
          
    # Order was bought, create new all buys database
    if transaction['side'] == "Buy":
        all_buys = database.register_buy(transaction, all_buys, info)
    
    # Order was sold, create new all buys database, rebalance database and clear all sells
    if transaction['side'] == "Sell":

        # Debug to stdout
        if debug:
            defs.announce("Debug: All buy orders matching sell order")
            pprint.pprint(all_sells)
            print()

        # Calculate revenue
        revenue = calculate_revenue(transaction, all_sells, spot, info)
        
        # Create new all buys database
        all_buys = database.register_sell(all_buys, all_sells, info)
                
        # Clear all sells
        all_sells = []

    # Rebalance new database
    if config.database_rebalance:
        all_buys = orders.rebalance(all_buys, info)

    # Output to stdout
    defs.announce(f"Closed trailing {active_order['side'].lower()} order")

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))
    
    # Return modified data
    return active_order, all_buys, all_sells, transaction, revenue

# Trailing buy or sell
def trail(symbol, spot, compounding, active_order, info, all_buys, all_sells, prices):

    # Debug and speed
    debug = False
    speed = False
    stime = defs.now_utc()[4]
    
    # Initialize variables
    result   = ()
    do_amend = False

    # Debug to stdout
    if debug:
        defs.announce(f"Debug: Trailing {active_order['side']}: Checking if we can do trailing")

    # Check if the order still exists
    result       = check_order(symbol, spot, compounding, active_order, all_buys, all_sells, info)
    active_order = result[0]
    all_buys     = result[1]
    compounding  = result[2]
    info         = result[3]

    # Order still exists, we can do trailing buy or sell
    if active_order['active']:
       
        # We have a new price
        active_order['previous'] = active_order['current']
                    
        # Determine distance of trigger price
        active_order = distance.calculate(active_order, prices)
                    
        # Calculate new trigger price
        if active_order['side'] == "Sell":
            active_order['trigger_new'] = defs.round_number(active_order['current'] * (1 - (active_order['fluctuation'] / 100)), info['tickSize'], "down")
        else:
            active_order['trigger_new'] = defs.round_number(active_order['current'] * (1 + (active_order['fluctuation'] / 100)), info['tickSize'], "up")

        # Check if we can amend trigger price
        if active_order['side'] == "Sell":
            if active_order['trigger_new'] > active_order['trigger']:
                do_amend = True
        else:
            if active_order['trigger_new'] < active_order['trigger']:
                do_amend = True

        # Amend trigger price
        if do_amend:
            active_order = atp_helper(symbol, active_order, info)
        
    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return modified data
    return active_order, all_buys, compounding, info

# Change trigger price current trailing sell helper
def aqs_helper(symbol, active_order, info, all_sells, all_sells_new):

    # Initialize variables
    debug       = False
    result      = ()
    amend_code  = 0
    amend_error = ""

    # Amend order quantity
    result      = amend_quantity_sell(symbol, active_order, info)
    amend_code  = result[0]
    amend_error = result[1]

    # Determine what to do based on error code of amend result
    if amend_code == 0:
        # Everything went fine, we can continue trailing
        message = f"Adjusted quantity from {defs.format_number(active_order['qty'], info['basePrecision'])} "
        message = message + f"to {defs.format_number(active_order['qty_new'], info['basePrecision'])} {info['baseCoin']} in {active_order['side'].lower()} order"
        defs.announce(message, True, 0)
        all_sells           = all_sells_new
        active_order['qty'] = active_order['qty_new']

    if amend_code == 1:
        # Order does not exist, trailing order was sold in between
        all_sells_new = all_sells
        defs.announce("Adjusting trigger quantity not possible, sell order already hit", True, 0)
        
    if amend_code == 2:
        # Quantity could not be changed, do nothing
        all_sells_new = all_sells
        defs.announce("Sell order quantity could not be changed, doing nothing", True, 0)
        
    if amend_code == 10:
        all_sells_new = all_sells                        
        # Order does not support modification, do nothing
        defs.announce("Sell order quantity could not be changed, order does not support modification", True, 0)                        

    if amend_code == 100:
        # Critical error, let's log it and revert
        message = f"*** Warning S0010: Critical failure while trailing! ***\n>>> Message: {amend_error}"
        defs.announce(message, True, 1)
        defs.log_error(message)

    # Return data
    return active_order, all_sells, all_sells_new

# Change the quantity of the current trailing sell
def amend_quantity_sell(symbol, active_order, info):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]

    # Initialize variables
    data             = {}
    order            = {}
    result           = ()
    error_code       = 0
    response_message = ""
    response_skip    = False

    # Output to stdout
    message = f"Trying to adjust quantity from {defs.format_number(active_order['qty'], info['basePrecision'])} "
    message = message + f"to {defs.format_number(active_order['qty_new'], info['basePrecision'])} {info['baseCoin']}"
    defs.announce(message)

    # Amend order
    deribit.authenticate()
    message = defs.announce("session: amend_order")
    try:
        url     = config.api_url + "/private/edit"
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type" : "application/json"
        }
        params = {
            "amount"  : float(active_order['qty_new']),
            "order_id": str(active_order['orderid']),
        }
        response = requests.get(url, headers=headers, params=params)
        data     = response.json()
    except Exception as e:
        message = f"*** Error: Amend quantity sell failed: {e} ***"
        defs.announce(message)

    # Review response for errors
    result           = deribit.check_response(data)
    response_message = result[1]
    response_skip    = result[2]

    # Check response for errors
    if not response_skip:
        if response_message == "order_not_found" or response_message == "already_closed":
            error_code = 1
        elif response_message == "modification_not_allowed":
            error_code = 10
        else:
            # Any other error
            error_code = 100

    # Check API rate limit and log data if possible
    if data:
        data = defs.rate_limit(data)
        defs.log_exchange(data, message)

    # Assign data to order
    order = data

    # Debug to stdout
    if debug:
        defs.announce("Debug: Amended quantity sell order")
        pprint.pprint(order)
        print()

    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return error code 
    return error_code, response_message

# Change quantity trailing sell helper
def atp_helper(symbol, active_order, info):

    # Initialize variables
    debug      = False
    result     = ()
    amend_code = 0
    amend_error = ""
    
    # Amend trigger price
    result      = amend_trigger_price(symbol, active_order, info)
    amend_code  = result[0]
    amend_error = result[1]

    # Determine what to do based on error code of amend result
    if amend_code == 0:
        # Everything went fine, we can continue trailing
        message = f"Adjusted trigger price from {defs.format_number(active_order['trigger'], info['tickSize'])} to "
        message = message + f"{defs.format_number(active_order['trigger_new'], info['tickSize'])} {info['quoteCoin']} in {active_order['side'].lower()} order"
        defs.announce(message, True, 0)
        active_order['trigger'] = active_order['trigger_new']

    if amend_code == 1:
        # Order does not exist, trailing order sold or bought in between
        defs.announce(f"Adjusting trigger price not possible, {active_order['side'].lower()} order already hit", True, 0)

    if amend_code == 10:
        # Order does not support modification
        defs.announce(f"Adjusting trigger price not possible, {active_order['side'].lower()} order does not support modification", True, 0)

    if amend_code == 11:
        # Order does not support modification
        defs.announce(f"Adjusting trigger price not possible, {active_order['side'].lower()} trigger price too high", True, 0)

    if amend_code == 12:
        # Order does not support modification
        defs.announce(f"Adjusting trigger price not possible, {active_order['side'].lower()} trigger price too low", True, 0)

    if amend_code == 100:
        # Critical error, let's log it and revert
        message = f"*** Warning S0011: Critical failure while trailing! ***\n>>> Message: {amend_error}"
        defs.announce(message, True, 1)
        defs.log_error(message)
    
    # Return active_order
    return active_order

# Change the trigger price of the current trailing sell
def amend_trigger_price(symbol, active_order, info):

    # Debug and speed
    debug = False
    speed = True
    stime = defs.now_utc()[4]

    # Initialize variables
    data             = {}
    order            = {}
    result           = ()
    error_code       = 0
    exception        = ""
    response_message = ""
    response_skip    = False
    
    # Output to stdout
    message = f"Trying to adjust trigger price from {defs.format_number(active_order['trigger'], info['tickSize'])} to "
    message = message + f"{defs.format_number(active_order['trigger_new'], info['tickSize'])} {info['quoteCoin']}"
    defs.announce(message)
   
    # Amend order
    deribit.authenticate()
    message = defs.announce("session: /private/edit")
    try:
        url     = config.api_url + "/private/edit"
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type" : "application/json"
        }
        params = {
            "amount"       : float(active_order['qty']),
            "order_id"     : str(active_order['orderid']),
            "trigger_price": str(active_order['trigger_new'])
        }
        response = requests.get(url, headers=headers, params=params)
        data     = response.json()
    except Exception as e:
        message = f"*** Error: Amend trigger price failed: {e}"
        defs.announce(message)
        
    # Review response for errors
    result           = deribit.check_response(data)
    response_message = result[1]
    response_skip    = result[2]

    # Check response for errors
    if not response_skip:
        if response_message == "order_not_found" or response_message == "already_closed":
            error_code = 1
        elif response_message == "modification_not_allowed":
            error_code = 10
        elif response_message == "trigger_price_too_high":
            error_code = 11
        elif response_message == "trigger_price_too_low":
            error_code = 12
        else:
            # Any other error
            error_code = 100

    # Check API rate limit and log data if possible
    if data:
        data = defs.rate_limit(data)
        defs.log_exchange(data, message)

    # Assign data to order
    order = data

    # Debug to stdout
    if debug:
        defs.announce("Debug: Amended trigger price order")
        pprint.pprint(order)
        print()
        
    # Report execution time
    if speed: defs.announce(defs.report_exec(stime))

    # Return error code 
    return error_code, exception
