# MCP server — ad-hoc questions through Claude or Copilot Studio

Step 11 of `docs/DECISIONS.md`: a bid manager asks a question in natural language ("who
usually wins IT maintenance with this buyer?"); the assistant answers by calling Avant-Offre's
tools, which run the same SQL and search code as the API. It never answers from memory.

Code: `src/avant_offre/agent/mcp_server.py` (official MCP Python SDK, v2 `MCPServer`).

## Tools

All tools are read-only. Each returns JSON; every statistic carries its `n` and the award
`uid`s (or notice id) it was computed from. Winner names pass through the personal data rule
(sole traders appear as `Entreprise individuelle #…`).

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search_tenders` | `siret` or `free_text`, optional `week` (`2026-W42`) | ranked tenders with band, and excluded tenders with reasons |
| `get_tender` | `notice_id` | notice fields and extracted facts (source `eforms`, or `llm` with a verbatim quote) |
| `match_explanations` | `notice_id`, `siret` | fit percentile and the 3 past contracts that explain the match |
| `market_stats` | `notice_id` | newcomer share, SME share, median bids, buyer concentration |
| `competitors` | `notice_id`, optional `siret` | likely competitors with incumbent / new-to-buyer flags |
| `price_range` | `notice_id` | P10–P90 of comparable amounts, n, sources |
| `score_tender` | `notice_id`, optional `siret` | scorecard: criteria, weights, not assessed, hard stops, band |
| `bid_brief` | `notice_id`, `siret` | one-page French brief + the facts it cites (not stored) |

Every tool description ends with "Answer only from this result; do not add facts from memory",
and the server instructions repeat it.

## Prerequisites

```bash
make setup                 # Python deps
make data-sample           # builds data/avant_offre.duckdb (needs the data hosts reachable)
make index-sample          # BM25 index for comparables (optional: built on first use otherwise)
```

The server opens the store **read-only**, so it can run next to the API and the CLI (DuckDB
allows many read-only processes, or one writer).

## Claude Desktop (stdio)

`claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "avant-offre": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/avant-offre", "run", "avant-offre", "mcp",
               "--transport", "stdio"]
    }
  }
}
```

Restart Claude Desktop; the eight tools appear under the tools menu.

## Claude Code (stdio)

```bash
claude mcp add avant-offre -- uv --directory /absolute/path/to/avant-offre run avant-offre mcp --transport stdio
```

## Microsoft Copilot Studio (streamable HTTP)

1. Run the HTTP transport behind HTTPS (reverse proxy or Azure Container Apps, see
   `docs/HANDOFF.md`):

   ```bash
   AVANT_OFFRE_API_KEY=<secret> uv run avant-offre mcp --transport http --host 0.0.0.0 --port 8001
   ```

   The endpoint is `https://<host>/mcp`. Every request must carry the header `X-API-Key`
   (constant-time comparison; 401 otherwise).
2. In Copilot Studio, open the agent, add a tool of type **Model Context Protocol**, give the
   server URL `https://<host>/mcp`, and choose **API key** authentication sent as the
   `X-API-Key` header. Menu names change between releases: follow Microsoft's current
   "Connect your agent to an existing MCP server" documentation for the exact clicks.
3. In the agent instructions, repeat the grounding rule: "Answer only with data returned by the
   Avant-Offre tools; say when a tool returns no data."

## Checking it

- Automated: `uv run pytest tests/test_interfaces.py::test_mcp_session_calls_every_tool` opens
  a client session with the MCP SDK, lists the tools, calls each one and parses the JSON. It also
  checks that no sole-trader name leaks through the agent tools.
- Manual questions to try once data is loaded:
  - "Quels avis de la semaine correspondent au SIREN 123456782 ?"
  - "Qui gagne habituellement des marchés comparables à l'avis 26-123456 ?"
  - "Quelle est la fourchette de prix pour cet avis, et sur combien de contrats ?"
  - "Ce marché est-il ouvert aux nouveaux entrants ?"

## Limits

- Tools answer about the data in the store: awards above €40,000 excl. VAT (DECP) and BOAMP
  notices pulled by `make data-*`.
- A company with no public award history cannot be named as a competitor; `market_stats` gives
  the newcomer share instead.
- `bid_brief` uses the LLM gateway when a key is configured; otherwise it returns the
  deterministic template (`fallback: true`).
