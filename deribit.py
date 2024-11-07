### Sunflow Cryptobot ###
#
# Authenticate Deribit

# Load external libraries
from datetime import datetime
import hashlib, requests, pprint

# Load internal libraries
from loader import load_config
import defs

# Load config
config = load_config()

# Authenticate at Deribit
def authenticate():
  
    # Debug
    debug = False
  
    # Debug to stdout
    if debug:
        defs.announce("Debug: Authenticating...")
  
    # Initialize variables
    access_token     = ""
    refresh_token    = ""
    token_expiration = 0
    token_action     = "new"
    token_adjust     = 0
    current_time     = defs.now_utc()[4]
    
    # See if token is initialized
    try:
        config.access_token
    except AttributeError:
        config.access_token     = ""
        config.refresh_token    = ""
        config.token_expiration = 0
    
    # Fill temporal variables
    if config.access_token and config.refresh_token and config.token_expiration:
        access_token     = config.access_token
        refresh_token    = config.refresh_token
        token_expiration = config.token_expiration
       
    # Token still valid
    if access_token and current_time < token_expiration:
        if debug:
            defs.announce("Debug: Reauthentication was not required")
        token_action = "none"
        return access_token, refresh_token, token_expiration
    
    # Token not valid anymore
    if access_token and current_time > token_expiration:
        token_action = "refresh"

    # Get refreshed token via normal session
    if token_action == "refresh":
        if debug:
            defs.announce("Debug: Refreshing token")
        message = defs.announce("session: /public/auth")
        try:
            url    = config.api_url + "/public/auth"
            params = {
                "grant_type"   : "refresh_token",
                "refresh_token": str(refresh_token),
                "client_id"    : str(config.api_key),
                "client_secret": str(config.api_secret)
            }
            response = requests.get(url, params=params)
            data = response.json()
        except Exception as e:
            message = f"*** Warning S0002: Warning when refreshing token: {e}"
            defs.announce(message)
            defs.log_error(message)
            token_action = "new"

    # Get new token via normal session
    if token_action == "new":
        if debug:
            defs.announce("Debug: Creating new token")
        message = defs.announce("session: /public/auth")
        try:
            url    = config.api_url + "/public/auth"
            params = {
                "grant_type"   : "client_credentials",
                "client_id"    : str(config.api_key),
                "client_secret": str(config.api_secret)
            }
            response = requests.get(url, params=params)
            data = response.json()
        except Exception as e:
            message = f"*** Error: S0001: Error when creating a new token: {e}"
            defs.announce(message)
            defs.log_error(message)
    
    # Extract token data
    if 'result' in data:
        access_token     = data['result']['access_token']
        refresh_token    = data['result']['refresh_token']
        expires_in       = data['result']['expires_in']
        token_expiration = (current_time + expires_in) - token_adjust
        defs.announce(f"Deribit {token_action} authentication successful, expires in {expires_in} ms")
    else:
        message = f"Authentication failed: {data}"
        defs.announce(message)
        defs.log_error(message)
    
    # Set token
    config.access_token     = access_token
    config.refresh_token    = refresh_token
    config.token_expiration = token_expiration
       
    # Return
    return

# Create a Custom ID, also called label
def custom_id():

    # Debug
    debug = False

    # Initialize variables
    prefix    = "Sunflow_"
    timestamp = datetime.now().isoformat() + "_"
    hash_part = hashlib.sha256(timestamp.encode()).hexdigest()[:28]

    # Create label
    label     = (prefix + timestamp + hash_part)[:64]

    # Debug to stdout
    if debug:
        defs.announce(f"Debug: Custom ID is {label} with a length of {len(label)}")
    
    # Return Custom ID
    return label

# Prepare for decode
def prep_decode(data):
        
    # Debug
    debug = False

    # Debug to stdout
    if debug:
        defs.announce("Debug: Before prep decode:")
        pprint.pprint(data)

    # Create a copy of data to avoid mutating the original
    order = data.copy()
    
    # Move 'order' contents directly into 'result' and remove 'trades'
    if 'result' in order and 'order' in order['result']:
        order['result'] = order['result']['order']
    
    # Remove the 'trades' key from order_a if it exists
    if 'trades' in data['result']:
        order['result'].pop('trades', None)

    # Debug to stdout
    if debug:
        defs.announce("Debug: After prep decode:")
        pprint.pprint(order)

    # Return order
    return order
