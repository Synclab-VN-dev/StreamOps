#pragma once

#include "pch.h"
#include <string>
#include <vector>
#include <functional>
#include "output-config.h"

// Forward declare the obs-websocket vendor handle type
typedef void* obs_websocket_vendor;

class PushWidget;
class MultiOutputWidget;

class MultiRTMPWebsocketVendor {
public:
    static MultiRTMPWebsocketVendor* Instance();
    
    bool Initialize();
    void Shutdown();
    
    // Individual vendor request callback functions
    static void HandleListTargetsRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleGetTargetStateRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleStartTargetRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleStopTargetRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleToggleTargetRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleStartAllRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleStopAllRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleAddTargetRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleCloneTargetRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleUpdateTargetNameRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleUpdateStreamKeyRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleUpdateServiceParamRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleDeleteTargetRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleUpdateSyncStartRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleUpdateSyncStopRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);
    static void HandleGetTargetStatsRequest(obs_data_t* request_data, obs_data_t* response_data, void* private_data);

private:
    MultiRTMPWebsocketVendor() = default;
    ~MultiRTMPWebsocketVendor() = default;
    
    // Method to register all vendor requests
    void RegisterVendorRequests(obs_websocket_vendor vendor_handle);
    
    // Internal handler implementations (these return bool)
    bool HandleListTargets(obs_data_t* response_data);
    bool HandleGetTargetState(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleStartTarget(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleStopTarget(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleToggleTarget(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleStartAll(obs_data_t* response_data);
    bool HandleStopAll(obs_data_t* response_data);
    
    // Configuration management handlers
    bool HandleAddTarget(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleCloneTarget(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleUpdateTargetName(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleUpdateStreamKey(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleUpdateServiceParam(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleDeleteTarget(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleUpdateSyncStart(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleUpdateSyncStop(obs_data_t* request_data, obs_data_t* response_data);
    bool HandleGetTargetStats(obs_data_t* request_data, obs_data_t* response_data);
    
    // Helper methods
    MultiOutputWidget* GetMultiOutputWidget();
    PushWidget* FindPushWidgetByIdOrName(obs_data_t* request_data);
    void ExecuteInUIThread(std::function<void()> task);
    void ParseStatusText(const QString& statusText, obs_data_t* response_data);
    double ParseBitrateValue(const QString& bitrateStr);
    double ParseFpsValue(const QString& fpsStr);
    
    static MultiRTMPWebsocketVendor* s_instance;
    std::string m_vendorName = "sorayuki.multi_rtmp";
    obs_websocket_vendor m_vendorHandle = nullptr;
};
