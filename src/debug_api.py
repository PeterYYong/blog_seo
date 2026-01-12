import sys
import os
import json
from src.data_fetcher import fetch_real_data

def load_secrets():
    with open("secrets.json", "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    secrets = load_secrets()
    keyword = "캠핑의자"
    print(f"Testing API with keyword: {keyword}")
    
    data = fetch_real_data(keyword, secrets)
    print("RAW DATA:", data)
    
    # Check simple logic
    sv = data['search_volume']
    docs = data['doc_count']
    if sv > 0:
        sk = docs / sv
        print(f"Sk: {sk:.2f}")
    else:
        print("Search Volume is 0 (Error or No Data)")

if __name__ == "__main__":
    main()
