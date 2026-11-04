--[[
@title M-Film probe
@chdk_version 1.4
@param a Take test shot (1=yes)
@default a 1
@range a 0 1
]]
-- SPDX-License-Identifier: GPL-2.0-only
-- Read-only hardware probe (docs/03 "Required hardware probe"): CHDK build,
-- heaps, battery, temperatures, zoom, card, RAW settings, and optionally one
-- shot to time shoot() and the DNG write. Writes A/MFPROBE.TXT. Changes no
-- camera settings except switching to shooting mode if needed for the shot.

local out = {}
local function p(...) local s = string.format(...) out[#out+1] = s print(s) end
local function save()
  local f = io.open("A/MFPROBE.TXT", "wb")
  if f then f:write(table.concat(out, "\n"), "\n") f:close() end
end

p("M-Film probe %s", os.date("%Y-%m-%d %H:%M:%S"))
local bi = get_buildinfo()
for _, k in ipairs({"platform", "platsub", "version", "build_number", "build_revision", "build_date",
                    "build_time", "os", "platformid"}) do
  p("build.%s = %s", k, tostring(bi[k]))
end
for _, h in ipairs({"combined", "system", "aram", "exmem"}) do
  local m = get_meminfo(h)
  if m then
    p("mem.%s: free %s, largest block %s, total %s, allocated %s, chdk start 0x%x size %s", h,
      tostring(m.free_size), tostring(m.free_block_max_size), tostring(m.total_size),
      tostring(m.allocated_size), m.chdk_start or 0, tostring(m.chdk_size))
  else
    p("mem.%s: not available", h)
  end
end
p("battery mV: %d", get_vbatt())
p("temperature optical/CCD/battery: %d / %d / %d C", get_temperature(0), get_temperature(1), get_temperature(2))
p("zoom: step %d of %d, focal %d um", get_zoom(), get_zoom_steps(), get_focal_length())
p("card: free %d KB of %d KB, image dir %s", get_free_disk_space(), get_disk_size(), tostring(get_image_dir()))
p("raw: supported %s, enabled %s, raw nr %s", tostring(get_raw_support()), tostring(get_raw()), tostring(get_raw_nr()))
p("canon raw support: %s", tostring(get_canon_raw_support and get_canon_raw_support()))
save()

-- CPU reference for interpreted Lua (the film core runs as C, see MFBENCH.FLT)
local t0 = get_tick_count()
local x = 0
for i = 1, 200000 do x = (x * 3 + i) % 65521 end
p("lua loop 200k: %d ms", get_tick_count() - t0)
save()

local function newest(dir, pat)
  local best
  for _, n in ipairs(os.listdir(dir) or {}) do
    if n:match(pat) and (not best or n > best) then best = n end
  end
  return best
end

if a == 1 then
  if not get_mode() then
    set_record(1)
    local t = get_tick_count()
    while not get_mode() and get_tick_count() - t < 5000 do sleep(100) end
    sleep(1000)
  end
  local dir = get_image_dir()
  local before_dng = dir and newest(dir, "%.DNG$")
  p("before shot: last DNG %s, raw count left %d", tostring(before_dng), get_raw_count())
  local t1 = get_tick_count()
  shoot()
  local t2 = get_tick_count()
  p("shoot() returned after %d ms", t2 - t1)
  dir = get_image_dir()
  -- wait for a new DNG whose size stops changing
  local name, size, stable_at
  while get_tick_count() - t2 < 30000 do
    local n = newest(dir, "%.DNG$")
    if n and n ~= before_dng then
      local st = os.stat(dir .. "/" .. n)
      if st and st.size == size and size > 0 then stable_at = get_tick_count() break end
      name, size = n, st and st.size
    end
    sleep(100)
  end
  if stable_at then
    p("DNG %s/%s: %d bytes, stable %d ms after shoot() returned", dir, name, size, stable_at - t2)
  else
    p("no new DNG within 30 s (is RAW/DNG enabled in CHDK RAW parameters?)")
  end
  p("JPEG: %s", tostring(newest(dir, "%.JPG$")))
  p("battery mV after shot: %d", get_vbatt())
end
p("done")
save()
