/* Default isolated test profile. No BC250 patch and no board trial profile. */
#define ROUTER_PROFILE_NAME "isolated-demo"
#define ROUTER_PROFILE_ROWS 6u
#define ROUTER_PROFILE_RUNS 4u
#define ROUTER_PROFILE_PAYLOAD_WORDS 3u
static struct router_run router_runs[] = {
    {0x03000100, 2, ROUTER_NO_PAYLOAD},
    {0x039db140, 2, 0},
    {0x039db140, 1, ROUTER_NO_PAYLOAD},
    {0x038f0800, 1, 2},
};
static uint32_t router_payload[] = {0xa501fe80, 0xffffffff, 0};
