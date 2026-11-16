import re
from urllib.parse import urlparse

from django import template
from django.utils.html import format_html, format_html_join

register = template.Library()

CITATION_PATTERN = re.compile(r"\[(\d+)\]")


def safe_source_url(url):
    parsed = urlparse(str(url or ""))
    return str(url) if parsed.scheme in {"http", "https"} and parsed.netloc else None


@register.simple_tag
def linked_citations(text, sources):
    """Escape model output while turning known citation numbers into links."""
    source_urls = {
        int(source["number"]): safe_source_url(source.get("url"))
        for source in (sources or [])
        if str(source.get("number", "")).isdigit()
    }
    pieces = []
    cursor = 0
    for match in CITATION_PATTERN.finditer(str(text)):
        pieces.append(str(text)[cursor:match.start()])
        url = source_urls.get(int(match.group(1)))
        if url:
            pieces.append(format_html(
                '<a class="citation-link" href="{}" target="_blank" '
                'rel="noopener noreferrer" aria-label="Open source {}">{}</a>',
                url,
                match.group(1),
                match.group(0),
            ))
        else:
            pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(str(text)[cursor:])
    return format_html_join("", "{}", ((piece,) for piece in pieces))
