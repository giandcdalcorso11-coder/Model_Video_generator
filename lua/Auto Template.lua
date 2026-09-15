--[[
Auto Template -- builds a Resolve timeline from an AI-analyzed video.

Written in Lua (not Python) because DaVinci Resolve 21.1 restricted
Scripts-menu Python execution to Resolve Studio; Lua scripting is
unrestricted on both Free and Studio. This script itself never runs any AI
or video analysis -- it shells out to a separate Python process
(resolve_plugin/analyze_cli.py, via the run_analysis.py bootstrap next to
it) for that, then reads the resulting template.json and translates it into
Resolve API calls.

This file is a TEMPLATE: scripts/install.py fills in the three __X__
placeholders below and copies the result into your Resolve
Scripts/Edit folder. Don't edit the installed copy directly -- edit this
source file and re-run scripts/install.py, or your changes will be
overwritten on the next install.
--]]

local PYTHON_EXE = "__PYTHON_EXE__"
local LIB_DIR = "__LIB_DIR__"
local PROJECTS_ROOT = "__PROJECTS_ROOT__"

local function log(msg)
  print("[Auto Template] " .. msg)
end

-- ===================== minimal JSON decoder =====================
-- Decode-only (we never need to write JSON from Lua). Handles objects,
-- arrays, strings with the common escapes, numbers, true/false/null.
local json = {}

function json.decode(str)
  local pos = 1
  local len = #str
  local parse_value

  local function skip_ws()
    while pos <= len do
      local c = str:sub(pos, pos)
      if c == " " or c == "\t" or c == "\n" or c == "\r" then
        pos = pos + 1
      else
        break
      end
    end
  end

  local function parse_string()
    pos = pos + 1
    local buf = {}
    while pos <= len do
      local c = str:sub(pos, pos)
      if c == '"' then
        pos = pos + 1
        return table.concat(buf)
      elseif c == "\\" then
        local nc = str:sub(pos + 1, pos + 1)
        if nc == "n" then table.insert(buf, "\n")
        elseif nc == "t" then table.insert(buf, "\t")
        elseif nc == "r" then table.insert(buf, "\r")
        elseif nc == "u" then
          local hex = str:sub(pos + 2, pos + 5)
          local code = tonumber(hex, 16) or 63
          table.insert(buf, string.char(code < 256 and code or 63))
          pos = pos + 4
        else
          table.insert(buf, nc)
        end
        pos = pos + 2
      else
        table.insert(buf, c)
        pos = pos + 1
      end
    end
    error("JSON: stringa non terminata")
  end

  local function parse_number()
    local start = pos
    while pos <= len and str:sub(pos, pos):match("[%d%.%-%+eE]") do
      pos = pos + 1
    end
    return tonumber(str:sub(start, pos - 1))
  end

  local function parse_array()
    pos = pos + 1
    local arr = {}
    skip_ws()
    if str:sub(pos, pos) == "]" then
      pos = pos + 1
      return arr
    end
    while true do
      skip_ws()
      table.insert(arr, parse_value())
      skip_ws()
      local c = str:sub(pos, pos)
      if c == "," then
        pos = pos + 1
      elseif c == "]" then
        pos = pos + 1
        break
      else
        error("JSON: array malformato in posizione " .. pos)
      end
    end
    return arr
  end

  local function parse_object()
    pos = pos + 1
    local obj = {}
    skip_ws()
    if str:sub(pos, pos) == "}" then
      pos = pos + 1
      return obj
    end
    while true do
      skip_ws()
      if str:sub(pos, pos) ~= '"' then
        error("JSON: chiave stringa attesa in posizione " .. pos)
      end
      local key = parse_string()
      skip_ws()
      if str:sub(pos, pos) ~= ":" then
        error("JSON: ':' atteso in posizione " .. pos)
      end
      pos = pos + 1
      skip_ws()
      obj[key] = parse_value()
      skip_ws()
      local c = str:sub(pos, pos)
      if c == "," then
        pos = pos + 1
      elseif c == "}" then
        pos = pos + 1
        break
      else
        error("JSON: oggetto malformato in posizione " .. pos)
      end
    end
    return obj
  end

  parse_value = function()
    skip_ws()
    local c = str:sub(pos, pos)
    if c == '"' then return parse_string()
    elseif c == "{" then return parse_object()
    elseif c == "[" then return parse_array()
    elseif str:sub(pos, pos + 3) == "true" then pos = pos + 4; return true
    elseif str:sub(pos, pos + 4) == "false" then pos = pos + 5; return false
    elseif str:sub(pos, pos + 3) == "null" then pos = pos + 4; return nil
    elseif c:match("[%d%-]") then return parse_number()
    else
      error("JSON: carattere inatteso '" .. tostring(c) .. "' in posizione " .. pos)
    end
  end

  skip_ws()
  return parse_value()
end

-- ===================== helpers =====================

local function sanitize_filename(name)
  return (name:gsub('[<>:"/\\|?*]', "_"))
end

local function get_extension(path)
  return path:match("%.([^.\\/]+)$") or "mp4"
end

local function get_stem(path)
  return path:match("([^\\/]+)%.[^.\\/]+$") or "progetto"
end

local function read_file(path)
  local f = io.open(path, "rb")
  if not f then return nil end
  local content = f:read("*a")
  f:close()
  return content
end

local function write_file(path, content)
  local f = io.open(path, "w")
  if not f then error("Impossibile scrivere: " .. path) end
  f:write(content)
  f:close()
end

local function seconds_to_srt_timestamp(seconds)
  local ms_total = math.floor(seconds * 1000 + 0.5)
  local hours = math.floor(ms_total / 3600000)
  ms_total = ms_total % 3600000
  local minutes = math.floor(ms_total / 60000)
  ms_total = ms_total % 60000
  local secs = math.floor(ms_total / 1000)
  local ms = ms_total % 1000
  return string.format("%02d:%02d:%02d,%03d", hours, minutes, secs, ms)
end

-- ===================== 1. pick video =====================

local fu = fusion or fu
if not fu then
  log("Errore: variabile globale 'fusion' non disponibile. Esegui questo script dal menu Script di Resolve.")
  return
end

local video_path = fu:RequestFile()
if not video_path or video_path == "" then
  log("Nessun video selezionato, uscita.")
  return
end

-- ===================== 2. run the Python analysis =====================

local video_stem = sanitize_filename(get_stem(video_path))
local timestamp = os.date("%Y%m%d_%H%M%S")
local project_dir = PROJECTS_ROOT .. "\\" .. video_stem .. "_" .. timestamp
os.execute('mkdir "' .. project_dir .. '"')

log("Analisi in corso, potrebbe richiedere qualche minuto...")
local analysis_cmd = string.format(
  '"%s" "%s\\run_analysis.py" "%s" "%s"',
  PYTHON_EXE, LIB_DIR, video_path, project_dir
)
os.execute(analysis_cmd)

local template_path = project_dir .. "\\template.json"
local template_raw = read_file(template_path)
if not template_raw then
  log("Errore: analisi non riuscita, template.json non trovato in " .. project_dir)
  log("Controlla la finestra/console di Python per il messaggio di errore esatto.")
  return
end

local ok, template = pcall(json.decode, template_raw)
if not ok or not template then
  log("Errore: template.json non e' un JSON valido (" .. tostring(template) .. ").")
  return
end

log("Analisi completata: " .. #(template.clips or {}) .. " clip, " .. #(template.gaps or {}) .. " spazi vuoti.")

-- ===================== 3. connect to Resolve =====================

if not resolve then
  log("Errore: variabile globale 'resolve' non disponibile. Esegui questo script dal menu Script di Resolve.")
  return
end

local projectManager = resolve:GetProjectManager()
local project = projectManager:GetCurrentProject()
if not project then
  log("Errore: nessun progetto aperto in Resolve. Apri o crea un progetto e riprova.")
  return
end
local mediaPool = project:GetMediaPool()

-- ===================== 4. build the timeline =====================

local timelineName = video_stem
local timeline = mediaPool:CreateEmptyTimeline(timelineName)
if not timeline then
  log("Errore: Resolve non e' riuscito a creare la timeline '" .. timelineName .. "'.")
  return
end
project:SetCurrentTimeline(timeline)

local source_video_path = project_dir .. "\\source_video." .. get_extension(video_path)
local sourceItems = mediaPool:ImportMedia({ source_video_path })
if not sourceItems or not sourceItems[1] then
  log("Errore: impossibile importare " .. source_video_path .. " nel Media Pool.")
  return
end
local sourceItem = sourceItems[1]

local fps = template.fps or 30

local function seconds_to_frames(seconds)
  return math.max(0, math.floor(seconds * fps + 0.5))
end

local placeholder_cache = {}
local function get_or_create_placeholder(min_duration)
  local ceil_s = math.max(1, math.floor(min_duration) + 1)
  if placeholder_cache[ceil_s] then return placeholder_cache[ceil_s] end
  local out_path = project_dir .. "\\placeholder_" .. ceil_s .. "s.mp4"
  local cmd = string.format(
    'ffmpeg -y -f lavfi -i "color=c=black:s=1920x1080:r=%s:d=%d" -c:v libx264 -pix_fmt yuv420p "%s"',
    tostring(fps), ceil_s, out_path
  )
  os.execute(cmd)
  placeholder_cache[ceil_s] = out_path
  return out_path
end

local silence_cache = {}
local function get_or_create_silence(min_duration)
  local ceil_s = math.max(1, math.floor(min_duration) + 1)
  if silence_cache[ceil_s] then return silence_cache[ceil_s] end
  local out_path = project_dir .. "\\silence_" .. ceil_s .. "s.wav"
  local cmd = string.format(
    'ffmpeg -y -f lavfi -i "anullsrc=r=48000:cl=stereo" -t %d -c:a pcm_s16le "%s"',
    ceil_s, out_path
  )
  os.execute(cmd)
  silence_cache[ceil_s] = out_path
  return out_path
end

-- clips + gaps, chronological, contiguous -> correct absolute timing from
-- simple sequential appends (same trick the original Python version used)
local timeline_items = {}
for _, clip in ipairs(template.clips or {}) do
  table.insert(timeline_items, { kind = "clip", data = clip, start_at = clip.source_in_seconds })
end
for _, gap in ipairs(template.gaps or {}) do
  table.insert(timeline_items, { kind = "gap", data = gap, start_at = gap.start_seconds })
end
table.sort(timeline_items, function(a, b) return a.start_at < b.start_at end)

local clip_items = {} -- clip.index -> TimelineItem (for a future Takes-based replace step)

for _, item in ipairs(timeline_items) do
  if item.kind == "clip" then
    local c = item.data
    local startFrame = seconds_to_frames(c.source_in_seconds)
    local endFrame = math.max(startFrame, seconds_to_frames(c.source_out_seconds) - 1)
    local appended = mediaPool:AppendToTimeline({
      { mediaPoolItem = sourceItem, startFrame = startFrame, endFrame = endFrame },
    })
    if appended and appended[1] then
      clip_items[c.index] = appended[1]
      for _, transform in ipairs(c.transforms or {}) do
        for key, value in pairs(transform.properties or {}) do
          appended[1]:SetProperty(key, value)
        end
      end
    end
  else
    local g = item.data
    local duration = g.end_seconds - g.start_seconds
    if duration > 0 then
      local placeholderItems = mediaPool:ImportMedia({ get_or_create_placeholder(duration) })
      if placeholderItems and placeholderItems[1] then
        local endFrame = math.max(0, seconds_to_frames(duration) - 1)
        mediaPool:AppendToTimeline({
          { mediaPoolItem = placeholderItems[1], startFrame = 0, endFrame = endFrame },
        })
      end
    end
  end
end

-- markers for anything the API can't apply automatically (transitions, possible music changes)
for _, note in ipairs(template.effect_notes or {}) do
  local frameId = seconds_to_frames(note.at_seconds)
  timeline:AddMarker(
    frameId, "Yellow", note.label or "Effetto rilevato",
    string.format(
      "Rilevato automaticamente (%s, confidenza=%.2f). Applica manualmente l'effetto/transizione corrispondente qui.",
      note.source or "ai", note.confidence or 0
    ),
    1
  )
end

-- on-screen text and spoken dialogue: two independent subtitle tracks, two
-- independent .srt files -- never merged, see resolve_plugin/analysis/speech.py
local function inject_subtitle_track(overlays, filename, track_name)
  local lines = {}
  local n = 0
  for _, overlay in ipairs(overlays or {}) do
    if overlay.content and overlay.content:match("%S") then
      n = n + 1
      table.insert(lines, tostring(n))
      table.insert(lines, seconds_to_srt_timestamp(overlay.start_seconds) .. " --> " .. seconds_to_srt_timestamp(overlay.end_seconds))
      table.insert(lines, overlay.content)
      table.insert(lines, "")
    end
  end
  if n == 0 then return end
  local srt_path = project_dir .. "\\" .. filename
  write_file(srt_path, table.concat(lines, "\n"))
  timeline:ImportIntoTimeline(srt_path, { insertAsSubtitle = true })
  local idx = timeline:GetTrackCount("subtitle")
  if idx and idx > 0 then
    timeline:SetTrackName("subtitle", idx, track_name)
  end
end

inject_subtitle_track(template.texts, "on_screen_text.srt", "Testo a schermo")
inject_subtitle_track(template.dialogue, "dialogue.srt", "Dialogo (trascrizione)")

-- voice/music: two audio tracks, contiguous fill (real audio + silent
-- placeholder) so sequential appends land at the right absolute time
local voice_segments = template.voice_segments or {}
local music_segments = template.music_segments or {}
if #voice_segments > 0 or #music_segments > 0 then
  timeline:AddTrack("audio")
  local voiceTrackIndex = timeline:GetTrackCount("audio")
  timeline:SetTrackName("audio", voiceTrackIndex, "Voce")

  timeline:AddTrack("audio")
  local musicTrackIndex = timeline:GetTrackCount("audio")
  timeline:SetTrackName("audio", musicTrackIndex, "Musica")

  local audio_items = {}
  for _, v in ipairs(voice_segments) do
    table.insert(audio_items, { is_voice = true, start_seconds = v.start_seconds, end_seconds = v.end_seconds })
  end
  for _, m in ipairs(music_segments) do
    table.insert(audio_items, { is_voice = false, start_seconds = m.start_seconds, end_seconds = m.end_seconds })
  end
  table.sort(audio_items, function(a, b) return a.start_seconds < b.start_seconds end)

  local function append_audio(place_real_audio, targetTrackIndex, item)
    local duration = item.end_seconds - item.start_seconds
    if duration <= 0 then return end
    if place_real_audio then
      local startFrame = seconds_to_frames(item.start_seconds)
      local endFrame = math.max(startFrame, seconds_to_frames(item.end_seconds) - 1)
      mediaPool:AppendToTimeline({
        {
          mediaPoolItem = sourceItem, startFrame = startFrame, endFrame = endFrame,
          mediaType = 2, trackIndex = targetTrackIndex,
        },
      })
    else
      local silenceItems = mediaPool:ImportMedia({ get_or_create_silence(duration) })
      if silenceItems and silenceItems[1] then
        local endFrame = math.max(0, seconds_to_frames(duration) - 1)
        mediaPool:AppendToTimeline({
          { mediaPoolItem = silenceItems[1], startFrame = 0, endFrame = endFrame, trackIndex = targetTrackIndex },
        })
      end
    end
  end

  for _, item in ipairs(audio_items) do
    append_audio(item.is_voice, voiceTrackIndex, item)
    append_audio(not item.is_voice, musicTrackIndex, item)
  end
end

log("Timeline '" .. timelineName .. "' creata con successo.")
log("Nota: la sostituzione clip con le tue riprese (Take) non e' ancora disponibile in questa versione Lua.")
