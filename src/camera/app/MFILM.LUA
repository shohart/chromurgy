--[[
@title M-Film alpha
@chdk_version 1.6
]]
-- SPDX-License-Identifier: GPL-2.0-only
-- M-Film camera app (alpha): load a "film" (profile + 12/24/36 frames),
-- shoot normally, every DNG the camera writes becomes the next frame of the
-- roll, the roll seals when full (or from the menu). The card then goes to
-- the receiver (mfilmctl import-card), which develops and publishes it.
--
-- Keys
--   while shooting : Playback (short) = M-Film menu; everything else is the camera
--   in the menu    : Up/Down select, Set confirm, Menu back, half-shutter or
--                    Playback = back to shooting, Video = quit the app
-- Frames shot while this script is not running are not on any roll.

local mf = require("mfroll")

local KEYS = {"up", "down", "left", "right", "set", "menu", "shoot_half", "display", "zoom_in", "zoom_out"}
local C = {bg = 256 + 1, fg = 256 + 2, hi = 256 + 15, dim = 256 + 14, warn = 256 + 3, ok = 256 + 6,
           sel = 256 + 10, clear = 256 + 0}
local W, H = 360, 240
local FW, FH = 8, 16
local COLS = 40            -- text columns that fit the screen (set in main)

local roll = nil          -- active roll (state table) or nil
local watcher = nil
local shots_seen = 0
local notice, notice_until = nil, 0
local selftest = {}
local quit = false

local function have(name) return type(_G[name]) == "function" end

local function shot_count()
  if type(hook_raw) == "table" and type(hook_raw.count) == "function" then return hook_raw.count() end
  if have("get_exp_count") then return get_exp_count() end
  return 0
end

local function say(msg, ms)
  notice, notice_until = msg, get_tick_count() + (ms or 4000)
  mf.log("notice: " .. msg)
end

-- ------------------------------------------------------------ self-test (logged once per start)

local function run_selftest()
  local t = {}
  local function add(s) t[#t + 1] = s; mf.log("selftest: " .. s) end
  local bi = have("get_buildinfo") and get_buildinfo() or {}
  add(string.format("app %s on %s %s CHDK %s-%s", mf.VERSION, tostring(bi.platform), tostring(bi.platsub),
      tostring(bi.build_number), tostring(bi.build_revision)))
  local missing = {}
  for _, n in ipairs({"get_image_dir", "exit_alt", "enter_alt", "get_alt_mode", "draw_string", "draw_rect_filled",
                      "draw_clear", "wait_click", "is_key", "set_exit_key", "get_exp_count", "get_tick_count",
                      "get_gui_screen_width", "get_gui_screen_height", "get_raw", "get_vbatt", "sleep"}) do
    if not have(n) then missing[#missing + 1] = n end
  end
  for _, n in ipairs({"listdir", "stat", "rename", "remove", "mkdir", "date", "time"}) do
    if type(os[n]) ~= "function" then missing[#missing + 1] = "os." .. n end
  end
  add("missing functions: " .. (#missing > 0 and table.concat(missing, " ") or "none"))
  add("hook_raw: " .. ((type(hook_raw) == "table" and type(hook_raw.count) == "function") and "yes" or "no (using get_exp_count)"))
  -- no rename test: on this camera rename refuses to replace a file, and the
  -- camera powered off renaming inside a long-named directory. Nothing renames.
  local d = mf.ROOT .. "/LOGS"
  local ap = d .. "/APTEST.TMP"
  local f = io.open(ap, "a")
  add("append mode: " .. (f and "yes" or "no (rewrite fallback)"))
  if f then f:close() end
  os.remove(ap)
  if have("get_raw") then add("RAW/DNG saving: " .. (get_raw() and "on" or "OFF")) end
  add("screen " .. W .. "x" .. H .. ", image dir " .. tostring(have("get_image_dir") and get_image_dir()))
  if have("get_vbatt") then add("battery " .. get_vbatt() .. " mV") end
  return t
end

-- ------------------------------------------------------------ drawing

local function text(col, row, s, fg, bg)
  draw_string(col * FW, row * FH, s, fg or C.fg, bg or C.bg)
end

local function frame_text(r)
  if not r then return "NO FILM" end
  return string.format("%s %d/%d", mf.film_name(r.film), #r.frames, r.length)
end

-- small status line drawn over the live view while shooting
local function overlay()
  local s = "M-Film " .. frame_text(roll)
  if roll and roll.state == "SEALED" then s = s .. " DONE" end
  local fg = roll and C.fg or C.warn
  draw_string(4, 4, string.sub(s, 1, COLS - 1), fg, C.bg)
  if notice and get_tick_count() < notice_until then
    draw_string(4, 4 + FH + 2, string.sub(notice, 1, COLS - 1), C.hi, C.bg)
  end
end

-- Menus are drawn only when their content changes (and every few seconds, in
-- case the camera's own display update erased them): redrawing the whole
-- screen on every key poll made it flicker over the live view. No full-screen
-- fill either; each line is drawn with its own background and padded to the
-- screen width. The bottom text row belongs to CHDK's <ALT>/<EXIT> bar.
local last_key, last_full = nil, 0

local function pad(s)
  s = string.sub(s or "", 1, COLS)
  return s .. string.rep(" ", COLS - string.len(s))
end

local function screen(title, lines, items, sel, footer)
  local rows_total = H / FH - 1                 -- last row: CHDK's bar
  local key_ = title .. "|" .. tostring(sel) .. "|" .. table.concat(items or {}, "/")
  for _, l in ipairs(lines or {}) do key_ = key_ .. "|" .. (type(l) == "table" and l[1] or l) end
  if key_ == last_key and get_tick_count() - last_full < 3000 then return end
  if key_ ~= last_key then draw_clear() end
  last_key, last_full = key_, get_tick_count()
  local row = 0
  text(0, row, pad(" " .. title), C.hi)
  row = row + 1
  for _, l in ipairs(lines or {}) do
    if row >= rows_total - 1 then break end
    local s, col = l, C.dim
    if type(l) == "table" then s, col = l[1], l[2] or C.dim end
    text(0, row, pad(" " .. s), col)
    row = row + 1
  end
  if items then
    text(0, row, pad(""), C.fg)
    row = row + 1
    local rows = rows_total - row - 1
    local first = 1
    if sel > rows then first = sel - rows + 1 end
    for i = first, math.min(#items, first + rows - 1) do
      if i == sel then text(0, row, pad(" > " .. items[i]), C.fg, C.sel)
      else text(0, row, pad("   " .. items[i]), C.fg) end
      row = row + 1
    end
    while row < rows_total - 1 do text(0, row, pad(""), C.fg); row = row + 1 end
  end
  text(0, rows_total - 1, pad(footer or " SET ok  MENU back  half-press: shoot"), C.dim)
end

-- wait for one of KEYS; returns the key name, "shoot" if alt mode was left, or nil on timeout
local function key(ms)
  wait_click(ms or 250)
  for _, k in ipairs(KEYS) do
    if is_key(k) then return k end
  end
  if have("get_alt_mode") and not get_alt_mode() then return "shoot" end
  return nil
end

-- generic list chooser: returns index or nil (back) or "shoot"
local function choose(title, lines, items, sel)
  sel = sel or 1
  while true do
    screen(title, lines, items, sel)
    local k = key()
    if k == "up" then sel = (sel > 1) and sel - 1 or #items
    elseif k == "down" then sel = (sel < #items) and sel + 1 or 1
    elseif k == "set" or k == "right" then return sel
    elseif k == "menu" or k == "left" then return nil
    elseif k == "shoot_half" or k == "shoot" then return "shoot"
    end
  end
end

local function confirm(title, lines)
  local r = choose(title, lines, {"Yes", "No"}, 2)
  return r == 1
end

-- ------------------------------------------------------------ actions

local function load_film()
  if roll and roll.state ~= "SEALED" and #roll.frames > 0 then
    if not confirm("Load new film", {"The roll in the camera has " .. #roll.frames .. " frame(s).",
                                     "Finish (seal) it and load a new one?"}) then return end
    mf.seal(roll, "new film loaded")
  elseif roll and roll.state ~= "SEALED" then
    -- empty roll: replace it, no frames are lost
    mf.journal(roll, "UNLOADED empty")
    roll.state = "SEALED"
    mf.set_active(nil)
  end
  local names = {}
  for _, f in ipairs(mf.cfg.films) do names[#names + 1] = f.name end
  mf.log("film list: " .. #names .. " films")
  local fi = choose("Choose film", {}, names, 1)
  if type(fi) ~= "number" then return fi end
  mf.log("film chosen: " .. mf.cfg.films[fi].key)
  local li = choose("Roll length: " .. mf.cfg.films[fi].name, {}, {"36 frames", "24 frames", "12 frames"}, 1)
  if type(li) ~= "number" then return li end
  local r, err = mf.new_roll(mf.cfg.films[fi].key, ({36, 24, 12})[li])
  if not r then say("ERROR: " .. tostring(err), 8000) return end
  roll = r
  say("Loaded " .. mf.film_name(r.film) .. " x" .. r.length, 5000)
  return "shoot"
end

local function seal_now()
  if not roll or roll.state == "SEALED" then return end
  if #roll.frames == 0 then say("Roll is empty: nothing to finish") return end
  if confirm("Finish roll", {frame_text(roll), "Seal it now? It is then ready for the server."}) then
    mf.seal(roll, "finished from menu")
    roll = nil
    say("Roll finished: ready for import", 6000)
  end
end

local function show_rolls()
  local rolls = mf.list_rolls()
  local items = {}
  for _, r in ipairs(rolls) do
    items[#items + 1] = string.format("%s %s %d/%d %s", string.sub(r.created_at or "", 6, 10),
                                      string.sub(mf.film_name(r.film), 1, 14), #r.frames, r.length,
                                      r.state == "SEALED" and "ready" or "in camera")
  end
  if #items == 0 then items = {"(no rolls yet)"} end
  return choose("Rolls on this card (" .. #rolls .. ")", {}, items, 1)
end

local function show_diag()
  last_key = nil
  local lines = {}
  for _, s in ipairs(selftest) do lines[#lines + 1] = s end
  lines[#lines + 1] = "device " .. mf.device.device_id
  lines[#lines + 1] = "log: CHDK/MFILM/LOGS/APP.LOG"
  screen("Diagnostics", lines, nil, 1, "any key: back")
  repeat until key(1000)
end

local function menu()
  draw_clear()
  last_key = nil
  local sel = 1
  while not quit do
    local status = {{"Film: " .. frame_text(roll), roll and C.fg or C.warn}}
    if have("get_raw") and not get_raw() then status[#status + 1] = {"RAW/DNG is OFF: enable it in CHDK RAW menu", C.warn} end
    if notice and get_tick_count() < notice_until then status[#status + 1] = {notice, C.hi} end
    local items = {"Shoot", roll and roll.state ~= "SEALED" and "Load new film (finish this one)" or "Load film",
                   "Finish roll now", "Rolls on card", "Diagnostics", "Quit M-Film"}
    local i = choose("M-Film " .. mf.VERSION, status, items, sel)
    if i == "shoot" or i == 1 or i == nil then break end
    sel = i
    mf.log("menu: " .. items[i])
    local r
    if i == 2 then r = load_film()
    elseif i == 3 then seal_now()
    elseif i == 4 then r = show_rolls()
    elseif i == 5 then show_diag()
    elseif i == 6 then
      if confirm("Quit M-Film", {"Frames shot after quitting are NOT recorded.", "The roll stays loaded."}) then
        quit = true
      end
    end
    if r == "shoot" then break end
  end
  draw_clear()
end

-- ------------------------------------------------------------ shooting

local function on_new_dng(f)
  if f.changed then
    local fr = roll and mf.has_path(roll, f.path)
    mf.log("WARNING: DNG changed after it was recorded: " .. f.path .. " size " .. f.size)
    if fr then
      mf.journal(roll, "WARNING frame " .. fr.ordinal .. " file changed (size " .. f.size .. ")")
      say("WARNING: frame " .. fr.ordinal .. " DNG was overwritten", 8000)
    end
    return
  end
  if not roll or roll.state == "SEALED" then
    mf.log("shot outside a roll: " .. f.path)
    say("NO FILM: shot not on a roll (Playback = menu)", 5000)
    return
  end
  local fr, err = mf.add_frame(roll, f.path, f.size, f.mtime)
  if not fr then
    mf.log("frame not recorded (" .. tostring(err) .. "): " .. f.path)
    say("ERROR: frame not recorded: " .. tostring(err), 8000)
    return
  end
  if #roll.frames >= roll.length then
    mf.seal(roll, "roll full")
    say(string.format("Roll complete (%d). Playback = load new film", roll.length), 15000)
  end
end

local function shooting()
  if have("exit_alt") then exit_alt() end
  local last_draw, pending_since = 0, nil
  while not quit do
    local dir = get_image_dir()
    local n = shot_count()
    if n ~= shots_seen then
      shots_seen = n
      pending_since = pending_since or get_tick_count()
    end
    local found = watcher.poll(dir)
    for _, f in ipairs(found) do on_new_dng(f) end
    if #found > 0 then pending_since = nil end
    if pending_since and get_tick_count() - pending_since > 10000 then
      pending_since = nil
      mf.log("shot without a new DNG within 10 s (RAW off?)")
      say("No DNG written: is RAW/DNG on in CHDK?", 8000)
    end
    if get_tick_count() - last_draw > 500 then
      overlay()
      last_draw = get_tick_count()
    end
    if have("get_alt_mode") and get_alt_mode() then return end   -- Playback pressed: menu
    sleep(pending_since and 100 or 200)
  end
end

-- ------------------------------------------------------------ main

local function main()
  if have("get_gui_screen_width") then W, H = get_gui_screen_width(), get_gui_screen_height() end
  COLS = W / FW
  if COLS > 60 then COLS = 60 end
  local problems = mf.init()
  mf.log("---- start " .. mf.VERSION)
  selftest = run_selftest()
  for _, p in ipairs(problems) do selftest[#selftest + 1] = "CONFIG: " .. p; mf.log("CONFIG problem: " .. p) end
  if have("set_exit_key") then set_exit_key("video") end
  roll = mf.active_roll()
  if roll and roll.state == "SEALED" then roll = nil end
  watcher = mf.watcher(get_image_dir())
  shots_seen = shot_count()
  if #problems > 0 then say("Setup problem: see Diagnostics", 15000) end
  if roll then
    mf.journal(roll, "RESUMED app start, " .. #roll.frames .. " frame(s)")
    say("Resumed " .. frame_text(roll), 5000)
  end
  while not quit do
    menu()
    if quit then break end
    shooting()
  end
  mf.log("---- quit")
end

-- no pcall around main: CHDK's sleep/wait_click yield the script coroutine,
-- and Lua 5.1 cannot yield across pcall. Errors end the script with CHDK's
-- own message; state on the card is always consistent (atomic writes).
main()
