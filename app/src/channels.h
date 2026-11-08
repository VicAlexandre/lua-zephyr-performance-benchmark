#ifndef CHANNELS_H_
#define CHANNELS_H_

#include <stdint.h>
#include <zephyr/zbus/zbus.h>

#define BENCH_ACT_STRUCT(n)                                                                        \
	struct bench_act_t##n {                                                                    \
		uint32_t seq;                                                                      \
		char data[CONFIG_BENCH_T##n##_P_BYTES];                                            \
	}

BENCH_ACT_STRUCT(1);
BENCH_ACT_STRUCT(2);
BENCH_ACT_STRUCT(3);
BENCH_ACT_STRUCT(4);
BENCH_ACT_STRUCT(5);
BENCH_ACT_STRUCT(6);

struct bench_tlm {
	uint32_t seq;
	char data[CONFIG_BENCH_T5_P_BYTES];
};

struct bench_task_cfg {
	int32_t period_ms;
	int32_t c_us;
	int32_t m_bytes;
	int32_t p_bytes;
};

struct bench_cfg {
	struct bench_task_cfg t1, t2, t3, t4, t5, t6;
	int32_t slot_bytes;
	int32_t slice_us;
	int32_t t5_pubs;
	int32_t measured;
};

ZBUS_CHAN_DECLARE(chan_cfg, chan_t1, chan_t2, chan_t3, chan_t4, chan_t5, chan_t6, chan_tlm);

#endif
