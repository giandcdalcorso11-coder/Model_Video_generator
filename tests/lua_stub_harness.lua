-- Generic stub harness for generated "Auto Template - ...lua" scripts.
-- Usage: lua5.1 tests/lua_stub_harness.lua <path-to-generated-script.lua>
--
-- Deliberately leaves `io` and `os.execute` nil, matching Resolve's real
-- scripting sandbox (confirmed interactively: neither works there, nor do
-- bmd.readfile/writefile/execute). A generated script that touches either
-- will error out here exactly like it would in real Resolve.
io = nil
os.execute = nil

local script_path = arg[1]
if not script_path then
  print("SCRIPT ERROR: no script path given as arg[1]")
  os.exit(1)
end

local calls = {}
local function record(name, ...)
  table.insert(calls, { name = name, args = { ... } })
end

local track_counts = { subtitle = 0, audio = 1 }

local timeline_item_mt = {}
timeline_item_mt.__index = timeline_item_mt
function timeline_item_mt:SetProperty(key, value)
  record("TimelineItem:SetProperty", key, value)
end

local timeline_mt = {}
timeline_mt.__index = timeline_mt
function timeline_mt:AddMarker(...) record("Timeline:AddMarker", ...) end
function timeline_mt:ImportIntoTimeline(path, opts)
  record("Timeline:ImportIntoTimeline", path, opts.insertAsSubtitle)
  track_counts.subtitle = track_counts.subtitle + 1
end
function timeline_mt:GetTrackCount(t) return track_counts[t] or 0 end
function timeline_mt:SetTrackName(t, i, n) record("Timeline:SetTrackName", t, i, n) end
function timeline_mt:AddTrack(t) track_counts[t] = (track_counts[t] or 0) + 1 end

local mediaPool_mt = {}
mediaPool_mt.__index = mediaPool_mt
function mediaPool_mt:CreateEmptyTimeline(name)
  record("MediaPool:CreateEmptyTimeline", name)
  return setmetatable({}, timeline_mt)
end
function mediaPool_mt:ImportMedia(paths)
  record("MediaPool:ImportMedia", paths[1])
  return { setmetatable({}, timeline_item_mt) }
end
function mediaPool_mt:AppendToTimeline(clipInfos)
  local info = clipInfos[1]
  record("MediaPool:AppendToTimeline", info.startFrame, info.endFrame, info.mediaType, info.trackIndex)
  return { setmetatable({}, timeline_item_mt) }
end

local project_mt = {}
project_mt.__index = project_mt
function project_mt:GetMediaPool() return setmetatable({}, mediaPool_mt) end
function project_mt:SetCurrentTimeline(t) record("Project:SetCurrentTimeline") end

local projectManager_mt = {}
projectManager_mt.__index = projectManager_mt
function projectManager_mt:GetCurrentProject() return setmetatable({}, project_mt) end

resolve = {
  GetProjectManager = function(self) return setmetatable({}, projectManager_mt) end,
}

local chunk, load_err = loadfile(script_path)
if not chunk then
  print("SCRIPT ERROR (load): " .. tostring(load_err))
  os_exit_requested = true
end

if chunk then
  local ok, err = pcall(chunk)
  if not ok then
    print("SCRIPT ERROR (run): " .. tostring(err))
    os_exit_requested = true
  end
end

print(string.format("Total calls recorded: %d", #calls))
for _, c in ipairs(calls) do
  local parts = {}
  for _, a in ipairs(c.args) do table.insert(parts, tostring(a)) end
  print(c.name .. "(" .. table.concat(parts, ", ") .. ")")
end
