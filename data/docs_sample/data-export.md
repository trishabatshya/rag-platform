# Exporting documents

Workspace owners can request a full document export from Settings > Data > Export.
The export is a ZIP archive containing UTF-8 Markdown documents and a manifest.json
file with document IDs and project names. API secrets and billing payment details
are never included in document exports.

An export download link expires after 24 hours. Exports are encrypted in storage and
require the requesting owner's authenticated session to download. Export preparation
usually completes asynchronously, and the owner receives an email when it is ready.

Read-only workspaces can still export documents. An export does not include deleted
documents or the security audit log; audit logs have a separate Team-only export.
Exporting documents does not cancel the subscription or delete the workspace.
