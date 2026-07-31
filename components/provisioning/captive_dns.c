#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "esp_check.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"

#define DNS_PORT 53
#define DNS_MAX_LEN 256
#define DNS_REPLY_TTL_SEC 300
#define DNS_QR_FLAG 0x8000
#define DNS_OPCODE_MASK 0x7800
#define DNS_QTYPE_A 0x0001
#define DNS_QCLASS_IN 0x0001

static const char *TAG = "ancs_captive_dns";

typedef struct __attribute__((packed)) {
    uint16_t id;
    uint16_t flags;
    uint16_t qd_count;
    uint16_t an_count;
    uint16_t ns_count;
    uint16_t ar_count;
} dns_header_t;

typedef struct __attribute__((packed)) {
    uint16_t ptr_offset;
    uint16_t type;
    uint16_t class;
    uint32_t ttl;
    uint16_t addr_len;
    uint32_t ip_addr;
} dns_answer_t;

typedef struct {
    bool started;
    TaskHandle_t task;
    int sock;
    esp_netif_t *ap_netif;
} captive_dns_handle_t;

static captive_dns_handle_t s_dns;

static char *skip_dns_name(char *packet, char *end)
{
    char *label = packet;
    while (label < end && *label != 0) {
        uint8_t label_len = (uint8_t)*label;
        if ((label_len & 0xC0) != 0 || label + label_len + 1 >= end) {
            return NULL;
        }
        label += label_len + 1;
    }
    return label < end ? label + 1 : NULL;
}

static int build_wildcard_reply(char *request,
                                size_t request_len,
                                char *reply,
                                size_t reply_len,
                                esp_ip4_addr_t ap_ip)
{
    if (request_len < sizeof(dns_header_t) || request_len > reply_len) {
        return -1;
    }

    memset(reply, 0, reply_len);
    memcpy(reply, request, request_len);

    dns_header_t *header = (dns_header_t *)reply;
    if ((ntohs(header->flags) & DNS_OPCODE_MASK) != 0) {
        return 0;
    }

    uint16_t qd_count = ntohs(header->qd_count);
    if (qd_count != 1) {
        return 0;
    }

    char *packet_end = reply + request_len;
    char *question_start = reply + sizeof(dns_header_t);
    char *question_end = skip_dns_name(question_start, packet_end);
    if (question_end == NULL || question_end + 4 > packet_end) {
        return -1;
    }

    uint16_t qtype_raw = 0;
    uint16_t qclass_raw = 0;
    memcpy(&qtype_raw, question_end, sizeof(qtype_raw));
    memcpy(&qclass_raw, question_end + sizeof(qtype_raw), sizeof(qclass_raw));
    uint16_t qtype = ntohs(qtype_raw);
    uint16_t qclass = ntohs(qclass_raw);
    if (qtype != DNS_QTYPE_A || qclass != DNS_QCLASS_IN) {
        return 0;
    }

    size_t question_len = (size_t)(question_end + 4 - reply);
    size_t total_len = question_len + sizeof(dns_answer_t);
    if (total_len > reply_len) {
        return -1;
    }

    header->flags = htons(ntohs(header->flags) | DNS_QR_FLAG);
    header->qd_count = htons(1);
    header->an_count = htons(1);
    header->ns_count = 0;
    header->ar_count = 0;

    dns_answer_t *answer = (dns_answer_t *)(reply + question_len);
    answer->ptr_offset = htons(0xC000 | (question_start - reply));
    answer->type = htons(DNS_QTYPE_A);
    answer->class = htons(DNS_QCLASS_IN);
    answer->ttl = htonl(DNS_REPLY_TTL_SEC);
    answer->addr_len = htons(sizeof(ap_ip.addr));
    answer->ip_addr = ap_ip.addr;
    return (int)total_len;
}

static void captive_dns_task(void *arg)
{
    captive_dns_handle_t *handle = (captive_dns_handle_t *)arg;
    int sock = handle->sock;

    while (handle->started) {
        char request[128];
        char reply[DNS_MAX_LEN];
        struct sockaddr_storage source_addr;
        socklen_t source_len = sizeof(source_addr);
        int len = recvfrom(sock,
                           request,
                           sizeof(request),
                           0,
                           (struct sockaddr *)&source_addr,
                           &source_len);
        if (len < 0) {
            if (handle->started && errno != EWOULDBLOCK && errno != EAGAIN) {
                ESP_LOGW(TAG, "recvfrom failed errno=%d", errno);
                break;
            }
            continue;
        }

        esp_netif_ip_info_t ip_info = {0};
        if (esp_netif_get_ip_info(handle->ap_netif, &ip_info) != ESP_OK) {
            continue;
        }
        int reply_size = build_wildcard_reply(
            request, (size_t)len, reply, sizeof(reply), ip_info.ip);
        if (reply_size > 0) {
            (void)sendto(sock,
                         reply,
                         (size_t)reply_size,
                         0,
                         (struct sockaddr *)&source_addr,
                         source_len);
        }
    }

    shutdown(sock, 0);
    close(sock);
    handle->sock = -1;
    handle->started = false;
    handle->task = NULL;
    vTaskDelete(NULL);
}

esp_err_t provisioning_captive_dns_start(esp_netif_t *ap_netif)
{
    ESP_RETURN_ON_FALSE(ap_netif != NULL, ESP_ERR_INVALID_ARG, TAG, "missing AP netif");
    if (s_dns.started) {
        return ESP_OK;
    }
    while (s_dns.task != NULL) {
        vTaskDelay(pdMS_TO_TICKS(20));
    }

    memset(&s_dns, 0, sizeof(s_dns));
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "socket failed errno=%d", errno);
        return ESP_FAIL;
    }

    struct timeval timeout = {
        .tv_sec = 1,
        .tv_usec = 0,
    };
    (void)setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

    struct sockaddr_in bind_addr = {
        .sin_family = AF_INET,
        .sin_port = htons(DNS_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(sock, (struct sockaddr *)&bind_addr, sizeof(bind_addr)) < 0) {
        ESP_LOGE(TAG, "bind failed errno=%d", errno);
        close(sock);
        return ESP_FAIL;
    }

    s_dns.started = true;
    s_dns.sock = sock;
    s_dns.ap_netif = ap_netif;
    BaseType_t ok = xTaskCreate(captive_dns_task,
                                "ancs_captive_dns",
                                4096,
                                &s_dns,
                                5,
                                &s_dns.task);
    if (ok != pdPASS) {
        close(sock);
        memset(&s_dns, 0, sizeof(s_dns));
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "wildcard DNS started");
    return ESP_OK;
}

esp_err_t provisioning_captive_dns_stop(void)
{
    if (!s_dns.started) {
        return ESP_OK;
    }

    s_dns.started = false;
    if (s_dns.sock >= 0) {
        shutdown(s_dns.sock, 0);
    }
    while (s_dns.task != NULL) {
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    return ESP_OK;
}
