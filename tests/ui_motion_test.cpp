#include "ui_motion.hpp"
#include "actor_motion.hpp"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <iostream>
using namespace tenshi;

int main() {
    UiTransition transition;
    assert(!transition.active(0) && transition.coverAlpha(0) == 0);
    transition.begin(1000, true, 200);
    assert(transition.active(1000) && transition.coverAlpha(1000) == 255);
    assert(transition.coverAlpha(1100) == 128);
    int previous = 255;
    for (uint32_t now = 1000; now <= 1200; now++) {
        int alpha = transition.coverAlpha(now);
        assert(alpha <= previous && alpha >= 0);
        previous = alpha;
    }
    assert(!transition.active(1200) && transition.coverAlpha(1400) == 0);
    transition.begin(2000, false);
    assert(!transition.active(2000) && transition.coverAlpha(2000) == 0);
    transition.begin(0xfffffff0u, true, 200);
    assert(transition.coverAlpha(84) == 128 && !transition.active(184));
    transition.begin(1000, true, 200);
    transition.shift(5000);
    assert(transition.coverAlpha(6100) == 128);
    transition.begin(1000, true);
    assert(transition.active(1250)); // A visible menu action must not finish in 180ms.
    transition.begin(1000, true, 340);
    assert(transition.incomingOffset(1000, 72) == 72);
    assert(transition.incomingOffset(1170, 72) == 36);
    assert(transition.outgoingOffset(1170, 72) == -36);
    assert(transition.incomingOffset(1340, -72) == 0);
    ActorTween actor;
    actor.begin(1000, 399, 399, false, true, false, true, true);
    auto first = actor.sample(1000), middle = actor.sample(1160), last = actor.sample(1320);
    assert(first.newAlpha == 0 && first.newOffset == 24);
    assert(middle.newAlpha == 127 && middle.newOffset == 12);
    assert(last.newAlpha == 255 && last.newOffset == 0);
    actor.begin(1000, 399, 209, true, true, true, false, true);
    middle = actor.sample(1160);
    assert(middle.x == 304 && middle.newAlpha == 255 && middle.oldAlpha == 0);
    actor.begin(1000, 209, 209, true, true, true, true, true);
    middle = actor.sample(1120);
    assert(middle.oldAlpha == 128 && middle.newAlpha == 127 && middle.newOffset == 0);
    actor.begin(1000, 209, 209, true, false, false, true, true);
    assert(actor.sample(1160).oldAlpha == 128 && actor.sample(1320).oldAlpha == 0);
    actor.begin(0xfffffff0u, 399, 209, true, true, true, false, true);
    assert(actor.sample(144).x == 304);
    actor.clock.shift(5000);
    assert(actor.sample(5144).x == 304);
    actor.begin(1000, 399, 209, true, true, true, true, false);
    assert(actor.sample(1000).x == 209 && actor.sample(1000).newAlpha == 255);

    Pixels source(3, 1);
    source.x = 4;
    source.y = 9;
    source.rgba = {255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 0};
    const auto original = source.rgba;
    auto gray = menuBackdrop(source);
    assert(source.rgba == original);
    assert(gray.w == 3 && gray.h == 1 && gray.x == 4 && gray.y == 9);
    assert(gray.rgba == Bytes({68, 68, 68, 255, 145, 145, 145, 128, 47, 47, 47, 0}));

    UiFeedback feedback;
    assert(feedback.alpha(0) == 0);
    feedback.show(12, 1000);
    assert(feedback.slot == 12 && feedback.alpha(1000) == 0);
    assert(feedback.alpha(1200) == 255 && feedback.alpha(2200) == 255);
    assert(feedback.alpha(2480) > 0 && feedback.alpha(2480) < 255);
    assert(feedback.alpha(2600) == 0);
    feedback.show(8, 0xffffff00u);
    assert(feedback.alpha(0) == 255);
    feedback.shift(5000);
    assert(feedback.alpha(5000) == 255);
    feedback.show(2, 1000, false);
    assert(feedback.alpha(1000) == 255 && feedback.alpha(2599) == 255);
    assert(feedback.alpha(2600) == 0);
    std::cout << "UI motion: easing, reduced motion, clock wrap/suspend, immutable grayscale, timed feedback passed\n";
}
