/*
 * untrash-memd - proactive memory offloading ("felt RAM", v1.2).
 *
 * The NAS has 1 GB of RAM.  Memory is used in tiers: RAM -> zswap (lz4,
 * compressed in RAM) -> swap device.  Kernel 6.6 moves pages down a tier only
 * under pressure (and zswap writes back only when its pool is full), so cold
 * memory of idle services fills RAM until a burst of demand has to reclaim it
 * the slow way.  This daemon does what Meta's Senpai/TMO does: every
 * INTERVAL it asks each target cgroup (memory.reclaim) to give back a little
 * memory as long as the cgroup's memory pressure (PSI) stays below its
 * target, and backs off as soon as the pressure rises.  The pressure is the
 * measure of harm, so the controller settles where offloading stops costing.
 *
 * Targets (most aggressive first): untrash-background.slice, system.slice,
 * user.slice.  untrash-interactive.slice (Desk, shares, SSH) is never a
 * target; its memory.low protects it from the reclaim of its parents too.
 *
 * Proactive reclaim only runs where it is cheap:
 *   ssd    a non-rotational swap device with free space is active
 *   zswap  only rotational swap: allowed while the zswap pool is below
 *          ZSWAP_FILL of its limit (no disk spin-up for cold pages)
 *   off    no swap, or zswap full on rotational swap
 * A global brake stops all reclaim while the whole system stalls on memory
 * (/proc/pressure/memory).  vm.page-cluster follows the swap: 0 (single
 * pages) with an SSD, 3 (kernel default) otherwise.
 *
 * State for Untrash Desk: /run/untrash/memd.json, rewritten every round.
 * Without PSI or the memory controller (older kernel) it exits 0.
 *
 * Tests: ZT_MEMD_ROOT prefixes every path, ZT_MEMD_INTERVAL_MS sets the
 * round length (image/tests/test_memd_host.py).
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define MiB (1024ULL * 1024)
static const unsigned long long MAX_STEP = 16 * MiB, MIN_STEP = MiB / 4;
static const double ZSWAP_FILL = 0.8;
static const double BRAKE_SOME = 20000, BRAKE_FULL = 2000;	/* us stall per s */

static struct target {
	const char *name;
	double target;	/* allowed pressure, us stall per s (1000 = 0.1 %) */
	double ratio;	/* share of memory.current per round at zero pressure */
	unsigned long long prev, requested, reclaimed;
	int have_prev, present;
	double pressure;
} T[] = {
	{ .name = "untrash-background.slice", .target = 5000, .ratio = 0.010 },
	{ .name = "system.slice", .target = 1000, .ratio = 0.002 },
	{ .name = "user.slice", .target = 1000, .ratio = 0.002 },
};
#define NT (sizeof T / sizeof T[0])

static const char *root = "";
static volatile sig_atomic_t stop;

static void on_term(int s) { (void)s; stop = 1; }

static void say(const char *fmt, ...)
{
	va_list ap;
	fprintf(stderr, "untrash-memd: ");
	va_start(ap, fmt);
	vfprintf(stderr, fmt, ap);
	va_end(ap);
	fputc('\n', stderr);
}

static const char *P(char *b, size_t n, const char *fmt, ...)
{
	va_list ap;
	int k = snprintf(b, n, "%s", root);
	va_start(ap, fmt);
	vsnprintf(b + k, n - k, fmt, ap);
	va_end(ap);
	return b;
}

static int slurp(const char *path, char *buf, size_t n)
{
	int fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	ssize_t r = read(fd, buf, n - 1);
	close(fd);
	if (r < 0)
		return -1;
	buf[r] = 0;
	return 0;
}

/* sysfs, procfs and cgroupfs files: never created, truncated on write */
static int put(const char *path, const char *val)
{
	int fd = open(path, O_WRONLY | O_TRUNC | O_CLOEXEC);
	if (fd < 0)
		return -1;
	ssize_t r = write(fd, val, strlen(val));
	int e = errno;
	close(fd);
	errno = e;
	return r == (ssize_t)strlen(val) ? 0 : -1;
}

/* "some ... total=N" / "full ... total=N" of a PSI file */
static int psi_total(const char *path, const char *kind, unsigned long long *v)
{
	char b[512];
	if (slurp(path, b, sizeof b))
		return -1;
	size_t k = strlen(kind);
	for (char *l = b; *l; ) {
		char *e = strchr(l, '\n');
		if (e)
			*e = 0;
		char *t = strstr(l, "total=");
		if (!strncmp(l, kind, k) && t) {
			*v = strtoull(t + 6, NULL, 10);
			return 0;
		}
		if (!e)
			break;
		l = e + 1;
	}
	return -1;
}

static int read_ull(const char *path, unsigned long long *v)
{
	char b[64];
	if (slurp(path, b, sizeof b))
		return -1;
	*v = strtoull(b, NULL, 10);
	return 0;
}

/* value of "key N" in memory.stat or "Key: N kB" in /proc/meminfo */
static int keyed(const char *path, const char *key, unsigned long long *v)
{
	char b[8192];
	if (slurp(path, b, sizeof b))
		return -1;
	size_t k = strlen(key);
	for (char *l = b; *l; ) {
		if (!strncmp(l, key, k) && (l[k] == ' ' || l[k] == ':')) {
			*v = strtoull(l + k + 1, NULL, 10);
			return 0;
		}
		char *e = strchr(l, '\n');
		if (!e)
			break;
		l = e + 1;
	}
	return -1;
}

/* 1 = rotational, 0 = not, -1 = unknown; partitions ask their disk */
static int rotational(const char *dev)
{
	char b[PATH_MAX], real[PATH_MAX], q[PATH_MAX + 32], v[8];
	if (!realpath(P(b, sizeof b, "/sys/class/block/%s", dev), real))
		return -1;
	snprintf(q, sizeof q, "%s/queue/rotational", real);
	if (slurp(q, v, sizeof v)) {
		snprintf(q, sizeof q, "%s/../queue/rotational", real);
		if (slurp(q, v, sizeof v))
			return -1;
	}
	return v[0] == '0' ? 0 : 1;
}

enum mode { OFF, ZSWAP, SSD };
static const char *mode_name[] = { "off", "zswap", "ssd" };

struct swapinfo {
	enum mode mode;
	int any_swap, zswap_on;
	unsigned long long zswap_bytes, zswap_limit;
};

static void swap_state(struct swapinfo *s)
{
	char b[PATH_MAX], buf[4096];
	memset(s, 0, sizeof *s);
	if (!slurp(P(b, sizeof b, "/proc/swaps"), buf, sizeof buf)) {
		char *l = strchr(buf, '\n');	/* header */
		while (l && *++l) {
			char name[256], type[32];
			unsigned long long size, used;
			if (sscanf(l, "%255s %31s %llu %llu", name, type, &size, &used) == 4) {
				s->any_swap = 1;
				/* swap files: the backing disk is not resolved, count as slow */
				const char *base = strrchr(name, '/') ? strrchr(name, '/') + 1 : name;
				if (!strcmp(type, "partition") && rotational(base) == 0 && used < size * 9 / 10)
					s->mode = SSD;
			}
			l = strchr(l, '\n');
		}
	}
	char z[8];
	s->zswap_on = !slurp(P(b, sizeof b, "/sys/module/zswap/parameters/enabled"), z, sizeof z) && z[0] == 'Y';
	unsigned long long pct = 20, kb = 0;
	read_ull(P(b, sizeof b, "/sys/module/zswap/parameters/max_pool_percent"), &pct);
	keyed(P(b, sizeof b, "/proc/meminfo"), "MemTotal", &kb);
	s->zswap_limit = kb * 1024 / 100 * pct;
	keyed(P(b, sizeof b, "/sys/fs/cgroup/memory.stat"), "zswap", &s->zswap_bytes);
	if (s->mode != SSD && s->any_swap && s->zswap_on && s->zswap_bytes < s->zswap_limit * ZSWAP_FILL)
		s->mode = ZSWAP;
}

static double now(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

static void status(const struct swapinfo *s, double some, double full, int brake)
{
	char b[PATH_MAX], tmp[PATH_MAX + 8];
	mkdir(P(b, sizeof b, "/run/untrash"), 0755);
	P(b, sizeof b, "/run/untrash/memd.json");
	snprintf(tmp, sizeof tmp, "%s.tmp", b);
	FILE *f = fopen(tmp, "w");
	if (!f)
		return;
	fprintf(f, "{\"mode\": \"%s\", \"brake\": %s, \"pressure_some\": %.0f, \"pressure_full\": %.0f, "
		"\"zswap_bytes\": %llu, \"zswap_limit\": %llu, \"targets\": [",
		mode_name[s->mode], brake ? "true" : "false", some, full, s->zswap_bytes, s->zswap_limit);
	int first = 1;
	for (size_t i = 0; i < NT; i++) {
		if (!T[i].present)
			continue;
		fprintf(f, "%s{\"name\": \"%s\", \"pressure\": %.0f, \"requested\": %llu, \"reclaimed\": %llu}",
			first ? "" : ", ", T[i].name, T[i].pressure, T[i].requested, T[i].reclaimed);
		first = 0;
	}
	fprintf(f, "]}\n");
	if (fclose(f) == 0)
		rename(tmp, b);
}

int main(void)
{
	char b[PATH_MAX];
	if (getenv("ZT_MEMD_ROOT"))
		root = getenv("ZT_MEMD_ROOT");
	long interval_ms = getenv("ZT_MEMD_INTERVAL_MS") ? atol(getenv("ZT_MEMD_INTERVAL_MS")) : 6000;
	unsigned long long gsome, gfull;
	if (psi_total(P(b, sizeof b, "/proc/pressure/memory"), "some", &gsome) ||
	    access(P(b, sizeof b, "/sys/fs/cgroup/memory.stat"), R_OK)) {
		say("no memory PSI or memory cgroup in this kernel: nothing to do");
		return 0;
	}
	if (psi_total(P(b, sizeof b, "/proc/pressure/memory"), "full", &gfull))
		gfull = 0;
	mlockall(MCL_CURRENT | MCL_FUTURE);	/* the controller itself never swaps */
	struct sigaction sa = { .sa_handler = on_term };
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);
	say("running, round %ld ms", interval_ms);

	int last_mode = -1;
	int page_cluster = -1;
	double last = now();
	while (!stop) {
		struct timespec ts = { interval_ms / 1000, interval_ms % 1000 * 1000000L };
		while (nanosleep(&ts, &ts) && errno == EINTR && !stop)
			;
		if (stop)
			break;
		double t = now(), dt = t - last;
		last = t;
		if (dt <= 0)
			continue;

		struct swapinfo s;
		swap_state(&s);
		if ((int)s.mode != last_mode) {
			say("mode %s (zswap %s, %llu of %llu bytes)", mode_name[s.mode],
			    s.zswap_on ? "on" : "off", s.zswap_bytes, s.zswap_limit);
			last_mode = s.mode;
		}
		int pc = s.mode == SSD ? 0 : 3;
		if (pc != page_cluster && !put(P(b, sizeof b, "/proc/sys/vm/page-cluster"), pc ? "3" : "0"))
			page_cluster = pc;

		unsigned long long v;
		double some = 0, full = 0;
		if (!psi_total(P(b, sizeof b, "/proc/pressure/memory"), "some", &v)) {
			some = (v - gsome) / dt;
			gsome = v;
		}
		if (!psi_total(P(b, sizeof b, "/proc/pressure/memory"), "full", &v)) {
			full = (v - gfull) / dt;
			gfull = v;
		}
		int brake = some > BRAKE_SOME || full > BRAKE_FULL;

		for (size_t i = 0; i < NT; i++) {
			struct target *c = &T[i];
			unsigned long long tot, cur, after;
			if (psi_total(P(b, sizeof b, "/sys/fs/cgroup/%s/memory.pressure", c->name), "some", &tot) ||
			    read_ull(P(b, sizeof b, "/sys/fs/cgroup/%s/memory.current", c->name), &cur)) {
				c->present = c->have_prev = 0;
				continue;
			}
			c->present = 1;
			if (!c->have_prev) {
				c->prev = tot;
				c->have_prev = 1;
				continue;
			}
			if (tot < c->prev) {	/* slice was stopped and created again */
				c->prev = tot;
				continue;
			}
			c->pressure = (tot - c->prev) / dt;
			c->prev = tot;
			if (brake || s.mode == OFF || c->pressure >= c->target)
				continue;
			double step = cur * c->ratio * (1 - c->pressure / c->target);
			if (step > MAX_STEP)
				step = MAX_STEP;
			if (step < MIN_STEP)
				continue;
			char n[32];
			snprintf(n, sizeof n, "%llu", (unsigned long long)step);
			/* EAGAIN = less than asked was reclaimed: normal */
			if (put(P(b, sizeof b, "/sys/fs/cgroup/%s/memory.reclaim", c->name), n) && errno != EAGAIN)
				continue;
			c->requested += (unsigned long long)step;
			if (!read_ull(P(b, sizeof b, "/sys/fs/cgroup/%s/memory.current", c->name), &after) && after < cur)
				c->reclaimed += cur - after;
		}
		status(&s, some, full, brake);
	}
	say("stopped");
	return 0;
}
