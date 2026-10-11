# Document API rate limits

The Pro plan permits 60 document API requests per minute per workspace. The Team plan
permits 300 document API requests per minute per workspace. The Free plan permits
20 document API requests per minute per workspace. All API keys in a workspace share
the same rate-limit bucket.

Requests above the limit receive HTTP 429. The Retry-After response header gives the
number of seconds to wait. Use exponential backoff with jitter when retrying. Rate-limit
windows reset every minute, and unused capacity does not carry over.

Bulk import requests count as one API request, even when they contain multiple files.
The rate limit applies to reads and writes together. A revoked API key returns HTTP 401,
not HTTP 429. Contact sales if a Team workspace needs a higher sustained rate.
