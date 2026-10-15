import argparse
import sys

from . import __version__
from .client import build_client
from .errors import NotionSyncError
from .page_ref import PageRef
from .publisher import DocsPublisher
from .service import PageSyncService


class Cli:
    """Command-line front end. Parses args, delegates to PageSyncService."""

    def __init__(self, service_factory=None, publisher_factory=None):
        # Built lazily so `--help` works without NOTION_TOKEN set.
        self._service_factory = service_factory or (lambda: PageSyncService(build_client()))
        self._publisher_factory = publisher_factory or (lambda: DocsPublisher(build_client()))

    def build_parser(self):
        parser = argparse.ArgumentParser(
            prog="notion-sync", description="Read and update Notion pages as Markdown."
        )
        parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
        sub = parser.add_subparsers(dest="command", required=True)

        pull = sub.add_parser("pull", help="download a Notion page as Markdown")
        pull.add_argument("page", help="page URL or ID")
        pull.add_argument("-o", "--output", help="write to this file instead of stdout")
        pull.set_defaults(handler=self._pull)

        push = sub.add_parser("push", help="replace a page's content with a Markdown file")
        push.add_argument("file", help="Markdown file to upload")
        push.add_argument("page", help="page URL or ID")
        push.add_argument(
            "--allow-deleting-content",
            action="store_true",
            help="permit the push to delete child pages and databases",
        )
        push.set_defaults(handler=self._push)

        edit = sub.add_parser("edit", help="replace specific text on a page, leaving the rest")
        edit.add_argument("page", help="page URL or ID")
        edit.add_argument(
            "-r", "--replace", nargs=2, action="append", required=True,
            metavar=("OLD", "NEW"), help="exact text to find and its replacement (repeatable)",
        )
        edit.add_argument("--all", action="store_true", help="replace every match, not just a unique one")
        edit.set_defaults(handler=self._edit)

        publish = sub.add_parser(
            "publish", help="publish a folder of Markdown files into a Notion database"
        )
        publish.add_argument("folder", help="docs folder to publish")
        publish.add_argument("--state", default="notion-map.json",
                             help="file mapping docs to Notion pages (commit it)")
        publish.add_argument("--parent", help="Notion page URL to create the database under (first run only)")
        publish.add_argument("--title", default="Docs", help="database title (first run only)")
        publish.add_argument("--source-url",
                             help="base URL of the files in git, stored in each page's Source property")
        publish.add_argument("--prune", action="store_true",
                             help="move pages whose file no longer exists to Notion's trash")
        publish.set_defaults(handler=self._publish)

        search = sub.add_parser("search", help="find pages the token can access")
        search.add_argument("query", nargs="?", default="", help="title text; omit to list all")
        search.set_defaults(handler=self._search)
        return parser

    def run(self, argv=None):
        args = self.build_parser().parse_args(argv)
        try:
            args.handler(args)
        except NotionSyncError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0

    # -- command handlers ----------------------------------------------

    def _pull(self, args):
        pulled = self._service_factory().pull(PageRef.parse(args.page))
        if pulled.truncated:
            print(
                f"warning: page truncated or partly inaccessible "
                f"({len(pulled.unknown_block_ids)} unknown blocks)",
                file=sys.stderr,
            )
        if args.output:
            with open(args.output, "w", encoding="utf-8", newline="\n") as f:
                f.write(pulled.markdown)
            print(f"wrote {args.output}")
        else:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stdout.write(pulled.markdown)

    def _push(self, args):
        with open(args.file, encoding="utf-8") as f:
            markdown = f.read()
        page = PageRef.parse(args.page)
        self._service_factory().push(page, markdown, args.allow_deleting_content)
        print(f"pushed {args.file} to {page.id}")

    def _edit(self, args):
        page = PageRef.parse(args.page)
        replacements = [tuple(pair) for pair in args.replace]
        self._service_factory().edit(page, replacements, args.all)
        print(f"applied {len(replacements)} replacement(s) to {page.id}")

    def _publish(self, args):
        report = self._publisher_factory().publish(
            args.folder, args.state, parent=args.parent, title=args.title,
            source_base_url=args.source_url, prune=args.prune,
        )
        print(
            f"published: {report.created} created, {report.updated} updated, "
            f"{report.unchanged} unchanged, {report.trashed} trashed"
        )

    def _search(self, args):
        for hit in self._service_factory().search(args.query):
            print(f"{hit.page_id}  {hit.title}  {hit.url}")


def main(argv=None):
    return Cli().run(argv)
