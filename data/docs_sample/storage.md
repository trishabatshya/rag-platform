# Document storage and uploads

The maximum size of a single uploaded document is 10 MB. Supported document formats are
Markdown (.md) and plain text (.txt), encoded as UTF-8. Images, archives and PDFs cannot
be uploaded as documents. Each uploaded document receives a stable document ID.

The Pro plan includes 20 GB of storage; Team includes 100 GB. Storage is measured using
the original UTF-8 file size. Document revision history counts toward storage usage.
Deleted documents stop counting toward storage after the daily cleanup job.

An upload that would exceed the storage allowance is rejected on Free. Paid plans permit
overages at their documented rates. Workspace owners can view storage usage from
Settings > Usage. Bulk imports accept up to 100 documents in a single request.
