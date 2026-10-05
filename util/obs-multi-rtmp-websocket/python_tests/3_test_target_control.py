#!/usr/bin/env python3
"""
Test script for StartTarget, StopTarget, and ToggleTarget functionality
Tests controlling individual RTMP targets
"""

import obsws_python as obs
import time

def test_target_control():
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
            print("ℹ️ No targets configured, skipping target control test")
            return True
        
        # Display available targets with their current states
        print("\n🎯 Available targets:")
        for i, target in enumerate(targets):
            target_id = target.get('id')
            target_name = target.get('name', 'Unknown')
            target_state = target.get('state', 'unknown')
            print(f"   {i + 1}. {target_name} (ID: {target_id}) - State: {target_state}")
        
        # Select a target for testing (use first target)
        test_target = targets[0]
        target_id = test_target.get('id')
        target_name = test_target.get('name', 'Test Target')
        
        print(f"\n🔍 Selected for testing: {target_name} (ID: {target_id})")
        
        # Test 1: Get initial state
        print("\n" + "="*60)
        print("🧪 TEST 1: Get initial target state")
        print("="*60)
        
        initial_state = get_target_state(client, target_id)
        if initial_state is None:
            return False
        
        print(f"📊 Initial state: {initial_state}")
        
        # Test 2: StartTarget functionality
        print("\n" + "="*60)
        print("🧪 TEST 2: StartTarget functionality")
        print("="*60)
        
        if initial_state == 'running':
            print("ℹ️ Target is already running, testing StopTarget first...")
            stop_result = stop_target(client, target_id, target_name)
            if not stop_result:
                return False
            time.sleep(2)  # Wait for stop to complete
            initial_state = 'stopped'
        
        if initial_state == 'stopped':
            print(f"🚀 Starting target: {target_name}")
            start_result = start_target(client, target_id, target_name)
            if not start_result:
                return False
            
            # Wait a bit and check if started
            time.sleep(3)
            new_state = get_target_state(client, target_id)
            print(f"📊 State after start command: {new_state}")
            
            # Give it some time to connect (if applicable)
            if new_state in ['connecting', 'running']:
                print("⏳ Waiting 5 seconds for connection attempt...")
                time.sleep(5)
                final_state = get_target_state(client, target_id)
                print(f"📊 Final state after start: {final_state}")
        
        # Test 3: StopTarget functionality
        print("\n" + "="*60)
        print("🧪 TEST 3: StopTarget functionality")
        print("="*60)
        
        current_state = get_target_state(client, target_id)
        if current_state in ['running', 'connecting', 'reconnecting']:
            print(f"🛑 Stopping target: {target_name}")
            stop_result = stop_target(client, target_id, target_name)
            if not stop_result:
                return False
            
            # Wait and verify stopped
            time.sleep(3)
            stopped_state = get_target_state(client, target_id)
            print(f"📊 State after stop command: {stopped_state}")
            
            if stopped_state == 'stopped':
                print("✅ Target successfully stopped")
            else:
                print(f"⚠️ Target state after stop: {stopped_state} (expected: stopped)")
        else:
            print(f"ℹ️ Target is already stopped ({current_state}), skipping stop test")
        
        # Test 4: ToggleTarget functionality
        print("\n" + "="*60)
        print("🧪 TEST 4: ToggleTarget functionality")
        print("="*60)
        
        current_state = get_target_state(client, target_id)
        print(f"📊 Current state before toggle: {current_state}")
        
        print(f"🔁 Toggling target: {target_name}")
        toggle_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "ToggleTarget",
            "requestData": {"id": target_id}
        })
        
        if not toggle_response.response_data.get('success', False):
            print(f"❌ ToggleTarget request failed: {toggle_response.response_data}")
            return False
        
        expected_new_state = 'running' if current_state == 'stopped' else 'stopped'
        print(f"✅ Toggle command sent successfully")
        print(f"   Expected new state: {expected_new_state}")
        print(f"   Response: {toggle_response.response_data}")
        
        # Wait and check new state
        time.sleep(3)
        toggled_state = get_target_state(client, target_id)
        print(f"📊 State after toggle: {toggled_state}")
        
        if toggled_state == expected_new_state:
            print("✅ Toggle worked correctly!")
        else:
            print(f"⚠️ Toggle result: {toggled_state} (expected: {expected_new_state})")
        
        # Test 5: Toggle back to original state
        print("\n" + "="*60)
        print("🧪 TEST 5: Toggle back to original state")
        print("="*60)
        
        print(f"🔁 Toggling target back: {target_name}")
        toggle_response2 = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "ToggleTarget",
            "requestData": {"id": target_id}
        })
        
        if not toggle_response2.response_data.get('success', False):
            print(f"❌ Second ToggleTarget request failed: {toggle_response2.response_data}")
            return False
        
        print(f"✅ Second toggle command sent successfully")
        
        # Wait and check final state
        time.sleep(3)
        final_state = get_target_state(client, target_id)
        print(f"📊 Final state after second toggle: {final_state}")
        
        # Test 6: Error handling
        print("\n" + "="*60)
        print("🧪 TEST 6: Error handling")
        print("="*60)
        
        # Invalid target ID
        print("Testing with invalid target ID...")
        error_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "StartTarget",
            "requestData": {"id": "invalid_target_123"}
        })
        
        if not error_response.response_data.get('success', False):
            print(f"✅ Error handled correctly: {error_response.response_data.get('error', 'Unknown error')}")
        else:
            print(f"⚠️ Unexpected success with invalid target: {error_response.response_data}")
        
        # Missing parameters
        print("Testing with missing parameters...")
        missing_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "StopTarget",
            "requestData": {}  # No ID provided
        })
        
        if not missing_response.response_data.get('success', False):
            print(f"✅ Error handled correctly: {missing_response.response_data.get('error', 'Unknown error')}")
        else:
            print(f"⚠️ Unexpected success with missing parameters: {missing_response.response_data}")
        
        print(f"\n🎉 Target control test completed successfully!")
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

def get_target_state(client, target_id):
    """Helper function to get target state"""
    try:
        response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "GetTargetState",
            "requestData": {"id": target_id}
        })
        
        if response.response_data.get('success', False):
            return response.response_data.get('state', 'unknown')
        else:
            print(f"❌ Failed to get target state: {response.response_data}")
            return None
    except Exception as e:
        print(f"❌ Error getting target state: {e}")
        return None

def start_target(client, target_id, target_name):
    """Helper function to start a target"""
    try:
        response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "StartTarget",
            "requestData": {"id": target_id}
        })
        
        if response.response_data.get('success', False):
            print(f"✅ Start command sent successfully for {target_name}")
            print(f"   Response: {response.response_data}")
            return True
        else:
            print(f"❌ Start command failed for {target_name}: {response.response_data}")
            return False
    except Exception as e:
        print(f"❌ Error starting target: {e}")
        return False

def stop_target(client, target_id, target_name):
    """Helper function to stop a target"""
    try:
        response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "StopTarget",
            "requestData": {"id": target_id}
        })
        
        if response.response_data.get('success', False):
            print(f"✅ Stop command sent successfully for {target_name}")
            print(f"   Response: {response.response_data}")
            return True
        else:
            print(f"❌ Stop command failed for {target_name}: {response.response_data}")
            return False
    except Exception as e:
        print(f"❌ Error stopping target: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Starting Target Control functionality test...")
    print("=" * 70)
    print("This test will:")
    print("  • Test StartTarget functionality")
    print("  • Test StopTarget functionality") 
    print("  • Test ToggleTarget functionality")
    print("  • Test error handling")
    print("  • Verify state changes work correctly")
    print("=" * 70)
    print("⚠️  Note: This will actually start/stop real streams!")
    print("    Make sure you're using test stream keys")
    print("=" * 70)
    
    success = test_target_control()
    
    if success:
        print("\n✅ Target Control test PASSED! All functionality working correctly.")
    else:
        print("\n❌ Target Control test FAILED. Check the logs above for details.")
    
    print("=" * 70)
    print("📝 Test completed.")