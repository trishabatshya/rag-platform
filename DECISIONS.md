# Decisions

## Live Qdrant leakage scope (2026-10-16)

- The original leakage suite is in-memory regardless of an externally selected real
  mode: conftest resets per-test RAG_MODE, and RecordingClient() independently defaults
  to QdrantClient(":memory:"). Module fixtures precede the per-test reset, so both the
  retrieval and cached harness now explicitly force mock model mode during ingestion
  too, and reliably close their owned clients/audit handles.
- New integration tests opt in with RUN_QDRANT_INTEGRATION=1 and explicitly construct
  the recording client with http://localhost:6333. Mock embeddings/completions and SQLite
  audit remain intentional; the only live adapter in this suite is Qdrant. No environment
  mode switch or application factory can redirect this explicit URL to memory. Enabled
  connection failures fail, and there is no backend fallback. Reuse the original exact
  600 positive case assertions and both negative-control functions to avoid divergent
  security oracles. A disabled prefilter must produce an oracle-detected raw leak while
  the post-check protects the response; disabling both must expose response leaks.
- The fixture owns only a UUID-named test collection, refuses an existing name, creates
  server ACL indexes through production ingestion and cleans up only that collection.
  Application collections are untouched. The observed live server/client versions are
  1.17.0/1.19.1; retain the compatibility warning and limit the claim to this tested small
  fixture. Do not claim real-model, PostgreSQL, live cache or load-test verification.

## Judge tolerance and independent reference check (2026-10-16)

- Search whole verdict words case-insensitively, INCORRECT first, then CORRECT. Preserve
  raw completion text; an unknown reply has correct=None and judge_label=unparseable.
  Exclude unknown verdicts from accuracy/disagreement denominators and report coverage,
  rather than silently counting them as wrong. Shared benchmark/report consumers retain
  unknown quality instead of converting None to a boolean or crashing.
- The judge prompt compares the key fact, permits harmless sentences/citations and gives
  two short few-shot examples. The independent reference_in_answer metric matches a
  normalized contiguous phrase at token boundaries, avoiding number-substring matches.
  It can still accept negation/contradiction or miss synonyms; it is not a ground-truth
  judge. Judge accuracy here means the fraction of answers it rates correct, not a
  validated classifier accuracy against human labels. No evaluation questions changed.
- Baseline warm-up calls load the answer and judge paths before measured questions;
  their usage/cost is separate. This reduces startup effects but cannot prevent model
  eviction/reloads under different-model or concurrent serving. Do not compare these
  warmed latency samples directly with earlier cold-start CSVs.

## Real-mode dependency profile (2026-10-16)

- `requirements-real.txt` includes the base requirements and pins the additional installed
  model stack, including sentence-transformers 6.1.0 and LiteLLM 1.105.1. Default install
  and CI remain on the offline stack. Shared filelock and huggingface-hub pins were changed
  to 3.32.7 and 1.33.0: the earlier 4.x/2.x pins conflict with LiteLLM's declared bounds
  (and the model stack's hub bound). Both profiles must resolve together rather than
  silently overriding conflicting requirements with a second pip command.
- Installation, pip check, installed encode/predict/completion API inspection, a local
  384-dimensional normalized SentenceTransformer BoW adapter check and LiteLLM's offline
  mock-response path succeeded on Windows/Python 3.11. No pretrained weights or live
  provider were used. Platform-specific dependencies such as Linux CUDA packages remain
  pip-resolved; GPU builds and other platforms need their own validation.
- The embedding adapter catches only an absent sentence_transformers module and gives
  the exact real-profile install command. Missing transitive modules and model-loading
  errors retain their original diagnostics. Mock embeddings never import optional models.
- The default Docker image still installs the base profile. README explicitly separates
  host real-mode installation from a custom real-mode image; installing Python libraries
  does not provide model weights, Ollama or database services.

## M0

- **Portable commands:** tasks.py uses sys.executable, pathlib and subprocess argument
  lists with shell=False. Alternatives were shell scripts and duplicated Makefile
  recipes. One runner keeps Windows and POSIX behavior consistent.
- **Python version:** use the installed Python 3.11 interpreter in .venv311; the
  machine defaults to 3.14. Python 3.11 matches the task and container runtime.
- **Mock embedding:** SHA-256 token feature hashing with signed buckets, normalized
  to 384 dimensions. A fixed fallback vector handles empty/cancelled text. This
  enables deterministic lexical similarity without claiming semantic quality.
- **Dependencies:** keep mock requirements separate from expensive real-model
  packages. Real adapters import providers only when called. Real-mode packages
  must be installed and inspected before their APIs can be declared validated.
- **M0 feature scope:** provide a working health endpoint and adapter contracts;
  later target commands point to their milestone modules. Do not add fake success
  handlers or empty implementations for unfinished features.
- **Compose:** persist all service data in named volumes. Missing .env is allowed
  using Compose's optional env_file support; development defaults are public.
- **Validation boundary:** M0's offline acceptance commands pass. The optional
  real-provider download did not finish and was stopped, so real model APIs have
  not been validated or pinned. Treat real adapters as unverified until the
  installed implementations are inspected. Docker configuration validation passed,
  but the daemon check did not return and Ollama is not on PATH.
- **Installed API detail:** QdrantClient 1.19.1 has query_points and collection_exists,
  but is not a context manager. Tests use contextlib.closing. Starlette 1.7.0 emits
  a deprecation warning for httpx-backed TestClient; tests pass with the installed
  httpx 0.28.1. Revisit the transport dependency before upgrading the HTTP tests.

## M1

- **Process-local mock index:** service and evaluation reload the configured sample
  corpus on first use. A separate mock ingestion process cannot share an in-memory
  Qdrant client. Alternatives were persistent local Qdrant or an HTTP ingestion
  endpoint; reload preserves M0's required in-memory mock adapter and simple CLI.
- **Version and IDs:** a SQLite transaction serializes version increments and tracks
  folder manifests. Every successful ingestion, including identical re-ingestion,
  bumps the version. UUID5 IDs use resolved folder path, relative source and chunk
  position; re-ingestion does not duplicate points. Sources use portable forward
  slashes, but moving the corpus folder changes its IDs. Removed documents and
  shortened documents lose stale chunks.
- **Cross-store failure:** all text decoding and embedding precede mutation; version
  metadata advances only after Qdrant writes complete. Qdrant and SQLite are not
  transactionally coupled. A vector write failure can leave partial replacements;
  rerun ingestion and do not serve during ingestion. Atomic index swaps are deferred.
- **Retrieval provenance:** response sources are parsed citations; evaluation hit
  uses all retrieved chunk sources. Unanswerable items have a null source and a blank
  hit cell, excluded from hit rate but included in correctness. This avoids treating
  an expected absence of a source as a retrieval failure.
- **Judge limitation:** mock correctness uses multiset token F1 >= 0.5, as requested.
  This is a weak lexical metric that can pass wrong-region/wrong-number answers.
  Mock completions quote whole context, so their correctness is not a model-quality
  result. Real binary judging is implemented but unverified with a live provider.
  Human-review samples use a fixed seed, preserve blanks, and refuse overwrite.
- **Reference prices:** initial tier prices are illustrative assumptions in USD per
  million tokens, not asserted provider list prices or actual local-model charges.
  Evaluation separates judge tokens/cost from answer tokens/cost and rejects an
  unknown model price tier. Update assumptions before interpreting real savings.
- **Public-corpus boundary:** M1 has no authentication. It rejects retrieved chunks
  carrying tenant_id rather than silently treating them as public. User identity
  arguments are rejected until M2 implements the authenticated retrieval path.
- **Installed APIs:** inspected QdrantClient 1.19.1 delete/filter/scroll interfaces.
  Pydantic on Python 3.11 requires typing_extensions.TypedDict for response schemas;
  updated the existing contracts import while preserving its fields.
- **Helpers:** fetch accepts only HTTP(S) URLs and stores decoded response text;
  HTML main-content extraction is outside this optional helper. Candidate generation
  validates JSON, labels every draft needs_review, and never overwrites the golden
  evaluation. Mock candidates are templates, not reviewed new evaluation facts.

## M2

- **Collection isolation:** keep M1's public evaluator in baseline_chunks; the HTTP API
  uses chunks exclusively and always requires a verified JWT. This preserves the public
  evaluation without weakening tenant filters or ingesting anonymous evidence into the
  ACL collection. The public baseline and isolated raw benchmark are not authenticated
  request paths; every authenticated retrieval is audited.
- **ACL semantics:** tenant equality AND (role intersection OR explicit user grant).
  Use Qdrant MinShould(min_count=1), verified in installed 1.19.1 source. A public label
  never bypasses tenant matching. Classification is descriptive; grants determine access.
  Empty grants deny everyone. Admin has no implicit grant, including for user-only docs.
- **Seed IDs:** explicit tenant-prefixed IDs prevent ingestion collisions across
  tenants. Every secure chunk inherits validated metadata. Bare folder ingestion cannot
  write to chunks; server payload indexes cover tenant, roles, users and doc_id, and
  installed-client init_options guard unsupported indexing in local memory mode.
- **Defense validation:** 15 identities x 40 adversarial queries check raw vector results
  and returned chunk/answer evidence using grants from committed seed data. Positive
  access assertions prevent a deny-all implementation from passing. Disabling the filter
  makes the raw-result oracle fail while the post-check blocks the response; disabling
  both defenses makes the response oracle fail. These controls are test-only monkeypatches.
- **JWT/passwords:** HS256 only; verify signature, exp, iat and strict claim types.
  PBKDF2-SHA256 uses 600000 iterations and random per-user salts. Demo passwords are
  deliberately public and no production account management is provided. Empty JWT_SECRET
  produces a random process-local key only in mock mode; real mode requires >=32 bytes.
  Old role claims remain valid until token expiration; document ACL changes are immediate.
- **Audit:** SQLAlchemy writes the immutable record and exact document index in one
  transaction before generation. Retrieval errors are logged; failed audit commits block
  generation. Dropped forbidden chunks are not linked as delivered evidence; the record
  contains a violation count and critical logs contain IDs, not document text. Exact joins
  avoid JSON substring matches, and reads require verified admin plus tenant equality.
- **Database enforcement:** SQLite UPDATE/DELETE triggers were executed in tests.
  Existing-identity INSERT guards also reject REPLACE, which can otherwise bypass
  SQLite DELETE triggers when recursive triggers are off.
  PostgreSQL statement triggers also reject TRUNCATE; startup applies the SQL migration.
  Syntax checked against [PostgreSQL 16 documentation](https://www.postgresql.org/docs/16/sql-createtrigger.html),
  but no live PostgreSQL migration run occurred. Schema/file owners can still disable
  protections; use restricted runtime credentials and a separate migration owner in production.
- **Revocation/epoch:** bump the SQLite cache_epoch before waited Qdrant mutation, so
  even partial failures invalidate future cache entries. A process-local lock serializes
  retrieval snapshots and API mutations. Generation already in flight can finish its
  snapshot; mock process restart restores seeded ACLs. Epoch metadata is currently local,
  so shared invalidation must precede horizontally scaled caching in later milestones.
- **Benchmark scope:** at least 200 paired queries alternate order in a disposable
  collection; no production ACLs are changed and no unfiltered contents are written to
  output. Filtering timings exclude embedding/generation/audit. Revoke timing includes
  epoch update, waited payload write and one verification query. Negative paired timings
  from noise are retained, not clamped. Every mock output is labeled and remains outside
  README's real-results table.
- **Installed versions/limits:** inspected PyJWT 2.15.1, SQLAlchemy 2.1.4 and Qdrant 1.19.1
  APIs; installed and pinned psycopg 3.3.6 and PyYAML 6.0.3. Windows mock tests exercise
  JWTs, SQLite triggers and in-memory filters. Live Qdrant payload indexes/filters,
  PostgreSQL trigger execution, real models and hosted GitHub Actions remain unverified.

## M3

- **Instrumentation:** requests stores actual route/cache/escalation, usage, reference
  cost, measured latency, run tag and runtime mode. API quality remains NULL; benchmarks
  attach only their actual judge verdicts. Error rows contain usage from completed calls,
  not invented usage for a failed provider response. Benchmark wall timing includes the
  final request-log commit; dashboard/service timing ends before that commit.
- **Reference pricing:** retain the small/large tier values after checking published
  [GPT-4o Mini](https://developers.openai.com/api/docs/models/gpt-4o-mini) and
  [GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o) input/output prices on
  2026-10-12. They are reference proxies, not prices charged by Ollama. Env overrides
  support another comparison. Earlier M0/M1 notes called these values illustrative;
  M3 supplies their source and verifies them. Escalation sums both calls at their own
  tier; LLM classification overhead is included and reference-judge cost is separate.
- **Cache identity:** add user_id to tenant and sorted-role fingerprint. M2 explicitly
  supports user-only grants, so identical roles do not imply identical permissions.
  The conservative key forfeits sharing between users who happen to have equal access
  but prevents cross-user disclosure. Missing identity never performs a cache search.
- **Cache eligibility:** version, epoch and TTL constraints join identity predicates
  inside Qdrant. Recheck them in Python, including similarity, then consider up to ten
  neighbors so a guard rejection does not hide another valid candidate. Never cache
  empty, uncited, abstaining or failed responses. Changed snapshots during generation
  cannot be stored; final request-log failure discards that request's new cache entry.
- **Cached evidence:** cache hits re-query all original chunk IDs with the current ACL
  filter, post-check metadata and compare text/source/doc_id before delivery. Missing,
  changed or forbidden evidence rejects the entire hit. It commits cache_hit=true plus
  evidence IDs to immutable audit before returning. This extra read is intentionally
  part of M3, because new caching must retain M2's guarantees.
- **Guard limits:** compare number sets and capitalized entity-like token sets, excluding
  common question openers. It can reject synonyms/capitalization changes and cannot
  detect every enable/disable or negation flip. The tuning sweep reports real observed
  false hits rather than assuming the guard solves equivalence. Mock threshold tuning
  never changes the default real deployment threshold automatically.
- **Router/audit ordering:** a pure rule callback sees approved retrieval scores and
  selects the model before audit commits, keeping audit.model accurate. Optional LLM
  classification uses only the verified caller's question before retrieval, so the
  subsequent audit can record its chosen model before evidence reaches generation.
  Invalid classifier output selects complex. Small-model weak evidence, invalid/absent
  citations or abstention triggers large-model escalation using the same approved chunks.
- **Benchmark data:** 50 paraphrase/50 near-miss pairs are curated domain templates;
  100 router intents are hand-written and include keyword counterexamples. These are
  small tuning/regression sets, not held-out production evidence. Router intent accuracy
  and actual QA quality/cost are measured separately, without assigning reference answers
  to arbitrary router-label questions.
- **Fair replay:** use an isolated ACL copy of the public sample corpus and a verified
  benchmark operator. Baseline and optimized systems replay identical seeded requests;
  optimized starts with a cleared cache. Repeats follow original queries, half use a
  template paraphrase, and both requested/rounded actual ratios are recorded. Indexing
  and judging are outside service wall time. Real warm-model/order effects still need
  review before interpreting deployment performance.
- **Dashboard/dependencies:** Streamlit 1.65.0 installed after an initial download hash
  mismatch/DNS failure; the successful retry retained pip's integrity checks. Inspected
  installed AppTest/from_file/run and chart signatures, tested empty/filled views and
  run-tag filtering headlessly, and pinned installed transitive dependencies. No browser
  screenshot or live real-mode dashboard run occurred. It is an operator tool with no
  multi-tenant authentication, not a customer-facing data portal.
- **Validation scope:** cache invalidation, user/tenant/role isolation, escalation token/
  cost sums, anonymous lookup prevention, request errors and poisoned evidence all ran
  offline. The seed-derived oracle also covers 600 cached-service combinations in addition
  to M2's 600 retrieval cases. Live Qdrant/PostgreSQL, real LLM/router quality, GPU/model
  setup and hosted GitHub Actions remain unverified; no mock metrics are real results.

## M4 GraphRAG

- **Scope:** standalone public-corpus pipeline and three-system evaluator; no graph mode
  is added to authenticated `/ask` before M5. Graph ACLs would need chunk/edge-evidence
  grants and filtering before expansion. Namespace isolation is not permission checking.
- **Data/API:** inspected installed datasets 5.1.0 load_dataset/shuffle/select signatures
  and a current HotpotQA viewer row's context/supporting_facts dict fields. Use the
  namespaced dataset ID, distractor config, validation split and seeded shuffle/select.
  Also accept historical pair fields. Join sentences per paragraph, deduplicate identical
  title/text and index distinct paragraphs under the same title. A full real download
  was not attempted. Network failures visibly fall back unless --no-fallback is supplied;
  malformed data does not silently become fixture data. Single-hop is <=1 unique gold
  title for HotpotQA, which may yield no single-hop rows; fixture labels are authored.
- **Fixture honesty:** twelve fictional film/director/birthplace bridges and three
  organization/location questions have query-like event distractors. Annotated paragraph
  extraction simulates perfect extraction with zero LLM calls/tokens. Rules parse only
  retrieved text for mock answers and the question for mock planning; question gold
  labels never reach indexing, retrieval or generation. This narrow fixture proves
  plumbing/sanity, not generalization, GraphRAG quality or reference cost savings.
- **Extraction:** three retries means four maximum attempts. Strict Pydantic entity and
  relation literals reject unknown types, extra fields and dangling endpoints. Provider
  exceptions are normalized only around complete(); invalid JSON calls count in usage.
  Failed chunks remain vector evidence but have no graph extraction. Persist only validated
  successes atomically with pathlib. Hash includes mode/model/text/schema and mock annotation,
  so a mock run never contaminates real extraction. Corrupt cache entries are rebuilt.
  New extraction tokens/cost and extraction wall time are separate from total indexing time;
  reference indexing cost excludes embedding/storage/local compute. Failed unreturned
  completions have unknown usage, not fabricated counts.
- **Resolution/risk:** rapidfuzz token_set_ratio("Chris Nolan", "Christopher Nolan") is
  only 78.57 in installed 3.14.6, so PERSON first-token Chris is explicitly normalized to
  Christopher before the required >=92 match. Christopher Norton stays separate. Grouping
  is type-scoped, complete-link and deterministic; longest original name is canonical.
  **Known failing-risk case:** John Smith and John Adam Smith score 100 as token subsets
  and merge even if they are different people. Chris may also be a different person's
  full name. Without disambiguating attributes this cannot be solved by name threshold
  alone; the regression explicitly exposes this risk and the report requires human review.
  Optional cosine >=0.97 merging is off by default and can add false merges.
- **Storage:** inspected NetworkX 3.6.1 MultiDiGraph and Neo4j 6.4.0 driver APIs and official
  vector-index documentation. Target Neo4j 5-compatible CREATE VECTOR INDEX / queryNodes,
  not the newer server-only SEARCH syntax. Typed Entity keys and Chunk keys include an
  owned run namespace to prevent cross-run graph paths and destructive global cleanup.
  REL stores relation type and supporting chunk_id. Constraints/indexes remain; owned
  nodes are deleted on close. ANN namespace overfetch may miss neighbors; insufficient
  candidates fall back to exact owned vectors. This is for small public experiments.
- **Retrieval:** vector baseline returns six of top fifteen without graph/reranking.
  Hybrid links whole canonical/alias phrases, expands undirected REL paths of length
  zero through two, deduplicates candidates and reranks. Graph-connected entity names
  enrich the reranker question in both modes so the lexical mock can resolve bridges;
  real cross-encoder benefit still needs an ablation. Only selected-chunk, link-relevant
  triples reach generation. Both systems have the same six-paragraph generation budget.
- **Decomposition:** planner returns up to four validated steps using prior-answer
  placeholders. Sequential vector retrieval isolates the decomposition baseline from
  graph expansion. Stop at intermediate abstention; invalid plans fall back to original
  question. Count planner plus every step's completed tokens; union evidence across steps
  for supporting recall. Decomposition may use more total evidence/tokens than a one-shot
  system; report that trade-off, rather than claiming identical compute budgets.
- **Evaluation:** SQuAD normalization/EM/multiset F1 and unique-title recall are tested
  with hand-computed examples. Record actual data origin, mode, subset sizes and null
  metrics for empty subsets. First-use query latency includes model loading. Failure
  review shows up to ten observed answer/evidence failures, never fabricated rows; leave
  categories blank for humans. Generated merge/review artifacts are ignored; save filled
  review elsewhere before rerunning. Live Neo4j tests opt in via NEO4J_URI and do not
  silently fall back. Real extraction/generation/embedding/reranking, full HotpotQA load,
  live Neo4j and hosted CI remain unverified; optional real model dependencies from M0
  are still pending because this environment lacks Ollama/model setup.

## M5 integration and polish

- **Mode boundary:** the task asks for RETRIEVAL_MODE on the multi-hop dataset and calls
  that corpus standalone/public. Implement selection in graphrag.pipeline, preserving
  the shared question/model/user interface and rejecting any supplied tenant identity
  before indexing. The CLI accepts fixture/HotpotQA with explicit fallback policy.
  `/ask` continues to use the secure vector/cache/audit service in either setting;
  routing tenant documents through the unprotected graph would contradict the security
  contract. New HTTP regressions exercise cache-hit audit/doc IDs and revocation under
  both settings, and prove no request reaches public indexing. A later ACL graph needs
  chunk and edge-evidence grants, pre-expansion filtering and post-checks of every path.
- **Resource ownership:** the standalone public entry point owns one graph configuration,
  closes it before rebuilding for a changed configuration, and closes on CLI exit.
  It is a local single-process entry point, not an authenticated graph service or a
  distributed persistent graph deployment. Its output records actual dataset origin.
- **Report integrity:** latest completed artifacts are selected by mtime/name separately
  per runtime mode. Mock runs display status/provenance only, with no numeric performance
  claims. Baseline and ACL metrics are recomputed from CSV; Project 1 requires a matching
  baseline/optimized run tag and identical workload before comparison. Unpaired files
  cannot establish a cost reduction. Missing real runs stay NOT YET RUN; graph empty
  subsets are not applicable. Mixed/missing modes and invalid selected measurements fail
  before writing README. Report updates only the validated marker region and are idempotent.
- **Indexing provenance:** fixed latest summaries are convenient but overwrite earlier
  modes. Archive Project 1 and GraphRAG summaries with timestamped names as well. A graph
  indexing summary is accepted only when CSV filename, mode and corpus match; an absent
  matching summary is unknown, not zero indexing cost. Old mock metrics are never relabeled
  real, and a newer mock run cannot displace a retained real CSV in the report.
- **Documentation scope:** README now leads with architecture, pitch, container and host
  quickstarts, reproduction commands and measured/mock status. Host quickstart starts
  database services only before running the host API, avoiding a competing port 8000
  container. Study notes distinguish tested software properties from unmeasured quality,
  costs and deployment behavior. A dashboard screenshot is an honest placeholder, not a
  fabricated real-mode UI capture. Real provider dependency installation/API validation,
  live services, full HotpotQA download, GPU setup, browser use and hosted CI remain
  pending; completing offline M5 acceptance does not turn these into verified results.

## Project 1 threshold and citation policy (2026-10-16)

Select CACHE_THRESHOLD=0.96, the lowest hundredth with zero false hits in the
full REAL guarded all-MiniLM-L6-v2 sweep (50 paraphrases, 50 near misses), run
in this session using cached pretrained weights. Source:
`eval/results/cache_sweep_20261016T133308209063Z.csv`.
At 0.95: 4/50 true hits and 1/50 false hits; at 0.96: 3/50 (6%) true hits
and 0/50 false hits; at 0.97: 1/50 true hits and 0/50 false hits;
0.98 and 0.99: zero true hits and zero false hits. Prefer 0.96 to retain the
most recall among tested guarded zero-false-hit thresholds. This is tuning-set
evidence, not a held-out safety guarantee; different embedding models/corpora
require retuning. Existing environment overrides still apply; do not edit user .env.
Mock sweep scores are software checks and did not select the real default.

Missing citations no longer escalate by default: correct factual answers can
lack markers. ESCALATE_NO_CITATION=true restores that trigger. Weak retrieval
and abstention remain unconditional triggers; cache admission still requires
citations. Record all first-answer reasons before large-model generation, so
successful escalations do not erase their cause. Reason counts may overlap.
Escalation denominator is simple-routed requests; route shares use all requests.

Compare reuses one always-large baseline and independently clears the cache for
OFF and ON optimized runs of the identical seeded workload. Preserve ordinary
baseline/OFF filenames for report pairing; store ON in citation_policy_on CSV
and both policies in the summary. Primary answer quality and request-log quality
are reference_in_answer; retain judge verdict/raw reply as secondary evidence.
Lexical matching is transparent but cannot establish semantic correctness.

## Extraction timeout and relation salvage (2026-10-17)

Limit extraction to three total attempts (two retries), overriding the earlier M4
retry rule at the user's request. Pass EXTRACT_TIMEOUT_SECONDS (positive finite,
default 90) through the shared completion adapter only for extraction, disabling
LiteLLM retries on those calls to avoid multiplying attempts. Three consecutive
timeout/connection failures abort indexing rather than skipping an entire unavailable
provider's corpus. A returned completion resets the outage streak independently of
JSON validity. Other completion callers retain their existing provider options.

Only salvage the strict schema's endpoint-membership error. Structural/type/extra-field
errors still fail the chunk after bounded retries; never invent missing entities or
widen allowed types. Keep declared entities and valid relations, caching the successful
salvaged extraction. Existing schema-valid caches remain usable. Failures are not cached.
Indexing usage counts kept relations including cached successes, newly dropped relations,
and fully failed chunks (skipped_chunks remains a compatible alias). Archived benchmark
JSON carries these counts through existing dataclass serialization; report unknown counts
for older summaries rather than assuming zeros. Live provider behavior: NOT YET RUN;
offline injected failures verify the control flow and request parameters.

## Extraction output cap and skipped diagnostics (2026-10-17)

EXTRACT_MAX_TOKENS defaults to 700 and must be positive. Forward it only on graph
extraction calls; other completion callers retain their existing generation limits.
Preserve the provider finish_reason to detect token-limited replies, and also recognize
JSON validation EOF errors when a provider omits finish metadata. Reject the whole
partial extraction immediately, retain vector evidence and continue to the next chunk;
do not retry a capped partial response repeatedly or cache it. Other validation errors
retain two retries and endpoint-only salvage remains unchanged.

Record one final reason per skipped chunk, not per failed attempt. Summaries carry
skipped_chunk_details and skipped_reasons; skipped_chunks.txt is a mode-labeled UTF-8
JSON-lines diagnostic rewritten for each indexing run. Persist it in a finally block
so the existing three-timeout abort cannot erase diagnostic evidence. Abort summaries
are explicitly incomplete, have no CSV reference, and are archived separately; they
cannot be mistaken for completed benchmark measurements. Successful summary archives
remain intact. Failure records never become extraction-cache entries.

## Constrained extraction and explicit lossy repair (2026-10-18)

Keep EntityType/RelationType unchanged. Send Extraction.model_json_schema via
LiteLLM response_format.type=json_schema, with maxItems=8 on both top-level arrays.
Use a short important-facts prompt and default EXTRACT_MAX_TOKENS=1000. The installed
LiteLLM 1.105.1 Ollama completion/chat adapters map json_schema to the schema-valued
Ollama format argument; the running server reports 0.40.5. Three fresh llama3.2:3b
calls verified allowed types on raw objects before any repair (no invented types).
Artifact: eval/results/extraction_schema_smoke_20261018T073650034507Z.json.
This is adapter/schema evidence for three authored paragraphs, not corpus quality.

Repair before strict validation: coerce string entities, discard blank names, apply
the requested entity aliases then OTHER fallback; unknown predicates become RELATED_TO.
This deliberately loses predicate semantics rather than widening the fixed vocabulary.
Repair typed endpoints consistently; resolve bare endpoint names only when unique, then
drop relations without declared typed endpoints. Do not guess names or add entities.
Malformed shapes/extra fields still fail, and failures never enter the cache.

Count fresh attempted/clean/repaired/failed chunks separately from historical cache hits.
Count repaired type occurrences in successful outputs, including endpoint objects and
unknown predicates later dropped as dangling relations. Preserve valid old cache entries;
their original repair history is unknown, so do not label cache hits as newly clean.
Console diagnostics contain one chunk ID/reason per skipped chunk; append full errors
and raw responses to extraction_failures.log. Isolate all unit-test logs in temporary
directories and keep diagnostics out of Git because they include public corpus text.

## Bounded completions and resumable graph evaluation (2026-10-18)

Always resolve missing completion limits centrally: LLM_TIMEOUT_SECONDS=120 and
LLM_MAX_TOKENS=400. Validate positive finite limits and explicitly pass timeout,
max_tokens and num_retries=0 to the sole LiteLLM completion boundary. Extraction's
explicit 90/1000 overrides remain intact. Source search found no other direct provider
completion calls. Timeouts bound individual calls, not an entire multi-step question.

Default graph benchmark systems to vector,graph_hybrid; decomposition is explicit
--systems opt-in. Catch each question/system Exception, retain the full failure reason,
score failed answer/evidence metrics zero and continue. Preserve unknown partial total
usage as null rather than claiming zero cost. Count timeouts as a subset of failures;
count invalid decomposition even when its fallback answer later fails, through optional
diagnostics that leave the shared response contract unchanged. Interrupts and indexing,
configuration/checkpoint I/O failures still propagate instead of claiming success.

Append/flush/fsync each terminal result to a corpus/configuration-hashed JSONL. Include
mode, corpus/questions/mock annotations, model names, endpoint, limits and resolution
policy in the key; omit selected systems so adding decomposition can reuse vector rows.
Skip both successes and recorded failures on rerun; use a new output directory to retry
terminal failures. Rebuild the index through its existing success-only cache. Discard
only a partial trailing checkpoint line, fail on earlier corruption/duplicates, and keep
one writer per checkpoint. Summary counts separate reused rows from new measurements.
Report omitted systems as NOT YET RUN and allow unknown failed-row usage without
silently accepting malformed blank measurements on successful rows.

## Subset-safe resolution and original extraction-fill costs (2026-10-18)

Replace token_set_ratio with normalized plain ratio >=92. Reject strict token subsets
before fuzzy or optional embedding comparison, except PERSON names where the shorter
name contains exactly first+last tokens matching the longer name's first/last, with
inserted middle names. Keep normalization/nickname handling, type separation, longest
canonical selection and complete-link groups. Count one canonical-assignment reason
per eliminated unique typed entity (normalized_equal/person_first_last/ratio/embedding),
not all matching pairs. Close-spelling collisions remain possible at the requested ratio.

--fresh-extraction bypasses successful extraction-cache reads, still recording every
completed call and including validation retries in current usage. Preserve older valid
successes when a forced extraction fails; never return them for that failed forced call.
Store original successful-fill time, tokens, completed calls and reference cost under
cache/provenance, independently of current-run counters. Later cache hits and forced
regenerations must not overwrite the original record. Deduplicate cache keys in totals.
First-fill scope excludes failed uncached runs and non-extraction costs; token/reference
costs cover completed provider replies, not unknown usage from timed-out calls.

Always emit first_fill_extraction in indexing summaries, with known/unknown entry counts
and null complete totals when legacy records are missing. Do not backfill old provenance
using a cache-hit timing or a later fresh measurement. This run's fresh usage is separately
available even when historical original fill costs cannot be reconstructed. README report
labels current indexing separately from original fill costs, and retains matching archives.

Fingerprint the resolved graph in query checkpoints and bump resolver/checkpoint version,
so changing merges or forced extraction evidence cannot silently reuse older QA rows.
Rebuild merge_groups.txt from matching cached real HotpotQA paragraphs without models,
databases or a new QA benchmark. Read the cached Arrow dataset with in-memory sampling:
the normal dataset loader attempted an unwritable external cache lock. Do not rewrite
the earlier real benchmark summary/CSV with new graph counts and old QA measurements.
