#!/usr/bin/env python3
"""
Test script for ListTargets functionality
Tests the basic listing of all configured RTMP targets
"""

import obsws_python as obs
import time

def test_list_targets():
    # Configuration - update these values for your setup
    host = 'your-obs-websocket-host-ip' #replace with your actual websocket host IP
    port = 4455
    password = 'your-obs-websocket-password'  # Replace with your actual password
    
    try:
        # Connect to OBS websocket
        print("🔌 Connecting to OBS websocket...")
        client = obs.ReqClient(host=host, port=port, password=password)
        print("✅ Connected to OBS websocket successfully")
        
        # Test ListTargets request
        print("\n📋 Testing ListTargets request...")
        response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "ListTargets",
            "requestData": {}
        })
        
        # Check if request was successful
        if not response.response_data.get('success', False):
            print(f"❌ ListTargets request failed: {response.response_data}")
            return False
        
        # Extract and display targets
        targets = response.response_data.get('targets', [])
        print(f"✅ ListTargets successful! Found {len(targets)} target(s)")
        
        if not targets:
            print("ℹ️ No targets configured")
            return True
        
        print("\n📊 Target Details:")
        print("-" * 60)
        for i, target in enumerate(targets):
            print(f"🎯 Target #{i + 1}:")
            print(f"   ID: {target.get('id', 'N/A')}")
            print(f"   Name: {target.get('name', 'N/A')}")
            print(f"   State: {target.get('state', 'unknown')}")
            print(f"   Protocol: {target.get('protocol', 'N/A')}")
            print("-" * 60)
        
        # Test with some additional verification
        print("\n🧪 Additional verification tests:")
        
        # Test 1: Check response structure
        has_targets_array = 'targets' in response.response_data
        has_success_field = 'success' in response.response_data
        print(f"✅ Response contains targets array: {has_targets_array}")
        print(f"✅ Response contains success field: {has_success_field}")
        
        # Test 2: Verify target object structure
        if targets:
            first_target = targets[0]
            expected_fields = ['id', 'name', 'state']
            missing_fields = [field for field in expected_fields if field not in first_target]
            
            if missing_fields:
                print(f"⚠️ Missing fields in target object: {missing_fields}")
            else:
                print("✅ Target objects have all expected fields")
        
        # Test 3: Verify all targets have valid states
        valid_states = ['stopped', 'running', 'connecting', 'reconnecting']
        invalid_states = []
        
        for target in targets:
            state = target.get('state', '')
            if state and state not in valid_states:
                invalid_states.append(f"{target.get('name')}: {state}")
        
        if invalid_states:
            print(f"⚠️ Targets with unexpected states: {invalid_states}")
        else:
            print("✅ All targets have valid state values")
        
        print(f"\n🎉 ListTargets test completed successfully!")
        return True
        
    except obs.error.OBSSDKRequestError as e:
        print(f"❌ OBS SDK Request Error: {e}")
        return False
    except obs.error.OBSSDKError as e:
        print(f"❌ OBS SDK Error: {e}")
        return False
    except ConnectionRefusedError:
        print("❌ Connection refused. Make sure OBS is running and websocket server is enabled.")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Starting ListTargets functionality test...")
    print("=" * 50)
    
    success = test_list_targets()
    
    if success:
        print("\n✅ ListTargets test PASSED! The functionality is working correctly.")
    else:
        print("\n❌ ListTargets test FAILED. Check the logs above for details.")
    
    print("=" * 50)
    print("📝 Test completed.")