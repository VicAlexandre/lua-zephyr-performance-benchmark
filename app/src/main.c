#include <zephyr/kernel.h>
#include <zephyr/version.h>

int main(void)
{
	printk("#BOOT zephyr=%s board=%s\n", KERNEL_VERSION_STRING, CONFIG_BOARD_TARGET);
	return 0;
}
