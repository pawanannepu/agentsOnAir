# 0006. Live task streaming and interactive collaboration: Rationale

## Context

Autonomous software engineering tasks involve multi minute workflows within isolated microVM sandboxes: cloning repositories, installing packages, executing baseline test suites, generating code diffs, and running reviewer evaluations. Developers monitoring these tasks need immediate visibility into terminal outputs, tool calls, and agent reasoning steps. Without live streaming, users face opaque loading states and cannot diagnose failing steps until the entire run completes or times out.

In addition, autonomous agents frequently encounter ambiguous issue descriptions, missing credentials, or multiple viable implementation choices. If an agent makes an unguided guess, it risks wasting token budgets or generating flawed pull requests that require human rework. Enabling interactive human collaboration (answering clarification questions, injecting steering guidance, or aborting runaway runs) dramatically improves task success rates.

However, delivering real time streaming in a modern full stack monorepo presents distinct technical challenges. Web console deployments using Next.js serverless runtimes impose strict connection timeouts, making long lived proxy connections fragile. Furthermore, developers frequently navigate across pages, refresh browser tabs, or experience transient network drops. The streaming architecture must support instant reconnection and log replay without hammering the primary database.

Finally, human intervention requires strict concurrency safeguards to prevent conflicting inputs from multiple concurrent viewers, while pausing execution for human input must not starve background worker thread pools or cause idle microVM sandboxes to prematurely shut down.

## Options considered

### Option 1: Unified Redis Streams cursor streaming architecture with FastAPI Server Sent Events downstream and authenticated REST endpoints upstream

Browser clients connect directly to a FastAPI Server Sent Events endpoint using the `@microsoft/fetch-event-source` library with Clerk Bearer token authentication. Background workers append sandbox terminal chunks and LangGraph execution steps directly to a capped Redis Stream (`task:{task_id}:stream`). FastAPI streams events to clients using `XREAD BLOCK` starting from the client `Last-Event-ID` cursor (or `0-0` for initial connection). Upstream developer interventions (steering messages, clarification answers, and abort commands) route through authenticated REST endpoints that validate tenant permissions and push commands into task specific Redis queues. LangGraph handles clarification requests via explicit interrupt nodes that extend E2B sandbox timeouts, persist checkpoints to PostgreSQL, release worker processes to prevent thread starvation, and arm a persistent delayed queue watchdog.

**Pros**:
* Direct browser connection to FastAPI avoids Next.js serverless function timeouts completely.
* Server Sent Events run over standard HTTP/2 with automatic browser reconnect handling and native firewall traversal.
* Single Redis Streams transport handles both historical replay and live push using `XREAD BLOCK`, completely eliminating handoff race conditions and duplicate messages.
* Decoupled REST intervention endpoints provide clean stateless request handling, explicit HTTP error status codes, and standard JWT authentication.
* Worker process release during human wait prevents background worker pool starvation.
* Explicit E2B timeout extension prevents sandbox termination during the 15 minute clarification window.

**Cons**:
* Operates two communication channels (SSE downstream and REST upstream) rather than a single unified socket.
* Requires browser client configuration for direct API server URL (`NEXT_PUBLIC_AGENT_API_URL`).

### Option 2: Dual Redis Pub/Sub broadcast plus Redis Streams historical buffer

Workers publish live events to Redis Pub/Sub channels while simultaneously appending events to Redis Streams. FastAPI queries historical events from Streams and subscribes to Pub/Sub for live delivery.

**Pros**:
* Pub/Sub offers slightly lower latency fanout for high volume broadcast.

**Cons**:
* Critical handoff race condition: subscribing to Pub/Sub after querying Streams drops events emitted during the query window; subscribing before querying requires client deduplication buffers.
* Requires managing two separate Redis subsystems and connection pools for the same task data.

### Option 3: Full duplex bidirectional WebSocket connection directly from browser to agent service

Establish a persistent bidirectional WebSocket connection between the browser client and the FastAPI agent engine, streaming downstream logs and sending upstream intervention messages over a single socket frame protocol.

**Pros**:
* Single connection handles both downstream log streaming and upstream user interactions.
* Slightly lower round trip latency for rapid back and forth message exchange.

**Cons**:
* WebSockets bypass standard HTTP/2 multiplexing and require custom reconnection and heartbeat protocols.
* Browser WebSocket APIs do not support custom HTTP Authorization Bearer headers during the initial handshake, requiring token transmission via query parameters or cookies.
* Stateful socket connections complicate horizontal scaling and require sticky sessions or dedicated socket gateway servers.
* Corporate firewalls and reverse proxies frequently terminate or interfere with long lived WebSocket connections.

## Rationale

Option 1 is selected because it delivers low latency real time streaming while respecting operational reality and modern web constraints.

Direct browser connections to FastAPI over Server Sent Events resolve the primary architectural blocker in full stack Next.js applications: serverless function timeouts. By pointing `@microsoft/fetch-event-source` directly to the FastAPI API origin, streaming connections can stay open indefinitely without being terminated by edge gateway limits.

Server Sent Events are fundamentally superior to WebSockets (Option 3) for this workload because the data flow is overwhelmingly unidirectional from agent to browser. Server Sent Events run over standard HTTP/2 with built in browser reconnect mechanisms, transparent gzip compression, and full support for the `Last-Event-ID` header. Pairing Server Sent Events with dedicated REST POST endpoints for upstream interventions keeps the write path stateless, idempotent, and easy to secure using existing Clerk middleware and standard HTTP status codes (such as 409 Conflict when an interrupt has already been answered).

Choosing a unified Redis Streams architecture over dual Pub/Sub (Option 2) eliminates the subtle timing race conditions where events are either dropped or duplicated during reconnection. Because `XREAD BLOCK` handles both historical cursor catch up and blocking live notification over the exact same stream cursor, client reconnection logic is simple, robust, and zero maintenance.

Finally, implementing human collaboration via explicit LangGraph checkpoints and worker release ensures background workers remain available to process other tasks rather than sitting blocked on in memory sleep calls. Extending E2B sandbox timeouts prevents premature VM shutdown, and delayed queue watchdogs guarantee that stalled runs fail cleanly if developers do not answer. In flight log fallback allows clients on restrictive networks to poll current logs, while completed runs archive full compressed transcripts to PostgreSQL for permanent retention.
