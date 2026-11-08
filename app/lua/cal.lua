local z = require("zephyr")
local bench = require("bench")

for _ = 1, 16 do
	bench.tick() bench.tick()
end

local SLOTS = 1000
collectgarbage("collect")
collectgarbage("stop")
local m0 = collectgarbage("count")
local t = {}
for i = 1, SLOTS do
	t[i] = i
end
local m1 = collectgarbage("count")
collectgarbage("restart")
local bytes = ((m1 - m0) * 1024) // 1 | 0
z.printk("#CAL table slots=" .. SLOTS .. " bytes=" .. bytes)

bench.dump()
