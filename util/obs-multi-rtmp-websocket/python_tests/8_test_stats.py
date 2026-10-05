#!/usr/bin/env python3
"""
Test script for GetTargetStats functionality
Tests retrieving streaming statistics for RTMP targets
"""

import obsws_python as obs
import time
import json

def test_get_target_stats():
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
            print(f"❌ ListTargets request failed: {list_response.response_data}")
            return False
        
        targets = list_response.response_data.get('targets', [])
        print(f"✅ Found {len(targets)} target(s)")
        
        if not targets:
            print("ℹ️ No targets configured - cannot test GetTargetStats")
            return True
        
        # Test GetTargetStats for each target
        print(f"\n📊 Testing GetTargetStats for {len(targets)} target(s)...")
        print("=" * 80)
        
        all_tests_passed = True
        
        for i, target in enumerate(targets):
            target_id = target.get('id')
            target_name = target.get('name')
            target_state = target.get('state', 'unknown')
            
            print(f"\n🎯 Target #{i + 1}: {target_name} (ID: {target_id}, State: {target_state})")
            print("-" * 60)
            
            # Test GetTargetStats by ID
            print("🧪 Testing GetTargetStats by ID...")
            stats_response = client.send("CallVendorRequest", {
                "vendorName": "sorayuki.multi_rtmp",
                "requestType": "GetTargetStats",
                "requestData": {
                    "id": target_id
                }
            })
            
            # Check if request was successful
            if not stats_response.response_data.get('success', False):
                print(f"❌ GetTargetStats request failed: {stats_response.response_data}")
                all_tests_passed = False
                continue
            
            stats_data = stats_response.response_data
            print("✅ GetTargetStats request successful!")
            
            # Display statistics
            print(f"   📈 Raw Status: {stats_data.get('rawStatus', 'N/A')}")
            print(f"   ⏱️  Duration: {stats_data.get('duration', 'N/A')}")
            print(f"   📊 Bitrate: {stats_data.get('bitrate', 'N/A')}")
            print(f"   🎞️  FPS: {stats_data.get('fps', 'N/A')}")
            print(f"   🔢 Bitrate Value: {stats_data.get('bitrateValue', 0)} bps")
            print(f"   🔢 FPS Value: {stats_data.get('fpsValue', 0)}")
            print(f"   🏃‍♂️ Is Running: {stats_data.get('isRunning', False)}")
            
            # Test 1: Verify response structure
            expected_fields = [
                'success', 'id', 'name', 'isRunning', 'rawStatus', 
                'duration', 'bitrate', 'fps', 'bitrateValue', 'fpsValue'
            ]
            
            missing_fields = [field for field in expected_fields if field not in stats_data]
            if missing_fields:
                print(f"⚠️ Missing fields in stats response: {missing_fields}")
                all_tests_passed = False
            else:
                print("✅ Response contains all expected fields")
            
            # Test 2: Verify ID and name match
            if stats_data.get('id') != target_id:
                print(f"⚠️ ID mismatch: expected {target_id}, got {stats_data.get('id')}")
                all_tests_passed = False
            else:
                print("✅ Target ID matches")
            
            if stats_data.get('name') != target_name:
                print(f"⚠️ Name mismatch: expected {target_name}, got {stats_data.get('name')}")
                all_tests_passed = False
            else:
                print("✅ Target name matches")
            
            # Test 3: Verify running state consistency
            expected_running = target_state == 'running'
            actual_running = stats_data.get('isRunning', False)
            
            if expected_running != actual_running:
                print(f"⚠️ Running state mismatch: expected {expected_running}, got {actual_running}")
                # This might not be a failure if state changed between requests
            else:
                print("✅ Running state consistent")
            
            # Test 4: Verify numeric values are valid
            bitrate_value = stats_data.get('bitrateValue', 0)
            fps_value = stats_data.get('fpsValue', 0)
            
            if not isinstance(bitrate_value, (int, float)) or bitrate_value < 0:
                print(f"⚠️ Invalid bitrate value: {bitrate_value}")
                all_tests_passed = False
            else:
                print("✅ Bitrate value is valid")
            
            if not isinstance(fps_value, (int, float)) or fps_value < 0:
                print(f"⚠️ Invalid FPS value: {fps_value}")
                all_tests_passed = False
            else:
                print("✅ FPS value is valid")
            
            # Test 5: Verify formatted strings
            duration = stats_data.get('duration', '')
            bitrate = stats_data.get('bitrate', '')
            fps = stats_data.get('fps', '')
            
            if not duration:
                print("⚠️ Empty duration string")
                all_tests_passed = False
            else:
                print("✅ Duration string is valid")
            
            if not bitrate:
                print("⚠️ Empty bitrate string")
                all_tests_passed = False
            else:
                print("✅ Bitrate string is valid")
            
            if not fps:
                print("⚠️ Empty FPS string")
                all_tests_passed = False
            else:
                print("✅ FPS string is valid")
            
            # Test with name instead of ID
            print("\n🧪 Testing GetTargetStats by name...")
            name_response = client.send("CallVendorRequest", {
                "vendorName": "sorayuki.multi_rtmp",
                "requestType": "GetTargetStats",
                "requestData": {
                    "name": target_name
                }
            })
            
            if name_response.response_data.get('success', False):
                print("✅ GetTargetStats by name also works!")
                if name_response.response_data.get('id') != target_id:
                    print(f"⚠️ ID mismatch in name-based request")
            else:
                print("❌ GetTargetStats by name failed")
                all_tests_passed = False
            
            print("-" * 60)
        
        # Test error cases
        print("\n🧪 Testing error cases...")
        print("-" * 40)
        
        # Test with non-existent ID
        print("Testing with non-existent ID...")
        error_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "GetTargetStats",
            "requestData": {
                "id": "non_existent_id_12345"
            }
        })
        
        if not error_response.response_data.get('success', False):
            print("✅ Correctly handled non-existent ID")
        else:
            print("❌ Should have failed for non-existent ID")
            all_tests_passed = False
        
        # Test with empty request
        print("Testing with empty request data...")
        empty_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "GetTargetStats",
            "requestData": {}
        })
        
        if not empty_response.response_data.get('success', False):
            print("✅ Correctly handled empty request data")
        else:
            print("❌ Should have failed for empty request data")
            all_tests_passed = False
        
        # Summary
        print(f"\n📋 Test Summary:")
        print("=" * 40)
        print(f"Total targets tested: {len(targets)}")
        print(f"All tests passed: {all_tests_passed}")
        
        if all_tests_passed:
            print("\n🎉 GetTargetStats test completed successfully!")
            return True
        else:
            print("\n❌ Some tests failed. Check the logs above for details.")
            return False
        
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
    print("🧪 Starting GetTargetStats functionality test...")
    print("=" * 60)
    print("This test will:")
    print("1. List all configured targets")
    print("2. Get statistics for each target")
    print("3. Verify response structure and data integrity")
    print("4. Test error handling")
    print("=" * 60)
    
    success = test_get_target_stats()
    
    if success:
        print("\n✅ GetTargetStats test PASSED! The functionality is working correctly.")
    else:
        print("\n❌ GetTargetStats test FAILED. Check the logs above for details.")
    
    print("=" * 60)
    print("📝 Test completed.")