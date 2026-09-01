from src.seo_service import KeywordInput, MetricsInput, calculate_metrics, configuration_status, expand


def test_metrics_are_structured_and_sourced():
    result = calculate_metrics(MetricsInput(keyword="서울 캠핑", monthly_search_volume=2400, total_documents=1200))
    assert result["ok"] is True
    assert result["data"]["classification"] == "blue-ocean"
    assert result["data"]["saturation_index"] == 0.5
    assert result["retrieved_at"].endswith("+00:00")
    assert result["sources"]


def test_expansion_is_deterministic_and_deduplicated():
    first = expand(KeywordInput(keyword=" 캠핑  의자 "))
    second = expand(KeywordInput(keyword="캠핑 의자"))
    assert first["data"] == second["data"]
    assert len(first["data"]["keywords"]) == len(set(first["data"]["keywords"]))


def test_configuration_never_exposes_secret_values(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "do-not-leak")
    result = configuration_status()
    assert "do-not-leak" not in str(result)
    assert result["data"]["variables"]["NAVER_CLIENT_SECRET"] is True
