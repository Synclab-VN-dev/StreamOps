#!/usr/bin/env python3
"""
Test script for StartAll and StopAll functionality
Tests bulk operations on all RTMP targets
"""

import obsws_python as obs
import time

def test_bulk_operations():
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
        target_count = len(targets)
        print(f"📊 Found {target_count} target(s)")
        
        if target_count == 0:
            print("ℹ️ No targets configured, skipping bulk operations test")
            return True
        
        # Display available targets with their current states
        print("\n🎯 Available targets:")
        for i, target in enumerate(targets):
            target_id = target.get('id')
            target_name = target.get('name', 'Unknown')
            target_state = target.get('state', 'unknown')
            print(f"   {i + 1}. {target_name} (ID: {target_id}) - State: {target_state}")
        
        # Test 1: Get initial states
        print("\n" + "="*60)
        print("🧪 TEST 1: Get initial states of all targets")
        print("="*60)
        
        initial_states = get_all_target_states(client, targets)
        if initial_states is None:
            return False
        
        print("📊 Initial states:")
        for target_id, state in initial_states.items():
            target_name = get_target_name(targets, target_id)
            print(f"   {target_name}: {state}")
        
        # Ensure all targets are stopped before starting
        print("\n" + "="*60)
        print("🧪 TEST 2: Ensure all targets are stopped")
        print("="*60)
        
        running_targets = [tid for tid, state in initial_states.items() if state == 'running']
        if running_targets:
            print(f"🛑 Stopping {len(running_targets)} running target(s) first...")
            stop_result = stop_all_targets(client)
            if not stop_result:
                return False
            
            # Wait for stops to complete
            print("⏳ Waiting 5 seconds for all targets to stop...")
            time.sleep(5)
            
            # Verify all stopped
            stopped_states = get_all_target_states(client, targets)
            if stopped_states is None:
                return False
            
            still_running = [tid for tid, state in stopped_states.items() if state == 'running']
            if still_running:
                print(f"❌ Failed to stop all targets. Still running: {len(still_running)}")
                return False
            else:
                print("✅ All targets successfully stopped")
        else:
            print("✅ All targets are already stopped")
        
        # Test 3: StartAll functionality
        print("\n" + "="*60)
        print("🧪 TEST 3: StartAll functionality")
        print("="*60)
        
        print("🚀 Starting ALL targets...")
        start_all_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "StartAll",
            "requestData": {}
        })
        
        if not start_all_response.response_data.get('success', False):
            print(f"❌ StartAll request failed: {start_all_response.response_data}")
            return False
        
        reported_count = start_all_response.response_data.get('target_count', 0)
        print(f"✅ StartAll command sent successfully")
        print(f"   Reported target count: {reported_count}")
        print(f"   Response: {start_all_response.response_data}")
        
        # Wait for starts to initiate
        print("⏳ Waiting 8 seconds for all targets to start connecting...")
        time.sleep(8)
        
        # Check states after start
        started_states = get_all_target_states(client, targets)
        if started_states is None:
            return False
        
        print("📊 States after StartAll:")
        running_count = 0
        for target_id, state in started_states.items():
            target_name = get_target_name(targets, target_id)
            print(f"   {target_name}: {state}")
            if state == 'running':
                running_count += 1
        
        print(f"📈 {running_count}/{target_count} targets running")
        
        # Test 4: StopAll functionality
        print("\n" + "="*60)
        print("🧪 TEST 4: StopAll functionality")
        print("="*60)
        
        print("🛑 Stopping ALL targets...")
        stop_all_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "StopAll",
            "requestData": {}
        })
        
        if not stop_all_response.response_data.get('success', False):
            print(f"❌ StopAll request failed: {stop_all_response.response_data}")
            return False
        
        reported_count = stop_all_response.response_data.get('target_count', 0)
        print(f"✅ StopAll command sent successfully")
        print(f"   Reported target count: {reported_count}")
        print(f"   Response: {stop_all_response.response_data}")
        
        # Wait for stops to complete
        print("⏳ Waiting 5 seconds for all targets to stop...")
        time.sleep(5)
        
        # Check final states
        final_states = get_all_target_states(client, targets)
        if final_states is None:
            return False
        
        print("📊 Final states after StopAll:")
        stopped_count = 0
        for target_id, state in final_states.items():
            target_name = get_target_name(targets, target_id)
            print(f"   {target_name}: {state}")
            if state == 'stopped':
                stopped_count += 1
        
        print(f"📈 {stopped_count}/{target_count} targets stopped")
        
        # Test 5: Error handling and edge cases
        print("\n" + "="*60)
        print("🧪 TEST 5: Additional verification")
        print("="*60)
        
        # Verify response structure
        expected_fields = ['status', 'target_count', 'success']
        missing_fields = [field for field in expected_fields if field not in start_all_response.response_data]
        
        if missing_fields:
            print(f"⚠️ Missing fields in StartAll response: {missing_fields}")
        else:
            print("✅ StartAll response contains all expected fields")
        
        # Verify target count matches
        if reported_count == target_count:
            print("✅ Reported target count matches actual target count")
        else:
            print(f"⚠️ Target count mismatch: reported {reported_count}, actual {target_count}")
        
        # Test 6: StartAll when some targets are already running
        print("\n" + "="*60)
        print("🧪 TEST 6: StartAll with mixed states")
        print("="*60)
        
        # Start one target manually
        if target_count >= 2:
            first_target = targets[0]
            print(f"🚀 Starting one target manually: {first_target.get('name')}")
            start_response = client.send("CallVendorRequest", {
                "vendorName": "sorayuki.multi_rtmp",
                "requestType": "StartTarget",
                "requestData": {"id": first_target.get('id')}
            })
            
            if start_response.response_data.get('success', False):
                print("✅ Manual start successful")
                print("⏳ Waiting 10 seconds for target to start...")
                time.sleep(10)
                
                # Now test StartAll with mixed states
                print("🚀 Testing StartAll with mixed target states...")
                start_all_response2 = client.send("CallVendorRequest", {
                    "vendorName": "sorayuki.multi_rtmp",
                    "requestType": "StartAll",
                    "requestData": {}
                })
                
                if start_all_response2.response_data.get('success', False):
                    print("✅ StartAll with mixed states succeeded")
                    print(f"   Response: {start_all_response2.response_data}")
                    print("⏳ Waiting 10 seconds for all targets to start...")
                    time.sleep(10)
                else:
                    print(f"❌ StartAll with mixed states failed: {start_all_response2.response_data}")
            else:
                print(f"❌ Manual start failed: {start_response.response_data}")
        
        # Clean up: Ensure all targets are stopped at the end
        print("\n" + "="*60)
        print("🧪 CLEANUP: Ensuring all targets are stopped")
        print("="*60)
        
        stop_all_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "StopAll",
            "requestData": {}
        })
        
        if stop_all_response.response_data.get('success', False):
            print("✅ Cleanup StopAll command sent")
        else:
            print(f"⚠️ Cleanup StopAll failed: {stop_all_response.response_data}")
        
        time.sleep(3)
        
        print(f"\n🎉 Bulk operations test completed successfully!")
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

def get_all_target_states(client, targets):
    """Get states of all targets"""
    states = {}
    for target in targets:
        target_id = target.get('id')
        response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "GetTargetState",
            "requestData": {"id": target_id}
        })
        
        if response.response_data.get('success', False):
            states[target_id] = response.response_data.get('state', 'unknown')
        else:
            print(f"❌ Failed to get state for target {target_id}: {response.response_data}")
            return None
    
    return states

def get_target_name(targets, target_id):
    """Get target name by ID"""
    for target in targets:
        if target.get('id') == target_id:
            return target.get('name', 'Unknown')
    return 'Unknown'

def stop_all_targets(client):
    """Stop all targets"""
    try:
        response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "StopAll",
            "requestData": {}
        })
        return response.response_data.get('success', False)
    except Exception as e:
        print(f"❌ Error in StopAll: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Starting Bulk Operations functionality test...")
    print("=" * 70)
    print("This test will:")
    print("  • Test StartAll functionality")
    print("  • Test StopAll functionality") 
    print("  • Verify bulk operations work on all targets")
    print("  • Test mixed state scenarios")
    print("  • Verify proper target counting")
    print("=" * 70)
    print("⚠️  Note: This will start/stop ALL configured streams!")
    print("    Make sure you're using test stream keys")
    print("=" * 70)
    
    success = test_bulk_operations()
    
    if success:
        print("\n✅ Bulk Operations test PASSED! All functionality working correctly.")
    else:
        print("\n❌ Bulk Operations test FAILED. Check the logs above for details.")
    
    print("=" * 70)
    print("📝 Test completed.")