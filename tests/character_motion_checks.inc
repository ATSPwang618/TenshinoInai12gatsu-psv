// Real archive sprites + the production renderer, using only private smoke state.
{
    std::vector<int> codes;
    for (int id = 1; id < int(vm->metadata().at("characters").size()) / 2 && codes.size() < 2; id++) {
        codes.clear();
        const auto prefix = vm->metadata().at("characters").at(id * 2).get<std::string>();
        for (int pose = 1; pose < 10 && codes.size() < 2; pose++)
            for (int face = 1; face < 16 && codes.size() < 2; face++)
                if (asset("char.a").contains(prefix + number(pose * 100 + face) + ".px"))
                    codes.push_back((id << 8) | (face << 4) | pose);
    }
    require(codes.size() == 2, "Character animation needs two real expression sprites");
    const bool waitingBefore = messageWaiting;
    messageWaiting = false; // The animated dialogue cursor is not part of an actor transition.
    draw();
    const auto empty = snapshots.last.render().rgba;
    captureUi("actor-empty");
    visual["characters"] = {codes[0], 0, 0};
    visual["count"] = 1;
    draw();
    captureUi("actor-first");
    require(snapshots.last.render().rgba == empty,
            "Character entrance snapped straight to final image instead of starting from prior frame");
    auto phase = [&](uint32_t elapsed) {
        for (auto &layer : actorLayers)
            if (layer && layer->motion.clock.duration)
                layer->motion.clock.start = SDL_GetTicks() - elapsed;
        draw();
    };
    for (int frame = 0; frame <= 20; frame++) {
        phase(frame * 16);
        captureUi("actor-enter-" + number(frame, 2));
    }
    const auto entered = snapshots.last.render().rgba;
    require(entered != empty, "Character never became visible");
    require(actorLayers[0]->motion.sample(SDL_GetTicks()).x == 399,
            "Entrance did not land at the original center");
    visual["characters"] = {0, 0, 0};
    visual["count"] = 0;
    draw();
    phase(320);
    visual["characters"] = {0, codes[0], 0};
    visual["count"] = 2;
    draw();
    require(actorLayers[1]->motion.sample(actorLayers[1]->motion.clock.start).x == 589,
            "New right actor entered from a stale center rather than its own station");
    phase(320);
    visual["characters"] = {0, 0, 0};
    visual["count"] = 0;
    draw();
    phase(320);
    visual["characters"] = {codes[0], 0, 0};
    visual["count"] = 1;
    draw();
    phase(320);
    visual["characters"][0] = codes[1];
    draw();
    const auto expressionFirst = snapshots.last.render().rgba;
    int firstDifference = 0;
    for (size_t p = 0; p < entered.size(); p++)
        firstDifference = std::max(firstDifference, std::abs(int(entered[p]) - int(expressionFirst[p])));
    fprintf(stderr, "Expression first-frame maximum channel difference: %d\n", firstDifference);
    require(firstDifference <= 2, "Expression replacement flashed on its first frame");
    for (int frame = 0; frame <= 8; frame++) {
        phase(frame * 15);
        captureUi("actor-face-" + number(frame, 2));
    }
    const auto mixed = snapshots.last.render().rgba;
    require(mixed != entered, "Expression has no intermediate frame");
    visual["characters"][0] = codes[0];
    draw();
    const auto interrupted = snapshots.last.render().rgba;
    int jump = 0;
    for (size_t p = 0; p < mixed.size(); p++)
        jump = std::max(jump, std::abs(int(mixed[p]) - int(interrupted[p])));
    require(jump <= 4, "Interrupted expression jumped instead of continuing from visible mixture");
    for (int change = 0; change < 24; change++) {
        phase(80);
        visual["characters"][0] = codes[change % 2];
        draw();
        if (actorLayers[0]->from)
            require(actorLayers[0]->from->w <= 800 && actorLayers[0]->from->h <= 600,
                    "Interrupted sprite composites grew beyond the viewport");
    }
    phase(100);
    showUi(UiSettings);
    const auto pausedPose = actorLayers[0]->motion.sample(actorsPausedAt);
    draw();
    draw();
    require(actorLayers[0]->motion.sample(actorLayers[0]->drawnAt).newAlpha == pausedPose.newAlpha,
            "Actor animation advanced behind a modal menu");
    setSuspended(true);
    // Simulate a one-second suspend without a blocking sleep. Rebase every
    // paused timestamp consistently, then exercise the production resume path.
    suspendedAt -= 1000;
    actorsPausedAt -= 1000;
    for (auto &layer : actorLayers) {
        layer->motion.clock.start -= 1000;
        layer->drawnAt -= 1000;
    }
    setSuspended(false);
    draw();
    require(actorLayers[0]->motion.sample(actorLayers[0]->drawnAt).newAlpha == pausedPose.newAlpha,
            "Suspending inside a menu completed the paused actor animation");
    closeUi();
    settleUi();
    phase(320);
    visual["count"] = 2; // Same person moves from center399 to original left209.
    draw();
    phase(160);
    require(actorLayers[0]->motion.sample(actorLayers[0]->motion.clock.start + 160).x == 304,
            "Character station change teleported instead of moving through midpoint");
    captureUi("actor-move-middle");
    phase(320);
    visual["characters"] = {0, 0, 0};
    visual["count"] = 0;
    draw();
    for (int frame = 0; frame <= 20; frame++) {
        phase(frame * 16);
        captureUi("actor-exit-" + number(frame, 2));
    }
    require(snapshots.last.render().rgba == empty, "Departed character left a residual image");
    preferences["effects"] = false;
    visual["characters"] = {codes[0], 0, 0};
    visual["count"] = 1;
    draw();
    require(!actorLayers[0]->motion.clock.active(SDL_GetTicks()) &&
                actorLayers[0]->motion.sample(SDL_GetTicks()).newAlpha == 255,
            "Effects-off character change was not immediate");
    preferences["effects"] = true;
    skipMode = true;
    visual["characters"][0] = codes[1];
    draw();
    require(!actorLayers[0]->motion.clock.active(SDL_GetTicks()), "Fast-forward started actor animation");
    skipMode = false;
    heldSkip = true;
    visual["characters"][0] = codes[0];
    draw();
    require(!actorLayers[0]->motion.clock.active(SDL_GetTicks()), "Held skip started actor animation");
    heldSkip = false;
    require(beginEffect(2), "Original script transition fixture unavailable");
    visual["characters"][0] = codes[1];
    draw();
    require(!actorLayers[0]->motion.clock.active(SDL_GetTicks()),
            "Automatic actor animation overlapped an original script transition");
    effectId = 0;
    deadline = 0;
    draw();
    require(!actorLayers[0]->motion.clock.active(SDL_GetTicks()),
            "Automatic actor animation restarted after original transition");
    for (int tint : {42, 43}) {
        visual["tone"] = tint;
        draw();
        const auto original = composeScene(visual);
        const auto actual = snapshots.last.render();
        // Dialogue occupies the bottom; unobscured pixels must retain the
        // original whole-scene nonlinear tone arithmetic exactly at rest.
        require(std::equal(original.rgba.begin(), original.rgba.begin() + 800 * 450 * 4,
                           actual.rgba.begin()), "Settled actor tone changed original rendering");
    }
    visual["tone"] = 0;
    draw();
    slot = 39;
    captureDialogueAnchor();
    saveGame();
    visual["characters"][0] = codes[0];
    draw();
    loadGame();
    draw();
    require(!actorLayers[0]->motion.clock.active(SDL_GetTicks()) &&
                actorLayers[0]->motion.sample(SDL_GetTicks()).newAlpha == 255,
            "Loading a save replayed entrance from the previous scene");
    uiFeedback.duration = 0;
    messageWaiting = waitingBefore;
    fprintf(stderr, "Character motion passed: real-sprite entrance, expression/interruption, station movement, exit cleanup, off/skip/held-skip, script priority and load reset\n");
}
