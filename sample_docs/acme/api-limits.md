# API Rate Limits

The Acme Cloud REST API is rate limited per API key.
Starter keys may make 60 requests per minute, Team keys 600 requests per minute, and Enterprise keys 3,000 requests per minute.

When a limit is exceeded the API responds with HTTP 429 Too Many Requests and a Retry-After header in seconds.
Clients should back off exponentially and retry after the indicated delay.

## Webhooks

Webhook deliveries are retried up to 8 times over 24 hours with exponential backoff.
Each delivery is signed with an HMAC-SHA256 signature in the X-Acme-Signature header; always verify it before trusting the payload.
