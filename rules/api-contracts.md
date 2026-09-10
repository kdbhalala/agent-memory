# API Contracts & MCP Tool Interfaces

The `agent-memory` MCP server communicates via standard JSON-RPC 2.0 over `stdio`.

## Tool Specifications

### 1. `memory_recall`
Fast search over working session memory (decisions, past tool fixes, context).
- **Parameters**:
  - `query` (string, required): Search query or keywords.
  - `project` (string, optional): Project filter (e.g. `"agent-memory"`).
  - `limit` (integer, default: 5): Maximum observations to return.
- **Returns**: Markdown formatted string with ranked observations.

### 2. `memory_recall_deep`
Tiered recall: Searches L1 session memory AND L2 durable knowledge graph.
- **Parameters**:
  - `query` (string, required): Search query or keywords.
  - `project` (string, optional): Project filter.
  - `limit` (integer, default: 5): Maximum hits per layer.
- **Returns**: Markdown string structured into `## recent` and `## durable`.

### 3. `memory_record`
Persists verified technical learnings, decisions, or rules into session memory and optionally long-term knowledge graph.
- **Parameters**:
  - `text` (string, required): Detailed description of the decision, fix, or convention.
  - `title` (string, optional): Short descriptive title.
  - `category` (string, optional, default: `"decision"`): One of `"architecture"`, `"pattern"`, `"bugfix"`, `"convention"`, `"decision"`.
  - `project` (string, optional): Target project name.
  - `supersedes` (string, optional): ID (`#1234`) or keywords of an older memory that this record overrides/replaces.
  - `relations` (array of objects, optional): Knowledge graph triples to store directly into L2 durable memory:
    - `source` (string, required): Source concept/entity.
    - `relation` (string, required): Relationship type (`USES`, `REPLACES`, `IMPLEMENTS`, `FORBIDS`).
    - `target` (string, required): Target concept/entity.
    - `fact` (string, optional): Brief statement of the relationship.
- **Returns**: Confirmation message with assigned observation ID, count of L2 edges added, confirmation of superseded records, and an optional `[Notice - Potential Overlap Found]` steering alert if conflicting precedents exist.

### 4. `memory_promote`
Curates high-signal items from working memory into the knowledge graph.
- **Parameters**:
  - `project` (string, optional): Target project name.
  - `limit` (integer, default: 20): Maximum candidates to process.
- **Returns**: Count of newly ingested graph nodes and edges.

### 5. `memory_sync`
Controls multi-device Git synchronization and periodic database compaction.
- **Parameters**:
  - `action` (string, default: `"sync"`): One of `"sync"`, `"status"`, or `"dedupe"`.
- **Returns**: Execution summary or status report.
