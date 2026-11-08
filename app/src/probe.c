#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>

#include "bench.h"

#define TICK_PAIRS 32

static uint32_t samples[3][BENCH_TOTAL];
static uint32_t ticks[2 * TICK_PAIRS];
static atomic_t tick_count;

K_SEM_DEFINE(ready_sem, 0, K_SEM_MAX_LIMIT);

#define GC_MARKS 512
static uint32_t gc_cycles[GC_MARKS];
static uint32_t gc_seq[GC_MARKS];
static atomic_t gc_count;
static uint32_t last_seq = UINT32_MAX;

#ifdef CONFIG_BENCH_DIAG_COLS
static uint32_t diag[4][BENCH_TOTAL];
#endif

void bench_diag(int col, int task, uint32_t seq, uint32_t cycles)
{
#ifdef CONFIG_BENCH_DIAG_COLS
	if (task == CONFIG_BENCH_MEASURED_TASK && seq < BENCH_TOTAL && col >= 0 && col < 4) {
		diag[col][seq] = cycles;
	}
#else
	ARG_UNUSED(col);
	ARG_UNUSED(task);
	ARG_UNUSED(seq);
	ARG_UNUSED(cycles);
#endif
}

static int probe_init(void)
{
	DCB->DEMCR |= DCB_DEMCR_TRCENA_Msk;
	DWT->CYCCNT = 0;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
	return 0;
}

SYS_INIT(probe_init, PRE_KERNEL_1, 0);

uint32_t bench_hz(void)
{
	return sys_clock_hw_cycles_per_sec();
}

void bench_record(enum bench_point point, int task, uint32_t seq, uint32_t cycles)
{
	if (task != CONFIG_BENCH_MEASURED_TASK || seq >= BENCH_TOTAL) {
		return;
	}
	samples[point][seq] = cycles;
	if (point == BENCH_T1) {
		last_seq = seq;
	}
}

void bench_gc_mark(uint32_t cycles)
{
	atomic_val_t i = atomic_inc(&gc_count);

	if (i < GC_MARKS) {
		gc_cycles[i] = cycles;
		gc_seq[i] = last_seq;
	}
}

void bench_tick(uint32_t cycles)
{
	atomic_val_t i = atomic_inc(&tick_count);

	if (i < ARRAY_SIZE(ticks)) {
		ticks[i] = cycles;
	}
}

static uint32_t median(uint32_t *v, size_t n)
{
	for (size_t i = 1; i < n; i++) {
		uint32_t x = v[i];
		size_t j = i;

		while (j > 0 && v[j - 1] > x) {
			v[j] = v[j - 1];
			j--;
		}
		v[j] = x;
	}
	return n ? v[n / 2] : 0;
}

uint32_t bench_tick_median(void)
{
	size_t pairs = MIN((size_t)atomic_get(&tick_count), ARRAY_SIZE(ticks)) / 2;
	uint32_t d[TICK_PAIRS];

	for (size_t i = 0; i < pairs; i++) {
		d[i] = ticks[2 * i + 1] - ticks[2 * i];
	}
	return median(d, pairs);
}

uint32_t bench_probe_cost_c(void)
{
	uint32_t d[TICK_PAIRS];

	for (size_t i = 0; i < ARRAY_SIZE(d); i++) {
		uint32_t a = bench_cycles();
		uint32_t b = bench_cycles();

		d[i] = b - a;
	}
	return median(d, ARRAY_SIZE(d));
}

void bench_busy_us(uint32_t us)
{
	uint32_t start = bench_cycles();
	uint32_t span = (uint32_t)(((uint64_t)us * bench_hz()) / USEC_PER_SEC);

	while (bench_cycles() - start < span) {
	}
}

void bench_ready(void)
{
	k_sem_give(&ready_sem);
}

int bench_wait_ready(k_timeout_t timeout)
{
	for (int i = 0; i < CONFIG_BENCH_NTASKS; i++) {
		int err = k_sem_take(&ready_sem, timeout);

		if (err) {
			return err;
		}
	}
	return 0;
}

static const char *exp_name(void)
{
	return IS_ENABLED(CONFIG_BENCH_EXP_CAL) ? "CAL"
	       : IS_ENABLED(CONFIG_BENCH_EXP_A) ? "A"
	       : IS_ENABLED(CONFIG_BENCH_EXP_B) ? "B"
						: "C";
}

static const char *model_name(void)
{
	return IS_ENABLED(CONFIG_BENCH_MODEL_MT)   ? "MT"
	       : IS_ENABLED(CONFIG_BENCH_MODEL_MC) ? "MC"
	       : IS_ENABLED(CONFIG_BENCH_MODEL_BASE) ? "BASE"
						  : "NONE";
}

void bench_dump(void)
{
	printk("#BENCH exp=%s model=%s ntasks=%d seed=%d warmup=%d samples=%d hz=%u "
	       "payload_t4=%d slice_us=%d slot_bytes=%d\n",
	       exp_name(), model_name(), CONFIG_BENCH_NTASKS, CONFIG_BENCH_SEED,
	       CONFIG_BENCH_WARMUP, CONFIG_BENCH_SAMPLES, bench_hz(), CONFIG_BENCH_T4_P_BYTES,
	       CONFIG_BENCH_SLICE_US, CONFIG_BENCH_SLOT_BYTES);
	printk("#PROBE where=c cycles=%u\n", bench_probe_cost_c());
	if (atomic_get(&tick_count) >= 2) {
		printk("#PROBE where=lua cycles=%u\n", bench_tick_median());
	}
	bench_gen_dump();
	bench_heap_dump();
	for (size_t i = 0; i < MIN((size_t)atomic_get(&gc_count), GC_MARKS); i++) {
		printk("#GC after_seq=%d cycles=%u\n", (int)gc_seq[i], gc_cycles[i]);
	}

	if (CONFIG_BENCH_MEASURED_TASK != 0) {
#ifdef CONFIG_BENCH_DIAG_COLS
		printk("seq,t0,t1,t2,d0,d1,d2,d3\n");
		for (uint32_t i = 0; i < BENCH_TOTAL; i++) {
			printk("%u,%u,%u,%u,%u,%u,%u,%u\n", i, samples[BENCH_T0][i],
			       samples[BENCH_T1][i], samples[BENCH_T2][i], diag[0][i], diag[1][i],
			       diag[2][i], diag[3][i]);
		}
#else
		printk("seq,t0,t1,t2\n");
		for (uint32_t i = 0; i < BENCH_TOTAL; i++) {
			printk("%u,%u,%u,%u\n", i, samples[BENCH_T0][i], samples[BENCH_T1][i],
			       samples[BENCH_T2][i]);
		}
#endif
	}
	printk("#END\n");
}
