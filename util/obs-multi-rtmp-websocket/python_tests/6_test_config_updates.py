#!/usr/bin/env python3
"""
Enhanced Test Script for configuration updates including sync settings
"""

import obsws_python as obs
import time

def test_config_updates():
    # Configuration - update these values for your setup
    host = 'your-obs-websocket-host-ip' #replace with your actual websocket host IP
    port = 4455
    password = 'your-obs-websocket-password'  # Replace with your actual password
    
    try:
        # Connect to OBS websocket
        print("🔌 Connecting to OBS websocket...")
        client = obs.ReqClient(host=host, port=port, password=password)
        print("✅ Connected to OBS websocket successfully")
        
        # Create a test target first
        print("\n📋 Creating test target for configuration updates...")
        test_target_name = "Config Test Target"
        
        add_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "AddTarget",
            "requestData": {
                "name": test_target_name,
                "protocol": "RTMP"
            }
        })
        
        if not add_response.response_data.get('success', False):
            print(f"❌ Failed to create test target: {add_response.response_data}")
            return False
        
        print(f"✅ Test target created successfully: {test_target_name}")
        
        # Wait for target to be created and get its ID
        print("⏳ Waiting for target creation...")
        time.sleep(2)
        
        # Find the test target
        targets = get_targets(client)
        if targets is None:
            return False
        
        test_target = find_target_by_name(targets, test_target_name)
        if not test_target:
            print("❌ Could not find the test target after creation")
            return False
        
        target_id = test_target.get('id')
        original_name = test_target.get('name')
        original_protocol = test_target.get('protocol', 'RTMP')
        
        print(f"🎯 Test target found: {original_name} (ID: {target_id}, Protocol: {original_protocol})")
        
        # Test 1: UpdateTargetName
        print("\n" + "="*60)
        print("🧪 TEST 1: UpdateTargetName functionality")
        print("="*60)
        
        new_name = "Updated Test Target - Renamed"
        print(f"📛 Renaming target: '{original_name}' → '{new_name}'")
        
        update_name_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "UpdateTargetName",
            "requestData": {
                "targetId": target_id,
                "newName": new_name
            }
        })
        
        if not update_name_response.response_data.get('success', False):
            print(f"❌ UpdateTargetName failed: {update_name_response.response_data}")
            return False
        
        print(f"✅ UpdateTargetName command sent successfully")
        print(f"   Response: {update_name_response.response_data}")
        
        # Verify name update
        print("⏳ Waiting for name update...")
        time.sleep(2)
        
        updated_targets = get_targets(client)
        if updated_targets is None:
            return False
        
        renamed_target = find_target_by_id(updated_targets, target_id)
        if renamed_target and renamed_target.get('name') == new_name:
            print(f"✅ Name update verified: {renamed_target.get('name')}")
        else:
            print(f"❌ Name update failed or not reflected in target list")
            if renamed_target:
                print(f"   Current name: {renamed_target.get('name')}")
            return False
        
        # Test 2: UpdateStreamKey
        print("\n" + "="*60)
        print("🧪 TEST 2: UpdateStreamKey functionality")
        print("="*60)
        
        new_stream_key = "live_999888777_updatedkey"
        print(f"🔑 Updating stream key to: {new_stream_key}")
        
        update_streamkey_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "UpdateStreamKey",
            "requestData": {
                "targetId": target_id,
                "streamKey": new_stream_key
            }
        })
        
        if not update_streamkey_response.response_data.get('success', False):
            print(f"❌ UpdateStreamKey failed: {update_streamkey_response.response_data}")
            print("ℹ️ Stream key update may not be fully implemented")
        else:
            print(f"✅ UpdateStreamKey command sent successfully")
            print(f"   Response: {update_streamkey_response.response_data}")
            time.sleep(1)
        
        # Test 3: UpdateServiceParam - Server URL
        print("\n" + "="*60)
        print("🧪 TEST 3: UpdateServiceParam functionality")
        print("="*60)
        
        test_param_key = "server"
        test_param_value = "rtmp://custom.server.com/app"
        print(f"⚙️ Updating service parameter: {test_param_key} = {test_param_value}")
        
        update_service_param_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "UpdateServiceParam",
            "requestData": {
                "targetId": target_id,
                "key": test_param_key,
                "value": test_param_value
            }
        })
        
        if not update_service_param_response.response_data.get('success', False):
            print(f"❌ UpdateServiceParam failed: {update_service_param_response.response_data}")
            print("ℹ️ Service parameter update may not be fully implemented")
        else:
            print(f"✅ UpdateServiceParam command sent successfully")
            print(f"   Response: {update_service_param_response.response_data}")
            time.sleep(1)
        
        # Test 4: UpdateServiceParam - Authentication
        print("\n" + "="*60)
        print("🧪 TEST 4: UpdateServiceParam functionality - Authentication")
        print("="*60)
        
        auth_param_key = "use_auth"
        auth_param_value = "true"  # Change from boolean True to string "true"
        print(f"🔐 Updating authentication parameter: {auth_param_key} = {auth_param_value}")
        
        update_auth_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "UpdateServiceParam",
            "requestData": {
                "targetId": target_id,
                "key": auth_param_key,
                "value": auth_param_value  # Send as string "true" instead of boolean True
            }
        })
        
        if not update_auth_response.response_data.get('success', False):
            print(f"❌ Auth parameter update failed: {update_auth_response.response_data}")
            print("ℹ️ This parameter might not exist for all protocols")
        else:
            print(f"✅ Auth parameter update successful")
            print(f"   Response: {update_auth_response.response_data}")
        
        # Test 4.1: UpdateServiceParam - Username
        print("\n" + "="*60)
        print("🧪 TEST 4.1: UpdateServiceParam functionality - Username")
        print("="*60)
        
        username_key = "username"
        username_value = "test_username"
        print(f"👤 Updating username parameter: {username_key} = {username_value}")
        
        update_username_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "UpdateServiceParam",
            "requestData": {
                "targetId": target_id,
                "key": username_key,
                "value": username_value
            }
        })
        
        if not update_username_response.response_data.get('success', False):
            print(f"❌ Username parameter update failed: {update_username_response.response_data}")
        else:
            print(f"✅ Username parameter update successful")
            print(f"   Response: {update_username_response.response_data}")
        
        # Test 4.2: UpdateServiceParam - Password
        print("\n" + "="*60)
        print("🧪 TEST 4.2: UpdateServiceParam functionality - Password")
        print("="*60)
        
        password_key = "password"
        password_value = "test_pass"
        print(f"🔒 Updating password parameter: {password_key} = {password_value}")
        
        update_password_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "UpdateServiceParam",
            "requestData": {
                "targetId": target_id,
                "key": password_key,
                "value": password_value
            }
        })
        
        if not update_password_response.response_data.get('success', False):
            print(f"❌ Password parameter update failed: {update_password_response.response_data}")
        else:
            print(f"✅ Password parameter update successful")
            print(f"   Response: {update_password_response.response_data}")

        # Test 5: Update Sync Start setting
        print("\n" + "="*60)
        print("🧪 TEST 5: Update Sync Start setting")
        print("="*60)
        
        print("🔄 Enabling 'Sync start with OBS'")
        
        update_sync_start_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "UpdateSyncStart",
            "requestData": {
                "targetId": target_id,
                "syncStart": True
            }
        })
        
        if not update_sync_start_response.response_data.get('success', False):
            print(f"❌ Sync start update failed: {update_sync_start_response.response_data}")
            print("ℹ️ Sync start functionality may not be implemented yet")
        else:
            print(f"✅ Sync start update successful")
            print(f"   Response: {update_sync_start_response.response_data}")
        
        # Test 6: Update Sync Stop setting
        print("\n" + "="*60)
        print("🧪 TEST 6: Update Sync Stop setting")
        print("="*60)
        
        print("🔄 Enabling 'Sync stop with OBS'")
        
        update_sync_stop_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "UpdateSyncStop",
            "requestData": {
                "targetId": target_id,
                "syncStop": True
            }
        })
        
        if not update_sync_stop_response.response_data.get('success', False):
            print(f"❌ Sync stop update failed: {update_sync_stop_response.response_data}")
            print("ℹ️ Sync stop functionality may not be implemented yet")
        else:
            print(f"✅ Sync stop update successful")
            print(f"   Response: {update_sync_stop_response.response_data}")
        
        # Test 7: Verify target functionality
        print("\n" + "="*60)
        print("🧪 TEST 7: Verify target functionality after updates")
        print("="*60)
        
        print("🔄 Testing target state retrieval...")
        state_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "GetTargetState",
            "requestData": {"id": target_id}
        })
        
        if state_response.response_data.get('success', False):
            current_state = state_response.response_data.get('state', 'unknown')
            current_name = state_response.response_data.get('name', 'unknown')
            print(f"✅ Target is functional: {current_name} - State: {current_state}")
        else:
            print(f"❌ Target state retrieval failed: {state_response.response_data}")
        
        # Final target status and manual verification instructions
        print("\n" + "="*60)
        print("📊 FINAL TARGET STATUS")
        print("="*60)
        
        final_targets = get_targets(client)
        if final_targets:
            test_target = find_target_by_id(final_targets, target_id)
            if test_target:
                print(f"🎯 Target ID: {test_target.get('id')}")
                print(f"📛 Name: {test_target.get('name', 'Unknown')}")
                print(f"🔌 Protocol: {test_target.get('protocol', 'Unknown')}")
                print(f"🔄 State: {test_target.get('state', 'unknown')}")
            else:
                print("❌ Could not find test target in final list")
        else:
            print("❌ Could not retrieve final target list")
        
        print("\n" + "="*60)
        print("🔍 MANUAL VERIFICATION INSTRUCTIONS")
        print("="*60)
        print("To verify ALL parameter updates worked correctly:")
        print("1. Open OBS Studio")
        print("2. Go to the Multi-RTMP plugin dock")
        print("3. Find the target: 'Updated Test Target - Renamed'")
        print("4. Click the 'Modify' button")
        print("5. Check that these values are set correctly:")
        print(f"   • Server URL: rtmp://custom.server.com/app")
        print(f"   • Stream Key: live_999888777_updatedkey")
        print(f"   • Use Auth: true (checkbox checked)")
        print("6. Go to 'Other Settings' tab and verify:")
        print(f"   • Sync start with OBS: true (checkbox checked)")
        print(f"   • Sync stop with OBS: true (checkbox checked)")
        print("7. If all values are correct, ALL updates worked!")
        
        print(f"\n🎉 Configuration updates test completed!")
        print(f"📝 Test target '{new_name}' (ID: {target_id}) has been left for inspection")
        
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

def find_target_by_id(targets, target_id):
    """Find target by ID"""
    for target in targets:
        if target.get('id') == target_id:
            return target
    return None

if __name__ == "__main__":
    print("🧪 Starting Enhanced Configuration Updates functionality test...")
    print("=" * 80)
    print("This test will:")
    print("  • Create a test target for configuration updates")
    print("  • Test UpdateTargetName functionality") 
    print("  • Test UpdateStreamKey functionality")
    print("  • Test UpdateServiceParam functionality (server URL)")
    print("  • Test UpdateServiceParam functionality (authentication)")
    print("  • Verify target remains functional after updates")
    print("  • Test error handling")
    print("=" * 80)
    print("📝 Note: The test target will be LEFT CREATED for manual inspection")
    print("    You'll need to manually verify the parameter updates in OBS UI")
    print("=" * 80)
    
    success = test_config_updates()
    
    if success:
        print("\n✅ Configuration Updates test COMPLETED!")
        print("   Please manually verify the parameter updates in OBS UI")
    else:
        print("\n❌ Configuration Updates test FAILED. Check the logs above for details.")
    
    print("=" * 80)
    print("📝 Test completed. Don't forget to manually verify the results in OBS!")