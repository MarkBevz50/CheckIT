"""parser_service name normalisation and search-query simplification (pure functions)."""

from app.services.parser_service import _normalize_unicode, _simplify_product_name


def test_normalize_replaces_invisible_characters_and_collapses_spaces():
    assert _normalize_unicode("a  b​c  d ") == "a b c d"


def test_queries_go_from_specific_to_general():
    queries = _simplify_product_name("Масло вершкове моноліт жирністю не менше 72%")
    assert queries == [
        "Масло вершкове моноліт жирністю не менше 72%",
        "Масло вершкове жирністю 72%",
        "Масло вершкове 72%",
        "Масло вершкове",
    ]


def test_first_query_is_the_full_normalized_name():
    queries = _simplify_product_name("Сік апельсиновий Садочок 0,95​л")
    assert queries[0] == "Сік апельсиновий Садочок 0,95 л"


def test_short_name_gives_a_single_query():
    assert _simplify_product_name("Цукор білий") == ["Цукор білий"]
    assert _simplify_product_name("А4") == ["А4"]


def test_blank_name_gives_no_queries():
    assert _simplify_product_name("   ") == []


def test_queries_are_unique():
    queries = _simplify_product_name("Масло вершкове 72%")
    assert len(queries) == len(set(queries))


def test_percentage_is_kept_in_a_shortened_query():
    assert "Масло вершкове 72%" in _simplify_product_name("Масло вершкове моноліт жирністю не менше 72%")
