/* One process, no interpreter/imports/DNS/children. Total I/O deadline: 2s. */
#include <arpa/inet.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static void expired(int sig) { (void)sig; _exit(1); }
int main(void) {
    const char request[] = "GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    const char expected[] = "{\"status\":\"ok\",\"mode\":\"read-only\",\"store\":\"memory\"}";
    char response[4097];
    size_t used = 0, sent = 0;
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons(8000)};
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    signal(SIGALRM, expired);
    signal(SIGPIPE, SIG_IGN);
    alarm(2);
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0 || connect(fd, (struct sockaddr *)&address, sizeof(address))) return 1;
    while (sent < sizeof(request)-1) {
        ssize_t n = send(fd, request+sent, sizeof(request)-1-sent, 0);
        if (n <= 0) { close(fd); return 1; }
        sent += (size_t)n;
    }
    for (;;) {
        ssize_t n = recv(fd, response+used, sizeof(response)-1-used, 0);
        if (n < 0) { close(fd); return 1; }
        if (n == 0) break;
        used += (size_t)n;
        if (used == sizeof(response)-1) { close(fd); return 1; }
    }
    close(fd);
    response[used] = '\0';
    char *body = strstr(response, "\r\n\r\n");
    int ok = (strncmp(response, "HTTP/1.1 200 ", 13) == 0 ||
              strncmp(response, "HTTP/1.0 200 ", 13) == 0) && body &&
             used - (size_t)(body+4-response) == sizeof(expected)-1 &&
             memcmp(body+4, expected, sizeof(expected)-1) == 0;
    if (!ok) fputs("health HTTP status/payload invalid\n", stderr);
    return ok ? 0 : 1;
}
