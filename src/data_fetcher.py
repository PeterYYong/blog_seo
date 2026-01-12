import hashlib
import hmac
import base64
import time
import urllib.request
import urllib.parse
import json
import os
import requests
from typing import Dict, Any, Optional, List

class RealDataFetcher:
    def __init__(self):
        self.secrets = self._load_secrets()
        self.ad_api_key = self.secrets.get("NAVER_AD_API_KEY")
        self.ad_secret_key = self.secrets.get("NAVER_AD_SECRET_KEY")
        self.customer_id = self.secrets.get("NAVER_CUSTOMER_ID")
        self.client_id = self.secrets.get("NAVER_CLIENT_ID")
        self.client_secret = self.secrets.get("NAVER_CLIENT_SECRET")
        
        self.ad_base_url = "https://api.naver.com"
        self.search_base_url = "https://openapi.naver.com/v1/search/blog.json"

    def _load_secrets(self) -> Dict[str, str]:
        """
        Hybrid Auth:
        1. Try loading from Streamlit secrets (Cloud).
        2. Fallback to local secrets.json (Local).
        """
        # 1. Try Streamlit Secrets
        try:
            import streamlit as st
            if hasattr(st, "secrets") and "NAVER_AD_API_KEY" in st.secrets:
                return st.secrets
        except ImportError:
            pass
        except Exception:
            pass

        # 2. Fallback to Local secrets.json
        paths = ["secrets.json", "../secrets.json", os.path.join(os.path.dirname(__file__), "../secrets.json")]
        for p in paths:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
        
        raise FileNotFoundError("Authentication Failed: 'secrets.json' not found locally, and Streamlit secrets not available.")

    def _generate_signature(self, timestamp: str, method: str, uri: str) -> str:
        """Generates HMAC-SHA256 signature for Naver Ad API."""
        message = f"{timestamp}.{method}.{uri}"
        hash = hmac.new(
            self.ad_secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        )
        hash.hexdigest()
        return base64.b64encode(hash.digest()).decode("utf-8")

    def _get_header(self, method: str, uri: str) -> Dict[str, str]:
        """Returns headers for Naver Ad API."""
        timestamp = str(round(time.time() * 1000))
        signature = self._generate_signature(timestamp, method, uri)
        return {
            "Content-Type": "application/json; charset=UTF-8",
            "X-Timestamp": timestamp,
            "X-API-KEY": self.ad_api_key,
            "X-Customer": self.customer_id,
            "X-Signature": signature,
        }

    def get_search_volume(self, keyword: str) -> int:
        """
        Fetches monthly search volume (PC+Mobile) using Naver Ad API (RelKwdStat).
        """
        uri = "/keywordstool"
        method = "GET"
        params = {"hintKeywords": keyword.replace(" ", ""), "showDetail": 1}
        
        try:
            headers = self._get_header(method, uri)
            response = requests.get(f"{self.ad_base_url}{uri}", params=params, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            if not data.get("keywordList"):
                return 0
                
            for item in data["keywordList"]:
                if item["relKeyword"].replace(" ", "") == keyword.replace(" ", ""):
                    pc_qc = item["monthlyPcQcCnt"]
                    mo_qc = item["monthlyMobileQcCnt"]
                    
                    if isinstance(pc_qc, str) and "<" in pc_qc: pc_qc = 10
                    if isinstance(mo_qc, str) and "<" in mo_qc: mo_qc = 10
                    
                    return int(pc_qc) + int(mo_qc)
            
            # Fallback to first item
            if data["keywordList"]:
                 item = data["keywordList"][0]
                 pc_qc = item["monthlyPcQcCnt"]
                 mo_qc = item["monthlyMobileQcCnt"]
                 if isinstance(pc_qc, str) and "<" in pc_qc: pc_qc = 10
                 if isinstance(mo_qc, str) and "<" in mo_qc: mo_qc = 10
                 return int(pc_qc) + int(mo_qc)
            
            return 0
            
        except Exception as e:
            # print(f"Ad API Error: {e}")
            return 0

    def get_doc_count(self, keyword: str) -> int:
        """
        Fetches total blog document count using Naver Search API.
        """
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret
        }
        params = {"query": keyword, "display": 1}
        
        try:
            # Short sleep to prevent rate limiting, though app might need more robust handling
            time.sleep(0.1) 
            response = requests.get(self.search_base_url, headers=headers, params=params)
            
            if response.status_code != 200:
                return 0
                
            data = response.json()
            return data.get("total", 0)
            
        except Exception as e:
            # print(f"Search API Error: {e}")
            return 0

    def get_related_keywords(self, seed_keyword: str) -> List[Dict[str, Any]]:
        """
        Fetches related keywords from Naver Ad API based on seed.
        Returns list of dicts: {'keyword': str, 'volume': int}
        Filters out low volume keywords (< 100).
        """
        uri = "/keywordstool"
        method = "GET"
        params = {"hintKeywords": seed_keyword.replace(" ", ""), "showDetail": 1}
        
        related_list = []
        
        try:
            headers = self._get_header(method, uri)
            response = requests.get(f"{self.ad_base_url}{uri}", params=params, headers=headers)
            # response.raise_for_status() # Optional: Ad API sometimes returns errors if busy
            
            if response.status_code != 200:
                 return []
            
            data = response.json()
            if not data.get("keywordList"):
                return []
                
            for item in data["keywordList"]:
                kw = item["relKeyword"]
                pc_qc = item["monthlyPcQcCnt"]
                mo_qc = item["monthlyMobileQcCnt"]
                
                # Normalize values
                if isinstance(pc_qc, str) and "<" in pc_qc: pc_qc = 10
                if isinstance(mo_qc, str) and "<" in mo_qc: mo_qc = 10
                
                total_vol = int(pc_qc) + int(mo_qc)
                
                # Filter low volume
                if total_vol >= 100:
                    related_list.append({
                        "keyword": kw,
                        "volume": total_vol
                    })
            
            return related_list

        except Exception as e:
            print(f"Related Keyword Error: {e}")
            return []

def fetch_keyword_data(keyword: str) -> Dict[str, Any]:
    """
    Main entry point used by main.py.
    Loads secrets internally.
    Returns dictionary with Capitalized keys matching main.py expectations.
    """
    try:
        fetcher = RealDataFetcher()
        sv = fetcher.get_search_volume(keyword)
        docs = fetcher.get_doc_count(keyword)
        
        return {
            "Keyword": keyword,
            "Monthly_Search_Volume": sv,
            "Total_Docs": docs,
            "SmartBlock_Type": "Real Analysis Required" 
        }
    except Exception as e:
        print(f"Fetcher Init Error: {e}")
        return None
