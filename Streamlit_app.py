"""
Streamlit App (robust)
This file can run in two modes:
 1) Streamlit mode - if `streamlit` is installed, it runs the interactive app.
 2) Fallback CLI / notebook mode - if `streamlit` is NOT available (sandbox), it will run a non-interactive analysis pipeline and save outputs (CSV + Plotly HTML) so you can inspect results.

This addresses the error: ModuleNotFoundError: No module named 'streamlit' by providing a graceful fallback and clear instructions.

To run interactive app (recommended locally):
  pip install -r requirements.txt
  streamlit run streamlit_app.py

To run in fallback mode (no streamlit):
  python streamlit_app.py

"""

import sys
import os
import traceback
import pandas as pd
import numpy as np
import requests
import random
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import json

# ---------------------
# Shared data & logic
# ---------------------

def generate_survey(n=200, seed=42):
    from faker import Faker
    fake = Faker(['en_IN'])
    random.seed(seed)
    np.random.seed(seed)

    indian_cities = [
        'Mumbai','Delhi','Bangalore','Hyderabad','Chennai','Kolkata','Pune','Ahmedabad','Jaipur','Surat',
        'Lucknow','Kanpur','Nagpur','Indore','Thane','Bhopal','Visakhapatnam','Patna','Vadodara','Ghaziabad'
    ]
    electronics_keywords = [
        'phone','smartphone','mobile','charger','earbuds','headphones','laptop','tablet','smartwatch','speaker',
        'powerbank','cable','adapter','mouse','keyboard','monitor','webcam','hard drive','pendrive','router'
    ]
    rows = []
    for i in range(n):
        price_low = random.choice([500,1000,1500,2000,3000,5000,8000,10000,15000,20000])
        price_high = price_low + random.randint(2000,10000)
        rows.append({
            'user_id': f'USER_{i+1:04d}',
            'name': fake.name(),
            'age': random.randint(18,65),
            'city': random.choice(indian_cities),
            'preferred_category': 'electronics',
            'expected_price_low': price_low,
            'expected_price_high': price_high,
            'favorite_keyword': random.choice(electronics_keywords)
        })
    return pd.DataFrame(rows)


def fetch_products(expand=True, variants_per=20):
    api_url = "https://fakestoreapi.com/products"
    try:
        resp = requests.get(api_url, timeout=8)
        resp.raise_for_status()
        products_raw = resp.json()
    except Exception as e:
        # Network sandbox may block requests; return an empty list to be handled upstream
        print(f"WARN: fetch_products failed: {e}")
        products_raw = []

    electronics = [p for p in products_raw if p.get('category') == 'electronics']
    base = electronics if electronics else products_raw

    expanded = []
    for p in base:
        expanded.append(p)
        if expand:
            for i in range(1, variants_per+1):
                v = p.copy()
                v['price'] = round(p.get('price', 10) * random.uniform(0.7, 1.5) * 83, 2)
                v['id'] = f"{p.get('id')}_V{i}"
                v['title'] = f"{p.get('title','Product')} - Variant {i}"
                if 'rating' in v and isinstance(v['rating'], dict):
                    v['rating'] = {'rate': round(random.uniform(3.5,5.0),1), 'count': random.randint(10,1000)}
                expanded.append(v)

    products = []
    for x in expanded:
        products.append({
            'product_id': x.get('id'),
            'title': x.get('title'),
            'price': x.get('price', 0),
            'category': x.get('category', 'electronics'),
            'rating': x.get('rating', {}).get('rate', 0) if isinstance(x.get('rating', {}), dict) else 0,
            'rating_count': x.get('rating', {}).get('count', 0) if isinstance(x.get('rating', {}), dict) else 0
        })
    df = pd.DataFrame(products)
    return df


def calculate_score(price, rating, rating_count, user_price_low, user_price_high):
    mid_price = (user_price_low + user_price_high) / 2 if (user_price_low+user_price_high)>0 else 1
    price_distance = abs(price - mid_price) / mid_price
    price_penalty = price_distance * 2
    score = (rating * np.log1p(rating_count)) - price_penalty
    return score


def get_recommendations_for_user(user_row, df_products, top_n=5):
    if df_products is None or df_products.empty:
        return pd.DataFrame()
    buffer = 0.2
    price_low = user_row['expected_price_low'] * (1 - buffer)
    price_high = user_row['expected_price_high'] * (1 + buffer)
    candidates = df_products[(df_products['price']>=price_low) & (df_products['price']<=price_high)].copy()
    if candidates.empty:
        candidates = df_products.copy()
    candidates['score'] = candidates.apply(lambda r: calculate_score(r['price'], r['rating'], r['rating_count'], user_row['expected_price_low'], user_row['expected_price_high']), axis=1)
    return candidates.nlargest(min(top_n, len(candidates)), 'score')


def compute_metrics(df_survey, df_products, sample_n=50):
    out = {}
    out['category_coverage'] = (df_surve
