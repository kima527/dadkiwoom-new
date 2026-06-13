import os
import sys

# Add path to import config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import config

try:
    import kiwoom_rest_api
    print("kiwoom_rest_api is installed. Checking attributes...")
    print(dir(kiwoom_rest_api))
    
    # Try importing typical websocket classes
    try:
        from kiwoom_rest_api import WebSocketClient
        print("WebSocketClient imported successfully from root!")
    except ImportError:
        print("No WebSocketClient in root.")
        
    try:
        from kiwoom_rest_api.websocket.client import WebSocketClient
        print("WebSocketClient imported successfully from websocket.client!")
    except ImportError:
        print("No WebSocketClient in websocket.client.")
        
except Exception as e:
    print(f"Error: {e}")
