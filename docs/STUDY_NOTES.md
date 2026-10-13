# Interview study notes

These are roughly two pages per project: a problem/implementation page and a
measurement/trade-off page. They describe the repository that exists, including what
has and has not been verified. The only completed runs are offline mock checks.
Real quality, latency, cost savings and production leakage rates are **NOT YET RUN**.
Use README's reproduction commands and DECISIONS.md when discussing the evidence.

## Project 1, page 1: semantic caching and cost-aware routing

### Problem and motivating example

Repeated questions spend model work even when the evidence and permitted answer are
unchanged. Always choosing the large model also spends more reference-priced tokens
than a smaller model would for straightforward factual questions. The challenge is to
reduce repeated work without returning another user's answer, reviving revoked evidence,
or accepting a semantically different question just because its embedding looks similar.

For example, a paraphrase of a user's plan-pricing question may reuse an answer. A
question about another region's refund policy is a near miss and must not reuse the
first policy. A confidential salary answer must never be shared across tenants, or
between users who have the same roles but different explicit-user grants. That last
case makes a tenant-plus-roles cache key insufficient by itself.

### Implementation and request flow

`app.service.RAGService.ask()` is the orchestration boundary. JWT verification happens
before it receives the CurrentUser. Cache scope includes tenant, sorted-role fingerprint
and verified user ID; the stored snapshot also records corpus version, ACL epoch and
expiry. Qdrant stores normalized query vectors for semantic lookup. Mock mode uses an
in-memory Qdrant instance and deterministic 384-dimensional hash embeddings.

A potential hit must pass similarity threshold, snapshot and TTL checks. The optional
guard compares number sets and capitalized entity-like tokens. Then the secure engine
re-fetches every original evidence ID with the current ACL filter, post-checks grants,
and compares evidence text/provenance. A missing, changed or forbidden chunk rejects
the entire cached answer. Accepted hits commit an immutable audit row with cache_hit
and source document IDs before delivery. They record zero new completion tokens.

On a miss, retrieval applies the permission filter and Python post-check. A rule router
uses the question and approved retrieval scores; an optional small-model classifier
uses the question only. The chosen model is audited before generation. Weak evidence,
an abstention or missing/invalid citations from the small model can trigger a large-model
escalation using the same approved chunks. The request log sums the classifier and every
completed generation call at its own reference tier. Unknown API quality remains NULL;
judge results are attached only when actually measured.

The cache avoids empty, uncited, abstaining and failed responses. It checks the original
version/epoch again before insertion. An ACL change during generation can invalidate
the insertion even if generation started from an earlier authorized snapshot. Cache
checks and ACL mutations share a single-worker state lock. This is local consistency,
not a distributed transaction across model execution, Qdrant and PostgreSQL.

### How I would explain it at a whiteboard

Draw identity verification, scoped semantic lookup, evidence revalidation and cache-hit
audit as one branch. Draw ACL retrieval, routing, audit, generation/escalation and safe
cache insertion as the other. Emphasize that similarity decides whether an answer may
be reusable; authorization independently decides whether this caller may see its evidence.
An embedding threshold is not an access-control rule.

## Project 1, page 2: measurements, trade-offs and improvements

### What was measured or verified

The benchmark contains 50 authored paraphrase pairs and 50 near misses. The threshold
sweep records observed false hits with/without the guard rather than automatically
declaring any threshold safe. Router evaluation contains 100 hand-labeled intents,
including keyword counterexamples, and separately compares QA quality/reference cost.
The service comparison replays identical seeded workloads through always-large baseline
and cached/routed service. At the default 40% repeat ratio, each system receives 75
requests. The optimized system starts with an empty cache; judging is outside service
latency. CSVs include actual repeat ratio, tokens, reference cost, escalation and cache hits.

These scripts have completed in mock mode. Tests verify TTL/version/epoch rejection,
explicit-user isolation, poisoned evidence rejection, completed-call usage accounting,
cache-hit auditing and generation-time invalidation. The additional cached-service
leakage oracle covers 600 user/question combinations. Streamlit AppTest verifies empty
and populated dashboard states and filters. Those are software regressions. A mock hit
rate or simulated reference-cost reduction is not a measured real deployment saving.

### Why the trade-offs matter

Raising the similarity threshold reduces false reuse but also loses useful paraphrases.
The number/entity guard catches some obvious near misses while missing negation, action
changes, lowercase names and other semantic differences. It may reject correct synonyms.
The tuning pairs are small and authored; tuning on them cannot establish performance on
unseen production traffic. User-scoped cache entries reduce sharing, deliberately, to
preserve explicit-user grants.

Evidence revalidation adds vector/audit work on a cache hit. A cache can reduce model
tokens while increasing observed end-to-end latency on a small local mock workload.
Report both outcomes rather than equating token savings with response-time savings.
Similarly, a small-first policy may spend more tokens when it frequently escalates.
Classifier accuracy and QA quality are different metrics; choosing the intended route
does not prove the generated answer is correct.

Reference costs use configurable published small/large API tiers as comparison proxies.
Ollama calls do not incur those API charges. The estimate excludes CPU/GPU time, memory,
embedding work, database/storage and operational expense. Judge overhead is separate,
and local-model quality is unverified in this environment. No claim of monetary savings
should be made until a real replay with a stated cost model has been reviewed.

### What I would improve next

Use held-out, independently reviewed equivalence pairs and adversarial negation/entity
changes. Tune a quality-versus-token budget on real local models, then evaluate on a
separate workload. Add calibration for route confidence, explicit latency budgets and
abstention policies. Disaggregate cache lookup, revalidation, classifier and generation
latency to understand where savings disappear. For multiple workers, move invalidation
state and locking to a shared service and test concurrent ACL updates across processes.

An interview answer should say: “I verified scoped reuse and invalidation with an
independent offline oracle, and built the replay to measure quality, tokens and latency.
Real-model savings remain unmeasured.” Avoid substituting fixture outcomes for evidence.

## Project 2, page 1: permission-aware multi-tenant RAG

### Problem and security boundary

A vector database ranks relevant text, but relevance does not imply permission. If
retrieval sends another tenant's confidential chunk to a model, hiding the citation
after generation cannot undo the disclosure. Permission checks therefore must happen
before context crosses into generation, with a second check to defend against malformed
metadata or an incorrect query/filter implementation.

The demo models three fictional tenants with five users and six documents each. Documents
include tenant-public FAQs, engineering material, HR salaries, board notes and explicit-user
contractor instructions. “Public” is a classification label inside a tenant, not global
access. An administrator also has no universal bypass; its role must match a grant.
Distinct marker strings make forbidden evidence observable in offline tests.

### Identity and grants

`/auth/login` verifies committed demo users' salted PBKDF2 hashes and issues a JWT.
`/ask` derives tenant, user ID and roles exclusively from a verified token. Request-body
roles or tenant fields cannot set identity. Tokens with missing, expired, tampered or
unsupported-algorithm signatures are rejected. Real mode requires a configured signing
secret of at least 32 bytes shared by workers. Demo credentials are public and are not
production authentication infrastructure.

Every protected chunk requires tenant_id, allowed_roles and a validated classification;
allowed_users can grant specific users. `app.acl.build_filter()` requires tenant equality
AND at least one matching role/user grant. Qdrant's min_should/min_count expresses the
OR between grants while preserving the outer tenant condition. Metadata validation
prevents bare public paragraphs from silently becoming protected documents.

### Retrieval, post-check and audit

`SecureRAGEngine.retrieve()` embeds the query and applies the filter in the vector call.
Python `can_access()` checks each returned payload again. Malformed or forbidden chunks
are dropped, counted and logged before model prompting. The engine audits retrieval,
including empty/failed outcomes, before generation. If audit cannot commit, delivery
fails closed rather than returning an unaudited answer. Cache replays follow the same
current-permission checks and record cache_hit plus exact source document IDs.

`AuditStore` provides append/read operations only. SQLite triggers reject UPDATE,
DELETE and replacement of existing identities in mock mode. PostgreSQL enforcement
is installed from a migration in real mode. An exact document-access index avoids
substring matching in JSON arrays. Administrator read/update endpoints scope operations
to the verified admin's tenant. Ordinary users cannot call them.

ACL updates validate the replacement grants and bump the persisted cache epoch before
mutating vector payloads. This makes earlier cache snapshots unusable even if a payload
update partially fails. Revocation applies to future retrieval/cache checks; it cannot
recall an answer a caller already received or guarantee cancellation of an in-flight
generation that started from an authorized snapshot. The documented local deployment
uses one worker and does not claim globally synchronized revocation across replicas.

## Project 2, page 2: measurements, trade-offs and improvements

### Why the leakage oracle is independent

A test that calls the production permission function to compute expected access can
repeat the same bug on both sides. The leakage suite reads grants directly from seed
files and derives forbidden documents and marker strings independently. It covers
15 seeded users over 40 adversarial questions: 600 combinations, plus 600 cached-service
combinations. It inspects raw query results, returned chunks and generated answer text.
Positive checks ensure accessible evidence still appears, so “always return nothing”
cannot pass as a useful security implementation.

Negative controls remove the prefilter and then both defenses, proving the oracle can
detect exposed forbidden evidence. Other tests cover token/body spoofing, cross-tenant
admin operations, malformed metadata, explicit-user grants and append-only storage.
M5 HTTP regressions log in, ask twice, inspect the cache-hit audit row, revoke grants
through the admin endpoint and verify the next answer no longer contains the salary
marker. They run under both public GraphRAG mode settings to verify the mode switch
cannot redirect tenant retrieval to an unprotected corpus.

These checks passed in mock mode with deterministic completions and in-memory Qdrant.
They demonstrate the implemented software boundary for the tested cases. They do not
establish a real LLM's prompt-injection resistance, a production leakage-rate estimate,
or the behavior of live PostgreSQL triggers and Qdrant indexes in this environment.

### What the benchmark means

`eval.bench_acl` creates a disposable collection, runs at least 200 paired filtered and
unfiltered vector operations, and alternates operation order. It reports the median
of per-pair overhead, rather than subtracting two independently aggregated medians.
It also revokes a known document and verifies it is absent from the next query.
The unfiltered path exists only in this benchmark, never as an API option.

Raw vector timings exclude embedding, model generation and production audit work.
Revoke-to-effect includes epoch increment, payload update and one verification query.
The mock benchmark ran end to end, but its local in-memory timings are not production
overhead measurements. A real experiment needs stated collection size, filter selectivity,
index configuration, hardware, concurrency, warm-up and repeated trials. Without those
details, a small overhead number would be easy to misinterpret.

### Remaining risks and design choices

The second check is a defense against incorrect filters/metadata, not a replacement for
prefiltering. It can remove forbidden results after Qdrant returns them, but relying
only on it can starve the caller of permitted results because the top-k was already
filled by inaccessible neighbors. Pre-filtering improves both the security boundary and
the relevance search space. Audit-before-generation improves accountability but creates
an availability dependency on the audit database.

Ingestion and ACL writes span local state and Qdrant rather than one distributed
transaction. Failures can leave partial corpus/payload updates; epoch-first invalidation
is conservative, and failed ingestion requires review/re-ingestion. Append-only triggers
do not prevent a privileged database operator from disabling triggers or altering storage.
Production audit retention, access control, backup and tamper evidence remain separate work.

### What I would improve next

Replace demo login with a real identity provider and short-lived tokens with key rotation.
Add shared invalidation and concurrency tests, least-privilege database accounts, index
migrations and load tests with realistic grant selectivity. Review prompt-injection behavior
using real models while preserving the evidence authorization boundary. Monitor post-check
drops as incidents, not a routine path. Test revocation during concurrent cached/model
requests and document whether in-flight responses are canceled or use snapshot semantics.

## Project 3, page 1: evidence-backed GraphRAG

### Problem and bridge example

“Where was the director of Amber Signal born?” contains the film name, but its birthplace
answer is in a biography of Mara Vale. A vector search may retrieve the film or festival
distractors without the biography. Graph retrieval can follow the relation Mara Vale
DIRECTED Amber Signal and then Mara Vale BORN_IN Cedar Bay, while retaining the paragraphs
that actually support both facts. The graph is an evidence index, not an answer key.

The loader samples HotpotQA distractor validation questions with a seed, joins each
context's sentences into one paragraph, deduplicates title/text and assigns title::index
IDs. It accepts current dict-of-lists and historical pair fields. A visibly recorded
download fallback loads 39 authored fictional paragraphs with 12 bridge and 3 single-hop
questions. Strict --no-fallback prevents accidental fixture substitution for a real
HotpotQA evaluation. Single-hop means <=1 unique supporting title for HotpotQA; that
subset can be empty. The fixture has explicit authored labels.

### Index construction

Extraction uses a small fixed Pydantic schema: typed entities and nine relation literals.
The initial completion can be followed by three retries. Unknown types, dangling endpoints
and invalid JSON are rejected. A final failure skips that chunk's graph facts while
retaining its vector evidence. Valid successes are cached by text/model/mode/schema;
mock annotations also participate in the key. Cache hits add no new extraction tokens
or reference cost. Completed invalid-JSON calls still count toward indexing usage.

Resolution normalizes names, groups by type and fuzzy-matches at >=92 with the longest
original name canonical. A documented Chris/Christopher alias supports that particular
abbreviation. Complete-link groups avoid a chain of weak pairwise matches. Token subsets
can still merge distinct people, such as John Smith and John Adam Smith, and the optional
embedding pass may add false merges. Human review of merge_groups.txt is part of evaluating
the graph. More complex extraction is not automatically better if resolution loses identity.

Neo4j and NetworkX share vector search, bounded expansion and evidence-triple operations.
Real storage uses typed Entity/Chunk constraints, MERGE, MENTIONS edges and REL edges with
supporting chunk_id. A 384-dimensional cosine vector index supplies vector candidates.
Run namespaces prevent cross-run graph paths and limit cleanup to owned nodes. Namespace
filtering is not ACL enforcement; the entire corpus is public and standalone.

### Query flow and alternatives

Hybrid retrieval takes vector top15, links whole canonical/alias names in the question,
expands zero through two REL hops, merges by chunk ID and reranks to six paragraphs.
Graph-connected names enrich the reranker question in both runtime modes. Real mode uses
the specified MiniLM cross-encoder; mock mode uses deterministic lexical overlap. Up to
ten relevant triples are supplied only when backed by selected evidence. Generation
requests a short phrase and abstention if unsupported.

The vector baseline uses six of its top15 candidates without graph expansion/reranking.
Decomposition is a separate baseline: an LLM plans up to four subquestions, uses prior
answers as placeholders, and retrieves with vector search at each step. It stops on
intermediate abstention and aggregates planner/step tokens and evidence. RETRIEVAL_MODE
selects vector or graph_hybrid for the standalone entry point, never for protected /ask.

## Project 3, page 2: measurements, trade-offs and improvements

### Evaluation and verified evidence

Answer scoring uses SQuAD-style lowercase/punctuation/article normalization, exact match
and multiset token F1. Supporting-title recall checks how many unique gold titles occur
in retrieved evidence. Hand-computed tests verify normalization, repeated tokens and
empty answers. The three-system evaluator reports all, multi-hop and single-hop subsets,
query latency/tokens/reference cost and one-time extraction/indexing usage separately.
Absent subsets have null metrics rather than invented scores.

The offline fixture sanity test verifies hybrid supporting-title recall >= vector
baseline. Benchmark scripts ran all 15 fixture questions for all three systems, writing
45 labeled CSV rows, summaries, merge groups and up to ten observed failures per system
for human categorization. They never fabricate failures to meet a quota. Mock extraction
uses paragraph annotations with zero LLM calls; mock completion parses supplied text,
not gold question labels. Tests deliberately change gold labels to verify this separation.

Those are meaningful plumbing checks, but the annotations simulate perfect extraction
and the completion rules are narrow. Fixture performance cannot establish real extraction,
linking, reranker or generation quality. The full HotpotQA download and real model passes
have not run. The Neo4j integration test is opt-in via NEO4J_URI and was skipped here;
driver parameter tests and NetworkX path tests do not claim to execute live Cypher.

### Costs and comparison limits

Graph indexing introduces up-front extraction completions, resolution and storage work.
Persisted extraction cache can amortize model work over repeated experiments, so report
whether a run was cold or reused cached extractions. Indexing reference cost covers
returned extraction tokens only, excluding embeddings, cross-encoder loading, database
operations and CPU/GPU expense. Unreturned failed-provider usage is unknown. Archived
JSON summaries preserve indexing provenance for the matching CSV/mode/corpus.

Query latency includes embedding, retrieval, reranking, planning and generation, including
first-use model loading. One-shot vector and hybrid systems share a six-paragraph prompt
budget, but hybrid also adds triples. Decomposition can consume more total evidence/tokens
across steps. It would be misleading to attribute any quality difference solely to graph
structure without evaluating those context/compute differences and cold-start effects.

Whole-name linking misses pronouns, abbreviations outside the resolution map and implicit
entity references. Expansion can add popular-node distractors; a two-hop bound controls
work but may miss longer bridges. Neo4j 5 ANN overfetch is namespace-filtered and can fall
back to exact owned vectors on candidate starvation. That convenience suits small public
experiments; it is not a scalable tenant-aware vector/graph serving architecture.

### What I would improve next

Run a reviewed real benchmark, categorize extraction/resolution/linking/reranking/generation
failures and inspect evidence rather than answer strings alone. Add entity disambiguation
with attributes and aliases, measured extraction precision/recall and link-confidence
abstention. Ablate graph expansion, enriched reranker queries, triples and prompt budgets
to identify which component changes quality. Compare cold/warm indexing and query costs.
For tenant data, add grants to chunks and edge evidence, filter before expansion, and
post-check every path's evidence before generation. Keep that work separate from the
public graph until an independent graph-leakage oracle demonstrates the boundary.

An honest interview conclusion is: “I built the three retrieval alternatives, preserved
evidence provenance and created a reproducible evaluation/failure-review workflow. I
verified the offline contracts; real multi-hop gains and indexing economics are pending.”
