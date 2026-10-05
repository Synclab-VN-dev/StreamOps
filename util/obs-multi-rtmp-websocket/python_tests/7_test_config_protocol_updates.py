#!/usr/bin/env python3
"""
Enhanced Test Script for configuration updates 
Tests RTMP and SRT protocols with comprehensive settings
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
        
        # Get initial target count
        print("\n📋 Getting initial list of targets...")
        initial_targets = get_targets(client)
        if initial_targets is None:
            return False
        
        initial_count = len(initial_targets)
        print(f"📊 Initial target count: {initial_count}")
        
        test_targets = []
        
        # Test 1: Create RTMP target
        print("\n" + "="*60)
        print("🧪 TEST 1: Create and configure RTMP target")
        print("="*60)
        
        rtmp_target = create_and_test_rtmp_target(client, "RTMP Test Target", 
                                                 "rtmp://rtmp.test.server.com/app", 
                                                 "live_rtmp_test_stream_key_123")
        if rtmp_target:
            test_targets.append(rtmp_target)
        
        # Test 2: Create SRT target  
        print("\n" + "="*60)
        print("🧪 TEST 2: Create and configure SRT target")
        print("="*60)
        
        srt_target = create_and_test_srt_target(client, "SRT Test Target",
                                               "srt://srt.test.server.com:9000",
                                               "srt_test_stream_id_456")
        if srt_target:
            test_targets.append(srt_target)
        
        # Test 3: Create target for authentication testing
        print("\n" + "="*60)
        print("🧪 TEST 3: Create target for authentication testing")
        print("="*60)
        
        auth_target_name = "Auth Test Target"
        print(f"➕ Creating auth test target: {auth_target_name}")
        
        add_response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "AddTarget",
            "requestData": {
                "name": auth_target_name,
                "protocol": "RTMP"
            }
        })
        
        if not add_response.response_data.get('success', False):
            print(f"❌ Failed to create auth test target: {add_response.response_data}")
        else:
            print(f"✅ Auth test target created successfully")
            time.sleep(2)
            
            # Find the auth target
            targets = get_targets(client)
            auth_target = find_target_by_name(targets, auth_target_name)
            
            if auth_target:
                auth_target_id = auth_target.get('id')
                print(f"🎯 Auth target found: {auth_target.get('name')} (ID: {auth_target_id})")
                
                # Test authentication settings
                print("🔄 Testing authentication settings...")
                
                # Enable auth with username/password
                enable_auth_settings(client, auth_target_id)
                time.sleep(2)
                
                # Disable auth
                disable_auth_setting(client, auth_target_id)
                
                test_targets.append({
                    "id": auth_target_id,
                    "name": auth_target_name,
                    "protocol": "RTMP"
                })
        
        # Test 4: Verify all targets are functional
        print("\n" + "="*60)
        print("🧪 TEST 4: Verify all targets are functional")
        print("="*60)
        
        for target in test_targets:
            print(f"🔄 Testing target: {target['name']}")
            state_response = client.send("CallVendorRequest", {
                "vendorName": "sorayuki.multi_rtmp",
                "requestType": "GetTargetState",
                "requestData": {"id": target["id"]}
            })
            
            if state_response.response_data.get('success', False):
                current_state = state_response.response_data.get('state', 'unknown')
                print(f"✅ {target['name']} is functional - State: {current_state}")
            else:
                print(f"❌ {target['name']} state retrieval failed: {state_response.response_data}")
        
        # Final status and manual verification instructions
        print("\n" + "="*60)
        print("📊 FINAL TARGET STATUS")
        print("="*60)
        
        final_targets = get_targets(client)
        if final_targets:
            print(f"📊 Total targets: {len(final_targets)}")
            print("🎯 Test targets created:")
            for target in test_targets:
                found_target = find_target_by_id(final_targets, target["id"])
                if found_target:
                    print(f"   • {found_target.get('name')} ({found_target.get('protocol', 'Unknown')}) - {found_target.get('state', 'unknown')}")
        
        print("\n" + "="*60)
        print("🔍 MANUAL VERIFICATION INSTRUCTIONS")
        print("="*60)
        print("To verify ALL parameter updates worked correctly:")
        print("1. Open OBS Studio")
        print("2. Go to the Multi-RTMP plugin dock")
        print("3. Check each test target by clicking 'Modify':")
        print("   • RTMP Test Target: Verify server, stream key, auth, username, password")
        print("   • SRT Test Target: Verify server, stream ID, auth, username, password") 
        print("   • Auth Test Target: Verify auth is DISABLED")
        print("4. If all values are correct, ALL updates worked!")
        
        print(f"\n🎉 Configuration updates test completed!")
        print(f"📝 {len(test_targets)} test targets have been left for inspection")
        print("   You can manually delete them through the OBS UI or via websocket")
        
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

def create_and_test_rtmp_target(client, target_name, server_url, stream_key):
    """Create and configure an RTMP target"""
    print(f"➕ Creating RTMP target: {target_name}")
    
    add_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "AddTarget",
        "requestData": {
            "name": target_name,
            "protocol": "RTMP"
        }
    })
    
    if not add_response.response_data.get('success', False):
        print(f"❌ Failed to create RTMP target: {add_response.response_data}")
        return None
    
    print(f"✅ RTMP target created successfully")
    time.sleep(2)
    
    # Find the target
    targets = get_targets(client)
    target = find_target_by_name(targets, target_name)
    
    if not target:
        print(f"❌ Could not find RTMP target after creation")
        return None
    
    target_id = target.get('id')
    print(f"🎯 RTMP target found: {target.get('name')} (ID: {target_id})")
    
    # Configure the target
    print(f"⚙️ Configuring RTMP target...")
    
    # Set server URL
    server_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateServiceParam",
        "requestData": {
            "targetId": target_id,
            "key": "server",
            "value": server_url
        }
    })
    
    if server_response.response_data.get('success', False):
        print(f"✅ RTMP server URL set successfully")
    else:
        print(f"❌ RTMP server URL failed: {server_response.response_data}")
    
    # Set stream key
    streamkey_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateStreamKey",
        "requestData": {
            "targetId": target_id,
            "streamKey": stream_key
        }
    })
    
    if streamkey_response.response_data.get('success', False):
        print(f"✅ RTMP stream key set successfully")
    else:
        print(f"❌ RTMP stream key failed: {streamkey_response.response_data}")
    
    # Enable authentication
    auth_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateServiceParam",
        "requestData": {
            "targetId": target_id,
            "key": "use_auth",
            "value": "true"
        }
    })
    
    if auth_response.response_data.get('success', False):
        print("✅ Authentication enabled successfully")
    else:
        print(f"❌ Authentication failed: {auth_response.response_data}")
    
    # Set username
    username_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateServiceParam",
        "requestData": {
            "targetId": target_id,
            "key": "username",
            "value": "test_user_rtmp"
        }
    })
    
    if username_response.response_data.get('success', False):
        print("✅ Username set successfully")
    else:
        print(f"❌ Username failed: {username_response.response_data}")
    
    # Set password
    password_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateServiceParam",
        "requestData": {
            "targetId": target_id,
            "key": "password",
            "value": "test_pass_rtmp_123"
        }
    })
    
    if password_response.response_data.get('success', False):
        print("✅ Password set successfully")
    else:
        print(f"❌ Password failed: {password_response.response_data}")
    
    return {
        "id": target_id,
        "name": target_name,
        "protocol": "RTMP"
    }

def create_and_test_srt_target(client, target_name, server_url, stream_id):
    """Create and configure an SRT target"""
    print(f"➕ Creating SRT target: {target_name}")
    
    add_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "AddTarget",
        "requestData": {
            "name": target_name,
            "protocol": "SRT"  # Use "SRT" not "SRT_RIST"
        }
    })
    
    if not add_response.response_data.get('success', False):
        print(f"❌ Failed to create SRT target: {add_response.response_data}")
        return None
    
    print(f"✅ SRT target created successfully")
    time.sleep(2)
    
    # Find the target
    targets = get_targets(client)
    target = find_target_by_name(targets, target_name)
    
    if not target:
        print(f"❌ Could not find SRT target after creation")
        return None
    
    target_id = target.get('id')
    print(f"🎯 SRT target found: {target.get('name')} (ID: {target_id})")
    
    # Configure the target
    print(f"⚙️ Configuring SRT target...")
    
    # Set server URL
    server_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateServiceParam",
        "requestData": {
            "targetId": target_id,
            "key": "server",
            "value": server_url
        }
    })
    
    if server_response.response_data.get('success', False):
        print(f"✅ SRT server URL set successfully")
    else:
        print(f"❌ SRT server URL failed: {server_response.response_data}")
    
    # Set stream ID (SRT uses streamid parameter)
    streamid_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateServiceParam",
        "requestData": {
            "targetId": target_id,
            "key": "streamid",
            "value": stream_id
        }
    })
    
    if streamid_response.response_data.get('success', False):
        print(f"✅ SRT stream ID set successfully")
    else:
        print(f"❌ SRT stream ID failed: {streamid_response.response_data}")
    
    # Enable authentication
    auth_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateServiceParam",
        "requestData": {
            "targetId": target_id,
            "key": "use_auth",
            "value": "true"
        }
    })
    
    if auth_response.response_data.get('success', False):
        print("✅ Authentication enabled successfully")
    else:
        print(f"❌ Authentication failed: {auth_response.response_data}")
    
    # Set username
    username_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateServiceParam",
        "requestData": {
            "targetId": target_id,
            "key": "username",
            "value": "test_user_srt"
        }
    })
    
    if username_response.response_data.get('success', False):
        print("✅ Username set successfully")
    else:
        print(f"❌ Username failed: {username_response.response_data}")
    
    # Set password
    password_response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateServiceParam",
        "requestData": {
            "targetId": target_id,
            "key": "password",
            "value": "test_pass_srt_123"
        }
    })
    
    if password_response.response_data.get('success', False):
        print("✅ Password set successfully")
    else:
        print(f"❌ Password failed: {password_response.response_data}")
    
    return {
        "id": target_id,
        "name": target_name,
        "protocol": "SRT"
    }

def enable_auth_settings(client, target_id):
    """Enable authentication settings"""
    settings = [
        ("use_auth", "true", "Authentication"),
        ("username", "test_user_auth", "Username"),
        ("password", "test_pass_auth_123", "Password")
    ]
    
    for key, value, name in settings:
        response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "UpdateServiceParam",
            "requestData": {
                "targetId": target_id,
                "key": key,
                "value": value
            }
        })
        
        if response.response_data.get('success', False):
            print(f"✅ {name} set successfully")
        else:
            print(f"❌ {name} failed: {response.response_data}")

def disable_auth_setting(client, target_id):
    """Disable only the authentication flag (don't clear username/password)"""
    response = client.send("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "UpdateServiceParam",
        "requestData": {
            "targetId": target_id,
            "key": "use_auth",
            "value": "false"
        }
    })
    
    if response.response_data.get('success', False):
        print("✅ Authentication disabled successfully")
    else:
        print(f"❌ Authentication disable failed: {response.response_data}")

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
    print("🧪 Starting Multi-Protocol Configuration Test...")
    print("=" * 80)
    print("This test will:")
    print("  • Create and configure RTMP target with all settings")
    print("  • Create and configure SRT target with all settings")
    print("  • Test enabling/disabling authentication settings")
    print("  • Verify all targets remain functional")
    print("=" * 80)
    print("📝 Note: Test targets will be LEFT CREATED for manual inspection")
    print("    You'll need to verify the parameter updates in OBS UI")
    print("=" * 80)
    
    success = test_config_updates()
    
    if success:
        print("\n✅ Multi-Protocol Configuration test COMPLETED!")
        print("   Please manually verify all targets in OBS UI")
    else:
        print("\n❌ Multi-Protocol Configuration test FAILED. Check the logs above for details.")
    
    print("=" * 80)
    print("📝 Test completed. Don't forget to manually verify all the results in OBS!")