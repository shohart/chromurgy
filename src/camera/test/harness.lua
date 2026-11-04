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
--   {"restart"}            start the app again (after powercut or quit)
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

local function log(s) io.stderr:write(s, "\n") end

local function mkfile(p, data)
  local f = assert(io.open(p, "wb"))
  f:write(data)
  f:close()
end

local function mkdirs(p)
  local acc = ""
  for part in string.gmatch(p, "[^/]+") do
    acc = (acc == "") and part or (acc .. "/" .. part)
    os.mkdir(acc)
  end
end

local function dng_bytes(n)
  -- little-endian TIFF magic + filler; size differs per frame
  return "II*\0" .. string.rep(string.char(65 + n % 26), 4000 + n * 7)
end

-- ---------------------------------------------------------------- CHDK API stubs

function get_tick_count() return clock end
function sleep(ms) coroutine.yield("sleep", ms) end
function wait_click(ms) click = nil; coroutine.yield("wait", ms or 0) end
function is_key(k) return click == k end
function get_alt_mode() return alt end
function exit_alt() alt = false end
function enter_alt() alt = true end
function set_exit_key(k) exit_key = k end
-- CHDK does not clip: text past the bitmap edge writes outside the screen buffer
function draw_string(x, y, s, fg, bg)
  if x < 0 or y < 0 or x + 8 * string.len(s) > 360 or y + 16 > 240 then
    error(string.format("off-screen draw_string at %d,%d len %d: %s", x, y, string.len(s), s))
  end
  drawn[#drawn + 1] = s
end
function draw_rect_filled() end
function draw_rect() end
function draw_clear() drawn[#drawn + 1] = "<clear>" end
function get_gui_screen_width() return 360 end
function get_gui_screen_height() return 240 end
function get_image_dir() return image_dir end
function get_raw() return true end
function get_vbatt() return 3950 end
function get_exp_count() return shots end
function get_buildinfo() return {platform = "sx510hs", platsub = "101a", build_number = "host", build_revision = "0"} end
hook_raw = {count = function() return shots end}

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
    if s[1] == "restart" then i = i + 1; co = new_app(); exited = false
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
        if k == "key" then click = s[2]
        elseif k == "playback" then alt = not alt
        elseif k == "shoot" then step_shoot(s[2])
        elseif k == "wait" then pending = s[2]
        elseif k == "setdir" then image_dir = s[2]
        elseif k == "powercut" then co = coroutine.create(function() end); coroutine.resume(co)
        elseif k == "expect" then
          local hit = false
          for _, t in ipairs(drawn) do if string.find(t, s[2]) then hit = true end end
          if not hit then
            log("FAIL: step " .. (i - 1) .. ": no text matching '" .. s[2] .. "'; recent:")
            for j = math.max(1, #drawn - 25), #drawn do log("   " .. drawn[j]) end
            os.exit(1)
          end
          drawn = {}
        elseif k == "restart" then log("FAIL: restart while app is running") os.exit(1)
        elseif k == "expect_exit" then log("FAIL: app still running at expect_exit") os.exit(1)
        else log("FAIL: unknown step " .. tostring(k)) os.exit(1) end
      end
    end
  end
end
print("harness: OK, " .. shots .. " shot(s), " .. (i - 1) .. " step(s)")
