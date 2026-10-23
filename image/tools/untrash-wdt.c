/*
 * untrash-wdt - keeps the LS1024A hardware watchdog (17 s maximum) fed.
 *
 * systemd's own RuntimeWatchdogSec is not enough: systemd does not feed the
 * watchdog while PID 1 is busy with a daemon-reload, and under load (media
 * scan, ffprobe, disk wake-up) a reload can take longer than 15 s.  This
 * keeper runs with real-time priority and locked memory, so it keeps feeding
 * as long as the kernel schedules anything.
 *
 * It still guards the system: every CHECK_S it asks systemd for a trivial
 * property ("systemctl show -p Version"); when systemd has not answered for
 * DEAD_S, the keeper stops feeding and the watchdog resets the NAS.
 *
 * SIGTERM: exit WITHOUT the magic close, so the watchdog stays armed; at the
 * end of a shutdown systemd-shutdown takes over (RebootWatchdogSec).
 * Messages go to /dev/kmsg (prefix untrash-wdt:), so the blackbox sees them.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/watchdog.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static int FEED_S = 3, CHECK_S = 30, CHECK_TIMEOUT_S = 60, DEAD_S = 300;

static volatile sig_atomic_t stop;

static void on_term(int s) { (void)s; stop = 1; }

static void klog(const char *fmt, ...)
{
	char b[200];
	va_list ap;
	int n = snprintf(b, sizeof b, "untrash-wdt: ");
	va_start(ap, fmt);
	vsnprintf(b + n, sizeof b - n, fmt, ap);
	va_end(ap);
	int fd = open("/dev/kmsg", O_WRONLY | O_CLOEXEC);
	if (fd >= 0) {
		if (write(fd, b, strlen(b)) < 0) { /* nothing to do */ }
		close(fd);
	}
	fprintf(stderr, "%s\n", b);
}

static double now(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

int main(int argc, char **argv)
{
	const char *dev = argc > 1 ? argv[1] : "/dev/watchdog";
	const char *probe = getenv("ZT_WDT_PROBE");	/* tests: command instead of systemctl */
	if (getenv("ZT_WDT_TIMES"))			/* tests: "feed check timeout dead" in seconds */
		sscanf(getenv("ZT_WDT_TIMES"), "%d %d %d %d", &FEED_S, &CHECK_S, &CHECK_TIMEOUT_S, &DEAD_S);
	int fd = -1;

	for (int i = 0; i < 50 && fd < 0; i++) {	/* untrash-init's feeder may still close it */
		fd = open(dev, O_WRONLY | O_CLOEXEC);
		if (fd < 0 && errno != EBUSY)
			break;
		if (fd < 0)
			usleep(200000);
	}
	if (fd < 0) {
		klog("cannot open %s: %s", dev, strerror(errno));
		return 1;
	}
	struct sched_param sp = { .sched_priority = 50 };
	if (sched_setscheduler(0, SCHED_FIFO, &sp))
		klog("no real-time priority: %s", strerror(errno));
	mlockall(MCL_CURRENT | MCL_FUTURE);
	struct sigaction sa = { .sa_handler = on_term };
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);
	signal(SIGCHLD, SIG_DFL);
	klog("feeding %s every %d s (systemd check every %d s, gives up after %d s)", dev, FEED_S, CHECK_S, DEAD_S);

	double last_ok = now(), next_check = now() + CHECK_S, started = 0;
	pid_t child = 0;
	int feeding = 1;
	while (!stop) {
		if (feeding && (ioctl(fd, WDIOC_KEEPALIVE, 0) < 0 && write(fd, "x", 1) < 0))
			klog("feed failed: %s", strerror(errno));
		double t = now();
		if (child) {	/* liveness probe running */
			int st;
			pid_t r = waitpid(child, &st, WNOHANG);
			if (r == child) {
				if (WIFEXITED(st) && WEXITSTATUS(st) == 0)
					last_ok = t;
				child = 0;
			} else if (t - started > CHECK_TIMEOUT_S) {
				kill(child, SIGKILL);
				waitpid(child, &st, 0);
				child = 0;
			}
		} else if (t >= next_check) {
			next_check = t + CHECK_S;
			started = t;
			child = fork();
			if (child == 0) {
				struct sched_param np = { .sched_priority = 0 };
				sched_setscheduler(0, SCHED_OTHER, &np);
				int nul = open("/dev/null", O_RDWR);
				dup2(nul, 1);
				dup2(nul, 2);
				if (probe)
					execl("/bin/sh", "sh", "-c", probe, (char *)NULL);
				else
					execl("/usr/bin/systemctl", "systemctl", "show", "-p", "Version", "--value", (char *)NULL);
				_exit(127);
			}
			if (child < 0)
				child = 0;
		}
		if (feeding && t - last_ok > DEAD_S) {
			klog("systemd has not answered for %d s: no more feeding, the watchdog will reset the NAS", DEAD_S);
			feeding = 0;
		}
		sleep(FEED_S);
	}
	/* no magic close: the watchdog stays armed for systemd-shutdown */
	klog("stopped (watchdog stays armed)");
	return 0;
}
