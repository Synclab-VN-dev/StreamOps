#include "pch.h"
#include <list>
#include <regex>
#include <filesystem>
#include <unordered_map>
#include "push-widget.h"
#include "plugin-support.h"
#include "output-config.h"
#include "multi-output-widget.h"

#ifdef ENABLE_WEBSOCKET
#include "ws_vendor.hpp"
#endif

#ifdef _WIN32
#include <Windows.h>
#endif

#define ConfigSection "obs-multi-rtmp"

static class GlobalServiceImpl : public GlobalService
{
public:
    bool RunInUIThread(std::function<void()> task) override {
        if (uiThread_ == nullptr)
            return false;
        QMetaObject::invokeMethod(uiThread_, [func = std::move(task)]() {
            func();
        });
        return true;
    }
    QThread* uiThread_ = nullptr;
} s_service;

GlobalService& GetGlobalService() {
    return s_service;
}

OBS_DECLARE_MODULE()
OBS_MODULE_USE_DEFAULT_LOCALE("obs-multi-rtmp", "en-US")
OBS_MODULE_AUTHOR("雷鳴 (@sorayukinoyume)")

bool obs_module_load()
{
    auto mainwin = (QMainWindow*)obs_frontend_get_main_window();
    if (mainwin == nullptr)
        return false;

    QMetaObject::invokeMethod(mainwin, []() {
        s_service.uiThread_ = QThread::currentThread();
    });

#ifdef ENABLE_WEBSOCKET
    MultiRTMPWebsocketVendor::Instance();
    blog(LOG_INFO, TAG "Websocket vendor instance created (will register when obs-websocket loads)");
#endif

    auto dock = new MultiOutputWidget();
    dock->setObjectName("obs-multi-rtmp-dock");
    if (!obs_frontend_add_dock_by_id("obs-multi-rtmp-dock", obs_module_text("Title"), dock))
    {
        delete dock;
        return false;
    }

    blog(LOG_INFO, TAG "version: %s by SoraYuki https://github.com/sorayuki/obs-multi-rtmp/", PLUGIN_VERSION);

    obs_frontend_add_event_callback(
        [](enum obs_frontend_event event, void *private_data) {
            auto dock = static_cast<MultiOutputWidget*>(private_data);
            if (!dock) return;

            for (auto x : dock->GetAllPushWidgets()) {
                if (x) x->OnOBSEvent(event);
            }

            if (event == obs_frontend_event::OBS_FRONTEND_EVENT_EXIT)
            {   
                dock->SaveConfig();
            }
            else if (event == obs_frontend_event::OBS_FRONTEND_EVENT_PROFILE_CHANGED)
            {
                dock->LoadConfig();
            }
#ifdef ENABLE_WEBSOCKET
            else if (event == obs_frontend_event::OBS_FRONTEND_EVENT_FINISHED_LOADING)
            {
                MultiRTMPWebsocketVendor::Instance()->Initialize();
            }
#endif
        }, dock
    );

    return true;
}

void obs_module_unload(void)
{
#ifdef ENABLE_WEBSOCKET
    MultiRTMPWebsocketVendor::Instance()->Shutdown();
#endif
}

const char *obs_module_description(void)
{
    return "Multiple RTMP Output Plugin";
}
