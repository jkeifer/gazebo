from __future__ import annotations

from gazebo.linkheader import NAV_RELS, format_link_header


def test_formats_a_single_link() -> None:
    link = {'href': 'https://x/a', 'rel': 'self', 'type': 'application/json'}
    header = format_link_header([link])
    assert header == '<https://x/a>; rel="self"; type="application/json"'


def test_joins_multiple_links_in_order() -> None:
    links = [
        {'href': 'https://x/a', 'rel': 'self'},
        {'href': 'https://x/b', 'rel': 'next'},
    ]
    header = format_link_header(links)
    assert header == '<https://x/a>; rel="self", <https://x/b>; rel="next"'


def test_filters_to_the_rel_allow_list() -> None:
    links = [
        {'href': 'https://x/a', 'rel': 'self'},
        {'href': 'https://x/item/1', 'rel': 'item'},  # not navigational
        {'href': 'https://x/b', 'rel': 'next'},
    ]
    header = format_link_header(links)
    assert 'rel="item"' not in header
    assert 'rel="self"' in header
    assert 'rel="next"' in header


def test_rels_none_includes_everything() -> None:
    links = [{'href': 'https://x/item/1', 'rel': 'item'}]
    assert 'rel="item"' in format_link_header(links, rels=None)


def test_custom_rel_list() -> None:
    links = [
        {'href': 'https://x/a', 'rel': 'self'},
        {'href': 'https://x/b', 'rel': 'next'},
    ]
    header = format_link_header(links, rels=['next'])
    assert 'rel="self"' not in header
    assert 'rel="next"' in header


def test_max_links_caps_output() -> None:
    links = [{'href': f'https://x/{rel}', 'rel': rel} for rel in NAV_RELS]
    header = format_link_header(links, max_links=2)
    assert header.count('rel=') == 2


def test_skips_links_missing_href_or_rel() -> None:
    links = [{'rel': 'self'}, {'href': 'https://x/a'}, {'href': 'https://x/b', 'rel': 'next'}]
    assert format_link_header(links) == '<https://x/b>; rel="next"'


def test_includes_title_when_latin1_encodable() -> None:
    links = [{'href': 'https://x/a', 'rel': 'self', 'title': 'Home'}]
    assert 'title="Home"' in format_link_header(links)


def test_drops_non_latin1_title_but_keeps_link() -> None:
    links = [{'href': 'https://x/a', 'rel': 'self', 'title': 'Jardín 🌱'}]
    header = format_link_header(links)
    assert header == '<https://x/a>; rel="self"'


def test_escapes_quotes_in_title() -> None:
    links = [{'href': 'https://x/a', 'rel': 'self', 'title': 'a "b" c'}]
    assert r'title="a \"b\" c"' in format_link_header(links)


def test_empty_when_nothing_qualifies() -> None:
    assert format_link_header([{'href': 'https://x/i', 'rel': 'item'}]) == ''


def test_drops_link_with_non_latin1_href() -> None:
    # a non-ASCII IRI href can't go in a latin-1 ASGI header; drop the link rather than
    # let the glue's encode() raise. The output must be latin-1-encodable.
    links = [
        {'href': 'https://x/花园', 'rel': 'self'},  # CJK, outside latin-1
        {'href': 'https://x/b', 'rel': 'next'},
    ]
    header = format_link_header(links)
    assert header == '<https://x/b>; rel="next"'
    header.encode('latin-1')  # would raise if a bad href leaked through


def test_drops_link_with_non_latin1_rel() -> None:
    # with filtering off, an arbitrary rel could be non-encodable too; drop that link.
    links = [{'href': 'https://x/a', 'rel': 'rel-🌱'}, {'href': 'https://x/b', 'rel': 'next'}]
    header = format_link_header(links, rels=None)
    assert header == '<https://x/b>; rel="next"'
    header.encode('latin-1')
