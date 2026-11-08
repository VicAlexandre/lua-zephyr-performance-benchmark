#include <cmsis_core.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/version.h>

#define PAIRS 64

static void dwt_enable(void)
{
	DCB->DEMCR |= DCB_DEMCR_TRCENA_Msk;
	DWT->CYCCNT = 0;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

static uint32_t probe_cost(void)
{
	uint32_t d[PAIRS];

	for (int i = 0; i < PAIRS; i++) {
		uint32_t a = DWT->CYCCNT;
		uint32_t b = DWT->CYCCNT;

		d[i] = b - a;
	}
	for (int i = 1; i < PAIRS; i++) {
		uint32_t x = d[i];
		int j = i;

		while (j > 0 && d[j - 1] > x) {
			d[j] = d[j - 1];
			j--;
		}
		d[j] = x;
	}
	return d[PAIRS / 2];
}

int main(void)
{
	uint32_t round = 0;

	printk("#BOOT zephyr=%s board=%s\n", KERNEL_VERSION_STRING, CONFIG_BOARD_TARGET);
	dwt_enable();

	while (true) {
		bool has_cyccnt = (DWT->CTRL & DWT_CTRL_NOCYCCNT_Msk) == 0;
		uint32_t c0 = DWT->CYCCNT;
		uint32_t c1 = DWT->CYCCNT;
		bool running = (c1 != c0);

		uint32_t a = DWT->CYCCNT;
		k_busy_wait(100000);
		uint32_t busy = DWT->CYCCNT - a;

		int64_t t0 = k_uptime_get();
		uint32_t k0 = k_cycle_get_32();
		a = DWT->CYCCNT;
		k_msleep(1000);
		uint32_t dwt = DWT->CYCCNT - a;
		uint32_t kcyc = k_cycle_get_32() - k0;
		int64_t ms = k_uptime_get() - t0;

		uint32_t hz_busy = busy * 10;
		uint32_t hz_sleep = (uint32_t)((uint64_t)dwt * 1000 / ms);

		printk("#DWT round=%u has_cyccnt=%d running=%d demcr_trcena=%d ctrl=0x%08x\n", round,
		       has_cyccnt, running, (DCB->DEMCR & DCB_DEMCR_TRCENA_Msk) != 0, DWT->CTRL);
		printk("#FREQ sys_hz=%u dwt_hz_busy=%u dwt_hz_sleep=%u kcycle_per_s=%u uptime_ms=%lld\n",
		       sys_clock_hw_cycles_per_sec(), hz_busy, hz_sleep,
		       (uint32_t)((uint64_t)kcyc * 1000 / ms), ms);
		printk("#PROBE pair_median_cycles=%u\n", probe_cost());
		printk("#VERDICT %s\n",
		       has_cyccnt && running &&
				       hz_sleep > sys_clock_hw_cycles_per_sec() / 100 * 99 &&
				       hz_sleep < sys_clock_hw_cycles_per_sec() / 100 * 101
			       ? "OK"
			       : "FAIL");
		round++;
	}
	return 0;
}
