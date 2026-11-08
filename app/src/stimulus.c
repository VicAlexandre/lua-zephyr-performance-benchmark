#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/zbus/zbus.h>

#include "bench.h"
#include "channels.h"

struct gen_task {
	int id;
	const struct zbus_channel *chan;
	void *msg;
	size_t data_len;
	char *data;
	bool enabled;
	bool sporadic;
	uint32_t period_ms;
	uint32_t seq;
	k_ticks_t due;
};

#define GEN_MSG(n) static struct bench_act_t##n msg_t##n

GEN_MSG(1);
GEN_MSG(2);
GEN_MSG(3);
GEN_MSG(4);
GEN_MSG(5);
GEN_MSG(6);

#define GEN_TASK(n)                                                                                \
	{                                                                                          \
		.id = n, .chan = &chan_t##n, .msg = &msg_t##n,                                     \
		.data_len = sizeof(msg_t##n.data), .data = msg_t##n.data,                          \
		.enabled = IS_ENABLED(CONFIG_BENCH_T##n##_ENABLE),                                 \
		.sporadic = IS_ENABLED(CONFIG_BENCH_T##n##_SPORADIC),                              \
		.period_ms = CONFIG_BENCH_T##n##_PERIOD_MS,                                        \
	}

static struct gen_task tasks[] = {GEN_TASK(1), GEN_TASK(2), GEN_TASK(3),
				  GEN_TASK(4), GEN_TASK(5), GEN_TASK(6)};

static uint32_t rng_state = CONFIG_BENCH_SEED;

static struct gen_task *diag_pending;
static uint32_t diag_seq;
static uint32_t pub_errors;

static uint32_t rng_next(void)
{
	uint32_t x = rng_state;

	x ^= x << 13;
	x ^= x >> 17;
	x ^= x << 5;
	rng_state = x;
	return x;
}

static k_ticks_t interval(const struct gen_task *t)
{
	uint64_t min_us = (uint64_t)t->period_ms * USEC_PER_MSEC;

	if (!t->sporadic) {
		return k_us_to_ticks_near64(min_us);
	}
	return k_us_to_ticks_near64(min_us + (rng_next() % min_us));
}

static void publish(struct gen_task *t)
{
	uint32_t seq = t->seq++;

	*(uint32_t *)t->msg = seq;
	bench_record(BENCH_T0, t->id, seq, bench_cycles());
	if (zbus_chan_pub(t->chan, t->msg, K_MSEC(100)) != 0) {
		pub_errors++;
	}
	if (IS_ENABLED(CONFIG_BENCH_DIAG_COLS)) {
		bench_diag(0, t->id, seq, bench_cycles());
		diag_pending = t;
		diag_seq = seq;
	}
}

void bench_gen_dump(void)
{
	printk("#GEN pub_errors=%u", pub_errors);
	for (size_t i = 0; i < ARRAY_SIZE(tasks); i++) {
		if (tasks[i].enabled) {
			printk(" t%d=%u", tasks[i].id, tasks[i].seq);
		}
	}
	printk("\n");
}

static void gen_thread(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	if (IS_ENABLED(CONFIG_BENCH_EXP_CAL)) {
		return;
	}

	struct gen_task *measured = NULL;

	for (size_t i = 0; i < ARRAY_SIZE(tasks); i++) {
		struct gen_task *t = &tasks[i];

		memset(t->data, 'x', t->data_len - 1);
		t->data[t->data_len - 1] = '\0';
		if (t->enabled && t->id == CONFIG_BENCH_MEASURED_TASK) {
			measured = t;
		}
	}

	if (bench_wait_ready(K_SECONDS(30)) != 0) {
		printk("#ERROR ready timeout\n");
	}
	k_msleep(100);

	k_ticks_t start = k_uptime_ticks();
	k_ticks_t end = start + k_ms_to_ticks_ceil64(CONFIG_BENCH_RUN_MS);
	bool any = false;

	for (size_t i = 0; i < ARRAY_SIZE(tasks); i++) {
		struct gen_task *t = &tasks[i];

		any |= t->enabled;
		t->due = t->sporadic ? start + interval(t) : start;
	}

	while (any) {
		struct gen_task *next = NULL;

		for (size_t i = 0; i < ARRAY_SIZE(tasks); i++) {
			if (tasks[i].enabled && (next == NULL || tasks[i].due < next->due)) {
				next = &tasks[i];
			}
		}
		if (measured == NULL && next->due >= end) {
			break;
		}

		if (IS_ENABLED(CONFIG_BENCH_DIAG_COLS) && diag_pending != NULL) {
			bench_diag(1, diag_pending->id, diag_seq, bench_cycles());
			diag_pending = NULL;
		}
		k_sleep(K_TIMEOUT_ABS_TICKS(next->due));
		publish(next);
		next->due += interval(next);

		if (measured != NULL && measured->seq >= BENCH_TOTAL) {
			break;
		}
	}
	if (!any) {
		k_msleep(CONFIG_BENCH_RUN_MS);
	}

	k_msleep(MAX(1000, 3 * CONFIG_BENCH_SLICE_US / 1000));
	bench_dump();
}

K_THREAD_DEFINE(bench_gen, CONFIG_BENCH_GEN_STACK_SIZE, gen_thread, NULL, NULL, NULL,
		CONFIG_BENCH_GEN_PRIORITY, 0, 0);
