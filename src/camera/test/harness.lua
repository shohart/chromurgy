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
-- Exit status 0 = scenario passed.

local app_dir, scen_path = arg[1], arg[2]
package.path = app_dir .. "/?.lua;" .. package.path
local steps = dofile(scen_path)

local clock, shots, alt, click = 1000, 0, true, nil
local drawn = {}
local image_dir = "A/DCIM/101___01"
local file_no = 100
local exited = false
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
function sleep(ms) coroutine.yield("sleep", ms) end
function wait_click(ms) click = nil; coroutine.yield("wait", ms or 0) end
function is_key(k) return click == k end
function get_alt_mode() return alt end
function exit_alt() alt = false end
function enter_alt() alt = true end
function set_exit_key(k) exit_key = k end
-- CHDK does not clip: text past the bitmap edge writes outside the screen buffer
function draw_string(x, y, s, fg, bg, scale)
  local sc = scale or 1
  if x < 0 or y < 0 or x + 8 * sc * string.len(s) > 360 or y + 16 * sc > 240 then
    error(string.format("off-screen draw_string at %d,%d len %d: %s", x, y, string.len(s), s))
  end
  -- the menu must never be drawn over the live view (shooting mode): it
  -- flickered and showed Canon's and CHDK's icons through (alpha 0.1.0-0.1.4)
  if alt and rec_mode then error("menu text drawn in shooting mode: " .. s, 2) end
  drawn[#drawn + 1] = s
  dlog(string.format("S %d %d %d %d %d %s", x, y, sc, fg or 258, bg or 257, s))
end
local function check_rect(x1, y1, x2, y2)
  if x1 < 0 or y1 < 0 or x2 > 359 or y2 > 239 or x2 < x1 or y2 < y1 then
    error(string.format("off-screen rect %d,%d-%d,%d", x1, y1, x2, y2), 3)
  end
end
function draw_rect_filled(x1, y1, x2, y2, c1, c2) check_rect(x1, y1, x2, y2); dlog(string.format("R %d %d %d %d %d", x1, y1, x2, y2, c2 or c1)) end
function draw_rect(x1, y1, x2, y2) check_rect(x1, y1, x2, y2) end
function draw_clear() drawn[#drawn + 1] = "<clear>"; dlog("C") end
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
local conf = {[1] = 1}              -- CHDK config: 1 = show_osd
function get_mode() return rec_mode, false, rec_mode and 1 or 0 end
function set_record(v) rec_mode = (v == 1 or v == true) end
function get_config_value(id) return conf[id] end
function set_config_value(id, v) conf[id] = v end
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
    if s[1] == "restart" or s[1] == "boot" then
      booted = s[1] == "boot" and autostart_conf == 1   -- power-on with CHDK autostart
      i = i + 1; co = new_app(); exited = false
    elseif s[1] == "expect_exit" then i = i + 1
    else log("FAIL: app exited before step " .. i .. " (" .. s[1] .. ")") os.exit(1) end
  else
    local ok, kind, ms = coroutine.resume(co)
    if not ok then log("FAIL: app error: " .. tostring(kind)) os.exit(1) end
    if coroutine.status(co) ~= "dead" then
      clock = clock + ((kind == "sleep" or kind == "wait") and math.max(ms or 0, 10) or 10)
      if pending > 0 then
        pending = pending - (ms or 10)
      else
        local s = steps[i]
        if not s then break end
        i = i + 1
        local k = s[1]
        if k == "key" and kind ~= "wait" then        -- keys reach the app only when it waits for one
          i = i - 1
          k = "-"
        end
        if k == "-" then
        elseif k == "key" then click = s[2]
        elseif k == "playback" then alt = not alt
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
          if rec_mode ~= want_rec or conf[1] ~= want_osd then
            log(string.format("FAIL: rec=%s osd=%s, expected rec=%s osd=%s", tostring(rec_mode), tostring(conf[1]),
                tostring(want_rec), tostring(want_osd))) os.exit(1)
          end
        elseif k == "expect_autostart" then
          if autostart_conf ~= s[2] then log("FAIL: autostart is " .. autostart_conf .. ", expected " .. s[2]) os.exit(1) end
        elseif k == "expect_exit" then log("FAIL: app still running at expect_exit") os.exit(1)
        else log("FAIL: unknown step " .. tostring(k)) os.exit(1) end
      end
    end
  end
end
print("harness: OK, " .. shots .. " shot(s), " .. (i - 1) .. " step(s)")
