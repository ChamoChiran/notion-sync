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
Centric Docs            root page: "Table of contents" (links to every page), then README.md
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

- The top-level `README.md` is not a page of its own: it becomes the root page's body, under a
  `## Table of contents` heading and a nested list of links to every published page. The
  folder pages stay attached to the root (the tool reads their tags back and rewrites them
  with the new body so Notion does not delete them).
- Git is the source of truth. Pages are overwritten on every change, so edit in git only.
- `--parent` is a Notion page URL (a regular page, not a person profile) or `workspace`
  for a private top-level page. It is only used on the first run.
- `notion-map.json` (folders, path → page id, content hash) is written next to where you
  run the command. **Commit it**, so every run updates the same pages. A map from an older
  layout is ignored and rebuilt.
- Pages cannot hold properties, so optional front matter (`status`, `owner`, `component`,
  `last_reviewed`) is shown as a one-line quote at the top of each page. Keep it flat (`key: value`, no inline
  comments):

  ```markdown
  ---
  status: Draft
  owner: Name
  last_reviewed: 2026-10-15
  order: 2
  ---
  # Page title
  ```

  The first `# ` heading becomes the page title (not repeated in the body).
- **Reading order**: within a folder, documents come first, then subfolders. Each is sorted
  by the `order` number in front matter (lowest first; no `order` sorts last), then by path.
  A folder takes its `order` from its `index.md`. The table of contents, the folder
  listings and Previous / Next all follow this order.
- **Navigation on every page**: a breadcrumb at the top (`Docs / Architecture / ...`, each
  part a link) and a footer `← Previous | Docs home | Next →` that walks the whole book in
  reading order: root, then each folder page followed by its documents. Changing the order
  or a title rewrites only the pages whose neighbours changed.
- **Folder pages**: a folder's `index.md` (or else `README.md`; not the top-level one) is the
  body of its folder page, followed by an "In this section" list. It has no page of its own.
  Without one, the folder page is just the list.
- **On this page**: pages with three or more `##`/`###` headings get Notion's table of
  contents block after the header.
- **Links**: relative `.md` links become Notion page links, `folder/` links become the
  folder page, and a link to a folder's `index.md` goes to the folder page. With
  `--source-url https://github.com/org/repo/blob/main`, links to other files inside the
  docs folder become links to that URL. Any link that resolves to nothing is left as is and
  printed as `warning:` (it would be a dead link in Notion). Section anchors
  (`file.md#heading`) are dropped, because Notion cannot link to a heading. Images are not
  touched.
- `--prune` moves pages for deleted files, and folders left empty, to Notion's trash.
- If a page is deleted in Notion, the next run recreates it. (Pages that list it catch up
  on the run after.)
- `--title` sets the root page title: required-ish on the first run (default `Docs`), and
  it renames the root when it differs later. The title is kept in `notion-map.json` for the
  breadcrumbs.
- A changed title in git renames the page. Not handled: moving a file (a moved file
  becomes a new page; use `--prune` to trash the old one).
- Upgrading from 0.4: the map file stays compatible. The first run rewrites every page once
  (new header and footer) and clears page icons: published pages carry none.

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
| `publisher.py` | `DocsPublisher` | publish a folder as a page tree |
| `nav.py` | `Navigation` | reading order, folder landing pages |
| `layout.py` | | breadcrumb, footer, summary line |
| `links.py` | `LinkRewriter` | resolve relative links, collect warnings |
| `cli.py` | `Cli` | argument parsing and output |
| `errors.py` | `NotionSyncError` + subclasses | user-facing errors |

## Tests

```powershell
$env:PYTHONPATH = "src"; py -m unittest discover -s tests -v
```
