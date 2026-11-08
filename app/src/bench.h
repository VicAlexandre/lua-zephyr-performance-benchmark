#ifndef BENCH_H_
#define BENCH_H_

#include <stdint.h>
#include <zephyr/kernel.h>

#include <cmsis_core.h>

enum bench_point {
	BENCH_T0 = 0,
	BENCH_T1 = 1,
	BENCH_T2 = 2,
};

#define BENCH_TOTAL (CONFIG_BENCH_WARMUP + CONFIG_BENCH_SAMPLES)

static ALWAYS_INLINE uint32_t bench_cycles(void)
{
	return DWT->CYCCNT;
}

uint32_t bench_hz(void);

void bench_record(enum bench_point point, int task, uint32_t seq, uint32_t cycles);

void bench_tick(uint32_t cycles);

uint32_t bench_tick_median(void);

uint32_t bench_probe_cost_c(void);

void bench_busy_us(uint32_t us);

void bench_ready(void);

int bench_wait_ready(k_timeout_t timeout);

void bench_dump(void);

void bench_heap_dump(void);

void bench_diag(int col, int task, uint32_t seq, uint32_t cycles);

void bench_gc_mark(uint32_t cycles);

void bench_gen_dump(void);

#endif
