/* zt-sig -- Ed25519 signatures for UntrashOS slot manifests (TweetNaCl).
 *
 *   zt-sig keygen SECRET PUBLIC      (PC only) 64-byte secret, 32-byte public key
 *   zt-sig sign SECRET FILE SIG      (PC only) detached 64-byte signature
 *   zt-sig verify PUBLIC FILE SIG    exit 0 = valid, 1 = invalid, 2 = usage/IO
 *
 * Only small files (manifests) are signed; payloads are bound to the manifest
 * by their SHA-256.  Third-party code: third_party/tweetnacl (public domain).
 */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "tweetnacl.h"

#define MAX_FILE (1 << 20)

void randombytes(unsigned char *buf, unsigned long long n)
{
	int fd = open("/dev/urandom", O_RDONLY);

	if (fd < 0 || read(fd, buf, n) != (ssize_t)n)
		abort();
	close(fd);
}

static unsigned char *slurp(const char *path, unsigned long long *len)
{
	struct stat st;
	unsigned char *b;
	int fd = open(path, O_RDONLY);

	if (fd < 0 || fstat(fd, &st) || st.st_size > MAX_FILE)
		return NULL;
	b = malloc(st.st_size + 64);
	if (!b || read(fd, b + 64, st.st_size) != st.st_size)
		return NULL;
	close(fd);
	*len = st.st_size;
	return b;
}

static int spit(const char *path, const unsigned char *b, size_t n, int mode)
{
	int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, mode);

	if (fd < 0 || write(fd, b, n) != (ssize_t)n)
		return -1;
	return close(fd);
}

int main(int argc, char **argv)
{
	unsigned char pk[32], sk[64], *m, *sm, *out;
	unsigned long long n, smlen, mlen;

	if (argc == 4 && !strcmp(argv[1], "keygen")) {
		crypto_sign_keypair(pk, sk);
		return spit(argv[2], sk, 64, 0600) || spit(argv[3], pk, 32, 0644) ? 2 : 0;
	}
	if (argc != 5)
		return fprintf(stderr, "usage: zt-sig keygen|sign|verify ...\n"), 2;
	if (!(m = slurp(argv[3], &n)))
		return fprintf(stderr, "cannot read %s\n", argv[3]), 2;
	if (!strcmp(argv[1], "sign")) {
		int fd = open(argv[2], O_RDONLY);

		if (fd < 0 || read(fd, sk, 64) != 64)
			return 2;
		sm = malloc(n + 64);
		crypto_sign(sm, &smlen, m + 64, n, sk);
		return spit(argv[4], sm, 64, 0644) ? 2 : 0;	/* sig = first 64 bytes */
	}
	if (!strcmp(argv[1], "verify")) {
		int fd = open(argv[2], O_RDONLY), fs = open(argv[4], O_RDONLY);

		if (fd < 0 || read(fd, pk, 32) != 32 || fs < 0 || read(fs, m, 64) != 64)
			return 2;
		out = malloc(n + 64);
		if (crypto_sign_open(out, &mlen, m, n + 64, pk)) {
			puts("INVALID");
			return 1;
		}
		puts("VALID");
		return 0;
	}
	return 2;
}
