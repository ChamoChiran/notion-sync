import argparse
import sys

from . import __version__
from .client import build_client
from .errors import NotionSyncError
from .page_ref import PageRef
from .service import PageSyncService


class Cli:
    """Command-line front end. Parses args, delegates to PageSyncService."""

    def __init__(self, service_factory=None):
        # Built lazily so `--help` works without NOTION_TOKEN set.
        self._service_factory = service_factory or (lambda: PageSyncService(build_client()))

    def build_parser(self):
        parser = argparse.ArgumentParser(
            prog="notion-sync", description="Read and update Notion pages from Markdown files."
        )
        parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
        sub = parser.add_subparsers(dest="command", required=True)

        pull = sub.add_parser("pull", help="download a Notion page as Markdown")
        pull.add_argument("page", help="page URL or ID")
        pull.add_argument("-o", "--output", help="write to this file instead of stdout")
        pull.set_defaults(handler=self._pull)

        push = sub.add_parser("push", help="replace a Notion page's content with a Markdown file")
        push.add_argument("file", help="Markdown file to upload")
        push.add_argument("page", help="page URL or ID")
        push.set_defaults(handler=self._push)

        search = sub.add_parser("search", help="find pages shared with the integration")
        search.add_argument("query")
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
        markdown = self._service_factory().pull(PageRef.parse(args.page))
        if args.output:
            with open(args.output, "w", encoding="utf-8", newline="\n") as f:
                f.write(markdown)
            print(f"wrote {args.output}")
        else:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stdout.write(markdown)

    def _push(self, args):
        with open(args.file, encoding="utf-8") as f:
            markdown = f.read()
        result = self._service_factory().push(PageRef.parse(args.page), markdown)
        print(
            f"pushed {result.blocks_written} top-level blocks "
            f"(removed {result.blocks_removed} old) to {result.page_id}"
        )

    def _search(self, args):
        for hit in self._service_factory().search(args.query):
            print(f"{hit.page_id}  {hit.title}  {hit.url}")


def main(argv=None):
    return Cli().run(argv)
