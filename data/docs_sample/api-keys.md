# API keys

Create an API key from Settings > Developer > API Keys. API keys have a nw_live_ prefix
and are shown only once at creation. Store keys in a secret manager. Never put an API
key in a public repository, browser bundle or support ticket.

API keys expire after 90 days. Rotate a key by creating a replacement, updating clients,
and then revoking the old key. Revocation takes effect immediately. Existing keys cannot
be recovered; create a new key if the secret has been lost.

Each API key is bound to its creating workspace and receives a read or read-write scope.
Send the key using the Authorization: Bearer header. API keys cannot be transferred
between workspaces, and deleting a workspace revokes all of its API keys.
