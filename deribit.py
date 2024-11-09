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

# Initialize token stuck counter
token_stuck = 0

# Set token data
def set_token_data(token):
    
    # Debug
    debug = False

    # Debug to stdout
    if debug:
        defs.announce("Debug: Setting token to config")
        
    # Set token
    config.access_token     = token['access']
    config.refresh_token    = token['refresh']
    config.token_expiration = token['expires']

    # Return
    return token
    
# Extract token data
def extract_token_data(data, token):

    # Debug
    debug = False

    # Declare global token stuck counter
    global token_stuck

    # Debug to stdout
    if debug:
        defs.announce("Debug: Extracting token data")

    # Check if we have a valid token
    if 'result' in data:
        
        # Reset token stuck counter
        token_stuck = 0

        # Asssign token variable
        token['access']  = data['result']['access_token']
        token['refresh'] = data['result']['refresh_token']
        token['valid']   = data['result']['expires_in']
        token['now']     = defs.now_utc()[4]
        token['expires'] = token['now'] + token['valid'] - token['adjust']
        
        # Broadcast
        defs.announce(f"Deribit {token['action']} authentication successful, valid for {token['valid']} ms")
        
    else:
        # Get a new token or fail
        if token_stuck < 3:

            # Throw a warning and get a new token
            message = f"*** Warning S0002a: Authentication failed for the {token_stuck + 1} time: {data} ***"
            defs.log_error(message)
            
            # Get a new token
            defs.announce("Getting a new token, because it failed")
            token = new_token(token)

        else:
            # Too many authentication failures
            message = f"*** Error S0002b: Authentication failed three times: {data} ***"
            defs.log_error(message)
    
    # Return
    return token
    
# Get new token
def new_token(token):
    
    # Debug
    debug = False

    # Debug to stdout
    if debug:
        defs.announce("Debug: Getting new token")

    # Get new token
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
        if debug:
            defs.announce("Debug: Raw new token response:")
            pprint.pprint(data)
            print()
    except Exception as e:
        message = f"*** Error: S0001: Error when creating a new token: {e} ***"
        defs.log_error(message)
    
    # Extract token data and check validity
    token = extract_token_data(data, token)

    # Return token
    return token
    
# Refresh token
def refresh_token(token):
    
    # Debug
    debug = False

    # Debug to stdout
    if debug:
        defs.announce("Debug: Refreshing token")
    
    # Refresh token
    message = defs.announce("session: /public/auth")
    try:
        url    = config.api_url + "/public/auth"
        params = {
            "grant_type"   : "refresh_token",
            "refresh_token": str(token['refresh']),
            "client_id"    : str(config.api_key),
            "client_secret": str(config.api_secret)
        }
        response = requests.get(url, params=params)
        data = response.json()
        if debug:
            defs.announce("Debug: Raw refresh token response:")
            pprint.pprint(data)
            print()
    except Exception as e:
        
        # Throw warning
        message = f"*** Warning S0002: Warning when refreshing token: {e} ***"
        defs.log_error(message)
        
        # Get new token
        defs.announce("Requesting new token")
        token = new_token(token)

    # Extract token data and check validity
    token = extract_token_data(data, token)

    # Return token
    return token

# Authenticate at Deribit
def authenticate():
  
    # Debug
    debug = False
  
    # Debug to stdout
    if debug:
        defs.announce("Debug: Authenticating")
  
    # Initialize token
    token            = {}                   # All token data
    token['access']  = ""                   # Access token
    token['refresh'] = ""                   # Refresh token
    token['expires'] = 0                    # When will the token expiry
    token['adjust']  = 100                  # Subtract from expires
    token['action']  = "new"                # Get a new or refresh token
    token['now']     = defs.now_utc()[4]    # Current time
    
    # Initialize token in config if required
    try:
        config.access_token
        config.refresh_token
        config.token_expiration
    except AttributeError:
        config.access_token     = ""
        config.refresh_token    = ""
        config.token_expiration = 0
    
    # Fill token if possible
    if config.access_token and config.refresh_token and config.token_expiration:
        token['access']  = config.access_token
        token['refresh'] = config.refresh_token
        token['expires'] = config.token_expiration
       
    # Check if can keep old token
    if token['access'] and token['refresh'] and token['now'] < token['expires']:
        if debug: defs.announce("Debug: Reauthentication not required")
        return

    # Check if a new token is needed
    if not token['access'] or not token['refresh'] or not token['expires']:
        token['action'] = "new"
        
    # Check if we can just refresh the token
    if token['access'] and token['refresh'] and token['now'] > token['expires']:
        token['action'] = "refresh"

    # Get refreshed token
    if token['action'] == "refresh":
        token = refresh_token(token)

    # Get new token
    if token['action'] == "new":
        token = new_token(token)
    
    # Set token data
    token = set_token_data(token)

    # Debug to stdout
    if debug:
        defs.announce("Debug: This is our token data:")
        pprint.pprint(token)
        print()

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

# Get the actual code and message
def check_response(data):
    
    # Debug
    debug = False
    
    # Initialize variables
    skip = False
    
    # Get code and error
    try:
        code    = int(data['error']['code'])
        message = str(data['error']['message'])
    except KeyError:
        code    = 0
        message = ""
        skip    = True

    # Return    
    return code, message, skip