-- SPDX-License-Identifier: GPL-2.0-only
-- mfroll: M-Film roll model for CHDK Lua (installed as A/CHDK/LUALIB/mfroll.lua).
--
-- Pure logic, no UI: configuration, ids, roll state, frame detection from
-- the files the camera writes, manifest + journal on the card. CHDK Lua
-- numbers are integers (no floats anywhere here).
--
-- Card layout (docs/04). Every name is 8.3 and upper case, and nothing is
-- ever renamed: on the SX510 HS (CHDK 1.6.1, DryOS) os.rename refuses to
-- replace a file and the camera powered off renaming inside a long-named
-- directory (alpha test 2026-11-04).
--   A/CHDK/MFILM/CONFIG/MFILM.CFG       written by the host (bundle hash, films, utc offset)
--   A/CHDK/MFILM/CONFIG/DEVICE_A|B.CFG  device id, generated on first run
--   A/CHDK/MFILM/CONFIG/ACTIVE_A|B.CFG  the roll in the camera
--   A/CHDK/MFILM/ROLLS/<8 hex>/STATE_A|B.CFG  roll state: two alternating copies with a generation
--   A/CHDK/MFILM/ROLLS/<8 hex>/MANIFEST.JSN   docs/04 + contracts/roll-manifest.schema.json
--   A/CHDK/MFILM/ROLLS/<8 hex>/JOURNAL.LOG    one line per event
--   A/CHDK/MFILM/LOGS/APP.LOG
-- Frames are the DNGs CHDK writes; they stay where the camera put them.
-- The camera does not hash them (~10 s per DNG): frames are WRITTEN and the
-- receiver hashes them on import.

local M = {}

M.VERSION = "0.2.1-alpha"
M.ROOT = "A/CHDK/MFILM"
M.LENGTHS = {12, 24, 36}

-- ------------------------------------------------------------------ files

local function stat(p)
  local ok, st = pcall(os.stat, p)
  if ok then return st end
  return nil
end
M.stat = stat

function M.exists(p) return stat(p) ~= nil end

-- create the directories of an "A/..." path; never touches the bare drive "A"
-- (DryOS asserts in DriveLetterManager on odd paths and powers off)
function M.mkdirs(p)
  local acc = "A"
  for part in string.gmatch(string.sub(p, 3), "[^/]+") do
    acc = acc .. "/" .. part
    if not stat(acc) then os.mkdir(acc) end
  end
end

function M.read(p)
  local f = io.open(p, "rb")
  if not f then return nil end
  local s = f:read("*a")
  f:close()
  return s
end

local function write_plain(p, data)
  local f, err = io.open(p, "wb")
  if not f then return nil, err end
  local ok = f:write(data)
  f:close()
  if not ok then return nil, "write failed" end
  return true
end

-- Crash-safe small state without rename: two copies NAME_A.CFG / NAME_B.CFG,
-- written alternately, each ending in a marker with its generation. A torn
-- write leaves the other copy intact; load picks the newest complete one.
local slot_gen = {}

local function slot_read(p)
  local s = M.read(p)
  if not s then return nil end
  local gen = string.match(s, "\n%-%- end gen=(%d+)\n$")
  if not gen then return nil end
  local f = loadstring(s)
  if not f then return nil end
  local ok, t = pcall(f)
  if ok and type(t) == "table" then return t, tonumber(gen) end
  return nil
end

function M.load_slots(dir, name)
  local a, ga = slot_read(dir .. "/" .. name .. "_A.CFG")
  local b, gb = slot_read(dir .. "/" .. name .. "_B.CFG")
  local key = dir .. "/" .. name
  if a and (not b or ga > gb) then slot_gen[key] = {ga, "A"} return a end
  if b then slot_gen[key] = {gb, "B"} return b end
  slot_gen[key] = {0, "B"}
  return nil
end

function M.save_slots(dir, name, t, ser_fn)
  local key = dir .. "/" .. name
  if not slot_gen[key] then M.load_slots(dir, name) end
  local g = slot_gen[key]
  local slot = g[2] == "A" and "B" or "A"
  local gen = g[1] + 1
  local ok, err = write_plain(dir .. "/" .. name .. "_" .. slot .. ".CFG",
                              "return " .. ser_fn(t) .. "\n-- end gen=" .. gen .. "\n")
  if not ok then return nil, err end
  slot_gen[key] = {gen, slot}
  return true
end

-- append a line; "a" mode is not guaranteed on every DryOS, fall back to rewrite
function M.append(p, line)
  local f = io.open(p, "a")
  if f then
    f:write(line, "\n")
    f:close()
    return true
  end
  local old = M.read(p) or ""
  return write_plain(p, old .. line .. "\n")
end

-- ------------------------------------------------------------------ time, ids, log

M.utc_offset = "+00:00"

function M.now_iso()
  return os.date("%Y-%m-%dT%H:%M:%S") .. M.utc_offset
end

function M.log(msg)
  M.append(M.ROOT .. "/LOGS/APP.LOG", os.date("%Y-%m-%d %H:%M:%S") .. " " .. msg)
end

local seeded = false
local function seed()
  if seeded then return end
  local t = os.time() or 0
  math.randomseed((t % 1000003) * 997 + (get_tick_count() % 1000003))
  seeded = true
end

local function hex(n)
  local s = ""
  for i = 1, n do s = s .. string.format("%x", math.random(0, 15)) end
  return s
end

-- random UUIDv4-shaped id (4 bits of version, 2 of variant)
function M.uuid()
  seed()
  local i = math.random(1, 4)
  local y = string.sub("89ab", i, i)
  return hex(8) .. "-" .. hex(4) .. "-4" .. hex(3) .. "-" .. y .. hex(3) .. "-" .. hex(12)
end

-- ------------------------------------------------------------------ serialisation

local function ser(v, ind)
  local t = type(v)
  if t == "number" then return string.format("%d", v) end
  if t == "boolean" then return v and "true" or "false" end
  if t == "string" then return string.format("%q", v) end
  if t == "table" then
    local out, pad = {}, ind .. "  "
    local n = #v
    for i = 1, n do out[#out + 1] = pad .. ser(v[i], pad) end
    local keys = {}
    for k in pairs(v) do
      if type(k) == "string" then keys[#keys + 1] = k end
    end
    table.sort(keys)
    for _, k in ipairs(keys) do out[#out + 1] = pad .. "[" .. string.format("%q", k) .. "]=" .. ser(v[k], pad) end
    return "{\n" .. table.concat(out, ",\n") .. "\n" .. ind .. "}"
  end
  return "nil"
end

local function ser0(t) return ser(t, "") end
function M.save(dir, name, t) return M.save_slots(dir, name, t, ser0) end
function M.load(dir, name) return M.load_slots(dir, name) end

local function jstr(s)
  s = string.gsub(s, '[%c"\\]', function(c)
    if c == '"' then return '\\"' end
    if c == "\\" then return "\\\\" end
    return string.format("\\u%04x", string.byte(c))
  end)
  return '"' .. s .. '"'
end

-- ordered JSON object: list of {key, value}; values: string, number, boolean, nested lists
local function json(v, ind)
  local t = type(v)
  if t == "string" then return jstr(v) end
  if t == "number" then return string.format("%d", v) end
  if t == "boolean" then return v and "true" or "false" end
  local pad = ind .. "  "
  if v.obj then
    local out = {}
    for _, kv in ipairs(v.obj) do
      if kv[2] ~= nil then out[#out + 1] = pad .. jstr(kv[1]) .. ": " .. json(kv[2], pad) end
    end
    return "{\n" .. table.concat(out, ",\n") .. "\n" .. ind .. "}"
  end
  if #v == 0 then return "[]" end
  local out = {}
  for _, x in ipairs(v) do out[#out + 1] = pad .. json(x, pad) end
  return "[\n" .. table.concat(out, ",\n") .. "\n" .. ind .. "]"
end
M.json = function(v) return json(v, "") end

-- ------------------------------------------------------------------ config

M.cfg = nil
M.device = nil

-- parse mfilm.cfg: "key=value" lines; "film=key|Display name" repeated
function M.parse_cfg(s)
  local cfg = {films = {}}
  for line in string.gmatch(s or "", "[^\r\n]+") do
    local k, v = string.match(line, "^%s*([%w_]+)%s*=%s*(.-)%s*$")
    if k == "film" then
      local key, rest = string.match(v, "^([^|]+)|(.*)$")
      if key then
        local name, short = string.match(rest, "^([^|]*)|(.*)$")
        cfg.films[#cfg.films + 1] = {key = key, name = name or rest, short = short or key}
      end
    elseif k then
      cfg[k] = v
    end
  end
  return cfg
end

function M.init()
  M.mkdirs(M.ROOT .. "/CONFIG")
  M.mkdirs(M.ROOT .. "/ROLLS")
  M.mkdirs(M.ROOT .. "/LOGS")
  M.cfg = M.parse_cfg(M.read(M.ROOT .. "/CONFIG/MFILM.CFG"))
  if M.cfg.utc_offset and string.match(M.cfg.utc_offset, "^[+-]%d%d:%d%d$") then M.utc_offset = M.cfg.utc_offset end
  local cdir = M.ROOT .. "/CONFIG"
  local dev = M.load(cdir, "DEVICE")
  if not dev or not dev.device_id then
    -- 0.1.0-alpha kept it in device.cfg (written once, readable)
    local s = M.read(cdir .. "/DEVICE.CFG")
    local f = s and loadstring(s)
    local ok, t = false, nil
    if f then ok, t = pcall(f) end
    if ok and type(t) == "table" and t.device_id then dev = t
    else dev = {device_id = "sx510hs-" .. string.sub(M.uuid(), 1, 8), created_at = M.now_iso()} end
    M.save(cdir, "DEVICE", dev)
    M.log("device id " .. dev.device_id)
  end
  M.device = dev
  local problems = {}
  if not M.cfg.profile_bundle_hash or not string.match(M.cfg.profile_bundle_hash, "^%x+$")
     or string.len(M.cfg.profile_bundle_hash) ~= 64 then
    problems[#problems + 1] = "CONFIG/mfilm.cfg: no profile_bundle_hash"
  end
  if #M.cfg.films == 0 then problems[#problems + 1] = "CONFIG/mfilm.cfg: no films" end
  return problems
end

function M.film_name(key)
  for _, f in ipairs(M.cfg.films) do
    if f.key == key then return f.name end
  end
  return key
end

function M.film_short(key)
  for _, f in ipairs(M.cfg.films) do
    if f.key == key then return f.short or key end
  end
  return key
end

-- ------------------------------------------------------------------ rolls

-- the roll's directory: 8 upper-case hex digits (8.3), the full roll_id is inside
function M.roll_dir(r) return M.ROOT .. "/ROLLS/" .. r.dir end

function M.manifest(r)
  local frames = {}
  for _, fr in ipairs(r.frames) do
    frames[#frames + 1] = {obj = {
      {"frame_id", fr.frame_id}, {"ordinal", fr.ordinal}, {"captured_at", fr.captured_at},
      {"source_path", fr.path}, {"source_size_bytes", fr.size}, {"original_status", "WRITTEN"}}}
  end
  return M.json({obj = {
    {"schema_version", 1}, {"kind", "mfilm.roll_manifest"}, {"device_id", r.device_id},
    {"roll_id", r.roll_id}, {"roll_state", r.state}, {"roll_length", r.length},
    {"captured_frames", #r.frames}, {"film_profile_id", r.film}, {"profile_bundle_hash", r.bundle},
    {"created_at", r.created_at}, {"sealed_at", r.sealed_at}, {"frames", frames}}}) .. "\n"
end

-- state first, then manifest: on restart the state is the truth and the
-- manifest is regenerated from it
-- the state (two copies) is the truth; the manifest is written after it and
-- rewritten from it on every start, so a torn manifest heals itself
function M.write_manifest(r)
  local ok, err = write_plain(M.roll_dir(r) .. "/MANIFEST.JSN", M.manifest(r))
  if not ok then M.log("ERROR saving manifest " .. r.roll_id .. ": " .. tostring(err)) end
  return ok, err
end

function M.save_roll(r)
  local ok, err = M.save(M.roll_dir(r), "STATE", r)
  if not ok then M.log("ERROR saving state " .. r.roll_id .. ": " .. tostring(err)) return nil, err end
  return M.write_manifest(r)
end

function M.journal(r, line) M.append(M.roll_dir(r) .. "/JOURNAL.LOG", M.now_iso() .. " " .. line) end

function M.load_roll(dir)
  local r = M.load(M.ROOT .. "/ROLLS/" .. dir, "STATE")
  if not r or not r.roll_id then return nil, "no state in " .. dir end
  r.dir = dir
  return r
end

function M.active_roll()
  local a = M.load(M.ROOT .. "/CONFIG", "ACTIVE")
  if not a or not a.dir then return nil end
  local r, err = M.load_roll(a.dir)
  if not r then M.log("active roll " .. a.dir .. " unreadable: " .. tostring(err)) return nil end
  M.write_manifest(r)
  return r
end

function M.set_active(r)
  M.save(M.ROOT .. "/CONFIG", "ACTIVE", {dir = r and r.dir or false})
end

function M.new_roll(film, length)
  local ok_len = false
  for _, l in ipairs(M.LENGTHS) do if l == length then ok_len = true end end
  if not ok_len then return nil, "bad length" end
  local id, dir
  for _ = 1, 20 do
    id = M.uuid()
    dir = string.upper(string.sub(id, 1, 8))
    if not M.exists(M.ROOT .. "/ROLLS/" .. dir) then break end
  end
  local r = {roll_id = id, dir = dir, device_id = M.device.device_id, film = film,
             bundle = M.cfg.profile_bundle_hash, length = length, state = "LOADED", created_at = M.now_iso(),
             frames = {}, app = M.VERSION}
  M.mkdirs(M.roll_dir(r))
  local ok, err = M.save_roll(r)
  if not ok then return nil, err end
  M.set_active(r)
  M.journal(r, "LOADED film=" .. film .. " length=" .. length)
  M.log("roll " .. r.roll_id .. " loaded: " .. film .. " x" .. length)
  return r
end

function M.seal(r, why)
  if r.state == "SEALED" then return true end
  r.state = "SEALED"
  r.sealed_at = M.now_iso()
  local ok, err = M.save_roll(r)
  M.journal(r, "SEALED frames=" .. #r.frames .. " (" .. (why or "") .. ")")
  M.log("roll " .. r.roll_id .. " sealed with " .. #r.frames .. " frame(s): " .. (why or ""))
  M.set_active(nil)
  return ok, err
end

function M.has_path(r, path)
  for _, fr in ipairs(r.frames) do
    if fr.path == path then return fr end
  end
  return nil
end

-- record one DNG as the next frame; returns the frame or nil, reason
function M.add_frame(r, path, size, mtime)
  if r.state == "SEALED" then return nil, "sealed" end
  if #r.frames >= r.length then return nil, "full" end
  local old = M.has_path(r, path)
  if old then return nil, "already on the roll" end
  local n = #r.frames + 1
  local fr = {frame_id = string.format("%s-%04d", r.roll_id, n), ordinal = n, path = path, size = size,
              mtime = mtime or 0, captured_at = M.now_iso()}
  r.frames[n] = fr
  r.state = "CAPTURING"
  local ok, err = M.save_roll(r)
  M.journal(r, string.format("FRAME %d %s %d", n, path, size))
  if not ok then return nil, err end
  return fr
end

function M.list_rolls()
  local out = {}
  local names = os.listdir(M.ROOT .. "/ROLLS") or {}
  table.sort(names)
  for _, dir in ipairs(names) do
    if string.match(dir, "^%x%x%x%x%x%x%x%x$") then     -- 8.3 roll dirs only (0.1.0 left long names)
      local r = M.load_roll(dir)
      if r then out[#out + 1] = r end
    end
  end
  table.sort(out, function(a, b) return (a.created_at or "") > (b.created_at or "") end)
  return out
end

-- ------------------------------------------------------------------ frame detection

-- DNGs in a directory: {name = size}
function M.dngs(dir)
  local out = {}
  if not dir then return out end
  for _, n in ipairs(os.listdir(dir) or {}) do
    if string.match(string.upper(n), "%.DNG$") then
      local st = stat(dir .. "/" .. n)
      if st and not st.is_dir then out[n] = st end
    end
  end
  return out
end

-- Watches the camera's image directories for DNGs that were not there
-- before. CRW numbers can lag the JPEG counter and DCIM folders roll over,
-- so a frame is "a DNG path not seen before", never a number we compute.
function M.watcher(image_dir)
  local w = {seen = {}, dirs = {}}
  function w.mark_dir(dir)
    if not dir or w.dirs[dir] then return end
    w.dirs[dir] = true
    for n, st in pairs(M.dngs(dir)) do w.seen[dir .. "/" .. n] = st.size end
  end
  -- new, size-stable DNGs since the last call: list of {path, size, mtime}, sorted by name
  function w.poll(dir)
    local found = {}
    if dir and not w.dirs[dir] then w.dirs[dir] = true end   -- a new folder: everything in it is new
    for d in pairs(w.dirs) do
      for n, st in pairs(M.dngs(d)) do
        local p = d .. "/" .. n
        local prev = w.seen[p]
        if prev == nil then
          w.seen[p] = -st.size            -- first sighting: negative = size not confirmed yet
        elseif prev < 0 then
          if -prev == st.size and st.size > 0 then
            w.seen[p] = st.size
            found[#found + 1] = {path = p, size = st.size, mtime = st.mtime}
          else
            w.seen[p] = -st.size
          end
        elseif prev ~= st.size then       -- a known DNG changed: overwritten by a later shot?
          w.seen[p] = st.size
          found[#found + 1] = {path = p, size = st.size, mtime = st.mtime, changed = true}
        end
      end
    end
    table.sort(found, function(a, b) return a.path < b.path end)
    return found
  end
  w.mark_dir(image_dir)
  return w
end

return M
