import asyncio
import json
import os
import sys
from datetime import datetime

HOST = os.getenv('ANGELIQUE_MT5_BRIDGE_HOST', '127.0.0.1')
PORT = int(os.getenv('ANGELIQUE_MT5_BRIDGE_PORT', '10001'))

def initialize_mt5():
    return {"status": "connected", "version": "5.0"}

def get_account_info():
    return {
        "login": 436885745,
        "balance": 500.0,
        "equity": 500.0,
        "free_margin": 500.0,
        "leverage": 2000
    }

async def handle_client(websocket, path=None):
    print(f" [Bridge] Client connected")
    try:
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")
            
            if action == "ping":
                response = {"status": "pong"}
            elif action == "get_account_info":
                response = get_account_info()
            else:
                response = {"error": f"Unknown action: {action}"}
            
            await websocket.send(json.dumps(response))
    except Exception as e:
        print(f" [Bridge] Error: {e}")
    finally:
        print(f" [Bridge] Client disconnected")

async def main():
    print(f"🚀 [Bridge] Starting MT5 Bridge Server on {HOST}:{PORT}")
    
    try:
        import websockets
        try:
            async with websockets.serve(handle_client, HOST, PORT, reuse_port=False):
                print(f"👂 [Bridge] Listening for commands...")
                await asyncio.Future()
        except OSError as bind_error:
            print(f"❌ [Bridge] Failed to bind to {HOST}:{PORT}: {bind_error}")
            print("   This usually means the port is already in use. Use a free port or stop the conflicting service.")
            sys.exit(1)
    except ImportError:
        print("⚠️ websockets not installed. Run: pip install websockets")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
