local z = require("zephyr")
local zbus = z.zbus
local bench = require("bench")

local M = {}

local cfg
local chan_tlm
local tlm_data

local function ops_mt()
	return {
		source = zbus.observer_declare,
		wait = function(obs)
			local _, _, msg = obs:wait_msg(z.K_FOREVER)
			return msg
		end,
		pub = function(chan, t) return chan:pub(t, z.K_FOREVER) end,
		read = function(chan)
			local _, t = chan:read(z.K_FOREVER)
			return t
		end,
		yield = function() z.msleep(0) end,
	}
end

local function ops_mc()
	local async = require("zephyr.async")
	return {
		source = zbus.channel_declare,
		wait = function(chan) return chan:await() end,
		pub = function(chan, t) return chan:pub_async(t) end,
		read = function(chan) return chan:read_async() end,
		yield = function() async.sleep(0) end,
	}
end

local cycles_per_us = bench.hz() // 1000000

local function work(us)
	local target = us * cycles_per_us
	local start = bench.cycles()
	local x = 0
	repeat
		for i = 1, 8 do
			x = x + i
		end
	until bench.elapsed(start, bench.cycles()) >= target
	return x
end

local function alloc(bytes)
	local t = {}
	for i = 1, bytes // cfg.slot_bytes do
		t[i] = i
	end
	return t
end

local diag_cols = bench.diag_cols()

local function body(arch, id, c, msg, ops)
	if arch == "t5" then
		for _ = 1, cfg.t5_pubs do
			ops.pub(chan_tlm, { seq = msg.seq, data = tlm_data })
		end
	elseif diag_cols then
		bench.mark(2, id, msg.seq)
		work(c.c_us)
		bench.mark(3, id, msg.seq)
	else
		work(c.c_us)
	end
	alloc(c.m_bytes)
end

local function gc_sentinel()
	setmetatable({}, { __gc = function()
		bench.gc_mark()
		gc_sentinel()
	end })
end

function M.run(model, arch, id, source)
	local ops = model == "mt" and ops_mt() or ops_mc()

	if cfg == nil then
		cfg = ops.read(zbus.channel_declare("chan_cfg"))
		chan_tlm = zbus.channel_declare("chan_tlm")
		tlm_data = ""
		for _ = 1, cfg.t5.p_bytes - 1 do
			tlm_data = tlm_data .. "x"
		end
	end

	if id == cfg.measured then
		if bench.diag_gc() then
			gc_sentinel()
		end
		for _ = 1, 16 do
			bench.tick() bench.tick()
		end
	end

	if arch == "t2bg" then
		bench.ready()
		while true do
			work(cfg.slice_us)
			ops.yield()
		end
	end

	local c = cfg[arch]
	local src = ops.source(source)
	bench.ready()
	while true do
		local msg = ops.wait(src)
		bench.t1(id, msg.seq)
		body(arch, id, c, msg, ops)
		bench.t2(id, msg.seq)
	end
end

return M
