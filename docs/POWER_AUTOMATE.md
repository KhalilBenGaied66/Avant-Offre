# Weekly digest — Power Automate delivery

Step 12 of `docs/DECISIONS.md`: Avant-Offre builds the digest payload; delivery is a Power
Automate flow that IT already governs. Avant-Offre itself never sends a message.

Payload endpoints (API key in the `X-API-Key` header):

| Endpoint | Content |
| --- | --- |
| `GET /digest/{siret}/weekly[?week=2026-W42]` | `digest` (JSON), `adaptive_card` (Adaptive Card 1.4), `teams_message` (webhook envelope) |
| `GET /digest/{siret}/weekly.html` | the same digest as an email-friendly HTML page |

The card uses schema **1.4**, rendered by every Teams client. Its elements are modelled with
strict pydantic types (`src/avant_offre/digest/adaptive_card.py`) and the test suite validates
every generated card against them. To preview a card: paste `adaptive_card` into the Adaptive
Cards Designer (adaptivecards.io/designer), host app "Microsoft Teams".

## Flow A — HTTP connector (premium licence)

The **HTTP** action is a premium connector: the flow owner needs a Power Automate Premium (or
per-flow) licence.

| # | Step | Configuration |
| --- | --- | --- |
| 1 | Trigger **Recurrence** | Frequency: Week · On these days: Monday · At these hours: 8 · At these minutes: 0 · Time zone: (UTC+01:00) Brussels, Copenhagen, Madrid, Paris |
| 2 | **Initialize variable** `siret` | String, the company's SIRET or SIREN |
| 3 | **HTTP** — get the digest | Method GET · URI `https://<api-host>/digest/@{variables('siret')}/weekly` · Headers `X-API-Key`: the key, read from Azure Key Vault (**Get secret** action) rather than typed in the flow; turn on *Secure inputs/outputs* |
| 4 | **Parse JSON** | Content: `body('HTTP')` · Schema: generate it from a sample response |
| 5 | **Condition** | `body('Parse_JSON')?['digest']?['counts']?['eligible']` is greater than 0 (skip empty weeks) |
| 6 | **Post card in a chat or channel** (Microsoft Teams) | Post as: Flow bot · Post in: Channel · Team / Channel: the bid office channel · Adaptive Card: `string(body('Parse_JSON')?['adaptive_card'])` |
| 7 | **HTTP** — get the HTML digest | GET `https://<api-host>/digest/@{variables('siret')}/weekly.html`, same header |
| 8 | **Send an email (V2)** (Office 365 Outlook) | To: bid office distribution list · Subject: `Avant-Offre — sélection de la semaine` · Body: `body('HTTP_2')` (the editor's code view keeps the HTML) |
| 9 | **Scope** + **Run after: has failed** | On failure of steps 3–8: post a plain message to the IT channel with `workflow()?['run']?['name']` so the run can be inspected |

Repeat steps 2–8 per company profile (or loop over an array variable).

## Flow B — no premium licence

Without the premium HTTP connector, invert the direction: Avant-Offre writes the digest files
locally, and a standard-connector flow picks them up.

1. **On the Avant-Offre host** (scheduled by IT: cron, Azure Container Apps job, Windows Task
   Scheduler), Monday 07:45:

   ```bash
   uv run avant-offre digest --siret <siret> --out /srv/avant-offre/digest/<siret>/$(date +%G-W%V)
   ```

   It writes `digest.json`, `card.json` and `digest.html` to a local folder. IT decides how that
   folder reaches Microsoft 365 (OneDrive sync client on the host, or an existing file-share
   integration); Avant-Offre does not write to Microsoft 365 itself.
2. **Flow**, all standard connectors:

| # | Step | Configuration |
| --- | --- | --- |
| 1 | Trigger **When a file is created** (OneDrive for Business or SharePoint) | Folder: the synced `digest` folder |
| 2 | **Condition** | File name is `card.json` |
| 3 | **Get file content** | the triggering file |
| 4 | **Post card in a chat or channel** | Adaptive Card: `base64ToString(body('Get_file_content')?['$content'])` |
| 5 | **Get file content using path** | `<same folder>/digest.html` |
| 6 | **Send an email (V2)** | Body: `base64ToString(body('Get_file_content_using_path')?['$content'])` |

## Governance notes for IT

- Use a service account for the flow connections, not a personal account.
- Store the API key in Azure Key Vault; rotate it by updating the secret and the server's
  `AVANT_OFFRE_API_KEY` together.
- Add the HTTP connector and the API host to the environment's DLP policy (business group).
- The digest contains no personal data beyond what the personal data rule allows: sole traders
  are pseudonymized before any payload is built.
