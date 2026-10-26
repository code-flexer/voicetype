if voicetype then
    voicetype.hotkey:delete()
    if voicetype.settingsHotkey then voicetype.settingsHotkey:delete() end
    if voicetype.chooser then voicetype.chooser:hide() end
    if voicetype.menu then voicetype.menu:delete() end
    if voicetype.alert then hs.alert.closeSpecific(voicetype.alert) end
end

voicetype = { recording = false, busy = false, audioMode = "mute" }
local state = voicetype
local script = os.getenv("HOME") .. "/Library/Application Support/local.voicetype/bin/voicetype"

local function updateTitle()
    if state.menu then
        local prefix = state.busy and "⏳ " or (state.recording and "🎙 " or "")
        state.menu:setTitle(prefix .. "VoiceType")
        state.menu:setTooltip(state.audioMode == "music" and "VoiceType · Keep music playing" or "VoiceType · Mute during recording")
    end
end

local function runControl(arguments, callback)
    state.controlTask = hs.task.new(script, function(code, stdout, stderr)
        state.controlTask = nil
        if code ~= 0 then
            hs.alert.show((stdout or "") ~= "" and stdout or stderr, 6)
            return
        end
        local ok, result = pcall(hs.json.decode, stdout or "")
        if ok and result then
            callback(result)
        else
            hs.alert.show("❌ Invalid VoiceType response", 3)
        end
    end, arguments)
    if not state.controlTask:start() then
        state.controlTask = nil
        hs.alert.show("❌ Unable to run VoiceType", 3)
    end
end

local function pasteResult(text)
    if not hs.pasteboard.setContents(text) then
        hs.alert.show("❌ Unable to copy to clipboard", 3)
        return false
    end
    if not hs.accessibilityState() then
        hs.alert.show("📋 Copied · Enable Accessibility for Hammerspoon to insert text", 6)
        return false
    end
    if hs.eventtap.isSecureInputEnabled() then
        hs.alert.show("📋 Copied · Secure Input prevents automatic insertion", 4)
        return false
    end
    local ok = pcall(hs.eventtap.keyStroke, { "cmd" }, "v", 0)
    if not ok then
        hs.alert.show("📋 Copied · Unable to insert. Press ⌘V to paste", 4)
        return false
    end
    hs.alert.show("✅ Inserted", 1.0)
    return true
end

local function onDone(code, stdout, stderr)
    state.busy = false
    state.task = nil
    if state.alert then hs.alert.closeSpecific(state.alert); state.alert = nil end
    local line = (stdout or ""):gsub("[\r\n]+$", "")
    if code == 0 and line == "STARTED" then
        state.recording = true
        state.alert = hs.alert.show("🎙 Recording… · ⌘⌥D to finish", 999999)
    elseif code == 0 and line:sub(1, 7) == "RESULT:" then
        state.recording = false
        local text = line:sub(8)
        if #text > 0 then
            pasteResult(text)
        else
            hs.alert.show("⚠️ No speech detected", 1.5)
        end
    else
        state.recording = false
        local message = line ~= "" and line or (stderr or "VoiceType failed")
        hs.alert.show("❌  " .. message:gsub("^ERROR:", ""), 5)
    end
    updateTitle()
end
state.onDone = onDone

local function selectMode(mode)
    if state.busy or state.recording then
        hs.alert.show("Finish recording before changing settings", 3)
        return
    end
    runControl({ "set-audio-mode", "--audio-mode", mode }, function(result)
        state.audioMode = result.audio_mode
        updateTitle()
        hs.alert.show(mode == "music" and "Keep music playing · Speaker audio reduction enabled" or "Mute during recording", 3)
    end)
end

state.chooser = hs.chooser.new(function(choice)
    if choice then selectMode(choice.mode) end
end)
state.chooser:placeholderText("Speaker behavior during recording")
state.chooser:rows(2)

local function showModeChooser()
    if state.busy or state.recording then
        hs.alert.show("Finish recording before changing settings", 3)
        return
    end
    state.chooser:choices({
        { text = "Mute during recording", subText = "Restore the original speaker state when recording ends", mode = "mute" },
        { text = "Keep music playing", subText = "Keep playback on and reduce speaker audio in the microphone", mode = "music" },
    })
    state.chooser:show()
end

local function toggleRecording()
    if state.busy then return end
    state.busy = true
    if state.alert then hs.alert.closeSpecific(state.alert) end
    state.alert = hs.alert.show(state.recording and "⏳ Transcribing…" or "🎙 Starting recording…", 999999)
    updateTitle()
    state.task = hs.task.new(script, onDone, { "toggle", "--plain" })
    if not state.task:start() then
        state.busy = false
        hs.alert.closeSpecific(state.alert)
        state.alert = nil
        updateTitle()
        hs.alert.show("❌ Unable to start VoiceType", 3)
    end
end

state.hotkey = hs.hotkey.bind({ "cmd", "alt" }, "D", toggleRecording)
state.settingsHotkey = hs.hotkey.bind({ "cmd", "alt", "shift" }, "M", showModeChooser)
state.menu = hs.menubar.new()
updateTitle()
state.menu:setMenu(function()
    return {
        { title = "VoiceType · Voice input", disabled = true },
        { title = "Speaker settings (⌘⌥⇧M)", fn = showModeChooser },
        { title = "Mute during recording", checked = state.audioMode == "mute", fn = function() selectMode("mute") end },
        { title = "Keep music playing", checked = state.audioMode == "music", fn = function() selectMode("music") end },
        { title = "-" },
        { title = state.recording and "Stop and insert at cursor" or "Start recording", fn = toggleRecording, disabled = state.busy },
        { title = "Grant audio permissions…", disabled = state.recording or state.busy, fn = function()
            runControl({ "audio-permissions" }, function(result)
                if result.microphone and result.system_audio then
                    hs.alert.show("Audio permissions granted", 3)
                else
                    hs.alert.show("Allow Microphone and Screen & System Audio Recording in macOS Privacy & Security", 8)
                end
            end)
        end },
        { title = "Grant input permission…", fn = function()
            if hs.accessibilityState(true) then
                hs.alert.show("Input permission granted", 3)
            end
        end },
    }
end)
runControl({ "status" }, function(result)
    state.audioMode = result.audio_mode or "mute"
    state.recording = result.status == "recording"
    updateTitle()
    if state.recording then
        state.alert = hs.alert.show("🎙 Recording… · ⌘⌥D to finish", 999999)
    end
end)

hs.alert.show("Ready · ⌘⌥D to dictate", 2.0)
