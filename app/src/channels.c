#include <luaz_msg_descr.h>
#include <zephyr/zbus/zbus.h>

#include "channels.h"

#define ACT_FIELDS(n)                                                                              \
	static const struct lua_msg_field_descr act_t##n##_fields[] = {                            \
		LUA_MSG_FIELD(struct bench_act_t##n, seq, LUA_MSG_TYPE_UINT),                      \
		LUA_MSG_FIELD(struct bench_act_t##n, data, LUA_MSG_TYPE_STRING_BUF),               \
	}

ACT_FIELDS(1);
ACT_FIELDS(2);
ACT_FIELDS(3);
ACT_FIELDS(4);
ACT_FIELDS(5);
ACT_FIELDS(6);

#define ACT_CHAN(n)                                                                                \
	ZBUS_CHAN_DEFINE(chan_t##n, struct bench_act_t##n, NULL,                                   \
			 LUA_ZBUS_MSG_DESCR(struct bench_act_t##n, act_t##n##_fields),             \
			 ZBUS_OBSERVERS_EMPTY, ZBUS_MSG_INIT(0))

ACT_CHAN(1);
ACT_CHAN(2);
ACT_CHAN(3);
ACT_CHAN(4);
ACT_CHAN(5);
ACT_CHAN(6);

static const struct lua_msg_field_descr tlm_fields[] = {
	LUA_MSG_FIELD(struct bench_tlm, seq, LUA_MSG_TYPE_UINT),
	LUA_MSG_FIELD(struct bench_tlm, data, LUA_MSG_TYPE_STRING_BUF),
};

ZBUS_CHAN_DEFINE(chan_tlm, struct bench_tlm, NULL, LUA_ZBUS_MSG_DESCR(struct bench_tlm, tlm_fields),
		 ZBUS_OBSERVERS_EMPTY, ZBUS_MSG_INIT(0));

static const struct lua_msg_field_descr task_cfg_fields[] = {
	LUA_MSG_FIELD(struct bench_task_cfg, period_ms, LUA_MSG_TYPE_INT),
	LUA_MSG_FIELD(struct bench_task_cfg, c_us, LUA_MSG_TYPE_INT),
	LUA_MSG_FIELD(struct bench_task_cfg, m_bytes, LUA_MSG_TYPE_INT),
	LUA_MSG_FIELD(struct bench_task_cfg, p_bytes, LUA_MSG_TYPE_INT),
};

static const struct lua_msg_field_descr cfg_fields[] = {
	LUA_MSG_FIELD_OBJECT(struct bench_cfg, t1, task_cfg_fields),
	LUA_MSG_FIELD_OBJECT(struct bench_cfg, t2, task_cfg_fields),
	LUA_MSG_FIELD_OBJECT(struct bench_cfg, t3, task_cfg_fields),
	LUA_MSG_FIELD_OBJECT(struct bench_cfg, t4, task_cfg_fields),
	LUA_MSG_FIELD_OBJECT(struct bench_cfg, t5, task_cfg_fields),
	LUA_MSG_FIELD_OBJECT(struct bench_cfg, t6, task_cfg_fields),
	LUA_MSG_FIELD(struct bench_cfg, slot_bytes, LUA_MSG_TYPE_INT),
	LUA_MSG_FIELD(struct bench_cfg, slice_us, LUA_MSG_TYPE_INT),
	LUA_MSG_FIELD(struct bench_cfg, t5_pubs, LUA_MSG_TYPE_INT),
	LUA_MSG_FIELD(struct bench_cfg, measured, LUA_MSG_TYPE_INT),
};

#define TASK_CFG(n)                                                                                \
	{                                                                                          \
		.period_ms = CONFIG_BENCH_T##n##_PERIOD_MS, .c_us = CONFIG_BENCH_T##n##_C_US,      \
		.m_bytes = CONFIG_BENCH_T##n##_M_BYTES, .p_bytes = CONFIG_BENCH_T##n##_P_BYTES,    \
	}

ZBUS_CHAN_DEFINE(chan_cfg, struct bench_cfg, NULL, LUA_ZBUS_MSG_DESCR(struct bench_cfg, cfg_fields),
		 ZBUS_OBSERVERS_EMPTY,
		 ZBUS_MSG_INIT(.t1 = TASK_CFG(1), .t2 = TASK_CFG(2), .t3 = TASK_CFG(3),
			       .t4 = TASK_CFG(4), .t5 = TASK_CFG(5), .t6 = TASK_CFG(6),
			       .slot_bytes = CONFIG_BENCH_SLOT_BYTES,
			       .slice_us = CONFIG_BENCH_SLICE_US, .t5_pubs = CONFIG_BENCH_T5_PUBS,
			       .measured = CONFIG_BENCH_MEASURED_TASK));
