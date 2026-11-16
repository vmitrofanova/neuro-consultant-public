from redis import Redis

COUNT_REQUEST = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('PTTL', KEYS[1])}
"""


class SyncRateLimit:
    def __init__(self, client: Redis, limit: int, window_seconds: int) -> None:
        self.count_request = client.register_script(COUNT_REQUEST)
        self.limit = limit
        self.window_ms = window_seconds * 1000

    def retry_after(self, client_host: str) -> int | None:
        count, ttl_ms = self.count_request(
            keys=[f"catalog:sync:rate:{client_host}"], args=[self.window_ms]
        )
        if count <= self.limit:
            return None
        return max(1, (ttl_ms + 999) // 1000)
