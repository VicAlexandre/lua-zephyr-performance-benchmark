#include <lauxlib.h>
#include <lua.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/sys_heap.h>

#include "bench.h"
#include "tasks_lua_bytecode.h"

#define MAX_HEAPS 32

struct heap_slot {
	const char *name;
	struct sys_heap *heap;
	lua_Alloc alloc;
	void *ud;
	uint32_t alloc_fail;
};

static struct heap_slot heaps[MAX_HEAPS];
static atomic_t heap_count;

static void *counting_alloc(void *ud, void *ptr, size_t osize, size_t nsize)
{
	struct heap_slot *slot = ud;
	void *res = slot->alloc(slot->ud, ptr, osize, nsize);

	if (res == NULL && nsize > 0) {
		slot->alloc_fail++;
	}
	return res;
}

void bench_heap_dump(void)
{
	size_t n = MIN((size_t)atomic_get(&heap_count), ARRAY_SIZE(heaps));

	for (size_t i = 0; i < n; i++) {
		struct sys_memory_stats st = {0};

		sys_heap_runtime_stats_get(heaps[i].heap, &st);
		printk("#HEAP name=%s size=%zu peak=%zu alloc_fail=%u\n", heaps[i].name,
		       st.free_bytes + st.allocated_bytes, st.max_allocated_bytes,
		       heaps[i].alloc_fail);
	}
}

static int l_t1(lua_State *L)
{
	uint32_t c = bench_cycles();

	bench_record(BENCH_T1, (int)luaL_checkinteger(L, 1), (uint32_t)luaL_checkinteger(L, 2), c);
	return 0;
}

static int l_t2(lua_State *L)
{
	uint32_t c = bench_cycles();

	bench_record(BENCH_T2, (int)luaL_checkinteger(L, 1), (uint32_t)luaL_checkinteger(L, 2), c);
	return 0;
}

static int l_tick(lua_State *L)
{
	ARG_UNUSED(L);
	bench_tick(bench_cycles());
	return 0;
}

static int l_ready(lua_State *L)
{
	ARG_UNUSED(L);
	bench_ready();
	return 0;
}

static int l_cycles(lua_State *L)
{
	lua_pushinteger(L, (lua_Integer)bench_cycles());
	return 1;
}

static int l_elapsed(lua_State *L)
{
	uint32_t a = (uint32_t)luaL_checkinteger(L, 1);
	uint32_t b = (uint32_t)luaL_checkinteger(L, 2);

	lua_pushinteger(L, (lua_Integer)(b - a));
	return 1;
}

static int l_hz(lua_State *L)
{
	lua_pushinteger(L, (lua_Integer)bench_hz());
	return 1;
}

static int l_mark(lua_State *L)
{
	uint32_t c = bench_cycles();

	bench_diag((int)luaL_checkinteger(L, 1), (int)luaL_checkinteger(L, 2),
		   (uint32_t)luaL_checkinteger(L, 3), c);
	return 0;
}

static int l_diag_cols(lua_State *L)
{
	lua_pushboolean(L, IS_ENABLED(CONFIG_BENCH_DIAG_COLS));
	return 1;
}

static int l_gc_mark(lua_State *L)
{
	ARG_UNUSED(L);
	bench_gc_mark(bench_cycles());
	return 0;
}

static int l_diag_gc(lua_State *L)
{
	lua_pushboolean(L, IS_ENABLED(CONFIG_BENCH_DIAG_GC));
	return 1;
}

static int l_dump(lua_State *L)
{
	ARG_UNUSED(L);
	bench_dump();
	return 0;
}

static const luaL_Reg bench_funcs[] = {
	{"t1", l_t1},         {"t2", l_t2},           {"tick", l_tick}, {"ready", l_ready},
	{"cycles", l_cycles}, {"elapsed", l_elapsed}, {"hz", l_hz},     {"dump", l_dump},
	{"gc_mark", l_gc_mark}, {"diag_gc", l_diag_gc}, {"mark", l_mark}, {"diag_cols", l_diag_cols},
	{NULL, NULL},
};

static int open_bench(lua_State *L)
{
	luaL_newlib(L, bench_funcs);
	return 1;
}

static int open_tasks(lua_State *L)
{
	if (luaL_loadbuffer(L, (const char *)tasks_lua_bytecode, tasks_lua_bytecode_len, "tasks") !=
	    LUA_OK) {
		return lua_error(L);
	}
	lua_call(L, 0, 1);
	return 1;
}

int bench_lua_setup(lua_State *L, const char *name)
{
	atomic_val_t i = atomic_inc(&heap_count);

	if (i < ARRAY_SIZE(heaps)) {
		struct heap_slot *slot = &heaps[i];

		slot->name = name;
		slot->alloc = lua_getallocf(L, &slot->ud);
		slot->heap = slot->ud;
		lua_setallocf(L, counting_alloc, slot);
	}

	luaL_getsubtable(L, LUA_REGISTRYINDEX, LUA_PRELOAD_TABLE);
	lua_pushcfunction(L, open_bench);
	lua_setfield(L, -2, "bench");
	lua_pushcfunction(L, open_tasks);
	lua_setfield(L, -2, "tasks");
	lua_pop(L, 1);

	return 0;
}
