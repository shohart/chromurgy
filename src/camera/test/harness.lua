-- SPDX-License-Identifier: GPL-2.0-only
-- Host harness for the M-Film camera app, run with CHDK's own host Lua
-- (integer numbers, same os/io libraries as the camera):
--
--     cd <tmp>; lua harness.lua <app_dir> <scenario.lua>
--
-- <tmp>/A is the SD card. The app runs as a coroutine and the stubbed
-- sleep()/wait_click() yield exactly where CHDK's do (lua_yield), so a
-- yield across pcall fails here as it would on the camera. A scenario is a
-- list of steps consumed whenever the app waits:
--   {"key", name}          click a key (seen by the next is_key)
--   {"playback"}           short Playback press: toggles ALT (menu) mode
--   {"shoot", opts}        the camera writes a DNG (+ JPG): opts.dir, opts.lag, opts.raw=false, opts.overwrite
--   {"wait", ms}           let time pass
--   {"powercut"}           kill the app mid-flight; the next step restarts it on the same card
--   {"restart"}            start the app again by hand (after powercut or quit)
--   {"boot"}               power-on: CHDK autostarts the app if autostart is set
--   {"expect_autostart", n} CHDK's autostart setting is n
--   {"expect", pattern}    some text drawn since the last expect matches pattern
--   {"setdir", dir}        the camera starts a new DCIM folder
--   {"expect_prop", id, v} Canon propcase id is v (105 = display mode, 0 = info shown)
--   {"set_prop", id, v}    the owner changes a Canon setting (e.g. presses DISP)
--   {"flip"}               Canon flips the two bitmap buffers
--   {"flip_every", n}      ... after every n draw_string calls (0/nil: never)
--   {"canon_erase"}        Canon erases the active bitmap buffer
--   {"expect_screen_full"} both buffers hold the same complete screen
--   {"stock_chdk"}         CHDK without the M-Film Lua functions
--   {"canon_playback"}     the owner switches the camera to Canon's playback
--   {"expect_shown", pat}  the last frame the viewer showed matches pat
--   {"expect_rec", bool}   shooting (true) or playback (false) mode
--   {"chaos", seed, flips_per_s, erases_per_s}  Canon flips / erases the overlay
--                          at random moments from now on (0, 0: off)
--   {"heap", free, largest} the camera's free heap (the developer needs a big block)
--   {"open_menu"}          press Playback if the M-Film menu is not up
--   {"fuzz"}               random walks: keys while shooting go to Canon, a quit app is started again
--   {"expect_glitches", max_flip, max_erase_ms}  display model, see below
-- Display model: at every yield the app has finished a pass, so the active
-- overlay buffer is what it means to show. Canon's events then happen; if the
-- buffer the screen shows differs from it, that is a visible glitch (flicker)
-- until the app's next pass. Counted while the app is in ALT mode (menus,
-- viewer, developer), split by cause; printed at the end as
-- "glitches: flip N, erase N, longest N ms".
-- Exit status 0 = scenario passed.

local app_dir, scen_path = arg[1], arg[2]
package.path = app_dir .. "/?.lua;" .. package.path
local steps = dofile(scen_path)

local clock, shots, alt, pressed_key = 1000, 0, true, nil
local drawn = {}
local image_dir = "A/DCIM/101___01"
local file_no = 100
local exited = false
titles = {}                                 -- screens seen (row 0 text), for fuzz coverage
fuzz = false                                -- {"fuzz"}: keys in shooting mode go to Canon; quit -> start again
local expect_deadline = nil

local function log(s) io.stderr:write(s, "\n") end

local function mkfile(p, data)
  local f = assert(io.open(p, "wb"))
  f:write(data)
  f:close()
end

local function mkdirs(p)                  -- "A/..." paths; the card root A exists already
  local acc = "A"
  for part in string.gmatch(string.sub(p, 3), "[^/]+") do
    acc = acc .. "/" .. part
    os.mkdir(acc)
  end
end

local function dng_bytes(n)
  -- little-endian TIFF magic + filler; size differs per frame
  return "II*\0" .. string.rep(string.char(65 + n % 26), 4000 + n * 7)
end

-- ---------------------------------------------------------------- CHDK API stubs
-- optional draw log for screenshots (tools/render_screens.py): MFILM_DRAWLOG=path
local drawlog = os.getenv and os.getenv("MFILM_DRAWLOG")
local dl = drawlog and io.open(drawlog, "wb")
local function dlog(s) if dl then dl:write(s, "\n") end end

function get_tick_count() return clock end
-- camera time from the harness clock, so runs replay exactly (uuid seeds, dates)
local raw_time, raw_date = os.time, os.date
local EPOCH = raw_time({year = 2026, month = 11, day = 5, hour = 10, min = 0, sec = 0})
os.time = function(t) if t then return raw_time(t) end return EPOCH + clock / 1000 end
os.date = function(f, t) return raw_date(f, t or os.time()) end
function sleep(ms) coroutine.yield("sleep", ms) end
function wait_click(ms) pressed_key = nil; coroutine.yield("wait", ms or 0) end
function is_key(k) return pressed_key == k end
function get_alt_mode() return alt end
function exit_alt() alt = false end
function enter_alt() alt = true end
function set_exit_key(k) exit_key = k end
-- Two bitmap buffers (SX510 HS: CHDK draws into the active one only, Canon
-- flips them). fbuf[b][text row][x] = string drawn there. peek() serves
-- active_bitmap_buffer (0x4138), bitmap_buffer[] (0x413c) and bitmap bytes:
-- a byte reads as a checksum of its text row in that buffer.
fbuf, fb_active, flip_every, draws_since_flip = {[0] = {}, [1] = {}}, 0, nil, 0
local FB_BASE = {[0] = 0x40000000, [1] = 0x40100000}
function fb_draw(x, y, sc, s)
  for r = y / 16, (y + 16 * sc - 1) / 16 do
    local row = fbuf[fb_active][r]
    if x == 0 or not row then row = {}; fbuf[fb_active][r] = row end
    row[x] = s
  end
  if flip_every then
    draws_since_flip = draws_since_flip + 1
    if draws_since_flip >= flip_every then draws_since_flip = 0; fb_active = 1 - fb_active end
  end
end
local function fb_row_text(b, r)
  local row, xs, t = fbuf[b][r], {}, {}
  if not row then return "" end
  for x in pairs(row) do xs[#xs + 1] = tostring(x) end
  table.sort(xs)
  for _, x in ipairs(xs) do t[#t + 1] = x .. ":" .. (row[x] or row[tonumber(x)]) end
  return table.concat(t, "|")
end
local function fb_sig(b)
  local t = {}
  for r = 0, 14 do t[#t + 1] = fb_row_text(b, r) end
  return table.concat(t, "\n")
end
local rng = 12345
-- CHDK's Lua numbers are 32-bit integers: the generator must not overflow
-- (a classic 1103515245 LCG did, went negative and fired on every tick)
local function lcg()
  rng = (rng * 75 + 74) % 65537             -- ZX81 generator: rng * 75 < 2^31
  return rng
end
local function rnd(n)                       -- 30 bits from two draws
  return ((lcg() % 32768) * 32768 + lcg() % 32768) % n
end
local chaos = {flips = 0, erases = 0}       -- events per second
local glitch = {flip = 0, erase = 0, longest = 0, since = nil, cause = nil}
splash_at = nil                             -- clock when CHDK's splash ends (erases the overlay)
heap = {free = 968000, largest = 964000}
transition_until = 0                        -- Canon redraws its whole screen after a mode switch / DISP
local function display_tick(dt)
  if not alt or clock < transition_until then glitch.since = nil; return end
  local meant = fb_sig(fb_active)
  local cause = nil
  if splash_at and clock >= splash_at then
    splash_at = nil
    fbuf = {[0] = {}, [1] = {}}
    cause = "erase"
  end
  local p = dt * 1000                       -- per-mille chance scaled by elapsed ms
  if chaos.flips > 0 and rnd(1000000) < chaos.flips * p then fb_active = 1 - fb_active; cause = cause or "flip" end
  if chaos.erases > 0 and rnd(1000000) < chaos.erases * p then fbuf[fb_active] = {}; cause = "erase" end
  if cause and os.getenv("MFILM_CHAOS_LOG") then
    log(string.format("chaos %s at %d dt %d active %d differs %s", cause, clock, dt, fb_active, tostring(fb_sig(fb_active) ~= meant)))
  end
  if cause and not glitch.since and fb_sig(fb_active) ~= meant then
    glitch[cause] = glitch[cause] + 1
    -- the event happened at some moment of the wait just ended: count it from its start
    glitch.since, glitch.cause, glitch.sig = clock - dt, cause, fb_sig(fb_active)
    glitch.where = app_co and string.gsub(debug.traceback(app_co, "", 1), "\n%s*", " | ") or nil
  end
end
local function glitch_close()
  -- after the app's pass: the glitch lasts until the app has changed what is shown
  if glitch.since and fb_sig(fb_active) ~= glitch.sig then
    local d = clock - glitch.since
    if d > glitch.longest then glitch.longest = d end
    if (d > 150 or glitch.cause == "flip") and os.getenv("MFILM_GLITCH_LOG") then
      log(string.format("glitch %s %d ms at %d, screen: %s / %s", glitch.cause, d, clock,
                        tostring(drawn[#drawn - 1]), tostring(drawn[#drawn])))
      if glitch.where then log("  app was at: " .. glitch.where) end
    end
    glitch.since = nil
  end
end
function peek(addr, size)
  size = size or 4
  if addr == 0x4138 and size == 4 then return fb_active end
  if addr == 0x413c and size == 4 then return FB_BASE[0] end
  if addr == 0x4140 and size == 4 then return FB_BASE[1] end
  for b = 0, 1 do
    local off = addr - FB_BASE[b]
    if size == 1 and off > 0 and off < 960 * 270 then
      local t, sum = fb_row_text(b, off / 960 / 16), 0
      for k = 1, string.len(t) do sum = (sum * 31 + string.byte(t, k)) % 251 end
      return t == "" and 0 or sum + 1           -- an erased row (transparent) reads 0, a drawn one never
    end
  end
  error(string.format("peek at unexpected address %x size %d", addr, size), 2)
end
-- CHDK does not clip: text past the bitmap edge writes outside the screen buffer
function draw_string(x, y, s, fg, bg, scale)
  local sc = scale or 1
  if x < 0 or y < 0 or x + 8 * sc * string.len(s) > 360 or y + 16 * sc > 240 then
    error(string.format("off-screen draw_string at %d,%d len %d: %s", x, y, string.len(s), s))
  end
  -- the menu must never be drawn while Canon's information display is on:
  -- Canon's icons collided with it and it flickered (alpha 0.1.0-0.1.7)
  if alt and rec_mode and props[105] == 0 then error("menu text drawn over Canon's information display: " .. s, 2) end
  drawn[#drawn + 1] = s
  if x == 0 and y == 0 then
    local t = string.match(s, "^%s*(%a[%a ]-)%s*[%d(]") or string.match(s, "^%s*(.-)%s*$")
    titles[t] = (titles[t] or 0) + 1
  end
  fb_draw(x, y, sc, s)
  dlog(string.format("S %d %d %d %d %d %s", x, y, sc, fg or 258, bg or 257, s))
end
local function check_rect(x1, y1, x2, y2)
  if x1 < 0 or y1 < 0 or x2 > 359 or y2 > 239 or x2 < x1 or y2 < y1 then
    error(string.format("off-screen rect %d,%d-%d,%d", x1, y1, x2, y2), 3)
  end
end
function draw_rect_filled(x1, y1, x2, y2, c1, c2)
  check_rect(x1, y1, x2, y2)
  if alt and rec_mode and props[105] == 0 then error("menu graphics drawn over Canon's information display", 2) end
  -- rows hold rects keyed by their origin, next to the text drawn there
  local k = string.format("r%d.%d", x1, y1)
  for r = y1 / 16, y2 / 16 do
    local row = fbuf[fb_active][r]
    if not row then row = {}; fbuf[fb_active][r] = row end
    row[k] = string.format("%d,%d,%d", x2, y2, c2 or c1)
  end
  dlog(string.format("R %d %d %d %d %d", x1, y1, x2, y2, c2 or c1))
end
function draw_rect(x1, y1, x2, y2) check_rect(x1, y1, x2, y2) end
function draw_clear() drawn[#drawn + 1] = "<clear>"; fbuf = {[0] = {}, [1] = {}}; dlog("C") end
function set_draw_title_line(on) title_line = on end
function get_gui_screen_width() return 360 end
function get_gui_screen_height() return 240 end
function get_image_dir() return image_dir end
function get_raw() return true end
function get_vbatt() return 3950 end
function get_exp_count() return shots end
function get_buildinfo() return {platform = "sx510hs", platsub = "101a", build_number = "host", build_revision = "0"} end
hook_raw = {count = function() return shots end}
local autostart_conf, booted = 0, false
rec_mode = true                     -- camera starts in shooting mode
-- Canon display mode (propcase 105): 0 = information shown; DISP in shooting
-- mode cycles 0 -> 1 -> 0
props = {[105] = 0}
local disp_modes = 2
-- M-Film CHDK build functions (src/camera/chdk/mfilm_lua.c)
shown_frames = {}
function mf_viewport() return 0x40a00000, 720, 480, 1080, 2, 0, not rec_mode end
function mf_show(path)
  if rec_mode then return nil, "not in playback mode" end
  local f = io.open(path, "rb")
  if not f then return nil, "cannot open file" end
  local hd = f:read(4); f:close()
  if hd ~= "MFV1" then return nil, "not an MFV1 file" end
  shown_frames[#shown_frames + 1] = path
  dlog("SHOW " .. path)
  return true, 40
end
-- the developer task: a frame takes DEV_MS of camera time; on success it writes
-- the JPEG and MFV paths it was given (tiny stand-ins)
DEV_MS = 3000
dev_job, dev_log = nil, {}
function mf_dev_start(camf, devf, film, dng, jpg, mfv, tmp, hi, lo)
  if dev_job and dev_job.state == "running" then return nil, "busy" end
  for _, p in ipairs({camf, devf}) do
    local f = io.open(p, "rb"); if not f then return nil, "bad arguments" end; f:close()
  end
  dev_job = {state = "running", t0 = clock, dng = dng, jpg = jpg, mfv = mfv, film = film, rc = 0}
  if heap.largest < 240000 or heap.free < 640000 then dev_job.state, dev_job.rc = "error", -22 end
  dev_log[#dev_log + 1] = dng .. " " .. film .. " " .. tostring(hi) .. "/" .. tostring(lo)
  local f = io.open(dng, "rb")
  if not f then dev_job.state, dev_job.rc = "error", -20 else f:close() end
  return true
end
function mf_dev_status()
  local j = dev_job
  if not j then return "idle", 0, 0, 0 end
  if j.state == "running" then
    if j.cancel then j.state, j.rc = "error", -25
    elseif clock - j.t0 >= DEV_MS then
      for _, p in ipairs({j.jpg, j.mfv}) do
        local f = assert(io.open(p, "wb")); f:write(p == j.mfv and "MFV1" .. string.rep("\0", 8) or "\255\216"); f:close()
      end
      j.state = "done"
    end
  end
  local pm = j.state == "running" and ((clock - j.t0) * 1000 / DEV_MS) or 1000
  return j.state, pm, j.rc, clock - j.t0
end
function mf_dev_cancel() if dev_job then dev_job.cancel = true end end
function mf_overlay_mirror()
  local c = {}
  for r, row in pairs(fbuf[fb_active]) do
    local t = {}
    for x, v in pairs(row) do t[x] = v end
    c[r] = t
  end
  fbuf[1 - fb_active] = c
  return true
end
function mf_overlay_clear() fbuf = {[0] = {}, [1] = {}}; dlog("C"); return true end
function get_prop(id) return props[id] end
function set_prop(id, v) props[id] = v end
function click(k)
  if k == "display" and rec_mode then props[105] = (props[105] + 1) % disp_modes; transition_until = clock + 600 end
  coroutine.yield("sleep", 10)
end
-- CHDK config (new ids, CONF_OSD 2000 + osd id); an id below 1000 is an OLD id
-- the camera would remap to some other setting: the stub refuses those
local conf = {[2001] = 1, [2102] = 1, [2104] = 1, [2080] = 2, [2220] = 1, [2200] = 1, [2201] = 1, [2182] = 1, [2183] = 1, [2120] = 1}
function get_mode() return rec_mode, false, rec_mode and 1 or 0 end
function set_record(v) rec_mode = (v == 1 or v == true); transition_until = clock + 1500 end
function get_config_value(id)
  if id < 1000 then error("old CHDK config id " .. id .. " (remapped by conf_migrate)", 2) end
  return conf[id]
end
function set_config_value(id, v)
  if id < 1000 then error("old CHDK config id " .. id .. " (remapped by conf_migrate)", 2) end
  conf[id] = v
end
function get_autostart() return autostart_conf end
function set_autostart(v) autostart_conf = v end
function autostarted() return booted end

-- ---------------------------------------------------------------- DryOS file rules
-- What the SX510 HS taught us (alpha 2026-11-04): os.rename refuses to replace
-- and powered the camera off inside a long-named directory. The app must use
-- 8.3 names only (upper case when it creates them) and never rename.
local function is83(c, create)
  local name, ext = string.match(c, "^([^.]+)%.?([^.]*)$")
  if not name or string.len(name) > 8 or string.len(ext) > 3 then return false end
  if string.find(c, "[^%w_%-~.]") then return false end
  if create and string.find(c, "%l") then return false end
  return true
end
local function check_path(p, create, what)
  if p == "A" or p == "A/" then error(what .. ": bare drive path (DriveLetterManager assert on the camera)", 3) end
  if string.sub(p, 1, 2) ~= "A/" then return end           -- harness-internal files
  for c in string.gmatch(string.sub(p, 3), "[^/]+") do
    if not is83(c, create) then error(what .. ": not an 8.3" .. (create and " upper-case" or "") .. " name: " .. p, 2) end
  end
end
local raw_open, raw_mkdir, raw_stat, raw_remove, raw_listdir = io.open, os.mkdir, os.stat, os.remove, os.listdir
io.open = function(p, mode)
  check_path(p, mode and string.find(mode, "[wa]") ~= nil, "io.open")
  return raw_open(p, mode)
end
os.mkdir = function(p) check_path(p, true, "os.mkdir") return raw_mkdir(p) end
os.stat = function(p) check_path(p, false, "os.stat") return raw_stat(p) end
os.remove = function(p) check_path(p, false, "os.remove") return raw_remove(p) end
os.listdir = function(p, ...) check_path(p, false, "os.listdir") return raw_listdir(p, ...) end
os.rename = function(a, b) error("os.rename is not used on the camera (refuses to replace; crashed in long dirs)", 2) end

-- ---------------------------------------------------------------- driver

local function new_app()
  local chunk = assert(loadfile(app_dir .. "/MFILM.LUA"))
  if conf[2120] == 1 then splash_at = clock + 2500 end   -- CHDK's splash ends and is erased
  package.loaded["mfroll"] = nil
  alt = true                                   -- CHDK starts scripts in ALT mode
  return coroutine.create(chunk)
end

-- continue the camera's file numbering from what is already on the card
for _, n in ipairs(os.listdir(image_dir) or {}) do
  local num = tonumber(string.match(n, "^%a%a%a_(%d%d%d%d)%.") or "")
  if num and num > file_no then file_no = num end
end

local co = new_app()
app_co = co
local i, pending, guard = 1, 0, 0

local function step_shoot(o)
  o = o or {}
  if o.dir then image_dir = o.dir end
  mkdirs(image_dir)
  shots = shots + 1
  file_no = file_no + 1
  local name = string.format("CRW_%04d.DNG", file_no - (o.lag and 1 or 0))
  if o.raw ~= false then
    if o.overwrite then name = o.overwrite end
    mkfile(image_dir .. "/" .. name, dng_bytes(file_no))
  end
  mkfile(image_dir .. string.format("/IMG_%04d.JPG", file_no), "\255\216\255jpeg")
end

while true do
  guard = guard + 1
  if guard > 200000 then log("FAIL: runaway (step " .. i .. ")") os.exit(2) end
  if coroutine.status(co) == "dead" then
    exited = true
    local s = steps[i]
    if not s then break end
    if fuzz and s[1] ~= "restart" and s[1] ~= "boot" then
      co = new_app(); exited = false; app_co = co  -- the owner starts M-Film again
    elseif s[1] == "restart" or s[1] == "boot" then
      booted = s[1] == "boot" and autostart_conf == 1   -- power-on with CHDK autostart
      i = i + 1; co = new_app(); exited = false; app_co = co
    elseif s[1] == "expect_exit" then i = i + 1; expect_deadline = nil
    elseif s[1] == "expect_prop" then              -- what the app left behind
      if props[s[2]] ~= s[3] then log("FAIL: prop " .. s[2] .. " = " .. tostring(props[s[2]]) .. " after exit, expected " .. s[3]) os.exit(1) end
      i = i + 1
    else log("FAIL: app exited before step " .. i .. " (" .. s[1] .. ")") os.exit(1) end
  else
    local ok, kind, ms = coroutine.resume(co)
    if not ok then log("FAIL: app error: " .. tostring(kind)) os.exit(1) end
    if coroutine.status(co) ~= "dead" then
      local dt = ((kind == "sleep" or kind == "wait") and math.max(ms or 0, 10) or 10)
      glitch_close()
      clock = clock + dt
      display_tick(dt)
      if pending > 0 then
        pending = pending - (ms or 10)
      else
        local s = steps[i]
        if not s then break end
        i = i + 1
        local k = s[1]
        if k == "key" and kind ~= "wait" then        -- keys reach the app only when it waits for one
          if not alt and fuzz then k = "-"            -- shooting: the key went to Canon
          else i = i - 1; k = "-" end
        end
        if k == "-" then
        elseif k == "key" then pressed_key = s[2]
        elseif k == "playback" then alt = not alt
        elseif k == "open_menu" then alt = true            -- Playback pressed only if the menu is not up
        elseif k == "shoot" then step_shoot(s[2])
        elseif k == "wait" then pending = s[2]
        elseif k == "setdir" then image_dir = s[2]
        elseif k == "snap" then dlog("SNAP " .. s[2])
        elseif k == "powercut" then co = coroutine.create(function() end); coroutine.resume(co)
        elseif k == "expect" then
          -- wait (up to 3 s of camera time) until some text drawn since the last expect matches
          local hit = false
          for _, t in ipairs(drawn) do if string.find(t, s[2]) then hit = true end end
          if hit then
            drawn, expect_deadline = {}, nil
          else
            expect_deadline = expect_deadline or (clock + 3000)
            if clock > expect_deadline then
              log("FAIL: step " .. (i - 1) .. ": no text matching '" .. s[2] .. "'; recent:")
              for j = math.max(1, #drawn - 25), #drawn do log("   " .. drawn[j]) end
              os.exit(1)
            end
            i = i - 1                               -- retry this step at the next yield
          end
        elseif k == "restart" or k == "boot" then log("FAIL: " .. k .. " while app is running") os.exit(1)
        elseif k == "expect_state" then
          local want_rec, want_osd = s[2], s[3]
          if rec_mode ~= want_rec or conf[2001] ~= want_osd then
            log(string.format("FAIL: rec=%s osd=%s, expected rec=%s osd=%s", tostring(rec_mode), tostring(conf[2001]),
                tostring(want_rec), tostring(want_osd))) os.exit(1)
          end
        elseif k == "flip" then fb_active = 1 - fb_active
        elseif k == "chaos" then rng, chaos.flips, chaos.erases = s[2] % 65537, s[3], s[4]
        elseif k == "fuzz" then fuzz = true
        elseif k == "heap" then heap.free, heap.largest = s[2], s[3]
        elseif k == "expect_glitches" then
          glitch_close()
          if glitch.flip > s[2] or glitch.longest > s[3] then
            log(string.format("FAIL: step %d: glitches flip %d (max %d), erase %d, longest %d ms (max %d)", i - 1,
                glitch.flip, s[2], glitch.erase, glitch.longest, s[3])) os.exit(1)
          end
        elseif k == "stock_chdk" then
          mf_show, mf_overlay_clear, mf_viewport, mf_dev_start, mf_overlay_mirror = nil, nil, nil, nil, nil
        elseif k == "canon_playback" then rec_mode = false     -- the owner opens Canon's gallery
        elseif k == "expect_shown" then
          local last = shown_frames[#shown_frames]
          if not last or not string.find(last, s[2]) then
            log("FAIL: step " .. (i - 1) .. ": shown " .. tostring(last) .. ", expected " .. s[2]) os.exit(1)
          end
        elseif k == "expect_rec" then
          if rec_mode ~= s[2] then log("FAIL: rec_mode " .. tostring(rec_mode)) os.exit(1) end
        elseif k == "no_mirror" then mf_overlay_mirror = nil       -- 0.4.1 module (or stock CHDK)
        elseif k == "flip_every" then flip_every = (s[2] ~= 0) and s[2] or nil
        elseif k == "canon_erase" then fbuf[fb_active] = {}
        elseif k == "expect_screen_full" then
          -- both buffers hold the same complete screen: no row missing
          local bad = {}
          for r = 0, 14 do
            local a, b = fb_row_text(0, r), fb_row_text(1, r)
            if a == "" or a ~= b then bad[#bad + 1] = string.format("row %d: [%s] / [%s]", r, a, b) end
          end
          if #bad > 0 then
            log("FAIL: step " .. (i - 1) .. ": screen incomplete:")
            for _, l in ipairs(bad) do log("   " .. l) end
            os.exit(1)
          end
        elseif k == "expect_prop" then
          if props[s[2]] ~= s[3] then log("FAIL: prop " .. s[2] .. " = " .. tostring(props[s[2]]) .. ", expected " .. s[3]) os.exit(1) end
        elseif k == "set_prop" then props[s[2]] = s[3]
        elseif k == "expect_conf" then
          if conf[s[2]] ~= s[3] then log("FAIL: conf " .. s[2] .. " = " .. tostring(conf[s[2]]) .. ", expected " .. s[3]) os.exit(1) end
        elseif k == "expect_autostart" then
          if autostart_conf ~= s[2] then log("FAIL: autostart is " .. autostart_conf .. ", expected " .. s[2]) os.exit(1) end
        elseif k == "expect_exit" then                -- patient: quitting restores Canon's display first
          expect_deadline = expect_deadline or (clock + 3000)
          if clock > expect_deadline then log("FAIL: app still running at expect_exit") os.exit(1) end
          i = i - 1
        else log("FAIL: unknown step " .. tostring(k)) os.exit(1) end
      end
    end
  end
end
glitch_close()
print(string.format("harness: OK, %d shot(s), %d step(s); glitches: flip %d, erase %d, longest %d ms", shots, i - 1,
                    glitch.flip, glitch.erase, glitch.longest))
local tl = {}
for t, n in pairs(titles) do tl[#tl + 1] = t end
table.sort(tl)
-- io.write: CHDK hostlua's print truncates long lines
io.write("screens: ")
for _, t in ipairs(tl) do io.write(t, "; ") end
io.write(string.format("viewer frames %d; developed %d\n", #shown_frames, #dev_log))
