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

local overlay_until_ref = nil
local function say(msg, ms)
  notice, notice_until = msg, get_tick_count() + (ms or 4000)
  if overlay_until_ref then overlay_until_ref(ms or 4000) end
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

-- ------------------------------------------------------------ graphics
-- CHDK Lua draws only rectangles, lines, ellipses and text (no images, no
-- emoji). Everything stays inside the 360x240 bitmap: CHDK does not clip.
local CC = {black = 256 + 1, white = 256 + 2, red = 256 + 3, red_lt = 256 + 5, green = 256 + 6, blue_lt = 256 + 11,
            grey = 256 + 12, grey_dk = 256 + 13, grey_lt = 256 + 14, yellow = 256 + 15, magenta = 256 + 19}

local function box(x1, y1, x2, y2, col)
  if x1 < 0 then x1 = 0 end
  if y1 < 0 then y1 = 0 end
  if x2 > W - 1 then x2 = W - 1 end
  if y2 > H - 1 then y2 = H - 1 end
  if x2 < x1 or y2 < y1 then return end
  draw_rect_filled(x1, y1, x2, y2, col, col)
end

-- canister colour by maker, from the film's display name
local function brand_colour(key)
  local n = string.lower(mf.film_name(key) or key)
  if string.find(n, "^kodak") then return CC.yellow end
  if string.find(n, "^fuji") then return CC.green end
  if string.find(n, "^cinestill") then return CC.red end
  if string.find(n, "^ilford") or string.find(n, "^kentmere") then return CC.grey_lt end
  if string.find(n, "^agfa") then return CC.red_lt end
  if string.find(n, "^lomo") then return CC.magenta end
  return CC.blue_lt
end

-- a 35 mm canister, 16x16, top-left at x,y
local function canister(x, y, key)
  local col = brand_colour(key)
  box(x + 6, y, x + 8, y + 1, CC.grey)           -- spool knob
  box(x + 1, y + 2, x + 11, y + 3, CC.grey_lt)   -- top cap
  box(x + 2, y + 4, x + 10, y + 12, col)         -- body
  box(x + 3, y + 6, x + 9, y + 7, CC.white)      -- label stripe
  box(x + 1, y + 13, x + 11, y + 14, CC.grey_lt) -- bottom cap
  box(x + 11, y + 6, x + 15, y + 11, CC.grey_dk) -- film leader
end

-- film strip: n frames across width w, the first `shot` exposed; 12 px high
local function strip(x, y, w, n, shot)
  if n < 1 then return end
  local cw = w / n
  if cw < 3 then cw = 3 end
  box(x, y, x + cw * n, y + 11, CC.black)
  for i = 0, n - 1 do
    local cx = x + i * cw
    if cw >= 5 then
      box(cx + 1, y + 1, cx + 2, y + 2, CC.grey)  -- sprocket holes
      box(cx + 1, y + 9, cx + 2, y + 10, CC.grey)
    end
    box(cx + 1, y + 4, cx + cw - 1, y + 7, i < shot and CC.yellow or CC.grey_dk)
  end
end

-- loading: the film slides into the frame (~0.4 s)
local function anim_load(key, n)
  local y = H / 2 - 8
  for step = 0, 8 do
    local x = W - (step * (W - 40)) / 8
    box(0, y - 4, W - 1, y + 19, CC.black)
    canister(x - 18, y, key)
    strip(x, y + 2, W - 40, n, 0)
    sleep(40)
  end
end

local function frame_text(r)
  if not r then return "NO FILM" end
  return string.format("%s %d/%d", mf.film_name(r.film), #r.frames, r.length)
end

-- While shooting the counter is shown only briefly (3 s after start, after
-- each shot, with a notice) in the lower part of the frame above Canon's
-- bottom row, then erased: permanent text collided with Canon's and CHDK's
-- own icons (camera tests 0.1.0-0.1.4).
local OVL_Y = 0                                  -- set in main from the screen height
local overlay_until = 0
local function show_overlay(ms) overlay_until = get_tick_count() + (ms or 3000) end
local function overlay()
  local s = roll and string.format("%s %d/%d", mf.film_short(roll.film), #roll.frames, roll.length) or "NO FILM"
  if roll and roll.state == "SEALED" then s = s .. " done" end
  local x = (W - 8 * string.len(string.sub(s, 1, 22))) / 2
  if notice and get_tick_count() < notice_until then
    local ns = string.sub(notice, 1, COLS - 1)
    draw_string((W - 8 * string.len(ns)) / 2, OVL_Y - FH - 4, ns, C.hi, C.bg)
  end
  draw_string(x, OVL_Y, string.sub(s, 1, 22), roll and C.fg or C.warn, C.bg)
  if roll then
    local w = roll.length * 4                                  -- 48..144 px: frames left at a glance
    strip((W - w) / 2, OVL_Y + FH + 2, w, roll.length, #roll.frames)
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

local function screen(title, lines, items, sel, footer, icons)
  local rows_total = H / FH                     -- CHDK's bar is hidden while the menu is up
  local key_ = title .. "|" .. tostring(sel) .. "|" .. table.concat(items or {}, "/")
  for _, l in ipairs(lines or {}) do
    if type(l) == "table" and l.hero then key_ = key_ .. "|hero" .. l.hero.film .. #l.hero.frames
    else key_ = key_ .. "|" .. (type(l) == "table" and l[1] or l) end
  end
  -- in playback nothing redraws over the menu: repaint only on change (and
  -- every 2 s as a safety net, without clearing)
  if key_ == last_key and get_tick_count() - last_full < 2000 then return end
  if key_ ~= last_key then draw_clear() end
  last_key, last_full = key_, get_tick_count()
  local row = 0
  text(0, row, pad(" " .. title), C.hi)
  row = row + 1
  for _, l in ipairs(lines or {}) do
    if row >= rows_total - 1 then break end
    if type(l) == "table" and l.hero then
      -- the loaded film: canister, big counter, strip (two text rows)
      local r = l.hero
      text(0, row, pad(""), C.fg)
      text(0, row + 1, pad(""), C.fg)
      canister(8, row * FH + 8, r.film)
      draw_string(32, row * FH, string.format("%d/%d", #r.frames, r.length), C.hi, C.bg, 2)
      local sx = 32 + 16 * string.len(string.format("%d/%d", #r.frames, r.length)) + 12
      strip(sx, row * FH + 10, W - sx - 8, r.length, #r.frames)
      row = row + 2
    else
      local s, col = l, C.dim
      if type(l) == "table" then s, col = l[1], l[2] or C.dim end
      text(0, row, pad(" " .. s), col)
      row = row + 1
    end
  end
  if items then
    text(0, row, pad(""), C.fg)
    row = row + 1
    local rows = rows_total - row - 1
    local first = 1
    if sel > rows then first = sel - rows + 1 end
    for i = first, math.min(#items, first + rows - 1) do
      local label = icons and icons[i] and ("   " .. items[i]) or items[i]
      if i == sel then text(0, row, pad(" > " .. label), C.fg, C.sel)
      else text(0, row, pad("   " .. label), C.fg) end
      if icons and icons[i] then canister(3 * FW, row * FH, icons[i]) end
      row = row + 1
    end
    while row < rows_total - 1 do text(0, row, pad(""), C.fg); row = row + 1 end
  end
  text(0, rows_total - 1, pad(footer or " SET ok  MENU back  half: shoot  VIDEO: quit"), C.dim)
end

-- wait for one of KEYS; returns the key name, "shoot" if alt mode was left, or nil on timeout
local function key(ms)
  wait_click(ms or 150)
  for _, k in ipairs(KEYS) do
    if is_key(k) then return k end
  end
  if have("get_alt_mode") and not get_alt_mode() then return "shoot" end
  return nil
end

-- generic list chooser: returns index or nil (back) or "shoot"
local function choose(title, lines, items, sel, icons)
  sel = sel or 1
  while true do
    screen(title, lines, items, sel, nil, icons)
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
  local names, icons = {}, {}
  for _, f in ipairs(mf.cfg.films) do names[#names + 1] = f.name; icons[#icons + 1] = f.key end
  mf.log("film list: " .. #names .. " films")
  local fi = choose("Choose film", {}, names, 1, icons)
  if type(fi) ~= "number" then return fi end
  mf.log("film chosen: " .. mf.cfg.films[fi].key)
  local li = choose("Roll length: " .. mf.cfg.films[fi].name, {}, {"36 frames", "24 frames", "12 frames"}, 1)
  if type(li) ~= "number" then return li end
  local r, err = mf.new_roll(mf.cfg.films[fi].key, ({36, 24, 12})[li])
  if not r then say("ERROR: " .. tostring(err), 8000) return end
  roll = r
  anim_load(r.film, r.length)
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

local function title_line(on)
  if have("set_draw_title_line") then set_draw_title_line(on and 1 or 0) end
end

-- The menu is shown in PLAYBACK mode with CHDK's own OSD switched off. In
-- shooting mode Canon (shots left, battery) and CHDK (clock, battery %,
-- temperature, DNG counter) keep drawing into the same bitmap and CHDK
-- clears it now and then, so a Lua menu over the live view showed through
-- and flickered whatever the repaint rate (camera tests 0.1.0-0.1.4).
-- Playback is static: drawn once, nothing redraws over it.
local CONF_SHOW_OSD = 1                          -- CHDK conf id of "Show OSD" (core/conf.c)
local osd_saved = nil

local function is_rec() return not have("get_mode") or get_mode() end

local function set_rec(on)
  if not have("set_record") or is_rec() == on then return true end
  set_record(on and 1 or 0)
  local t = get_tick_count()
  while is_rec() ~= on and get_tick_count() - t < 5000 do sleep(100) end
  if is_rec() ~= on then mf.log("mode switch to " .. (on and "record" or "playback") .. " timed out") return false end
  sleep(on and 300 or 700)                       -- let the camera finish drawing its own screen first
  return true
end

local function chdk_osd(on)
  if not have("get_config_value") or not have("set_config_value") then return end
  if not on then
    if osd_saved == nil then osd_saved = get_config_value(CONF_SHOW_OSD) end
    set_config_value(CONF_SHOW_OSD, 0)
  elseif osd_saved ~= nil then
    set_config_value(CONF_SHOW_OSD, osd_saved)
    osd_saved = nil
  end
end

local function menu()
  chdk_osd(false)
  set_rec(false)
  draw_clear()
  title_line(false)
  last_key = nil
  local sel = 1
  while not quit do
    local status = {{"Film: " .. (roll and mf.film_name(roll.film) or "NO FILM"), roll and C.fg or C.warn}}
    if roll then status[#status + 1] = {hero = roll} end
    if have("get_raw") and not get_raw() then status[#status + 1] = {"RAW/DNG is OFF: enable it in CHDK RAW menu", C.warn} end
    if notice and get_tick_count() < notice_until then status[#status + 1] = {notice, C.hi} end
    local auto_on = have("get_autostart") and get_autostart() == 1
    local items = {"Shoot", roll and roll.state ~= "SEALED" and "Load new film (finish this one)" or "Load film",
                   "Finish roll now", "Rolls on card", "Start with camera: " .. (auto_on and "ON" or "OFF"),
                   "Diagnostics", "Quit M-Film"}
    local i = choose("M-Film " .. mf.VERSION, status, items, sel)
    if i == "shoot" or i == 1 or i == nil then break end
    sel = i
    mf.log("menu: " .. items[i])
    local r
    if i == 2 then r = load_film()
    elseif i == 3 then seal_now()
    elseif i == 4 then r = show_rolls()
    elseif i == 5 then
      if have("set_autostart") then
        set_autostart(auto_on and 0 or 1)
        mf.log("autostart " .. (auto_on and "off" or "on"))
      end
    elseif i == 6 then show_diag()
    elseif i == 7 then
      if confirm("Quit M-Film", {"Frames shot after quitting are NOT recorded.", "The roll stays loaded."}) then
        quit = true
      end
    end
    if r == "shoot" then break end
  end
  draw_clear()
  title_line(true)
  if not quit then set_rec(true) end
  chdk_osd(true)
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
  show_overlay(3000)
  local last_draw, pending_since, shown = 0, nil, false
  while not quit do
    if have("get_alt_mode") and get_alt_mode() then return end   -- Playback pressed: menu (before drawing)
    local dir = get_image_dir()
    local n = shot_count()
    if n ~= shots_seen then
      shots_seen = n
      pending_since = pending_since or get_tick_count()
    end
    local found = watcher.poll(dir)
    for _, f in ipairs(found) do on_new_dng(f) end
    if #found > 0 then pending_since = nil; show_overlay(3000) end
    if pending_since and get_tick_count() - pending_since > 10000 then
      pending_since = nil
      mf.log("shot without a new DNG within 10 s (RAW off?)")
      say("No DNG written: is RAW/DNG on in CHDK?", 8000)
    end
    if get_tick_count() < overlay_until then
      if get_tick_count() - last_draw > 400 then
        overlay()
        last_draw, shown = get_tick_count(), true
      end
    elseif shown then
      draw_clear()                                 -- give the screen back to Canon
      shown = false
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
  OVL_Y = H - 3 * FH - 16                        -- above Canon's bottom row
  overlay_until_ref = function(ms) show_overlay(ms) end
  -- the menu switches CHDK's OSD off while it is up; a power-off in the menu
  -- must not leave it off
  if have("get_config_value") and get_config_value(CONF_SHOW_OSD) == 0 then
    set_config_value(CONF_SHOW_OSD, 1)
    mf.log("CHDK OSD was off: switched back on")
  end
  roll = mf.active_roll()
  if roll and roll.state == "SEALED" then roll = nil end
  watcher = mf.watcher(get_image_dir())
  shots_seen = shot_count()
  if #problems > 0 then say("Setup problem: see Diagnostics", 15000) end
  if roll then
    mf.journal(roll, "RESUMED app start, " .. #roll.frames .. " frame(s)")
    say("Resumed " .. frame_text(roll), 5000)
  end
  -- start with the camera: CHDK runs this script at every power-on (the
  -- setting is CHDK's own, saved by set_autostart; toggle it in the menu)
  local auto = have("autostarted") and autostarted()
  if have("get_autostart") and have("set_autostart") and get_autostart() == 0 and not auto then
    set_autostart(1)
    mf.log("autostart enabled")
    say("M-Film now starts with the camera", 5000)
  end
  local skip_menu = auto and roll ~= nil            -- powered on with film loaded: straight to shooting
  while not quit do
    if not skip_menu then menu() end
    skip_menu = false
    if quit then break end
    shooting()
  end
  mf.log("---- quit")
end

-- no pcall around main: CHDK's sleep/wait_click yield the script coroutine,
-- and Lua 5.1 cannot yield across pcall. Errors end the script with CHDK's
-- own message; state on the card is always consistent (atomic writes).
main()
