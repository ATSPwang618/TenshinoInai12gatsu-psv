#pragma once
#include "media.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace tenshi {
// Clock-driven, never frame-count driven. Unsigned subtraction also handles SDL tick wrap.
struct UiTransition {
    uint32_t start = 0, duration = 0;
    void begin(uint32_t now, bool enabled, uint32_t milliseconds = 340) {
        start = now;
        duration = enabled ? milliseconds : 0;
    }
    bool active(uint32_t now) const {
        return duration && uint32_t(now - start) < duration;
    }
    uint8_t coverAlpha(uint32_t now) const {
        if (!active(now))
            return 0;
        const float t = float(uint32_t(now - start)) / duration;
        return uint8_t(std::lround(255 * (1 - t * t * (3 - 2 * t))));
    }
    float progress(uint32_t now) const {
        if (!active(now))
            return 1;
        const float t = float(uint32_t(now - start)) / duration;
        return t * t * (3 - 2 * t);
    }
    int incomingOffset(uint32_t now, int distance) const {
        return int(std::lround(distance * (1 - progress(now))));
    }
    int outgoingOffset(uint32_t now, int distance) const {
        return -int(std::lround(distance * progress(now)));
    }
    void shift(uint32_t elapsed) { start += elapsed; }
};

// A single immutable capture per menu entry, not an expensive CPU filter every frame.
inline Pixels menuBackdrop(const Pixels &source) {
    Pixels gray = source;
    for (size_t i = 0; i < gray.rgba.size(); i += 4) {
        const int luminance = (54 * source.rgba[i] + 183 * source.rgba[i + 1] +
                               19 * source.rgba[i + 2] + 128) >> 8;
        const uint8_t value = uint8_t(luminance * 3 / 5 + 36);
        gray.rgba[i] = gray.rgba[i + 1] = gray.rgba[i + 2] = value;
    }
    return gray;
}

struct UiFeedback {
    uint32_t start = 0, duration = 0;
    int slot = 0;
    bool animated = true;
    void show(int selectedSlot, uint32_t now, bool effects = true) {
        slot = selectedSlot;
        start = now;
        duration = 1600;
        animated = effects;
    }
    uint8_t alpha(uint32_t now) const {
        const uint32_t elapsed = now - start;
        if (!duration || elapsed >= duration)
            return 0;
        if (!animated)
            return 255;
        const float in = std::min(1.f, elapsed / 120.f);
        const float out = std::min(1.f, (duration - elapsed) / 240.f);
        return uint8_t(std::lround(255 * std::min(in, out)));
    }
    void shift(uint32_t elapsed) { start += elapsed; }
};
} // namespace tenshi
