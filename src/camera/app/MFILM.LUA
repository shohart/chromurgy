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
local notice, notice_until, notice_good = nil, 0, false
local selftest = {}
local quit = false
local boot_alive = function() end                -- crash-loop guard heartbeat (set in main's section)

local function have(name) return type(_G[name]) == "function" end

-- after drawing outside the menu painter (animations, captions): copy the
-- overlay buffer just drawn into the other one (M-Film CHDK build), so a
-- buffer flip by Canon cannot show a half-old picture
local function overlay_commit()
  if have("mf_overlay_mirror") then mf_overlay_mirror() end
end

local function shot_count()
  if type(hook_raw) == "table" and type(hook_raw.count) == "function" then return hook_raw.count() end
  if have("get_exp_count") then return get_exp_count() end
  return 0
end

local overlay_until_ref = nil
local function say(msg, ms, good)
  notice, notice_until, notice_good = msg, get_tick_count() + (ms or 4000), good
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
                      "get_gui_screen_width", "get_gui_screen_height", "get_raw", "get_vbatt", "sleep",
                     "get_prop", "click"}) do
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
  if have("get_prop") then add("Canon display mode " .. tostring(get_prop(105)) .. " (0 = info shown)") end
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
-- Graphics are drawn so that every pixel is set once: no background box
-- under a detail that stays. Redrawing a picture over itself then changes
-- nothing on screen (the strip's black fill under its cells made the whole
-- strip flash at every redraw, camera 0.5.1).
local function canister(x, y, key)
  local col = brand_colour(key)
  box(x + 6, y, x + 8, y + 1, CC.grey)           -- spool knob
  box(x + 1, y + 2, x + 11, y + 3, CC.grey_lt)   -- top cap
  box(x + 2, y + 4, x + 10, y + 5, col)          -- body above the label
  box(x + 2, y + 6, x + 2, y + 7, col)
  box(x + 3, y + 6, x + 9, y + 7, CC.white)      -- label stripe
  box(x + 10, y + 6, x + 10, y + 7, col)
  box(x + 2, y + 8, x + 10, y + 12, col)         -- body below the label
  box(x + 1, y + 13, x + 11, y + 14, CC.grey_lt) -- bottom cap
  box(x + 11, y + 6, x + 15, y + 11, CC.grey_dk) -- film leader
end

-- film strip: n frames across width w, the first `shot` exposed; 12 px high,
-- tiled without overlaps (see above)
local function strip(x, y, w, n, shot)
  if n < 1 then return end
  local cw = w / n
  if cw < 3 then cw = 3 end
  local xe = x + cw * n
  for _, r in ipairs({0, 3, 8, 11}) do box(x, y + r, xe, y + r, CC.black) end
  box(xe, y + 1, xe, y + 2, CC.black)
  box(xe, y + 4, xe, y + 7, CC.black)
  box(xe, y + 9, xe, y + 10, CC.black)
  for i = 0, n - 1 do
    local cx = x + i * cw
    for _, r in ipairs({1, 9}) do                 -- sprocket rows
      if cw >= 5 then
        box(cx, y + r, cx, y + r + 1, CC.black)
        box(cx + 1, y + r, cx + 2, y + r + 1, CC.grey)
        box(cx + 3, y + r, cx + cw - 1, y + r + 1, CC.black)
      else
        box(cx, y + r, cx + cw - 1, y + r + 1, CC.black)
      end
    end
    box(cx, y + 4, cx, y + 7, CC.black)           -- the frame
    box(cx + 1, y + 4, cx + cw - 1, y + 7, i < shot and CC.yellow or CC.grey_dk)
  end
end

-- loading: the film slides into the frame (~0.4 s). Each step draws the
-- canister and strip at their new place and blacks out only what they left.
local function anim_load(key, n)
  local y = H / 2 - 8
  local px = nil
  for step = 0, 8 do
    local x = W - (step * (W - 40)) / 8
    if not px then box(0, y - 4, W - 1, y + 19, CC.black) end
    strip(x, y + 2, W - 40, n, 0)
    canister(x - 18, y, key)
    if px then
      local d = px - x
      box(px - 18, y, px - 3, y + 1, CC.black)              -- old canister, rows the strip does not cover
      box(px - 18, y + 14, px - 3, y + 14, CC.black)
      box(x + W - 40 + 1, y + 2, px + W - 40, y + 13, CC.black)   -- where the strip ended
      if d > 0 then box(x - 2, y, x - 1, y + 14, CC.black) end   -- between canister and strip
    end
    px = x
    overlay_commit()
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

-- Menus are drawn row by row, and only the rows whose content changed are
-- redrawn: moving the cursor repaints two rows. The screen is never cleared
-- while a menu is up (0.1.7: the photo showed through on every key press);
-- every row is opaque and full width, so a new screen overwrites the old one.
--
-- The SX510 HS has two bitmap buffers and Canon flips between them; CHDK
-- draws into the active one only (DRAW_ON_ACTIVE_BITMAP_BUFFER_ONLY in its
-- platform_camera.h). A menu painted once is therefore only half there: after
-- a flip, rows drawn before it are missing and the live view shows through
-- (camera test 0.2.0). CHDK's own menu repaints when its guard pixel is gone.
-- The app does the same from Lua: it reads (peek, read only) which buffer is
-- active and keeps a separate row cache per buffer, and it samples a few
-- bitmap bytes it painted to notice a buffer Canon erased. Addresses are
-- CHDK's own stubs for sx510hs 101a; on any other build the menu is simply
-- repainted in full every 300 ms (same pixels: no visible change).
local ADDR_ACTIVE, ADDR_BUFFERS, BITMAP_W = 0x4138, 0x413c, 960
local SAMPLE_OFFS = {4 * BITMAP_W + 40, 8 * BITMAP_W + 200, 12 * BITMAP_W + 500}
local fb = nil                                   -- {base = {b0, b1}} when buffer tracking works
local caches = {[0] = {}, [1] = {}, [9] = {}}   -- per buffer: row -> signature (9: untracked)
local samples = {}                               -- per buffer: bytes read after painting
local drawn = caches[9]
local last_full = 0
local function invalidate() caches = {[0] = {}, [1] = {}, [9] = {}}; samples = {}; drawn = caches[9] end

local function fb_init()
  fb = nil
  if not have("peek") or not have("get_buildinfo") then return "no peek" end
  local bi = get_buildinfo()
  if bi.platform ~= "sx510hs" or bi.platsub ~= "101a" then return "untracked build " .. tostring(bi.platform) end
  local act, b0, b1 = peek(ADDR_ACTIVE), peek(ADDR_BUFFERS), peek(ADDR_BUFFERS + 4)
  if (act ~= 0 and act ~= 1) or not b0 or not b1 or b0 == 0 or b1 == 0 or b0 == b1 or b0 % 4 ~= 0 or b1 % 4 ~= 0 then
    return string.format("buffer check failed: active %s buffers %s %s", tostring(act), tostring(b0), tostring(b1))
  end
  fb = {base = {[0] = b0, [1] = b1}}
  return string.format("bitmap buffers %x %x, active %d", b0, b1, act)
end

local function active_buffer()
  if not fb then return 9 end
  local a = peek(ADDR_ACTIVE)
  if a ~= 0 and a ~= 1 then return 9 end
  return a
end

local function read_samples(b)
  local t = {}
  for i, o in ipairs(SAMPLE_OFFS) do t[i] = peek(fb.base[b] + o, 1) end
  return t
end

-- true if buffer b still holds what we painted into it
local function samples_ok(b)
  local want = samples[b]
  if not want then return false end
  local now = read_samples(b)
  for i = 1, #want do if now[i] ~= want[i] then return false end end
  return true
end

local function pad(s)
  s = string.sub(s or "", 1, COLS)
  return s .. string.rep(" ", COLS - string.len(s))
end

-- fixed-width fields done in Lua: string.format on the camera is Canon's
-- _vsprintf, whose support for "%-12s" / "%4d" is not proven (only %02d is)
local function lpad(s, n) s = string.sub(tostring(s), 1, n) return s .. string.rep(" ", n - string.len(s)) end
local function rpad(s, n) s = string.sub(tostring(s), 1, n) return string.rep(" ", n - string.len(s)) .. s end

-- draw one text row unless it is already on screen; returns true if drawn
local painted = false                            -- this pass changed the active buffer
local function row_text(row, s, fg, bg, sig, force)
  local k = (sig or "") .. "|" .. s .. "|" .. tostring(fg) .. "|" .. tostring(bg)
  if drawn[row] == k and not force then return false end
  text(0, row, s, fg, bg)
  drawn[row] = k
  painted = true
  return true
end

-- M-Film CHDK build: copy the freshly painted overlay buffer into the other
-- one, so a flip by Canon shows the same menu (0.4.2 still flickered now and
-- then: the 60 ms until the flipped-to buffer was repainted were visible)
local function mirror(b)
  if b == 9 or not have("mf_overlay_mirror") then return end
  if not mf_overlay_mirror() then return end
  local o, c = 1 - b, {}
  for k, v in pairs(caches[b]) do c[k] = v end
  caches[o] = c
  samples[o] = read_samples(o)
end

local paint                                      -- forward: one pass into the active buffer

local function screen(...)
  -- paint into the active buffer; if Canon flipped buffers during the pass,
  -- the rows may have gone to the other one: forget both and paint again
  for _ = 1, 3 do
    local b = active_buffer()
    if b ~= 9 and not samples_ok(b) then caches[b] = {} end
    drawn = caches[b]
    -- untracked: full repaint every 300 ms; tracked: every 1 s as well (same
    -- pixels, no flicker), in case an erase slipped past the sampled bytes
    local full = get_tick_count() - last_full >= (b == 9 and 300 or 1000)
    if full then last_full = get_tick_count() end
    painted = false
    paint(full, ...)
    if b == 9 then return end
    if active_buffer() == b then
      samples[b] = read_samples(b)
      if painted then mirror(b) end
      return
    end
    caches[0], caches[1], samples = {}, {}, {}
  end
end

-- graphics over l.rows text rows. l.key names what the rows hold, l.sig
-- what changes. l.gfx(y, full): full when the rows do not hold this key yet
-- (new screen, erased buffer): they are cleared once and drawn whole;
-- otherwise only what changed is drawn, never a background under something
-- that stays (the whole contact strip flickered with the pulsing frame,
-- camera 0.5.1). Nothing on the safety refresh.
local function paint_gfx_line(row, l)
  local n = l.rows or 1
  local kp = "gfx:" .. (l.key or "") .. "#"
  local k = kp .. (l.sig or "")
  local full, changed = false, false
  for j = 0, n - 1 do
    local d = drawn[row + j] or ""
    if string.sub(d, 1, string.len(kp)) ~= kp then full = true end
    if d ~= k then changed = true end
  end
  if not (full or changed) then return end
  if full then for j = 0, n - 1 do text(0, row + j, pad(""), C.fg, C.bg) end end
  for j = 0, n - 1 do drawn[row + j] = k end
  l.gfx(row * FH, full)
  painted = true
end

paint = function(refresh, title, lines, items, sel, footer, icons)
  local rows_total = H / FH                     -- CHDK's bar is hidden while the menu is up
  local row = 0
  row_text(row, pad(" " .. title), C.hi, C.bg, nil, refresh)
  row = row + 1
  for _, l in ipairs(lines or {}) do
    if row >= rows_total - 1 then break end
    if type(l) == "table" and l.gfx then
      paint_gfx_line(row, l)
      row = row + (l.rows or 1)
    elseif type(l) == "table" and l.hero then
      -- the loaded film: canister, big counter, strip (two text rows), as a
      -- graphics line: redrawn when the count changes, never on the refresh
      local r = l.hero
      local cs = #r.frames .. "/" .. r.length
      paint_gfx_line(row, {rows = 2, key = "hero|" .. r.film .. "|" .. string.len(cs), sig = cs, gfx = function(y, full)
        if full then canister(8, y + 8, r.film) end
        draw_string(32, y, cs, C.hi, C.bg, 2)
        local sx = 32 + 16 * string.len(cs) + 12
        strip(sx, y + 10, W - sx - 8, r.length, #r.frames)
      end})
      row = row + 2
    else
      local s, col = l, C.dim
      if type(l) == "table" then s, col = l[1], l[2] or C.dim end
      row_text(row, pad(" " .. s), col, C.bg, nil, refresh)
      row = row + 1
    end
  end
  if items then
    row_text(row, pad(""), C.fg, C.bg, nil, refresh)
    row = row + 1
    local rows = rows_total - row - 1
    local first = 1
    if sel > rows then first = sel - rows + 1 end
    for i = first, math.min(#items, first + rows - 1) do
      local icon = icons and icons[i]
      local label = icon and ("   " .. items[i]) or items[i]
      local sig = icon and ("icon:" .. icon) or nil
      local s, bg = pad("   " .. label), C.bg
      if i == sel then s, bg = pad(" > " .. label), C.sel end
      -- rows with a canister icon are not refreshed: text over the icon and
      -- the icon again would flash it every second
      if row_text(row, s, C.fg, bg, sig, refresh and not icon) and icon then
        canister(3 * FW, row * FH, icon)
      end
      row = row + 1
    end
  end
  while row < rows_total - 1 do row_text(row, pad(""), C.fg, C.bg, nil, refresh); row = row + 1 end
  row_text(rows_total - 1, pad(footer or " SET ok  MENU back  half: shoot  VIDEO: quit"), C.dim, C.bg, nil, refresh)
end

-- wait for one of KEYS; returns the key name, "shoot" if alt mode was left, or nil on timeout
local function key(ms)
  boot_alive()
  wait_click(ms or 60)
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
  invalidate()
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

local function title_line(on)
  if have("set_draw_title_line") then set_draw_title_line(on and 1 or 0) end
end

-- Canon's own information display is switched off (DISP) for as long as the
-- app runs: its icons (shots left, battery, mode, focus) are drawn into the
-- same bitmap as CHDK's OSD and the app's menu, Canon redraws them whenever it
-- likes and CHDK repaints over them -- the source of the overlaps and flicker
-- seen in camera tests 0.1.0-0.1.7. The menu is drawn in shooting mode over the
-- live view (every row opaque and full width), with CHDK's OSD off while it is
-- up; while shooting only CHDK's OSD and the app's transient counter are shown.
-- Before 0.2.0 the menu went to playback mode instead, which still showed
-- the photo under it and Canon's playback icons.
-- CHDK config ids (release-1_6 r6355): CONF_OSD 2000 + osd_conf_info id. Ids
-- below 1000 are OLD ids remapped by conf_migrate: never use those.
local CONF = {show_osd = 2001, batt_perc_show = 2102, batt_icon_show = 2104, show_clock = 2080, show_temp = 2220,
              splash_show = 2120,
              show_remaining_raw = 2200, show_raw_state = 2201, space_mb_show = 2182, space_bar_show = 2183}
local CONF_SHOW_OSD = CONF.show_osd
local osd_saved = nil

local function is_rec() return not have("get_mode") or get_mode() end

-- Battery. The lens must not be driven on a nearly empty battery: on
-- 2026-11-05, after 9 min of developing (3.75 -> 3.35 V), every power-on
-- ended with the app extending the lens, the voltage collapsing and the
-- camera switching off -- a power-on loop with no ROMLOG.
local BATT_LOW_MV, BATT_DEV_STOP_MV, BATT_DEV_START_MV = 3500, 3450, 3600
local function vbatt() return have("get_vbatt") and get_vbatt() or 4000 end

local function set_rec(on)
  if not have("set_record") or is_rec() == on then return true end
  if on and vbatt() < BATT_LOW_MV then
    mf.log("not extending the lens: battery " .. vbatt() .. " mV")
    return false
  end
  set_record(on and 1 or 0)
  local t = get_tick_count()
  while is_rec() ~= on and get_tick_count() - t < 5000 do sleep(100) end
  if is_rec() ~= on then mf.log("mode switch to " .. (on and "record" or "playback") .. " timed out") return false end
  sleep(on and 300 or 700)                       -- let the camera finish drawing its own screen first
  return true
end

-- Canon display mode: propcase 105 (propset 6, SX510 HS); 0 = information
-- shown. DISP cycles the modes; the app presses it until the mode is not 0.
local PROP_DISP = 105
local disp_saved = nil

local function disp_mode() return get_prop(PROP_DISP) end

local function canon_info(show)
  if not have("get_prop") or not have("click") or not is_rec() then return end
  local v = disp_mode()
  if show then
    if disp_saved == nil or v == disp_saved then return end
    for _ = 1, 4 do
      click("display"); sleep(250)
      if disp_mode() == disp_saved then break end
    end
    mf.log("Canon display restored: " .. tostring(disp_mode()))
    disp_saved = nil
    return
  end
  if v ~= 0 then return end                      -- already without information
  if disp_saved == nil then disp_saved = v end
  for _ = 1, 4 do
    click("display"); sleep(250)
    v = disp_mode()
    if v ~= 0 then break end
  end
  mf.log("Canon display mode " .. tostring(v) .. (v ~= 0 and " (info off)" or " (could not switch info off)"))
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

-- ------------------------------------------------------------ viewer
-- Developed frames are shown full screen in playback mode: the app copies a
-- prepared frame (MFV, from the server) into the playback image buffer and
-- makes the overlay transparent, so Canon's own gallery is never seen. Needs
-- the M-Film CHDK build (mf_show, mf_overlay_clear in its Lua module).
local function caption_row(text_, painted)
  -- one opaque text row at the bottom. Redrawn every 250 ms even when
  -- unchanged (same pixels): Canon may erase the overlay at any time and the
  -- viewer has no other way to notice (fuzz: a caption gone for a second)
  local k = text_ or ""
  local off = (H - FH / 2) * BITMAP_W + 40         -- a byte inside the caption row
  local intact = true
  intact = get_tick_count() - (painted.t or 0) < 250  -- repaint (same pixels) at least every 250 ms
  if intact and fb and text_ then
    local b = active_buffer()
    intact = b ~= 9 and painted.sample == peek(fb.base[b] + off, 1)
  end
  if painted.k == k and intact then return end
  if text_ then text(0, H / FH - 1, pad(" " .. text_), C.fg, C.bg) end
  painted.k, painted.t = k, get_tick_count()
  overlay_commit()
  if fb and text_ then
    local b = active_buffer()
    if b ~= 9 then painted.sample = peek(fb.base[b] + off, 1) end
  end
end

local function viewer(title, frames, start)
  if not have("mf_show") or not have("mf_overlay_clear") then
    say("Viewer needs the M-Film CHDK build (DISKBOOT.BIN)", 8000)
    mf.log("viewer: mf_show missing (stock CHDK)")
    return
  end
  if not set_rec(false) then say("Could not switch to playback", 6000) return end
  local i, show_cap, quit_to = start or 1, true, nil
  local shown, err, painted = 0, nil, {}
  while true do
    if shown ~= i then
      local ok, e = mf_show(frames[i])
      err = (not ok) and tostring(e) or nil
      if err then mf.log("viewer: " .. frames[i] .. ": " .. err) end
      mf_overlay_clear()
      shown = i
      painted = {}
    end
    local cap = show_cap and string.format("%s  %d/%d", title, i, #frames) or nil
    if err then cap = "ERROR " .. err end
    caption_row(cap, painted)
    local k = key()
    if k == "right" or k == "down" then i = (i < #frames) and i + 1 or 1
    elseif k == "left" or k == "up" then i = (i > 1) and i - 1 or #frames
    elseif k == "set" then show_cap = not show_cap; mf_overlay_clear(); painted = {}
    elseif k == "menu" then break
    elseif k == "shoot_half" or k == "shoot" then quit_to = "shoot" break
    end
  end
  mf_overlay_clear()
  invalidate()                                   -- back to the menu, still in playback (lens in)
  return quit_to
end

-- ------------------------------------------------------------ developing on the camera
local DEV_ERR = {[-20] = "card read/write error", [-21] = "not a CHDK DNG", [-22] = "out of memory",
                 [-23] = "film data missing (MFDEV.BIN)", [-24] = "no lens data", [-25] = "stopped"}

local function bar(permille, width)
  local n = permille * width / 1000              -- CHDK Lua numbers are integers: no math.floor
  if n > width then n = width end
  if n < 0 then n = 0 end
  return "[" .. string.rep("#", n) .. string.rep(".", width - n) .. "]"
end

-- the developing screen ---------------------------------------------------
-- Layout (16 px text rows): 0 title; 1-3 tank + film; 5-6 contact strip;
-- 8-9 progress bars sharing one x range; 11 time; 14 footer.
local BAR_X, BAR_W, PCT_X = 120, 176, 304

-- a developing tank: lid, body, a window with the reel turning (4 phases)
-- and bubbles rising; 30 x 40 px at x, y. tank_full draws it all; tank_step
-- moves the reel and bubbles from one phase to the next, touching only the
-- pixels that change.
local function tank_parts(x, y, phase)
  local cx, cy, out = x + 14, y + 24, {}
  local arm = {{0, -9}, {6, -6}, {9, 0}, {6, 6}}     -- one spoke per phase, and its opposite
  for k = 0, 1 do
    local a = arm[(phase + 2 * k) % 4 + 1]
    for t = 3, 9, 2 do
      local px, py = cx + a[1] * t / 9, cy + a[2] * t / 9
      out[#out + 1] = {px - 1, py - 1, CC.yellow}
      out[#out + 1] = {2 * cx - px - 1, 2 * cy - py - 1, CC.yellow}
    end
  end
  for b = 0, 2 do                                     -- bubbles
    out[#out + 1] = {x + 7 + b * 6, y + 34 - ((phase * 3 + b * 7) % 20), CC.blue_lt}
  end
  return out                                          -- 2x2 dots: {x, y, colour}
end

local function tank_full(x, y, phase)
  box(x + 12, y, x + 17, y + 3, CC.grey_lt)        -- agitation knob
  box(x, y + 4, x + 29, y + 8, CC.grey_lt)          -- lid
  box(x + 2, y + 9, x + 27, y + 39, CC.grey_dk)     -- body
  box(x + 5, y + 12, x + 24, y + 36, CC.black)      -- window
  box(x + 13, y + 23, x + 15, y + 25, CC.grey_lt)   -- hub
  for _, d in ipairs(tank_parts(x, y, phase)) do box(d[1], d[2], d[1] + 1, d[2] + 1, d[3]) end
end

local function tank_step(x, y, from, to)
  local new, keep = tank_parts(x, y, to), {}
  for _, d in ipairs(new) do keep[d[1] .. "," .. d[2]] = d[3] end
  for _, d in ipairs(tank_parts(x, y, from)) do       -- old dots that are not new dots: back to black
    if not keep[d[1] .. "," .. d[2]] then box(d[1], d[2], d[1] + 1, d[2] + 1, CC.black) end
  end
  local hub = {}
  for _, d in ipairs(tank_parts(x, y, from)) do hub[d[1] .. "," .. d[2]] = d[3] end
  for _, d in ipairs(new) do
    if hub[d[1] .. "," .. d[2]] ~= d[3] then box(d[1], d[2], d[1] + 1, d[2] + 1, d[3]) end
  end
end

-- the roll as a contact strip: one cell per frame, done in the film's colour,
-- the current one pulsing, the rest dark; sprocket holes above and below.
-- strip_full draws it all; strip_cells redraws only cells whose state changed
-- (cells[i] remembers what each cell shows).
local function strip_geom(n)
  local x0, x1 = 8, W - 9
  local cw = (x1 - x0 - 4) / n
  if cw > 26 then cw = 26 end
  return x0, x1, cw
end

local function cell_state(i, film, shot, done, current, phase)
  if i > shot then return "unexposed" end
  if i <= done then return "done" end
  if i == current then return (phase % 2 == 0) and "pulse_on" or "pulse_off" end
  return "waiting"
end

local function draw_cell(y, film, n, i, state)
  local x0, _, cw = strip_geom(n)
  local cx = x0 + 3 + (i - 1) * cw
  if state == "unexposed" then                        -- never exposed: an outline only
    box(cx, y + 7, cx + cw - 3, y + 7, CC.grey_dk)
    box(cx, y + 20, cx + cw - 3, y + 20, CC.grey_dk)
    box(cx, y + 8, cx, y + 19, CC.grey_dk)
    box(cx + cw - 3, y + 8, cx + cw - 3, y + 19, CC.grey_dk)
  elseif state == "done" then
    box(cx, y + 7, cx + cw - 3, y + 8, brand_colour(film))
    if cw >= 8 then
      box(cx, y + 9, cx + 1, y + 13, brand_colour(film))
      box(cx + 2, y + 9, cx + cw - 5, y + 13, CC.white)              -- a frame's sky
      box(cx + cw - 4, y + 9, cx + cw - 3, y + 13, brand_colour(film))
    else
      box(cx, y + 9, cx + cw - 3, y + 13, brand_colour(film))
    end
    box(cx, y + 14, cx + cw - 3, y + 20, brand_colour(film))
  else
    local c = state == "pulse_on" and CC.yellow or (state == "pulse_off" and CC.grey or CC.grey_dk)
    box(cx, y + 7, cx + cw - 3, y + 20, c)
  end
end

local function strip_full(y, film, n, shot, done, current, phase, cells)
  local x0, x1 = strip_geom(n)
  box(x0, y, x1, y + 27, CC.black)
  for hx = x0 + 3, x1 - 4, 8 do
    box(hx, y + 2, hx + 3, y + 4, CC.grey_dk)
    box(hx, y + 23, hx + 3, y + 25, CC.grey_dk)
  end
  for i = 1, n do
    cells[i] = cell_state(i, film, shot, done, current, phase)
    draw_cell(y, film, n, i, cells[i])
  end
end

local function strip_cells(y, film, n, shot, done, current, phase, cells)
  for i = 1, n do
    local st = cell_state(i, film, shot, done, current, phase)
    if cells[i] ~= st then
      draw_cell(y, film, n, i, st)
      cells[i] = st
    end
  end
end

local function bar_row(y, label, permille)
  if permille < 0 then permille = 0 end
  if permille > 1000 then permille = 1000 end
  draw_string(FW, y, lpad(label, 13), C.fg, C.bg)
  local fill = BAR_W * permille / 1000
  if fill > 0 then box(BAR_X, y + 4, BAR_X + fill - 1, y + 11, CC.yellow) end
  if fill < BAR_W then box(BAR_X + fill, y + 4, BAR_X + BAR_W - 1, y + 11, CC.grey_dk) end
  draw_string(PCT_X, y, rpad(permille / 10, 4) .. "%", C.hi, C.bg)
end

local STAGES = {{600, "scanning the negative"}, {700, "halation"}, {1001, "printing"}}

local devui = {}                                   -- what the developing screen shows now

local function develop_lines(r, i, n, pm, done, failed, eta)
  local phase = get_tick_count() / 500 % 4
  local stage = ""
  for _, st in ipairs(STAGES) do if pm < st[1] then stage = st[2] break end end
  local roll_pm = ((i - 1) * 1000 + pm) / n
  local len = r.length or n
  return {
    {rows = 3, key = "tank|" .. r.film, sig = phase .. "|" .. stage, gfx = function(y, full)
      if full then
        tank_full(12, y + 4, phase)
        draw_string(56, y + 2, string.sub(mf.film_name(r.film), 1, 36), C.hi, C.bg)
        draw_string(56, y + 17, n .. " frames, shot " .. string.sub(r.created_at or "", 1, 10), C.dim, C.bg)
      elseif devui.phase ~= phase then
        tank_step(12, y + 4, devui.phase or 0, phase)
      end
      if full or devui.stage ~= stage then draw_string(56, y + 32, lpad(stage, 30), C.fg, C.bg) end
      devui.phase, devui.stage = phase, stage
    end},
    "",
    {rows = 2, key = "strip|" .. r.film .. "|" .. len .. "|" .. n, sig = done .. "|" .. i .. "|" .. phase % 2,
     gfx = function(y, full)
      devui.cells = (full or not devui.cells) and {} or devui.cells
      if full then strip_full(y + 2, r.film, len, n, done, i, phase, devui.cells)
      else strip_cells(y + 2, r.film, len, n, done, i, phase, devui.cells) end
    end},
    "",
    {rows = 1, key = "barf", sig = i .. "|" .. pm / 5, gfx = function(y)
      bar_row(y, "Frame " .. i .. "/" .. n, pm)
    end},
    {rows = 1, key = "barr", sig = tostring(roll_pm / 5), gfx = function(y) bar_row(y, "Roll", roll_pm) end},
    "",
    eta,
    failed > 0 and {failed .. " frame(s) failed", C.warn} or "",
  }
end

-- develop every frame of roll r; returns the number developed, or nil if stopped
local function develop_roll(r)
  if not have("mf_dev_start") or not have("mf_dev_status") or not have("mf_dev_cancel") then
    say("Developing needs the M-Film CHDK build (DISKBOOT.BIN)", 8000)
    return nil
  end
  local camf, devf = mf.DEV_ROOT .. "/MFCAM.BIN", mf.DEV_ROOT .. "/MFDEV.BIN"
  if not mf.exists(camf) or not mf.exists(devf) then
    say("Missing CHDK/MFDEV/MFCAM.BIN or MFDEV.BIN on the card", 8000)
    return nil
  end
  mf.mkdirs(mf.DEV_ROOT .. "/" .. mf.cam_dir(r))
  mf.mkdirs(mf.VIEW_ROOT .. "/" .. mf.cam_dir(r))
  local function heap()
    if not have("get_meminfo") then return "" end
    local m = get_meminfo()
    return m and string.format(" (heap free %s, largest block %s)", tostring(m.free_size),
                               tostring(m.free_block_max_size)) or ""
  end
  -- the developer needs ~420 KB in blocks of <= 92 KB plus one 216 KB block
  -- (the film table) and the 0.7 KB camera constants
  if have("get_meminfo") then
    local m = get_meminfo()
    if m and m.free_block_max_size and (m.free_block_max_size < 240000 or (m.free_size or 0) < 700000) then
      mf.log("develop: not enough memory" .. heap())
      say("Not enough free memory: restart the camera, then Develop", 10000)
      return nil
    end
  end
  if vbatt() < BATT_DEV_START_MV then
    say("Battery " .. vbatt() .. " mV: charge it before developing", 10000)
    return nil
  end
  devui = {}
  mf.journal(r, "DEVELOP on camera started, " .. #r.frames .. " frame(s)")
  mf.log("develop: start" .. heap())
  local last_err = nil
  mf.log("develop " .. r.roll_id .. ": " .. #r.frames .. " frames, film " .. r.film)
  local title = "Developing " .. (mf.film_short(r.film) or r.film)
  local done, failed, stopped, t_all = 0, 0, false, get_tick_count()
  local oom_run = 0
  for i, fr in ipairs(r.frames) do
    local jpg, mfv = mf.cam_paths(r, i)
    local hi, lo = mf.cam_seed(r, i)
    if mf.view_complete(mfv) then                 -- developed before (resumed): keep it
      done = done + 1
    else
      if vbatt() < BATT_DEV_STOP_MV then
        mf.log("develop: battery " .. vbatt() .. " mV, stopping before frame " .. i)
        say("Battery low: developing stopped, frames so far kept", 10000)
        stopped = true
        break
      end
      local tries = 0
      repeat
        tries = tries + 1
        collectgarbage("collect")                 -- Lua garbage holds heap the developer needs
        local st, pm, rc, ms, timing = "error", 0, 0, 0, nil
        -- the viewer needs only the MFV; a JPEG (800x600) costs ~2.5 s a frame and
        -- nothing uses it yet (the server develops full size): camera_jpeg=1 in MFILM.CFG
        local want_jpg = mf.cfg.camera_jpeg == "1" and jpg or nil
        local ok, err = mf_dev_start(camf, devf, r.film, fr.path, want_jpg, mfv, mf.DEV_ROOT .. "/WORK.TMP", hi, lo)
        if not ok then
          mf.log("develop frame " .. i .. ": " .. tostring(err))
          rc = -20
        else
          local lines, lines_t = nil, -1000
          while true do
            st, pm, rc, ms, timing = mf_dev_status()
            if st ~= "running" then break end
            -- the content (progress, animation) changes at 2 Hz: building and
            -- drawing it takes CPU from the developer; the screen itself is
            -- checked every 100 ms, so an erase by Canon is repaired at once
            if get_tick_count() - lines_t >= 500 then
              lines_t = get_tick_count()
              local elapsed = (lines_t - t_all) / 1000
              local eta = string.format("elapsed %d:%02d", elapsed / 60, elapsed % 60)
              if done > 0 then
                local per = (lines_t - t_all) / (done + pm / 1000)
                local left = (per * (#r.frames - done) - per * pm / 1000) / 1000
                if left < 0 then left = 0 end
                eta = eta .. string.format("      about %d:%02d left", left / 60, left % 60)
              end
              lines = develop_lines(r, i, #r.frames, pm, done, failed, eta)
            end
            screen("Developing", lines, nil, 1, " MENU: stop     developed frames are kept")
            local k = key(100)
            if k == "menu" and not stopped then
              stopped = true
              mf_dev_cancel()
            end
          end
        end
        local again = false
        if st == "done" then
          done = done + 1
          mf.journal(r, string.format("DEVELOPED frame %d on camera in %d ms", i, ms))
          mf.log(string.format("develop frame %d: %d ms%s", i, ms, heap()))
          if timing and timing ~= "" then mf.log("develop frame " .. i .. " timing ms: " .. timing) end
        else
          mf.log(string.format("develop frame %d: rc %d (%s)%s", i, rc, DEV_ERR[rc] or "error", heap()))
          if rc == -22 and tries == 1 and not stopped then
            again = true                          -- out of memory: free Lua's garbage, wait, once more
            local t = get_tick_count()
            while get_tick_count() - t < 1000 do
              screen("Developing", develop_lines(r, i, #r.frames, 0, done, failed, "waiting for memory"), nil, 1,
                     " MENU: stop     developed frames are kept")
              if key(200) == "menu" then stopped = true end
            end
            if stopped then again = false end
          elseif rc ~= -25 then
            failed = failed + 1
            last_err = DEV_ERR[rc] or ("error " .. rc)
            oom_run = rc == -22 and oom_run + 1 or 0
          end
        end
      until not again
      if last_err == DEV_ERR[-23] then say("Film " .. r.film .. " is not in MFDEV.BIN", 8000) break end
      if oom_run >= 2 then                        -- memory stays short: no point going through the roll
        say("Not enough memory: restart the camera, then Develop again", 12000)
        stopped = true
      end
    end
    if stopped then break end
  end
  if done > 0 then mf.cam_index_put(r, #r.frames) end   -- the viewer shows the frames that are there
  if done == #r.frames then
    mf.journal(r, string.format("DEVELOP on camera finished: %d frames in %d s", done,
                                (get_tick_count() - t_all) / 1000))
    say(string.format("Developed %d frames", done), 6000, true)
    return done
  end
  mf.journal(r, string.format("DEVELOP on camera incomplete: %d of %d, %d failed%s", done, #r.frames, failed,
                              stopped and ", stopped" or ""))
  if not (notice and (string.find(notice, "Battery", 1, true) or string.find(notice, "memory", 1, true))
          and get_tick_count() < notice_until) then
    say(stopped and "Developing stopped: Develop again to go on" or string.format("Developed %d of %d: %s", done,
        #r.frames, last_err or "see APP.LOG"), 10000)
  end
  return done > 0 and done or nil
end

local function roll_card(r, v)
  -- r: roll on this card (or nil), v: its developed set from the server (or nil)
  local film = r and r.film or v.film
  local lines = {{mf.film_name(film), C.hi}}
  lines[#lines + 1] = "shot " .. (r and string.sub(r.created_at or "", 1, 10) or v.day)
  if r then
    lines[#lines + 1] = string.format("%d of %d frames, %s", #r.frames, r.length,
                                      r.state == "SEALED" and "finished" or "in the camera")
  end
  -- frames actually there (a develop may have been stopped, or a frame failed)
  local have_frames = {}
  if v then
    for k = 1, v.frames do
      local p = mf.view_frame(v, k)
      if mf.view_complete(p) then have_frames[#have_frames + 1] = p end
    end
  end
  local partial = v and #have_frames < v.frames
  if v and not partial then
    lines[#lines + 1] = string.format("DEVELOPED: %d frames (%s)", v.frames, v.origin or "server")
  elseif v then
    lines[#lines + 1] = {string.format("DEVELOPED: %d of %d frames (%s)", #have_frames, v.frames,
                                       v.origin or "server"), C.warn}
  else
    lines[#lines + 1] = "not developed yet"
  end
  local items, acts = {}, {}
  if #have_frames > 0 then items[#items + 1] = "View developed frames"; acts[#acts + 1] = "view" end
  if r and (not v or (partial and v.origin == "camera")) then
    items[#items + 1] = v and "Develop the rest" or "Develop"; acts[#acts + 1] = "develop"
  end
  items[#items + 1] = "Delete roll"; acts[#acts + 1] = "delete"
  items[#items + 1] = "Back"; acts[#acts + 1] = "back"
  while true do
    local shown_lines = {}
    for _, l in ipairs(lines) do shown_lines[#shown_lines + 1] = l end
    if notice and get_tick_count() < notice_until then
      shown_lines[#shown_lines + 1] = {notice, notice_good and C.ok or C.warn}
    end
    local i = choose("Roll " .. string.sub((r and r.roll_id) or v.roll_id, 1, 8), shown_lines, items, 1)
    if i == "shoot" then return "shoot" end
    if i == nil or acts[i] == "back" then return end
    if acts[i] == "delete" then
      local on_server = v and v.origin == "server"
      local what = {mf.film_name(film) .. ", " .. ((r and #r.frames) or (v and v.frames) or 0) .. " frames",
                    "Deletes its RAW files and developed frames."}
      if not on_server then what[#what + 1] = {"NOT ON THE SERVER: the shots will be lost!", C.warn} end
      if confirm("Delete roll", what)
         and (on_server or confirm("Really delete?", {"The RAW files are not on the server.",
                                                       {"This cannot be undone.", C.warn}})) then
        if r and roll and roll.roll_id == r.roll_id then roll = nil end
        local dngs, frames = mf.delete_roll(r, v)
        say(string.format("Roll deleted: %d RAW, %d developed", dngs, frames), 6000, true)
        return "deleted"
      end
    elseif acts[i] == "view" then
      if viewer(mf.film_short(film) .. " " .. (v.day or ""), have_frames) == "shoot" then return "shoot" end
    elseif acts[i] == "develop" then
      if not r then
        say("The roll is not on this card", 6000)
      elseif #r.frames == 0 then
        say("The roll has no frames", 6000)
      elseif r.state ~= "SEALED" and not confirm("Develop", {"This roll is still in the camera.",
                                                               "Finish it and develop it now?"}) then
        -- back to the card
      else
        if r.state ~= "SEALED" then
          mf.seal(r, "finished to develop on camera")
          if roll and roll.roll_id == r.roll_id then roll = nil end
        end
        develop_roll(r)
        return roll_card(r, mf.view_index()[r.roll_id])
      end
    end
  end
end

local function show_rolls()
  local sel = 1
  while true do                                   -- rebuilt after a roll is deleted
    local rolls, dev = mf.list_rolls(), mf.view_index()
    local seen, entries = {}, {}
    for _, r in ipairs(rolls) do
      entries[#entries + 1] = {r = r, v = dev[r.roll_id]}
      seen[r.roll_id] = true
    end
    for id, v in pairs(dev) do                    -- developed but no longer on this card
      if not seen[id] then entries[#entries + 1] = {v = v} end
    end
    local items, icons = {}, {}
    for _, e in ipairs(entries) do
      local film = e.r and e.r.film or e.v.film
      local day = e.r and string.sub(e.r.created_at or "", 6, 10) or string.sub(e.v.day or "", 6, 10)
      local n = e.r and string.format("%d/%d", #e.r.frames, e.r.length) or tostring(e.v.frames)
      local st = e.v and "DEV" or (e.r.state == "SEALED" and "done" or "in cam")
      items[#items + 1] = day .. " " .. lpad(mf.film_short(film) or film, 12) .. " " .. rpad(n, 5) .. " " .. st
      icons[#icons + 1] = film
    end
    local lines = {}
    if notice and get_tick_count() < notice_until then
      lines[#lines + 1] = {notice, notice_good and C.ok or C.warn}
    end
    if #items == 0 then
      lines[#lines + 1] = "No rolls yet."
      return choose("Rolls on this card", lines, {"Back"}, 1)
    end
    if sel > #items then sel = #items end
    local i = choose("Rolls (" .. #entries .. ")", lines, items, sel, icons)
    if type(i) ~= "number" then return i end
    sel = i
    if roll_card(entries[i].r, entries[i].v) == "shoot" then return "shoot" end
  end
end

local function screen_test()
  local p = mf.VIEW_ROOT .. "/TEST.MFV"
  if have("mf_viewport") then
    local addr, w, h, bw, ys, off, play = mf_viewport()
    mf.log(string.format("viewport (rec): %x %dx%d bw %d ys %d off %d play %s", addr or 0, w or 0, h or 0, bw or 0,
                         ys or 0, off or 0, tostring(play)))
  end
  return viewer("Screen test", {p})
end

local function show_diag()
  invalidate()
  local lines = {}
  for _, s in ipairs(selftest) do lines[#lines + 1] = s end
  lines[#lines + 1] = "device " .. mf.device.device_id
  lines[#lines + 1] = "log: CHDK/MFILM/LOGS/APP.LOG"
  local k
  repeat
    screen("Diagnostics", lines, nil, 1, "SET: screen test   other keys: back")
    k = key()
  until k
  if k == "set" then return screen_test() end
end

local function menu()
  chdk_osd(false)
  -- the menu stays in whatever mode the camera is in: it covers the whole
  -- screen, so playback works as well, and the lens moves only to shoot
  canon_info(false)
  draw_clear()
  title_line(false)
  invalidate()
  local sel = 1
  while not quit do
    local status = {{"Film: " .. (roll and mf.film_name(roll.film) or "NO FILM"), roll and C.fg or C.warn}}
    if roll then status[#status + 1] = {hero = roll} end
    if have("get_raw") and not get_raw() then status[#status + 1] = {"RAW/DNG is OFF: enable it in CHDK RAW menu", C.warn} end
    if vbatt() < BATT_LOW_MV then status[#status + 1] = {"Battery low (" .. vbatt() .. " mV): charge it", C.warn} end
    if notice and get_tick_count() < notice_until then status[#status + 1] = {notice, C.hi} end
    local auto_on = have("get_autostart") and get_autostart() == 1
    local items = {"Shoot", roll and roll.state ~= "SEALED" and "Load new film (finish this one)" or "Load film",
                   "Finish roll now", "Rolls on card", "Start with camera: " .. (auto_on and "ON" or "OFF"),
                   "Diagnostics", "Quit M-Film"}
    local i = choose("M-Film " .. mf.VERSION, status, items, sel)
    if i == "shoot" or i == 1 or i == nil then
      -- to shoot the lens must be out; on a low battery stay in the menu
      if set_rec(true) then break end
      say(vbatt() < BATT_LOW_MV and "Battery low: the lens stays in" or "Could not switch to shooting", 6000)
      i = nil
    end
    local r
    if i then
      sel = i
      mf.log("menu: " .. items[i])
    end
    if not i then
    elseif i == 2 then r = load_film()
    elseif i == 3 then seal_now()
    elseif i == 4 then r = show_rolls()
    elseif i == 5 then
      if have("set_autostart") then
        set_autostart(auto_on and 0 or 1)
        mf.log("autostart " .. (auto_on and "off" or "on"))
      end
    elseif i == 6 then r = show_diag()
    elseif i == 7 then
      if confirm("Quit M-Film", {"Frames shot after quitting are NOT recorded.", "The roll stays loaded."}) then
        quit = true
      end
    end
    if r == "shoot" then break end
  end
  draw_clear()
  title_line(true)
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
  if not set_rec(true) then                      -- powered on in playback / low battery: back to the menu
    say(vbatt() < BATT_LOW_MV and "Battery low: the lens stays in" or "Could not switch to shooting", 6000)
    if have("enter_alt") then enter_alt() end
    return
  end
  canon_info(false)                              -- straight to shooting after autostart
  if have("exit_alt") then exit_alt() end
  local function canon_gallery()
    -- Canon's own gallery is not used: playback outside the app's viewer
    -- goes straight back to the M-Film menu (Rolls -> View shows developed frames)
    if is_rec() then return false end
    mf.log("Canon playback blocked: back to the menu")
    if have("enter_alt") then enter_alt() end
    return true
  end
  show_overlay(3000)
  local last_draw, pending_since, shown = 0, nil, false
  local last_poll, last_full_poll, last_dir = 0, get_tick_count(), nil
  while not quit do
    boot_alive()
    if canon_gallery() then return end
    if have("get_alt_mode") and get_alt_mode() then return end   -- Playback pressed: menu (before drawing)
    local dir = get_image_dir()
    local n = shot_count()
    if n ~= shots_seen then
      shots_seen = n
      pending_since = pending_since or get_tick_count()
    end
    -- the card is read when a shot was taken (until its DNG is in), on a new
    -- folder, and every 5 s anyway; every 30 s known DNGs are re-checked
    local now = get_tick_count()
    local found = {}
    if pending_since or dir ~= last_dir or now - last_poll >= 5000 then
      -- a shot with no new DNG after 1.5 s: maybe it overwrote one, check sizes now
      local full = now - last_full_poll >= 30000
                   or (pending_since and now - pending_since > 1500 and last_full_poll < pending_since)
      found = watcher.poll(dir, full)
      last_poll, last_dir = now, dir
      if full then last_full_poll = now end
    end
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

-- Crash-loop guard. CHDK starts this script at every power-on; if a start
-- dies before the app is up (the camera restarts), the next start would die
-- the same way, forever (2026-11-05: the camera rebooted in a loop). BOOT.TXT
-- says "starting" until the app has run for a few seconds; finding it still
-- there at an autostart means the last start failed: autostart is switched
-- off so the next power-on is a plain CHDK camera.
local BOOT = "A/CHDK/MFILM/BOOT.TXT"
local boot_t0, boot_ok = 0, false
-- BOOT.TXT: "starting"/"ok", then the times (os.time) of recent autostarts.
-- Four autostarts within 60 s also count as a loop: on 2026-11-05 each start
-- got past the first seconds and then the battery cut the camera off.
local boot_times = {}
local function boot_save(state)
  local f = io.open(BOOT, "wb")
  if f then f:write(state .. "\n" .. table.concat(boot_times, " ") .. "\n"); f:close() end
end
local function boot_guard()
  boot_t0 = get_tick_count()
  local f = io.open(BOOT, "rb")
  local last, times = nil, nil
  if f then last = f:read("*l"); times = f:read("*l"); f:close() end
  local now = os.time() or 0
  local auto = have("autostarted") and autostarted()
  for t in string.gmatch(times or "", "%d+") do
    local n = tonumber(t)
    if n and now - n >= 0 and now - n < 60 then boot_times[#boot_times + 1] = n end
  end
  if auto then boot_times[#boot_times + 1] = now end   -- autostarts only: a hand start is not a loop
  boot_save("starting")
  if auto and have("set_autostart") and (last == "starting" or #boot_times >= 4) then
    set_autostart(0)
    return true
  end
  return false
end
boot_alive = function()                          -- called from the wait loops
  if not boot_ok and get_tick_count() - boot_t0 > 5000 then
    boot_ok = true
    boot_save("ok")
  end
end

local function main()
  local looped = boot_guard()
  if have("get_gui_screen_width") then W, H = get_gui_screen_width(), get_gui_screen_height() end
  COLS = W / FW
  if COLS > 60 then COLS = 60 end
  local problems = mf.init()
  mf.log("---- start " .. mf.VERSION)
  if looped then
    mf.log("the previous start did not finish, or 4 autostarts in 60 s: CHDK autostart switched OFF")
    say("Last start failed: autostart is OFF (Diagnostics)", 15000)
  end
  selftest = run_selftest()
  local fbs = fb_init()
  selftest[#selftest + 1] = fbs
  mf.log("display: " .. fbs)
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
  -- CHDK's OSD replaces Canon's information display: only its battery icon
  -- stays (Canon's is hidden now); clock, temperature, RAW counter and state
  -- and card space are switched off as the owner asked (CHDK saves them)
  if have("get_config_value") then
    -- the CHDK splash (logo for the first seconds after power-on) is erased
    -- when it ends, taking the menu with it: the two flashes after boot (0.4.3)
    local want = {batt_icon_show = 1, batt_perc_show = 0, show_clock = 0, show_temp = 0, show_remaining_raw = 0,
                  show_raw_state = 0, space_mb_show = 0, space_bar_show = 0, splash_show = 0}
    for _, name in ipairs({"batt_icon_show", "batt_perc_show", "show_clock", "show_temp", "show_remaining_raw",
                           "show_raw_state", "space_mb_show", "space_bar_show", "splash_show"}) do
      local v = get_config_value(CONF[name])
      if v ~= nil and v ~= want[name] then
        set_config_value(CONF[name], want[name])
        mf.log("CHDK OSD: " .. name .. " " .. want[name] .. " (was " .. tostring(v) .. ")")
      end
    end
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
  if not looped and have("get_autostart") and have("set_autostart") and get_autostart() == 0 and not auto then
    set_autostart(1)
    mf.log("autostart enabled")
    say("M-Film now starts with the camera", 5000)
  end
  -- powered on with film loaded: straight to shooting -- unless it was switched
  -- on with the Playback button (lens in): then the menu, the lens stays in
  local skip_menu = auto and roll ~= nil and is_rec()
  while not quit do
    if not skip_menu then menu() end
    skip_menu = false
    if quit then break end
    shooting()
  end
  canon_info(true)                               -- quitting: the camera is Canon's again
  mf.log("---- quit")
end

-- no pcall around main: CHDK's sleep/wait_click yield the script coroutine,
-- and Lua 5.1 cannot yield across pcall. Errors end the script with CHDK's
-- own message; state on the card is always consistent (atomic writes).
main()
