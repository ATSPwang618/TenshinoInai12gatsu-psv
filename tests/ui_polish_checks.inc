// Included inside the existing real-App UI smoke, with private isolated save state.
{
    const bool enabledBefore = preferences.value("effects", true);
    preferences["effects"] = true;
    const auto titlePixels = snapshots.last.render().rgba;
    dispatch(2, 2);
    require(uiTransitionPending && uiInputBlocked(), "Menu opening failed to guard input before first draw");
    action(2);
    pointerDown(400, 200);
    pointerUp(400, 200);
    require(uiScreen == UiSettings, "Opening animation let cancel/touch leak through");
    draw();
    require(uiTransition.active(SDL_GetTicks()), "Menu fade expired while destination was loading");
    require(snapshots.last.render().rgba == titlePixels, "First menu frame flashed instead of preserving previous frame");
    captureUi("motion-0");
    const auto frozen = uiBackdrop.pixels;
    require(frozen != nullptr, "Menu has no immutable gray backdrop");
    for (size_t i = 0; i < frozen->rgba.size(); i += 4)
        require(frozen->rgba[i] == frozen->rgba[i + 1] && frozen->rgba[i + 1] == frozen->rgba[i + 2],
                "Menu backdrop did not desaturate");
    uiTransition.start = SDL_GetTicks() - 170;
    draw();
    const auto middle = snapshots.last.render().rgba;
    captureUi("motion-1");
    settleUi();
    const auto complete = snapshots.last.render().rgba;
    captureUi("motion-2");
    require(middle != titlePixels && middle != complete, "Menu fade has no intermediate frame");
    require(!uiInputBlocked(), "Menu did not release input after fade");
    require(uiBackdrop.pixels == frozen, "Menu reprocessed gray backdrop every frame");
    // Capture the actual engine's 340ms slide, not an independently drawn mock.
    closeUi();
    settleUi();
    dispatch(2, 2);
    draw();
    for (int frame = 0; frame <= 20; frame++) {
        uiTransition.start = SDL_GetTicks() - frame * 17;
        draw();
        captureUi("menu-slide-" + number(frame, 2));
    }
    dispatch(2, 3);
    require(uiTransitionPending, "Settings tab switched without a transition");
    require(uiSlideX == 72 && uiSlideY == 0, "Forward settings tab did not slide horizontally");
    settleUi();
    closeUi();
    require(uiInputBlocked(), "Menu closing did not protect the story from input");
    const bool wasInGame = inGame;
    inGame = true;
    require(keyboardShortcut(SDLK_F5) && keyboardShortcut(SDLK_F9) && keyboardShortcut(SDLK_v),
            "Production keyboard shortcuts not handled");
    require(uiScreen == UiNone, "Keyboard shortcut reopened a menu during the closing fade");
    inGame = wasInGame;
    settleUi();
    require(uiScreen == UiNone && !uiInputBlocked() && !uiBackdrop.ptr && !uiCover.ptr,
            "Closing transition did not release buffers/input");
    preferences["effects"] = false;
    dispatch(3, 1);
    draw();
    require(uiScreen == UiSave && !uiInputBlocked(), "Reduced-motion menu is not immediately usable");
    notifyUi("已保存至存档 01", 1);
    require(uiFeedback.alpha(SDL_GetTicks()) == 255, "Reduced-motion feedback still fades in");
    uiFeedback.duration = 0;
    ask("覆盖这个存档？", 72, 1);
    dispatch(64);
    require(uiScreen == UiSave, "Cancelling overwrite left the save page");
    ask("覆盖这个存档？", 72, 1);
    action(2);
    require(uiScreen == UiSave, "Circle/Escape cancelling overwrite left the save page");
    closeUi();
    preferences["effects"] = enabledBefore;
    settleUi();
    fprintf(stderr, "UI polish smoke passed: first/middle/final fades, frozen grayscale, blocked input, settings tabs, close cleanup, reduced motion, overwrite cancel\n");
}
