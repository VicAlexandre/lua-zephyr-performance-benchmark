#include <stdlib.h>
#include <string.h>

#include <cmsis_core.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/zbus/zbus.h>

#define XIP_CTRL_BASE 0x400c8000u
#define XIP_CTRL      (XIP_CTRL_BASE + 0x00)
#define XIP_CTR_HIT   (XIP_CTRL_BASE + 0x0c)
#define XIP_CTR_ACC   (XIP_CTRL_BASE + 0x10)

#define N 200

struct msg {
	uint32_t seq;
	char data[64];
};

ZBUS_CHAN_DEFINE(chan, struct msg, NULL, NULL, ZBUS_OBSERVERS_EMPTY, ZBUS_MSG_INIT(0));
ZBUS_MSG_SUBSCRIBER_DEFINE(sub);
ZBUS_CHAN_ADD_OBS(chan, sub, 3);

static const uint8_t flash_blob[64 * 1024] = {1};

struct meas {
	uint32_t cycles;
	uint32_t acc;
	uint32_t miss;
};

static struct msg m;
static struct meas res[4][N];

static void measure_pub(struct meas *out)
{
	sys_write32(0, XIP_CTR_HIT);
	sys_write32(0, XIP_CTR_ACC);
	uint32_t c0 = DWT->CYCCNT;

	m.seq++;
	(void)zbus_chan_pub(&chan, &m, K_MSEC(100));
	uint32_t c1 = DWT->CYCCNT;
	uint32_t hit = sys_read32(XIP_CTR_HIT);
	uint32_t acc = sys_read32(XIP_CTR_ACC);

	out->cycles = c1 - c0;
	out->acc = acc;
	out->miss = acc - hit;
}

static uint32_t evict(void)
{
	volatile const uint8_t *p = flash_blob;
	uint32_t sum = 0;

	for (size_t i = 0; i < sizeof(flash_blob); i += 8) {
		sum += p[i];
	}
	return sum;
}

static int cmp(const void *a, const void *b)
{
	uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;

	return (x > y) - (x < y);
}

static uint32_t median(int s, size_t field)
{
	uint32_t v[N];

	for (int i = 0; i < N; i++) {
		v[i] = ((uint32_t *)&res[s][i])[field];
	}
	qsort(v, N, sizeof(v[0]), cmp);
	return v[N / 2];
}

static void sub_thread(void *a, void *b, void *c)
{
	const struct zbus_channel *ch;
	struct msg in;

	while (true) {
		(void)zbus_sub_wait_msg(&sub, &ch, &in, K_FOREVER);
	}
}

K_THREAD_DEFINE(sub_tid, 1024, sub_thread, NULL, NULL, NULL, 7, 0, 0);

int main(void)
{
	static const char *const names[] = {"idle", "warm", "busy", "evicted"};
	uint32_t ctrl;

	DCB->DEMCR |= DCB_DEMCR_TRCENA_Msk;
	DWT->CYCCNT = 0;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
	memset(m.data, 'x', sizeof(m.data) - 1);

	k_msleep(500);
	ctrl = sys_read32(XIP_CTRL);
	printk("#BOOT xip_check\n");
	printk("#XIPCTRL ctrl=0x%08x en_secure=%d en_nonsecure=%d\n", ctrl, (ctrl & 1) != 0,
	       (ctrl & 2) != 0);

	for (int i = 0; i < N; i++) {
		k_msleep(15);
		measure_pub(&res[0][i]);
		measure_pub(&res[1][i]);
		k_busy_wait(15000);
		measure_pub(&res[2][i]);
		k_msleep(15);
		(void)evict();
		measure_pub(&res[3][i]);
	}

	for (int s = 0; s < 4; s++) {
		uint32_t cyc = median(s, 0);

		printk("#PUB case=%s cycles=%u us=%u.%u xip_acc=%u xip_miss=%u\n", names[s],
		       cyc, cyc / 150, (cyc % 150) * 10 / 150, median(s, 1), median(s, 2));
	}
	printk("#END\n");
	return 0;
}
