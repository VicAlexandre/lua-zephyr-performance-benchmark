#include <zephyr/kernel.h>
#include <zephyr/zbus/zbus.h>

#include "bench.h"
#include "channels.h"

ZBUS_MSG_SUBSCRIBER_DEFINE(base_sub);
ZBUS_CHAN_ADD_OBS(chan_t4, base_sub, 3);

static void base_thread(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	const struct zbus_channel *chan;
	struct bench_act_t4 msg;

	bench_ready();
	while (true) {
		if (zbus_sub_wait_msg(&base_sub, &chan, &msg, K_FOREVER) != 0) {
			continue;
		}
		bench_record(BENCH_T1, 4, msg.seq, bench_cycles());
		bench_busy_us(CONFIG_BENCH_T4_C_US);
		bench_record(BENCH_T2, 4, msg.seq, bench_cycles());
	}
}

K_THREAD_DEFINE(bench_base, 2048, base_thread, NULL, NULL, NULL, CONFIG_LUA_THREAD_PRIORITY, 0, 0);
