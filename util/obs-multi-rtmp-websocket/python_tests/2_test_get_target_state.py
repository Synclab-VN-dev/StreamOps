#!/usr/bin/env python3
"""
Test script for GetTargetState functionality
Tests retrieving the state of specific RTMP targets
"""

import obsws_python as obs
import time

def test_get_target_state():
    # Configuration - update these values for your setup
    host = 'your-obs-websocket-host-ip' #replace with your actual websocket host IP
    port = 4455
    password = 'your-obs-websocket-password'  # Replace with your actual password
    
    try:
        # Connect to OBS websocket
        print("🔌 Connecting to OBS websocket...")
        client = obs.ReqClient(host=host, port=port, password=password)
        print("✅ Connected to OBS websocket successfully")
        
        # First, get list of targets to test with
        print("\n📋 Getting list of targets...")
        list_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "ListTargets",
            "requestData": {}
        })
        
        if not list_response.response_data.get('success', False):
            print(f"❌ Failed to list targets: {list_response.response_data}")
            return False
        
        targets = list_response.response_data.get('targets', [])
        print(f"📊 Found {len(targets)} target(s)")
        
        if not targets:
            print("ℹ️ No targets configured, skipping GetTargetState test")
            return True
        
        # Display available targets
        print("\n🎯 Available targets:")
        for i, target in enumerate(targets):
            print(f"   {i + 1}. ID: {target.get('id', 'N/A')}, Name: {target.get('name', 'N/A')}")
        
        # Test 1: Get state by ID (primary test)
        print("\n" + "="*50)
        print("🧪 TEST 1: Get target state by ID")
        print("="*50)
        
        for i, target in enumerate(targets):
            target_id = target.get('id')
            target_name = target.get('name', 'Unknown')
            
            print(f"Testing target {i + 1}: {target_name} (ID: {target_id})")
            
            state_response = client.send("CallVendorRequest", {
                "vendorName": "sorayuki.multi_rtmp",
                "requestType": "GetTargetState",
                "requestData": {"id": target_id}
            })
            
            if not state_response.response_data.get('success', False):
                print(f"❌ GetTargetState request failed: {state_response.response_data}")
                return False
            
            print(f"✅ State: {state_response.response_data.get('state', 'unknown')}")
            print(f"   Response: {state_response.response_data}")
            print("-" * 30)
        
        # Test 2: Get state by name (check if implemented)
        print("\n" + "="*50)
        print("🧪 TEST 2: Check if name lookup is supported")
        print("="*50)
        
        first_target = targets[0]
        target_name = first_target.get('name', 'Unknown')
        
        print(f"Testing name lookup for: {target_name}")
        
        state_response2 = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "GetTargetState",
            "requestData": {"name": target_name}
        })
        
        if state_response2.response_data.get('success', False):
            print(f"✅ Name lookup IS supported!")
            print(f"   Target ID: {state_response2.response_data.get('id', 'N/A')}")
            print(f"   Target Name: {state_response2.response_data.get('name', 'N/A')}")
            print(f"   Current State: {state_response2.response_data.get('state', 'unknown')}")
        else:
            print(f"ℹ️ Name lookup is NOT supported (expected behavior)")
            print(f"   Error: {state_response2.response_data.get('error', 'Unknown error')}")
            print("   This is normal if the plugin only supports ID-based lookup")
        
        # Test 3: Error case - invalid target ID
        print("\n" + "="*50)
        print("🧪 TEST 3: Error handling - invalid target ID")
        print("="*50)
        
        error_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "GetTargetState",
            "requestData": {"id": "invalid_target_id_12345"}
        })
        
        if not error_response.response_data.get('success', False):
            print(f"✅ Expected error handled correctly: {error_response.response_data.get('error', 'Unknown error')}")
        else:
            print(f"⚠️ Unexpected: Invalid target ID request succeeded: {error_response.response_data}")
        
        # Test 4: Error case - missing parameters
        print("\n" + "="*50)
        print("🧪 TEST 4: Error handling - missing parameters")
        print("="*50)
        
        missing_params_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "GetTargetState",
            "requestData": {}  # No id or name provided
        })
        
        if not missing_params_response.response_data.get('success', False):
            print(f"✅ Expected error handled correctly: {missing_params_response.response_data.get('error', 'Unknown error')}")
        else:
            print(f"⚠️ Unexpected: Missing parameters request succeeded: {missing_params_response.response_data}")
        
        # Test 5: Response structure validation
        print("\n" + "="*50)
        print("🧪 TEST 5: Response structure validation")
        print("="*50)
        
        # Use the first successful response for validation
        state_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "GetTargetState",
            "requestData": {"id": targets[0].get('id')}
        })
        
        expected_fields = ['id', 'name', 'state', 'success']
        response_data = state_response.response_data
        
        print("Checking response structure...")
        for field in expected_fields:
            if field in response_data:
                print(f"✅ Field '{field}': {response_data[field]}")
            else:
                print(f"⚠️ Missing field: '{field}'")
        
        # Validate state values
        valid_states = ['stopped', 'running', 'connecting', 'reconnecting', 'stopping']
        actual_state = response_data.get('state', '')
        
        if actual_state and actual_state not in valid_states:
            print(f"⚠️ Unexpected state value: {actual_state}")
        else:
            print(f"✅ State value is valid: {actual_state}")
        
        print(f"\n🎉 GetTargetState test completed successfully!")
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
    print("🧪 Starting GetTargetState functionality test...")
    print("=" * 60)
    print("This test will:")
    print("  • Get target state by ID for ALL targets")
    print("  • Check if name lookup is supported")
    print("  • Test error handling for invalid inputs")
    print("  • Validate response structure")
    print("=" * 60)
    
    success = test_get_target_state()
    
    if success:
        print("\n✅ GetTargetState test PASSED! The functionality is working correctly.")
    else:
        print("\n❌ GetTargetState test FAILED. Check the logs above for details.")
    
    print("=" * 60)
    print("📝 Test completed.")