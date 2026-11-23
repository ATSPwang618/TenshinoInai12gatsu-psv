#pragma once
#include "ui_motion.hpp"

namespace tenshi {
struct ActorSample {
    float x = 399;
    int oldOffset = 0, newOffset = 0;
    uint8_t oldAlpha = 0, newAlpha = 255;
};

// Geometry/timing only. The renderer owns two bounded sprite textures per slot.
struct ActorTween {
    UiTransition clock;
    float fromX = 399, toX = 399;
    bool oldVisible = false, newVisible = false, sameActor = false, replace = false;
    void begin(uint32_t now, float from, float to, bool oldImage, bool newImage,
               bool same, bool imageChanged, bool enabled) {
        fromX = from;
        toX = to;
        oldVisible = oldImage;
        newVisible = newImage;
        sameActor = same;
        replace = imageChanged;
        clock.begin(now, enabled, same && imageChanged ? 240 : 320);
    }
    ActorSample sample(uint32_t now) const {
        const float p = clock.progress(now);
        ActorSample result;
        result.x = fromX + (toX - fromX) * p;
        result.oldAlpha = oldVisible && replace ? clock.coverAlpha(now) : 0;
        result.newAlpha = newVisible ? uint8_t(replace ? 255 - clock.coverAlpha(now) : 255) : 0;
        if (!sameActor) {
            result.oldOffset = -int(std::lround(24 * p));
            result.newOffset = int(std::lround(24 * (1 - p)));
        }
        return result;
    }
};
} // namespace tenshi
