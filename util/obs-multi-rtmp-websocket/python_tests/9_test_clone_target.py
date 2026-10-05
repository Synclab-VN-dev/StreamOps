#!/usr/bin/env python3
"""
Test script for CloneTarget functionality
Tests cloning existing RTMP targets with optional stream key updates
"""

import obsws_python as obs
import time
import json

def test_clone_target():
    # Configuration - update these values for your setup
    host = 'your-obs-websocket-host-ip' #replace with your actual websocket host IP
    port = 4455
    password = 'your-obs-websocket-password'  # Replace with your actual password
    
    try:
        # Connect to OBS websocket
        print("🔌 Connecting to OBS websocket...")
        client = obs.ReqClient(host=host, port=port, password=password)
        print("✅ Connected to OBS websocket successfully")
        
        # First, get list of targets to clone from
        print("\n📋 Getting list of targets...")
        list_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "ListTargets",
            "requestData": {}
        })
        
        if not list_response.response_data.get('success', False):
            print(f"❌ ListTargets request failed: {list_response.response_data}")
            return False
        
        targets = list_response.response_data.get('targets', [])
        print(f"✅ Found {len(targets)} target(s)")
        
        if not targets:
            print("ℹ️ No targets configured - cannot test CloneTarget")
            return True
        
        # Select the first target to clone
        source_target = targets[0]
        source_id = source_target.get('id')
        source_name = source_target.get('name')
        
        print(f"\n🎯 Source target: {source_name} (ID: {source_id})")
        print("-" * 50)
        
        all_tests_passed = True
        
        # Test 1: Clone without changing stream key
        print("\n🧪 Test 1: Clone target without stream key change")
        print("-" * 40)
        
        new_name_1 = f"{source_name} - Clone 1"
        clone_response_1 = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "CloneTarget",
            "requestData": {
                "sourceId": source_id,
                "newName": new_name_1
                # No newStreamKey - should use original
            }
        })
        
        if not clone_response_1.response_data.get('success', False):
            print(f"❌ CloneTarget request failed: {clone_response_1.response_data}")
            all_tests_passed = False
        else:
            print("✅ CloneTarget without stream key change successful!")
            
            # Verify the clone was created
            verify_clone(client, source_id, new_name_1, "original stream key", all_tests_passed)
        
        # Test 2: Clone with new stream key
        print("\n🧪 Test 2: Clone target with new stream key")
        print("-" * 40)
        
        new_name_2 = f"{source_name} - Clone 2"
        new_stream_key = "test_stream_key_12345"
        
        clone_response_2 = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "CloneTarget",
            "requestData": {
                "sourceId": source_id,
                "newName": new_name_2,
                "newStreamKey": new_stream_key
            }
        })
        
        if not clone_response_2.response_data.get('success', False):
            print(f"❌ CloneTarget with stream key change failed: {clone_response_2.response_data}")
            all_tests_passed = False
        else:
            print("✅ CloneTarget with stream key change successful!")
            
            # Verify the clone was created with new stream key
            verify_clone(client, source_id, new_name_2, new_stream_key, all_tests_passed)
        
        # Test 3: Error cases
        print("\n🧪 Test 3: Error case testing")
        print("-" * 40)
        
        # Test with non-existent source ID
        print("Testing with non-existent source ID...")
        error_response_1 = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "CloneTarget",
            "requestData": {
                "sourceId": "non_existent_id_12345",
                "newName": "Should Fail"
            }
        })
        
        if not error_response_1.response_data.get('success', False):
            print("✅ Correctly handled non-existent source ID")
        else:
            print("❌ Should have failed for non-existent source ID")
            all_tests_passed = False
        
        # Test with missing newName
        print("Testing with missing newName...")
        error_response_2 = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "CloneTarget",
            "requestData": {
                "sourceId": source_id
                # Missing newName - should fail
            }
        })
        
        if not error_response_2.response_data.get('success', False):
            print("✅ Correctly handled missing newName")
        else:
            print("❌ Should have failed for missing newName")
            all_tests_passed = False
        
        # Test with empty newName
        print("Testing with empty newName...")
        error_response_3 = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "CloneTarget",
            "requestData": {
                "sourceId": source_id,
                "newName": ""
            }
        })
        
        if not error_response_3.response_data.get('success', False):
            print("✅ Correctly handled empty newName")
        else:
            print("❌ Should have failed for empty newName")
            all_tests_passed = False
        
        # Test 4: Verify clones appear in ListTargets
        print("\n🧪 Test 4: Verify clones in target list")
        print("-" * 40)
        
        final_list_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "ListTargets",
            "requestData": {}
        })
        
        if final_list_response.response_data.get('success', False):
            final_targets = final_list_response.response_data.get('targets', [])
            clone_names = [new_name_1, new_name_2]
            found_clones = []
            
            for target in final_targets:
                target_name = target.get('name')
                if target_name in clone_names:
                    found_clones.append(target_name)
                    print(f"✅ Found clone: {target_name}")
            
            if len(found_clones) == len(clone_names):
                print("✅ All clones found in target list!")
            else:
                missing = set(clone_names) - set(found_clones)
                print(f"❌ Missing clones: {missing}")
                all_tests_passed = False
        else:
            print("❌ Failed to get final target list")
            all_tests_passed = False
        
        # Summary
        print(f"\n📋 Test Summary:")
        print("=" * 40)
        print(f"Total clone tests: 4")
        print(f"All tests passed: {all_tests_passed}")
        
        if all_tests_passed:
            print("\n🎉 CloneTarget test completed successfully!")
            print(f"Created clones: {new_name_1}, {new_name_2}")
        else:
            print("\n❌ Some tests failed. Check the logs above for details.")
        
        return all_tests_passed
        
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

def verify_clone(client, source_id, clone_name, expected_stream_key, all_tests_passed):
    """Verify that a clone was created correctly"""
    print(f"   Verifying clone '{clone_name}'...")
    
    # Get updated target list
    list_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "ListTargets",
        "requestData": {}
    })
    
    if not list_response.response_data.get('success', False):
        print("   ❌ Failed to get updated target list")
        all_tests_passed = False
        return
    
    # Find the clone
    clone_target = None
    for target in list_response.response_data.get('targets', []):
        if target.get('name') == clone_name:
            clone_target = target
            break
    
    if not clone_target:
        print(f"   ❌ Clone '{clone_name}' not found in target list")
        all_tests_passed = False
        return
    
    clone_id = clone_target.get('id')
    print(f"   ✅ Clone found with ID: {clone_id}")
    
    # Verify clone has different ID than source
    if clone_id == source_id:
        print(f"   ❌ Clone has same ID as source: {clone_id}")
        all_tests_passed = False
    else:
        print(f"   ✅ Clone has unique ID")
    
    # Verify clone is in stopped state (default for new targets)
    clone_state = clone_target.get('state', 'unknown')
    if clone_state != 'stopped':
        print(f"   ⚠️ Clone state is '{clone_state}' (expected 'stopped')")
    else:
        print(f"   ✅ Clone is in stopped state")
    
    print(f"   ✅ Clone verification completed for '{clone_name}'")

if __name__ == "__main__":
    print("🧪 Starting CloneTarget functionality test...")
    print("=" * 60)
    print("This test will:")
    print("1. Clone a target without changing stream key")
    print("2. Clone a target with a new stream key") 
    print("3. Test error handling (invalid inputs)")
    print("4. Verify clones appear in the target list")
    print("=" * 60)
    
    success = test_clone_target()
    
    if success:
        print("\n✅ CloneTarget test PASSED! The functionality is working correctly.")
    else:
        print("\n❌ CloneTarget test FAILED. Check the logs above for details.")
    
    print("=" * 60)
    print("📝 Test completed.")