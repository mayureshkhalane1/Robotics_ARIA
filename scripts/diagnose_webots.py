#!/usr/bin/env python3
"""Diagnostic tool to check Webots TCP connection."""

import socket
import json
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.common.config import WEBOTS_HOST, WEBOTS_PORT, WEBOTS_TIMEOUT

def diagnose_connection():
    """Run comprehensive diagnostics on Webots connection."""
    print("\n" + "=" * 70)
    print("WEBOTS TCP CONNECTION DIAGNOSTIC")
    print("=" * 70)
    
    print(f"\nConfig:")
    print(f"  Host: {WEBOTS_HOST}")
    print(f"  Port: {WEBOTS_PORT}")
    print(f"  Timeout: {WEBOTS_TIMEOUT}s")
    
    # Step 1: Check if port is open (TCP SYN)
    print(f"\n[1] Checking if Webots is listening on {WEBOTS_HOST}:{WEBOTS_PORT}...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)  # Quick SYN timeout
        result = sock.connect_ex((WEBOTS_HOST, WEBOTS_PORT))
        sock.close()
        
        if result == 0:
            print(f"    ✓ Port is OPEN")
        else:
            print(f"    ✗ Port is CLOSED/FILTERED (error code: {result})")
            print(f"\n    FIX: Make sure Webots simulator is running with the TCP controller.")
            print(f"         Run: ./scripts/run_webots.sh")
            return False
    except socket.timeout:
        print(f"    ✗ Connection TIMEOUT (no response in 2s)")
        print(f"\n    FIX: Check if Webots is running and if firewall is blocking port {WEBOTS_PORT}")
        return False
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False
    
    # Step 2: Try to establish full TCP connection
    print(f"\n[2] Establishing full TCP connection...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(WEBOTS_TIMEOUT)
        sock.connect((WEBOTS_HOST, WEBOTS_PORT))
        print(f"    ✓ Connected successfully")
    except socket.timeout:
        print(f"    ✗ Connection timeout after {WEBOTS_TIMEOUT}s")
        print(f"\n    FIX: Webots controller is slow or hanging. Check:")
        print(f"         - Is Webots simulation running?")
        print(f"         - Is the TCP controller properly set up?")
        return False
    except Exception as e:
        print(f"    ✗ Connection failed: {e}")
        return False
    
    # Step 3: Send get_state command
    print(f"\n[3] Sending 'get_state' command...")
    try:
        cmd = {"cmd": "get_state"}
        cmd_json = json.dumps(cmd) + "\n"
        sock.sendall(cmd_json.encode("utf-8"))
        print(f"    ✓ Command sent: {cmd}")
        
        # Receive response
        print(f"\n[4] Waiting for response (timeout={WEBOTS_TIMEOUT}s)...")
        chunks = []
        start = time.time()
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                print(f"    ✗ Connection closed without response")
                break
            chunks.append(chunk)
            elapsed = time.time() - start
            data = b"".join(chunks).decode("utf-8")
            
            if "\n" in data:
                line = data.split("\n", 1)[0].strip()
                print(f"    ✓ Received response in {elapsed:.2f}s")
                try:
                    response = json.loads(line)
                    print(f"\n[5] Response parsed successfully:")
                    print(f"    {json.dumps(response, indent=2)}")
                    
                    # Check for errors in response
                    if response.get("status") == "error":
                        print(f"\n    ✗ Webots returned error: {response.get('message')}")
                        return False
                    
                    print(f"\n" + "=" * 70)
                    print("✓ WEBOTS CONNECTION IS WORKING CORRECTLY")
                    print("=" * 70 + "\n")
                    return True
                except json.JSONDecodeError as e:
                    print(f"    ✗ Failed to parse response: {e}")
                    print(f"       Raw response: {repr(line)}")
                    return False
                break
        
        if not chunks:
            print(f"    ✗ No response received")
            return False
            
    except socket.timeout:
        print(f"    ✗ Timeout waiting for response after {WEBOTS_TIMEOUT}s")
        print(f"\n    FIX: The Webots controller is not responding. Possible causes:")
        print(f"         - Webots simulation is paused")
        print(f"         - TCP controller script has errors")
        print(f"         - Robot sensors not properly initialized")
        return False
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False
    finally:
        try:
            sock.close()
        except:
            pass

if __name__ == "__main__":
    success = diagnose_connection()
    sys.exit(0 if success else 1)
