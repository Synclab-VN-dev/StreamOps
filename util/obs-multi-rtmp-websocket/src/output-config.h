#pragma once

#include <string>
#include <optional>
#include <vector>
#include <unordered_map>
#include <memory>
#include <list>

#include <json.hpp>

struct VideoEncoderConfig {
    std::string id;
    std::string encoderId;
    int fpsDenumerator = 1;
    nlohmann::json encoderParams;
    std::optional<std::string> outputScene;
    std::optional<std::string> resolution;
};
using VideoEncoderConfigPtr = std::shared_ptr<VideoEncoderConfig>;

struct AudioTrackConfig {
    int mixer_track;
    int output_track;
};
using AudioTrackConfigPtr = std::shared_ptr<AudioTrackConfig>;

struct AudioEncoderConfig {
    std::string id;
    std::string encoderId;
    nlohmann::json encoderParams;
    int mixerId = 0;
    std::list<AudioTrackConfigPtr> audioTracks;
};
using AudioEncoderConfigPtr = std::shared_ptr<AudioEncoderConfig>; 


struct OutputTargetConfig {
    std::string id;
    std::string name;
    std::string protocol = "RTMP";
    bool syncStart = false;
    bool syncStop = false;

    // Keep these as JSON objects even before the target is edited in the UI.
    // nlohmann::json defaults to null, which is not valid OBS settings JSON.
    nlohmann::json serviceParam = nlohmann::json::object();
    nlohmann::json outputParam = nlohmann::json::object();

    std::optional<std::string> videoConfig;
    std::optional<std::string> audioConfig;
};
using OutputTargetConfigPtr = std::shared_ptr<OutputTargetConfig>;


struct MultiOutputConfig {
public:
    std::list<OutputTargetConfigPtr> targets;
    std::list<VideoEncoderConfigPtr> videoConfig;
    std::list<AudioEncoderConfigPtr> audioConfig;
};

template<class T, class S>
inline T FindById(std::list<T>& list, const S& id) {
    for(auto& x: list) {
        if (x->id == id)
            return x;
    }
    return nullptr;
}


MultiOutputConfig& GlobalMultiOutputConfig();

void SaveMultiOutputConfig();

bool LoadMultiOutputConfig();

std::string GenerateId(MultiOutputConfig& config);

// Create dedicated encoder configs for an API-created target. The selected
// encoders must support codecs accepted by the target output.
bool InitializeDedicatedTargetEncoders(OutputTargetConfig& target);
