#!/usr/bin/env python3
"""
Protocol Discovery Script
Find out what protocols are actually supported by the plugin
"""

import obsws_python as obs

def discover_protocols():
    host = 'your-obs-websocket-host-ip' #replace with your actual websocket host IP
    port = 4455
    password = 'your-obs-websocket-password'  # Replace with your actual password
    
    try:
        client = obs.ReqClient(host=host, port=port, password=password)
        print("✅ Connected to OBS websocket")
        
        # Try different protocol names to see what works
        protocols_to_test = [
            "RTMP", "rtmp",
            "SRT", "srt", "SRT_RIST", "srt_rist", "RIST", "rist",
            "WHIP", "whip", "WebRTC", "webrtc",
            "RTMPS", "rtmps"
        ]
        
        print("🔍 Testing protocol support...")
        
        supported_protocols = []
        
        for protocol in protocols_to_test:
            print(f"   Testing protocol: {protocol}")
            
            try:
                response = client.send("CallVendorRequest", {
                    "vendorName": "sorayuki.multi_rtmp",
                    "requestType": "AddTarget",
                    "requestData": {
                        "name": f"Test_{protocol}",
                        "protocol": protocol
                    }
                })
                
                if response.response_data.get('success', False):
                    print(f"      ✅ SUPPORTED: {protocol}")
                    supported_protocols.append(protocol)
                    
                    # Clean up the test target
                    targets = get_targets(client)
                    if targets:
                        test_target = find_target_by_name(targets, f"Test_{protocol}")
                        if test_target:
                            delete_response = client.send("CallVendorRequest", {
                                "vendorName": "sorayuki.multi_rtmp",
                                "requestType": "DeleteTarget",
                                "requestData": {"targetId": test_target.get('id')}
                            })
                else:
                    print(f"      ❌ NOT SUPPORTED: {protocol} - {response.response_data.get('error', 'Unknown error')}")
                    
            except Exception as e:
                print(f"      ❌ ERROR testing {protocol}: {e}")
        
        print(f"\n🎯 Supported protocols: {supported_protocols}")
        
        # Also check what protocols exist in current targets
        print("\n📋 Protocols used in existing targets:")
        targets = get_targets(client)
        if targets:
            for target in targets:
                print(f"   • {target.get('name')}: {target.get('protocol', 'Unknown')}")
        
        return supported_protocols
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return []

def get_targets(client):
    try:
        response = client.send("CallVendorRequest", {
            "vendorName": "sorayuki.multi_rtmp",
            "requestType": "ListTargets",
            "requestData": {}
        })
        return response.response_data.get('targets', []) if response.response_data.get('success', False) else None
    except:
        return None

def find_target_by_name(targets, name):
    for target in targets:
        if target.get('name') == name:
            return target
    return None

if __name__ == "__main__":
    print("🔍 Discovering supported protocols...")
    supported = discover_protocols()
    print(f"\n📋 Final supported protocols: {supported}")
