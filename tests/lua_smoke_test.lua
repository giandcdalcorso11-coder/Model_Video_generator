-- Stub-based smoke test for "lua/Auto Template.lua". Not part of the
-- installed plugin, and not run by `pytest` (different language/runtime) --
-- mocks `fusion`, `resolve` and `os.execute` so the real script's logic can
-- run end-to-end (JSON decode, chronological clip/gap tiling, markers,
-- subtitle tracks, voice/music tracks) without a real DaVinci Resolve or
-- Python/ffmpeg on this machine. Run manually from the repo root with:
--
--     lua5.1 tests/lua_smoke_test.lua
--
-- (or `lua`/`luajit`, whichever Lua 5.1-compatible interpreter you have).
-- A clean run ends by printing every Resolve API call the script made, with
-- no "SCRIPT ERROR" line. Re-run this after any change to the Lua script.

local calls = {}
local function record(name, ...)
  table.insert(calls, { name = name, args = { ... } })
end

local fake_json = [[
{
  "source_video_path": "unused",
  "fps": 25,
  "clips": [
    {"index": 0, "source_in_seconds": 0.0, "source_out_seconds": 2.0, "timeline_start_seconds": 0.0, "transforms": []},
    {"index": 1, "source_in_seconds": 3.0, "source_out_seconds": 5.0, "timeline_start_seconds": 3.0, "transforms": []}
  ],
  "gaps": [
    {"start_seconds": 2.0, "end_seconds": 3.0}
  ],
  "texts": [
    {"content": "ISCRIVITI", "start_seconds": 0.5, "end_seconds": 1.0, "position": {"x": 0.5, "y": 0.85}, "style_notes": ""}
  ],
  "dialogue": [
    {"content": "ciao a tutti", "start_seconds": 0.0, "end_seconds": 1.0, "position": {"x": 0.5, "y": 0.85}, "style_notes": ""}
  ],
  "effect_notes": [
    {"label": "dissolve", "at_seconds": 2.0, "confidence": 0.6, "source": "ai"}
  ],
  "voice_segments": [
    {"index": 0, "start_seconds": 0.0, "end_seconds": 1.0, "transcript": "ciao a tutti"}
  ],
  "music_segments": [
    {"index": 0, "start_seconds": 1.0, "end_seconds": 5.0}
  ]
}
]]

-- ---- fusion stub ----
fusion = {
  RequestFile = function(self)
    return "/fake/videos/my_clip.mp4"
  end,
}

-- ---- resolve stub ----
local track_counts = { subtitle = 0, audio = 1 }
local appended_items = {}

local timeline_item_mt = {}
timeline_item_mt.__index = timeline_item_mt
function timeline_item_mt:SetProperty(key, value)
  record("TimelineItem:SetProperty", key, value)
end

local function make_timeline_item()
  local item = setmetatable({}, timeline_item_mt)
  table.insert(appended_items, item)
  return item
end

local timeline_mt = {}
timeline_mt.__index = timeline_mt
function timeline_mt:AddMarker(...)
  record("Timeline:AddMarker", ...)
end
function timeline_mt:ImportIntoTimeline(path, opts)
  record("Timeline:ImportIntoTimeline", path, opts.insertAsSubtitle)
  track_counts.subtitle = track_counts.subtitle + 1
end
function timeline_mt:GetTrackCount(track_type)
  return track_counts[track_type] or 0
end
function timeline_mt:SetTrackName(track_type, index, name)
  record("Timeline:SetTrackName", track_type, index, name)
end
function timeline_mt:AddTrack(track_type)
  track_counts[track_type] = (track_counts[track_type] or 0) + 1
end

local mediaPool_mt = {}
mediaPool_mt.__index = mediaPool_mt
function mediaPool_mt:CreateEmptyTimeline(name)
  record("MediaPool:CreateEmptyTimeline", name)
  return setmetatable({}, timeline_mt)
end
function mediaPool_mt:ImportMedia(paths)
  record("MediaPool:ImportMedia", paths[1])
  return { { GetName = function() return paths[1] end } }
end
function mediaPool_mt:AppendToTimeline(clipInfos)
  local info = clipInfos[1]
  record("MediaPool:AppendToTimeline", info.startFrame, info.endFrame, info.mediaType, info.trackIndex)
  return { make_timeline_item() }
end

local project_mt = {}
project_mt.__index = project_mt
function project_mt:GetMediaPool()
  return setmetatable({}, mediaPool_mt)
end
function project_mt:SetCurrentTimeline(t)
  record("Project:SetCurrentTimeline")
end

local projectManager_mt = {}
projectManager_mt.__index = projectManager_mt
function projectManager_mt:GetCurrentProject()
  return setmetatable({}, project_mt)
end

resolve = {
  GetProjectManager = function(self)
    return setmetatable({}, projectManager_mt)
  end,
}

-- ---- os.execute stub: intercept the "run analysis" call and drop a fake
-- template.json where the script expects it, instead of really running
-- python/ffmpeg. ----
local real_os_execute = os.execute
os.execute = function(cmd)
  record("os.execute", cmd)
  local project_dir = cmd:match('run_analysis%.py" "[^"]*" "([^"]*)"')
  if project_dir then
    os.execute = real_os_execute
    -- The real script joins paths with a literal "\\" (Windows-style), which
    -- on this Linux test box is just a normal filename character, not a real
    -- directory separator -- so match that exactly here rather than using "/".
    local f = io.open(project_dir .. "\\template.json", "w")
    f:write(fake_json)
    f:close()
    local src = io.open(project_dir .. "\\source_video.mp4", "w")
    src:write("fake")
    src:close()
    os.execute = function(c) record("os.execute", c); return true end
  end
  return true
end

-- run the real script
local chunk = assert(loadfile("lua/Auto Template.lua"))
local ok, err = pcall(chunk)
if not ok then
  print("SCRIPT ERROR: " .. tostring(err))
  os.exit(1)
end

print(string.format("Total calls recorded: %d", #calls))
for _, c in ipairs(calls) do
  local parts = {}
  for _, a in ipairs(c.args) do
    table.insert(parts, tostring(a))
  end
  print(c.name .. "(" .. table.concat(parts, ", ") .. ")")
end
