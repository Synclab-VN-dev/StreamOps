#include "output-config.h"
#include "pch.h"

#include <obs.h>
#include <obs-frontend-api.h>
#include <random>
#include <filesystem>
#include <unordered_set>
#include <algorithm>
#include <util/platform.h>
#include "json-util.hpp"
#include "protocols.h"
#include "obs.hpp"


MultiOutputConfig& GlobalMultiOutputConfig()
{
    static MultiOutputConfig instance;
    return instance;
}


static nlohmann::json SaveTarget(OutputTargetConfig& config) {
    nlohmann::json json;
    json["id"] = config.id;
    json["name"] = config.name;
    json["protocol"] = config.protocol;
    json["service-param"] = config.serviceParam;
    json["output-param"] = config.outputParam;
    json["sync-start"] = config.syncStart;
    json["sync-stop"] = config.syncStop;
    if (config.videoConfig.has_value())
        json["video-config"] = *config.videoConfig;
    if (config.audioConfig.has_value())
        json["audio-config"] = *config.audioConfig;
    return json;
}

static nlohmann::json SaveVideoConfig(VideoEncoderConfig& config) {
    nlohmann::json json;
    json["id"] = config.id;
    json["encoder"] = config.encoderId;
    json["param"] = config.encoderParams;
    if (config.outputScene.has_value())
        json["scene"] = *config.outputScene;
    if (config.resolution.has_value())
        json["resolution"] = *config.resolution;
    json["fps-denumerator"] = config.fpsDenumerator;
    return json;
}

static nlohmann::json SaveAudioTrackConfig(AudioTrackConfig &config) {
	nlohmann::json json;
	json["mixer_track"] = config.mixer_track;
	json["output_track"] = config.output_track;
	return json;
}

static nlohmann::json SaveAudioConfig(AudioEncoderConfig& config) {
    nlohmann::json json;
    json["id"] = config.id;
    json["encoder"] = config.encoderId;
    json["param"] = config.encoderParams;
    json["mixerId"] = config.mixerId;


    nlohmann::json audio_tracks(nlohmann::json::value_t::array);
    for(auto& track: config.audioTracks) {
        audio_tracks.push_back(SaveAudioTrackConfig(*track));
    }

    json["audioTracks"] = audio_tracks;

    return json;
}

static std::string SaveMultiOutputConfig(MultiOutputConfig& config) {
    nlohmann::json json;

    std::unordered_set<std::string> videoconfig_in_use;
    std::unordered_set<std::string> audioconfig_in_use;

    int target_count = 0, videocfg_count = 0, audiocfg_count = 0;

    nlohmann::json targets(nlohmann::json::value_t::array);
    for(auto& target: config.targets) {
        targets.push_back(SaveTarget(*target));
        if (target->videoConfig.has_value())
            videoconfig_in_use.insert(*target->videoConfig);
        if (target->audioConfig.has_value())
            audioconfig_in_use.insert(*target->audioConfig);
        ++target_count;
    }

    nlohmann::json video_configs(nlohmann::json::value_t::array);
    for(auto& video_config: config.videoConfig) {
        if (videoconfig_in_use.find(video_config->id) != videoconfig_in_use.end())
            video_configs.push_back(SaveVideoConfig(*video_config));
        ++videocfg_count;
    }

    nlohmann::json audio_configs(nlohmann::json::value_t::array);
    for(auto& audio_config: config.audioConfig) {
        if (audioconfig_in_use.find(audio_config->id) != audioconfig_in_use.end())
            audio_configs.push_back(SaveAudioConfig(*audio_config));
        ++audiocfg_count;
    }

    json["targets"] = targets;
    json["video_configs"] = video_configs;
    json["audio_configs"] = audio_configs;

    blog(LOG_INFO, TAG "Save %d targets, %d video configs, %d audio configs", target_count, videocfg_count, audiocfg_count);

    return json.dump();
}




static OutputTargetConfigPtr LoadTargetConfig(nlohmann::json& json) {
    auto id = GetJsonField<std::string>(json, "id");
    if (!id.has_value())
        return {};

    auto config = std::make_shared<OutputTargetConfig>();
    config->id = *id;
    config->name = GetJsonField<std::string>(json, "name").value_or("");
    config->protocol = GetJsonField<std::string>(json, "protocol").value_or("RTMP"); // for compatibility
    config->syncStart = GetJsonField<bool>(json, "sync-start").value_or(false);
    config->syncStop = GetJsonField<bool>(json, "sync-stop").value_or(config->syncStart);
    config->serviceParam = GetJsonField<nlohmann::json>(json, "service-param").value_or(nlohmann::json{});
    config->outputParam = GetJsonField<nlohmann::json>(json, "output-param").value_or(nlohmann::json{});
    config->videoConfig = GetJsonField<std::string>(json, "video-config");
    config->audioConfig = GetJsonField<std::string>(json, "audio-config");

    return config;
}

static VideoEncoderConfigPtr LoadVideoConfig(nlohmann::json& json) {
    auto id = GetJsonField<std::string>(json, "id");
    if (!id.has_value())
        return {};

    auto config = std::make_shared<VideoEncoderConfig>();
    config->id = *id;
    config->encoderId = GetJsonField<std::string>(json, "encoder").value_or("");
    config->outputScene = GetJsonField<std::string>(json, "scene");
    config->resolution = GetJsonField<std::string>(json, "resolution");
    config->fpsDenumerator = GetJsonField<int>(json, "fps-denumerator").value_or(1);
    config->encoderParams = GetJsonField<nlohmann::json>(json, "param").value_or(nlohmann::json{});

    return config;
}

static AudioTrackConfigPtr LoadAudioTrackConfig(nlohmann::json& json) {
    auto config = std::make_shared<AudioTrackConfig>();
    config->mixer_track = GetJsonField<int>(json, "mixer_track").value_or(0);
    config->output_track = GetJsonField<int>(json, "output_track").value_or(0);

    return config;
}

static AudioEncoderConfigPtr LoadAudioConfig(nlohmann::json& json) {
    auto id = GetJsonField<std::string>(json, "id");
    if (!id.has_value())
        return {};
    
    auto config = std::make_shared<AudioEncoderConfig>();
    config->id = *id;
    config->encoderId = GetJsonField<std::string>(json, "encoder").value_or("");
    config->mixerId = GetJsonField<int>(json, "mixerId").value_or(0);
    config->encoderParams = GetJsonField<nlohmann::json>(json, "param").value_or(nlohmann::json{});

    auto it = json.find("audioTracks");
    if (it != json.end() && it->type() == nlohmann::json::value_t::array) {
        for(auto& audio_track_json: *it) {
            if (audio_track_json.type() != nlohmann::json::value_t::object)
                continue;
            auto audio_track = LoadAudioTrackConfig(audio_track_json);
            if (audio_track)
                config->audioTracks.emplace_back(audio_track);
        }
    }

    return config;
}

static MultiOutputConfig LoadMultiOutputConfig(const std::string& content) {
    try {
        int target_count = 0, videocfg_count = 0, audiocfg_count = 0;

        auto json = nlohmann::json::parse(content);
        MultiOutputConfig config;
        auto it = json.find("targets");
        if (it != json.end() && it->type() == nlohmann::json::value_t::array) {
            for(auto& target_json: *it) {
                if (target_json.type() != nlohmann::json::value_t::object)
                    continue;
                auto target = LoadTargetConfig(target_json);
                if (target)
                    config.targets.emplace_back(target);
                ++target_count;
            }
        }

        it = json.find("video_configs");
        if (it != json.end() && it->type() == nlohmann::json::value_t::array) {
            for(auto& video_enc_json: *it) {
                if (video_enc_json.type() != nlohmann::json::value_t::object)
                    continue;
                auto video_enc = LoadVideoConfig(video_enc_json);
                if (video_enc) {
                    config.videoConfig.emplace_back(video_enc);
                }
                ++videocfg_count;
            }
        }

        it = json.find("audio_configs");
        if (it != json.end() && it->type() == nlohmann::json::value_t::array) {
            for(auto& audio_enc_json: *it) {
                if (audio_enc_json.type() != nlohmann::json::value_t::object)
                    continue;
                auto audio_enc = LoadAudioConfig(audio_enc_json);
                if (audio_enc) {
                    config.audioConfig.emplace_back(audio_enc);
                }
                ++audiocfg_count;
            }
        }

        blog(LOG_INFO, TAG "Load %d targets, %d video configs, %d audio configs", target_count, videocfg_count, audiocfg_count);
        
        return config;
    }
    catch(const std::exception& e) {
        blog(LOG_ERROR, TAG "Fail to parse config json: %s", e.what());
        return {};
    }
}

void SaveMultiOutputConfig() {
    auto profiledir = obs_frontend_get_current_profile_path();
    if (profiledir) {
        std::string filename = profiledir;
        filename += "/obs-multi-rtmp.json";
        auto content = SaveMultiOutputConfig(GlobalMultiOutputConfig());
        os_quick_write_utf8_file_safe(filename.c_str(), content.c_str(), content.size(), true, "tmp", "bak");
        blog(LOG_INFO, TAG "Save config into %s", filename.c_str());
    }
    bfree(profiledir);
}


bool LoadMultiOutputConfig() {
    auto profiledir = obs_frontend_get_current_profile_path();
    bool ret = false;
    if (profiledir) {
        std::string filename = profiledir;
        filename += "/obs-multi-rtmp.json";
        auto content = os_quick_read_utf8_file(filename.c_str());
        if (content) {
            GlobalMultiOutputConfig() = LoadMultiOutputConfig(content);
            bfree(content);
            ret = true;
            blog(LOG_INFO, TAG "Load config from %s", filename.c_str());
        } else {
            blog(LOG_INFO, TAG "Load config from %s failed", filename.c_str());
        }
    }
    bfree(profiledir);
    return ret;
}


template<class T>
static bool has_id(T& container, const std::string& id) {
    for(auto& item: container) {
        if (item->id == id)
            return true;
    }
    return false;
}

std::string GenerateId(MultiOutputConfig& config) {
    static std::random_device rndgen;
    for(;;) {
        auto rndnum = rndgen();
        auto newid = std::to_string(rndnum);
        if (has_id(config.targets, newid))
            continue;
        if (has_id(config.audioConfig, newid))
            continue;
        if (has_id(config.videoConfig, newid))
            continue;
        return newid;
    }
}


static std::optional<std::string> FindEncoderForSupportedCodecs(const char* codecs)
{
    if (!codecs || !*codecs)
        return std::nullopt;

    std::string supported(codecs);
    size_t begin = 0;
    while (begin <= supported.size()) {
        auto end = supported.find(';', begin);
        auto codec = supported.substr(begin, end == std::string::npos ? std::string::npos : end - begin);
        codec.erase(0, codec.find_first_not_of(" \t\r\n"));
        auto last = codec.find_last_not_of(" \t\r\n");
        if (last != std::string::npos)
            codec.erase(last + 1);

        if (!codec.empty()) {
            size_t index = 0;
            const char* encoderId = nullptr;
            while (obs_enum_encoder_types(index++, &encoderId)) {
                if (!encoderId)
                    continue;
                if (obs_get_encoder_caps(encoderId) & OBS_ENCODER_CAP_DEPRECATED)
                    continue;
                const char* encoderCodec = obs_get_encoder_codec(encoderId);
                if (encoderCodec && codec == encoderCodec)
                    return std::string(encoderId);
            }
        }

        if (end == std::string::npos)
            break;
        begin = end + 1;
    }
    return std::nullopt;
}

bool InitializeDedicatedTargetEncoders(OutputTargetConfig& target)
{
    auto protocolInfo = GetProtocolInfos()->GetInfo(target.protocol.c_str());
    if (!protocolInfo) {
        blog(LOG_ERROR, TAG "Cannot initialize target %s: unsupported protocol %s",
             target.id.c_str(), target.protocol.c_str());
        return false;
    }

    OBSDataAutoRelease outputSettings = obs_data_create();
    OBSOutputAutoRelease output = obs_output_create(
        protocolInfo->outputId, ("multi-output-probe-" + target.id).c_str(), outputSettings, nullptr);
    if (!output) {
        blog(LOG_ERROR, TAG "Cannot initialize target %s: output probe creation failed", target.id.c_str());
        return false;
    }

    auto videoEncoderId = FindEncoderForSupportedCodecs(obs_output_get_supported_video_codecs(output));
    auto audioEncoderId = FindEncoderForSupportedCodecs(obs_output_get_supported_audio_codecs(output));
    if (!videoEncoderId || !audioEncoderId) {
        blog(LOG_ERROR, TAG "Cannot initialize target %s: no compatible dedicated video/audio encoder",
             target.id.c_str());
        return false;
    }

    auto& global = GlobalMultiOutputConfig();
    auto video = std::make_shared<VideoEncoderConfig>();
    video->id = GenerateId(global);
    video->encoderId = *videoEncoderId;
    video->encoderParams = nlohmann::json::object();

    // Generate the audio id before inserting the video config so both ids are
    // independently checked against the existing config namespace.
    auto audio = std::make_shared<AudioEncoderConfig>();
    audio->id = GenerateId(global);
    while (audio->id == video->id)
        audio->id = GenerateId(global);
    audio->encoderId = *audioEncoderId;
    audio->encoderParams = nlohmann::json::object();
    audio->mixerId = 0;

    global.videoConfig.emplace_back(video);
    global.audioConfig.emplace_back(audio);
    target.videoConfig = video->id;
    target.audioConfig = audio->id;
    target.serviceParam = nlohmann::json::object();
    target.outputParam = nlohmann::json::object();

    blog(LOG_INFO, TAG "Initialized dedicated encoders for target %s: video=%s audio=%s",
         target.id.c_str(), video->encoderId.c_str(), audio->encoderId.c_str());
    return true;
}
