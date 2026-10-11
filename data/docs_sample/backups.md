# Backups and recovery

Northwind Cloud takes encrypted document backups every 24 hours and retains backups
for 30 days. Backups remain in the workspace's selected hosting region. Backup copies
are not accessible through the document API and are managed by the operations team.

Workspace owners can request document recovery within 30 days of accidental deletion.
Send the workspace ID, document ID and deletion time to support@northwind.example.
The target recovery time is 8 business hours after the request is verified. Recovery
requests do not restore deleted API keys or cancelled automation runs.

Backups protect against operational failures but do not replace a customer's independent
export. The export document describes portable ZIP downloads and their retention period.
