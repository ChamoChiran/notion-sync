# notion-sync

Read and update Notion pages from Markdown files. Pure standard library, Python 3.9+.

## Setup

1. Create an internal integration at <https://www.notion.so/profile/integrations> and copy its token.
2. On the Notion page, open `...` → **Connections** and add the integration.
3. Install and set the token:

```powershell
py -m pip install -e .
$env:NOTION_TOKEN = "secret_xxx"
```

## Usage

```powershell
notion-sync search "meeting"              # list pages shared with the integration
notion-sync pull <page-url-or-id> -o doc.md
notion-sync push doc.md <page-url-or-id>  # replaces the page content in place
```

Without installing: `py -m notion_sync ...` from `src/`.

`push` keeps the page ID, URL and sharing; it replaces the blocks inside. Pull right
before editing, since edits made in Notion in between are overwritten.

## Supported Markdown

Headings (1-3), paragraphs, bulleted / numbered / to-do lists (nested), quotes, fenced
code, dividers, and inline **bold**, *italic*, `code`, ~~strike~~, links.
Tables, images, embeds and databases are not supported: `pull` emits an
`<!-- unsupported block -->` comment and `push` drops it.

## Layout

| Module | Class | Role |
|---|---|---|
| `config.py` | `Config` | token and API version from environment |
| `page_ref.py` | `PageRef` | parse a page URL or ID |
| `client.py` | `NotionClient` | HTTP, retry/backoff, pagination |
| `richtext.py` | `InlineParser`, `RichTextRenderer` | inline Markdown ↔ rich text |
| `parser.py` | `MarkdownParser` | Markdown → Notion blocks |
| `renderer.py` | `MarkdownRenderer` | Notion blocks → Markdown |
| `service.py` | `PageSyncService` | pull / push / search use cases |
| `cli.py` | `Cli` | argument parsing and output |

## Tests

```powershell
$env:PYTHONPATH = "src"; py -m unittest discover -s tests -v
```
