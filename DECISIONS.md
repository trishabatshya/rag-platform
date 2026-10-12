# Decisions

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
