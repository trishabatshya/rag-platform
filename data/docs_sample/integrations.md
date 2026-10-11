# Integrations and outbound webhooks

Northwind Cloud supports Slack notifications and outbound HTTPS webhooks. A workspace
owner configures integrations from Settings > Integrations. The Slack integration sends
notifications when automation jobs fail; it does not upload document contents to Slack.

Webhook requests include an X-Northwind-Signature header computed using HMAC-SHA256.
Verify this signature before acting on an event. Webhooks retry failed deliveries
three times, after 1 minute, 5 minutes and 30 minutes. A delivery is successful only
when the receiver returns an HTTP status between 200 and 299.

Webhook event IDs are stable across retries, so receivers should deduplicate events.
The service does not provide an inbound email integration. Owners can disable a webhook
without removing the webhook's configuration.
