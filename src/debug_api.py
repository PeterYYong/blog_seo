try:
    from .calculator import calculate_saturation
    from .data_fetcher import RealDataFetcher
    from .seo_sources import SourceError
except ImportError:  # Support ``python src/debug_api.py`` from the project root.
    from calculator import calculate_saturation
    from data_fetcher import RealDataFetcher
    from seo_sources import SourceError


def main() -> int:
    keyword = "캠핑의자"
    print(f"Testing API with keyword: {keyword}")

    fetcher = RealDataFetcher()
    try:
        data = {
            "keyword": keyword,
            "search_volume": fetcher.get_search_volume(keyword),
            "doc_count": fetcher.get_doc_count(keyword),
        }
    except SourceError as exc:
        print(f"API unavailable: {exc}")
        return 1
    print("RAW DATA:", data)

    # Check simple logic
    sv = data['search_volume']
    docs = data['doc_count']
    if sv > 0:
        sk = calculate_saturation(docs, sv)
        print(f"Sk: {sk:.2f}")
    else:
        print("Search Volume is 0 (verified zero demand, not an API error)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
