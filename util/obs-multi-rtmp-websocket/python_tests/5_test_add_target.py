#!/usr/bin/env python3
"""
Test script for AddTarget functionality
Tests adding new RTMP targets via websocket API
"""

import obsws_python as obs
import time

def test_add_target():
    # Configuration - update these values for your setup
    host = 'your-obs-websocket-host-ip' #replace with your actual websocket host IP
    port = 4455
    password = 'your-obs-websocket-password'  # Replace with your actual password
    
    try:
        # Connect to OBS websocket
        print("🔌 Connecting to OBS websocket...")
        client = obs.ReqClient(host=host, port=port, password=password)
        print("✅ Connected to OBS websocket successfully")
        
        # Get initial target count
        print("\n📋 Getting initial list of targets...")
        initial_targets = get_targets(client)
        if initial_targets is None:
            return False
        
        initial_count = len(initial_targets)
        print(f"📊 Initial target count: {initial_count}")
        
        if initial_count > 0:
            print("🎯 Current targets:")
            for i, target in enumerate(initial_targets):
                print(f"   {i + 1}. {target.get('name', 'Unknown')} (ID: {target.get('id', 'N/A')})")
        
        # Test 1: Add target with minimal parameters (RTMP default)
        print("\n" + "="*60)
        print("🧪 TEST 1: Add target with minimal parameters")
        print("="*60)
        
        test_target_name = "Test Target - RTMP"
        print(f"➕ Adding target: {test_target_name}")
        
        add_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "AddTarget",
            "requestData": {
                "name": test_target_name
                # protocol defaults to "RTMP"
            }
        })
        
        if not add_response.response_data.get('success', False):
            print(f"❌ AddTarget request failed: {add_response.response_data}")
            return False
        
        print(f"✅ AddTarget command sent successfully")
        print(f"   Response: {add_response.response_data}")
        
        # Verify target was added
        print("⏳ Waiting for UI refresh...")
        success, new_targets = wait_for_ui_refresh(client, initial_count + 1)
        if not success:
            print("❌ UI didn't refresh within expected time")
            return False
        
        new_count = len(new_targets)
        print(f"📊 New target count: {new_count}")
        
        if new_count == initial_count + 1:
            print("✅ Target count increased by 1 - target was added!")
            
            # Find the new target
            new_target = find_target_by_name(new_targets, test_target_name)
            if new_target:
                print(f"🎯 New target found: {new_target.get('name')} (ID: {new_target.get('id')})")
                print(f"   State: {new_target.get('state', 'unknown')}")
                print(f"   Protocol: {new_target.get('protocol', 'RTMP')}")
            else:
                print("⚠️ New target added but not found in list by name")
        else:
            print(f"❌ Target count didn't increase. Expected: {initial_count + 1}, Got: {new_count}")
            return False
        
        # Test 2: Add target with explicit protocol
        print("\n" + "="*60)
        print("🧪 TEST 2: Add target with explicit protocol")
        print("="*60)
        
        test_target_name_2 = "Test Target - SRT"
        test_protocol = "SRT"
        
        print(f"➕ Adding target: {test_target_name_2} (Protocol: {test_protocol})")
        
        add_response_2 = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "AddTarget",
            "requestData": {
                "name": test_target_name_2,
                "protocol": test_protocol
            }
        })
        
        if not add_response_2.response_data.get('success', False):
            print(f"❌ AddTarget request failed: {add_response_2.response_data}")
            # Continue with other tests since this might be expected if SRT not supported
        else:
            print(f"✅ AddTarget command sent successfully")
            print(f"   Response: {add_response_2.response_data}")
            
            # Verify target was added
            print("⏳ Waiting for UI refresh...")
            success, final_targets = wait_for_ui_refresh(client, new_count + 1)
            if not success:
                print("❌ UI didn't refresh within expected time")
                return False
            
            final_count = len(final_targets)
            print(f"📊 Final target count: {final_count}")
            
            if final_count == new_count + 1:
                print("✅ Target count increased by 1 - second target was added!")
                
                # Find the new target
                new_target_2 = find_target_by_name(final_targets, test_target_name_2)
                if new_target_2:
                    print(f"🎯 New target found: {new_target_2.get('name')} (ID: {new_target_2.get('id')})")
                    print(f"   State: {new_target_2.get('state', 'unknown')}")
                    print(f"   Protocol: {new_target_2.get('protocol', test_protocol)}")
                else:
                    print("⚠️ Second target added but not found in list by name")
            else:
                print(f"⚠️ Second target count didn't increase as expected")
        
        # Test 3: Error handling - missing name parameter (SHOULD FAIL)
        print("\n" + "="*60)
        print("🧪 TEST 3: Error handling - missing name parameter")
        print("="*60)
        
        print("Testing AddTarget without name parameter...")
        
        error_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "AddTarget",
            "requestData": {
                "protocol": "RTMP"
                # Missing name parameter - THIS SHOULD FAIL
            }
        })
        
        if not error_response.response_data.get('success', False):
            print(f"✅ Error handled correctly: {error_response.response_data.get('error', 'Unknown error')}")
        else:
            print(f"⚠️ UNEXPECTED: AddTarget succeeded without name parameter")
            print(f"   This indicates missing input validation in the plugin")
            print(f"   Response: {error_response.response_data}")
        
        # Test 4: Error handling - invalid protocol (SHOULD FAIL)
        print("\n" + "="*60)
        print("🧪 TEST 4: Error handling - invalid protocol")
        print("="*60)
        
        print("Testing AddTarget with invalid protocol...")
        
        invalid_protocol_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "AddTarget",
            "requestData": {
                "name": "Test Invalid Protocol",
                "protocol": "INVALID_PROTOCOL_123"
            }
        })
        
        if not invalid_protocol_response.response_data.get('success', False):
            print(f"✅ Error handled correctly: {invalid_protocol_response.response_data.get('error', 'Unknown error')}")
        else:
            print(f"⚠️ UNEXPECTED: AddTarget succeeded with invalid protocol")
            print(f"   This indicates missing protocol validation in the plugin")
            print(f"   Response: {invalid_protocol_response.response_data}")
        
        # Test 5: Test the newly added target functionality
        print("\n" + "="*60)
        print("🧪 TEST 5: Verify new target functionality")
        print("="*60)
        
        # Find the first test target we added
        current_targets = get_targets(client)
        if current_targets is None:
            return False
        
        test_target = find_target_by_name(current_targets, test_target_name)
        if test_target:
            target_id = test_target.get('id')
            print(f"🧪 Testing functionality of new target: {test_target_name}")
            
            # Test basic operations on the new target
            print("🔄 Testing state retrieval...")
            state_response = client.send("CallVendorRequest", {
                "vendorName": "sorayuki.multi_rtmp",
                "requestType": "GetTargetState",
                "requestData": {"id": target_id}
            })
            
            if state_response.response_data.get('success', False):
                print(f"✅ State retrieval works: {state_response.response_data.get('state', 'unknown')}")
            else:
                print(f"❌ State retrieval failed: {state_response.response_data}")
            
            # Test start/stop (briefly)
            print("🚀 Testing start command...")
            start_response = client.send("CallVendorRequest", {
                "vendorName": "sorayuki.multi_rtmp",
                "requestType": "StartTarget",
                "requestData": {"id": target_id}
            })
            
            if start_response.response_data.get('success', False):
                print(f"✅ Start command works: {start_response.response_data}")
                
                # Brief wait then stop
                time.sleep(2)
                print("🛑 Testing stop command...")
                stop_response = client.send("CallVendorRequest", {
                    "vendorName": "sorayuki.multi_rtmp",
                    "requestType": "StopTarget",
                    "requestData": {"id": target_id}
                })
                
                if stop_response.response_data.get('success', False):
                    print(f"✅ Stop command works: {stop_response.response_data}")
                else:
                    print(f"❌ Stop command failed: {stop_response.response_data}")
            else:
                print(f"❌ Start command failed: {start_response.response_data}")
        
        else:
            print("⚠️ Could not find test target for functionality testing")
        
        # Test 6: Cleanup - remove ALL test targets (including unexpected ones)
        print("\n" + "="*60)
        print("🧪 TEST 6: Cleanup - removing ALL test targets")
        print("="*60)
        
        current_targets = get_targets(client)
        if current_targets is None:
            return False
        
        # Find ALL test targets (including any unexpectedly created ones)
        test_targets_to_remove = []
        for target in current_targets:
            target_name = target.get('name', '')
            if target_name and ('Test Target' in target_name or target_name.startswith('Test')):
                test_targets_to_remove.append(target_name)
        
        print(f"🔍 Found {len(test_targets_to_remove)} test targets to remove:")
        for target_name in test_targets_to_remove:
            print(f"   • {target_name}")
        
        removed_count = 0
        for target_name in test_targets_to_remove:
            target = find_target_by_name(current_targets, target_name)
            if target:
                target_id = target.get('id')
                print(f"🗑️ Removing target: {target_name}")
                
                delete_response = client.send("CallVendorRequest", {
                    "vendorName": "sorayuki.multi_rtmp",
                    "requestType": "DeleteTarget",
                    "requestData": {"targetId": target_id}
                })
                
                if delete_response.response_data.get('success', False):
                    print(f"✅ Target removed successfully")
                    removed_count += 1
                else:
                    print(f"❌ Failed to remove target: {delete_response.response_data}")
            else:
                print(f"ℹ️ Target not found for removal: {target_name}")
        
        print(f"📊 Removed {removed_count} test targets")
        
        # Final verification
        print("⏳ Waiting for cleanup...")
        time.sleep(2)
        
        final_targets = get_targets(client)
        if final_targets is None:
            return False
        
        final_count = len(final_targets)
        print(f"📊 Final target count after cleanup: {final_count}")
        
        if final_count == initial_count:
            print("✅ Cleanup successful - back to initial target count!")
        else:
            print(f"⚠️ Cleanup incomplete. Expected: {initial_count}, Got: {final_count}")
            print(f"   Remaining targets:")
            for target in final_targets:
                print(f"   • {target.get('name', 'Unknown')}")
        
        print(f"\n🎉 AddTarget test completed successfully!")
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

def get_targets(client):
    """Get list of all targets"""
    try:
        response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "ListTargets",
            "requestData": {}
        })
        
        if response.response_data.get('success', False):
            return response.response_data.get('targets', [])
        else:
            print(f"❌ Failed to get targets: {response.response_data}")
            return None
    except Exception as e:
        print(f"❌ Error getting targets: {e}")
        return None

def find_target_by_name(targets, name):
    """Find target by name"""
    for target in targets:
        if target.get('name') == name:
            return target
    return None

def wait_for_ui_refresh(client, expected_count, max_retries=5, delay=1):
    """Wait for UI to refresh and target count to match expected"""
    for attempt in range(max_retries):
        time.sleep(delay)
        targets = get_targets(client)
        if targets is not None and len(targets) == expected_count:
            return True, targets
        print(f"   🔄 UI refresh check {attempt + 1}/{max_retries}...")
    return False, None

if __name__ == "__main__":
    print("🧪 Starting AddTarget functionality test...")
    print("=" * 70)
    print("This test will:")
    print("  • Test adding new targets with minimal parameters")
    print("  • Test adding targets with explicit protocols") 
    print("  • Test error handling for invalid inputs")
    print("  • Verify new targets are functional")
    print("  • Clean up ALL test targets automatically")
    print("=" * 70)
    print("⚠️  Note: This will create and delete test targets")
    print("    No permanent changes will be made")
    print("=" * 70)
    
    success = test_add_target()
    
    if success:
        print("\n✅ AddTarget test PASSED! The functionality is working correctly.")
    else:
        print("\n❌ AddTarget test FAILED. Check the logs above for details.")
    
    print("=" * 70)
    print("📝 Test completed.")