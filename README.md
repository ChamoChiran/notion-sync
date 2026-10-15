# notion-sync

Read and update Notion pages as Markdown from the command line. Built on Notion's native
page Markdown API (`Notion-Version: 2026-03-11`). Pure standard library, Python 3.9+.

## Setup

Pick one kind of token and put it in `NOTION_TOKEN`:

- **Personal access token** (simplest): Developer portal → *Personal access tokens* →
  *New token*. Acts as you, so no page sharing needed. On the Free plan only workspace
  owners can create one.
- **Internal integration**: <https://www.notion.so/profile/integrations>. Then on each page
  open `...` → **Connections** and add the integration.

```powershell
py -m pip install -e .
$env:NOTION_TOKEN = "secret_xxx"
```

## Usage

```powershell
notion-sync search "meeting"                       # find pages the token can access
notion-sync pull <page-url-or-id> -o doc.md        # read a page as Markdown
notion-sync push doc.md <page-url-or-id>           # replace the whole page body
notion-sync edit <page-url-or-id> -r "old text" "new text"   # change just that text
```

- `publish` mirrors a whole docs folder into a Notion database (see below).
- `push` replaces content in place; page ID, URL and sharing stay the same. It refuses to
  delete child pages or databases unless you pass `--allow-deleting-content`.
- `edit` takes `-r OLD NEW` (repeatable). `OLD` must match exactly one place, unless `--all`.
  Everything else on the page is untouched, so it is the safest way to make small changes.
- Pull right before editing: `push` overwrites changes made in Notion in between.
- Without installing: `py -m notion_sync ...` with `PYTHONPATH=src`.

## Publishing a docs folder (git → Notion)

Keep docs in git and mirror them into Notion as a tree of pages that follows the folders:

```
Centric Docs            root page
├─ Guide                README.md
├─ Architecture         folder page
│  ├─ Overview          architecture/00-overview.md
│  └─ Components        folder page
│     └─ Backend API    architecture/components/backend-api.md
└─ Templates            folder page
```

```powershell
# first run: create the root page and publish everything
notion-sync publish docs --parent workspace --title "Centric Docs"
# later runs (CI): only changed files are rewritten
notion-sync publish docs --prune
```

- Git is the source of truth. Pages are overwritten on every change, so edit in git only.
- `--parent` is a Notion page URL (a regular page, not a person profile) or `workspace`
  for a private top-level page. It is only used on the first run.
- `notion-map.json` (folders, path → page id, content hash) is written next to where you
  run the command. **Commit it**, so every run updates the same pages. A map from an older
  layout is ignored and rebuilt.
- Pages cannot hold properties, so optional front matter (`status`, `owner`, `component`,
  `last_reviewed`) is shown as a one-line summary at the top of each page. Keep it flat
  (`key: value`, no inline comments):

  ```markdown
  ---
  status: Draft
  owner: Name
  last_reviewed: 2026-10-15
  ---
  # Page title
  ```

  The first `# ` heading becomes the page title (not repeated in the body).
- Relative links between `.md` files are rewritten to Notion page links; links to files that
  aren't published stay as they are.
- Order: top-level files first, then folders, alphabetical by path.
- `--prune` moves pages for deleted files, and folders left empty, to Notion's trash.
- If a page is deleted in Notion, the next run recreates it.
- A changed title in git renames the page. Not handled: moving a file (a moved file
  becomes a new page; use `--prune` to trash the old one).

`notion-sync trash <page-url-or-id> [--database]` moves a page or database to Notion's trash.

## Limits

- Large writes (over ~5,000 blocks) are rejected by Notion; split the content. Async writes
  (`allow_async`) are not supported yet.
- Pages over ~20,000 blocks, or with content the token cannot see, come back truncated;
  `pull` prints a warning.
- Bookmarks, embeds and link previews appear as `<unknown>` tags and are not editable as Markdown.
- Synced pages cannot be updated.
- Notion separates top-level blocks with a single newline and uses `<br>` for line breaks.

## Layout

| Module | Class | Role |
|---|---|---|
| `config.py` | `Config` | token and API version from environment |
| `page_ref.py` | `PageRef` | parse a page URL or ID |
| `client.py` | `NotionClient` | HTTP, auth, retry/backoff, Markdown endpoints |
| `service.py` | `PageSyncService` | pull / push / edit / search use cases |
| `cli.py` | `Cli` | argument parsing and output |
| `errors.py` | `NotionSyncError` + subclasses | user-facing errors |

## Tests

```powershell
$env:PYTHONPATH = "src"; py -m unittest discover -s tests -v
```
