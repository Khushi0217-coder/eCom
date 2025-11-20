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
    out['category_coverage'] = (df_survey['preferred_category'] == 'electronics').mean() * 100

    def check_price_match(row):
        matches = df_products[(df_products['price']>=row['expected_price_low']) & (df_products['price']<=row['expected_price_high'])]
        return len(matches)>0

    df_survey = df_survey.copy()
    df_survey['price_match'] = df_survey.apply(check_price_match, axis=1)
    out['price_accuracy'] = df_survey['price_match'].mean()*100

    precision_1_keyword=[]
    precision_3_keyword=[]
    precision_1_price=[]
    precision_3_price=[]

    for _, u in df_survey.head(sample_n).iterrows():
        recs = get_recommendations_for_user(u, df_products, top_n=3)
        if recs.empty:
            continue
        kw = u['favorite_keyword'].lower()
        precision_1_keyword.append(int(kw in recs.iloc[0]['title'].lower()))
        precision_3_keyword.append(sum([kw in t.lower() for t in recs['title']])/min(3,len(recs)))
        precision_1_price.append(int(u['expected_price_low']<=recs.iloc[0]['price']<=u['expected_price_high']))
        price_matches = sum([u['expected_price_low']<=p<=u['expected_price_high'] for p in recs['price']])
        precision_3_price.append(price_matches/min(3,len(recs)))

    out['precision_1_keyword'] = np.mean(precision_1_keyword)*100 if precision_1_keyword else 0
    out['precision_3_keyword'] = np.mean(precision_3_keyword)*100 if precision_3_keyword else 0
    out['precision_1_price'] = np.mean(precision_1_price)*100 if precision_1_price else 0
    out['precision_3_price'] = np.mean(precision_3_price)*100 if precision_3_price else 0
    return out

# ---------------------
# Fallback CLI / Notebook runner (no streamlit)
# ---------------------

def run_fallback(save_folder='output'):
    os.makedirs(save_folder, exist_ok=True)
    print('Running fallback (non-interactive) pipeline...')

    # Load survey CSV if present otherwise generate
    if os.path.exists('survey_static.csv'):
        df_survey = pd.read_csv('survey_static.csv')
        print('Loaded survey_static.csv')
    else:
        df_survey = generate_survey(200)
        print('Generated synthetic survey (200 rows)')

    df_products = fetch_products(expand=True, variants_per=20)
    if df_products.empty:
        # if network blocked, generate synthetic product rows so charts work
        print('No products fetched from API — generating synthetic products for demo')
        df_products = pd.DataFrame([
            {'product_id': f'P_{i}', 'title': f'Product {i}', 'price': random.randint(500,20000), 'category':'electronics', 'rating': round(random.uniform(3.5,5.0),1), 'rating_count': random.randint(10,500)}
            for i in range(1,201)
        ])

    # Compute metrics
    metrics = compute_metrics(df_survey, df_products)
    print('\nMetrics:')
    print(json.dumps(metrics, indent=2))

    # Save CSVs
    df_survey.to_csv(os.path.join(save_folder, 'survey_static.csv'), index=False)
    df_products.to_csv(os.path.join(save_folder, 'products_market.csv'), index=False)
    print(f"Saved CSVs to {save_folder}/")

    # Visualizations (Plotly) -> save as HTML
    fig_price = px.histogram(df_products, x='price', nbins=40, title='Market Price Distribution')
    fig_expected = px.histogram(df_survey, x='expected_price_low', nbins=30, title='Customer Expected Price (Low)')
    city_counts = df_survey['city'].value_counts().reset_index()
    city_counts.columns = ['city','count']
    fig_city = px.bar(city_counts.head(12), x='city', y='count', title='Top Cities')

    figs = {'market_price': fig_price, 'expected_price': fig_expected, 'city_dist': fig_city}
    for name, fig in figs.items():
        outpath = os.path.join(save_folder, f'{name}.html')
        fig.write_html(outpath)
        print(f'Saved plot: {outpath}')

    # Generate sample recommendations for first 3 users and save
    recs_out = []
    for i in range(min(3, len(df_survey))):
        u = df_survey.iloc[i]
        recs = get_recommendations_for_user(u, df_products, top_n=3)
        for _, r in recs.iterrows():
            recs_out.append({'user_id': u['user_id'], 'user_name': u['name'], 'keyword': u['favorite_keyword'], 'product_title': r['title'], 'price': r['price'], 'score': r['score']})
    df_recs = pd.DataFrame(recs_out)
    df_recs.to_csv(os.path.join(save_folder, 'sample_recommendations.csv'), index=False)
    print(f'Saved sample recommendations to {save_folder}/sample_recommendations.csv')

    # Save metrics summary
    df_metrics = pd.DataFrame({
        'metric': ['Category Coverage (%)','Price Accuracy (%)','Precision@1 Keyword (%)','Precision@3 Keyword (%)','Precision@1 Price (%)','Precision@3 Price (%)'],
        'value': [metrics.get('category_coverage',0), metrics.get('price_accuracy',0), metrics.get('precision_1_keyword',0), metrics.get('precision_3_keyword',0), metrics.get('precision_1_price',0), metrics.get('precision_3_price',0)]
    })
    df_metrics.to_csv(os.path.join(save_folder, 'metrics_summary.csv'), index=False)
    print(f'Saved metrics summary to {save_folder}/metrics_summary.csv')

    print('\nFallback run complete. Open the HTML files in the output folder to view charts.')
    return {'survey': df_survey, 'products': df_products, 'metrics': metrics}

# ---------------------
# Streamlit app runner (if available)
# ---------------------

def run_streamlit_app():
    import streamlit as st

    st.set_page_config(page_title="E-commerce Market Intelligence", page_icon="🛒", layout="wide")

    st.markdown('''
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800&display=swap');
    *{font-family:Inter, sans-serif}
    #MainMenu, footer, header {visibility: hidden}
    .section-title{font-size:20px; font-weight:700; margin:12px 0}
    .stats-card{background:white; padding:12px; border-radius:10px; box-shadow:0 6px 18px rgba(0,0,0,0.06)}
    .metric-number{font-size:22px; font-weight:800}
    .small-muted{color:#6c757d; font-size:13px}
    .product-card{border-radius:8px; padding:10px; border:1px solid #eee}
    </style>
    ''', unsafe_allow_html=True)

    with st.spinner('Loading data...'):
        df_survey = None
        if os.path.exists('survey_static.csv'):
            df_survey = pd.read_csv('survey_static.csv')
        else:
            df_survey = generate_survey(200)

        df_products = fetch_products(expand=True, variants_per=20)
        if df_products.empty:
            # fallback synthetic
            df_products = pd.DataFrame([
                {'product_id': f'P_{i}', 'title': f'Product {i}', 'price': random.randint(500,20000), 'category':'electronics', 'rating': round(random.uniform(3.5,5.0),1), 'rating_count': random.randint(10,500)}
                for i in range(1,201)
            ])

        metrics = compute_metrics(df_survey, df_products)

    st.sidebar.title('Controls')
    page = st.sidebar.radio('', ['Overview','Metrics Dashboard','Recommendations','Data Explorer'])
    if st.sidebar.button('Refresh Products'):
        # Note: in Streamlit this will re-run the script and refresh the cached data
        st.experimental_rerun()

    if page == 'Overview':
        st.markdown('<div class="section-title">🛒 E-commerce Market Intelligence</div>', unsafe_allow_html=True)
        c1,c2,c3,c4 = st.columns(4)
        with c1:
            st.metric('Total Customers', len(df_survey))
        with c2:
            st.metric('Market Products', len(df_products))
        with c3:
            st.metric('Avg Customer Budget (High)', f"₹{df_survey['expected_price_high'].mean():,.0f}")
        with c4:
            st.metric('Price Accuracy', f"{metrics.get('price_accuracy',0):.1f}%")

        st.divider()
        st.plotly_chart(px.histogram(df_products, x='price', nbins=40, title='Market Price Distribution'), use_container_width=True)
        st.plotly_chart(px.histogram(df_survey, x='expected_price_low', nbins=30, title='Customer Expected Price (Low)'), use_container_width=True)
        city_counts = df_survey['city'].value_counts().reset_index()
        city_counts.columns = ['city','count']
        st.plotly_chart(px.bar(city_counts.head(12), x='city', y='count', title='Top Cities'), use_container_width=True)

    elif page == 'Metrics Dashboard':
        st.markdown('<div class="section-title">📈 Metrics Dashboard</div>', unsafe_allow_html=True)
        k1,k2,k3,k4 = st.columns(4)
        k1.metric('Category Coverage', f"{metrics.get('category_coverage',0):.1f}%")
        k2.metric('Price Accuracy', f"{metrics.get('price_accuracy',0):.1f}%")
        k3.metric('Precision@1 Keyword', f"{metrics.get('precision_1_keyword',0):.1f}%")
        k4.metric('Precision@3 Keyword', f"{metrics.get('precision_3_keyword',0):.1f}%")
        st.dataframe(pd.DataFrame({
            'metric': ['Category Coverage (%)','Price Accuracy (%)','Precision@1 Keyword (%)','Precision@3 Keyword (%)','Precision@1 Price (%)','Precision@3 Price (%)'],
            'value': [metrics.get('category_coverage',0), metrics.get('price_accuracy',0), metrics.get('precision_1_keyword',0), metrics.get('precision_3_keyword',0), metrics.get('precision_1_price',0), metrics.get('precision_3_price',0)]
        }))

    elif page == 'Recommendations':
        st.markdown('<div class="section-title">🎯 Recommendations</div>', unsafe_allow_html=True)
        user_select = st.selectbox('Pick a sample user', df_survey['user_id'].tolist())
        user_row = df_survey[df_survey['user_id']==user_select].iloc[0]
        st.write(f"User: {user_row['name']} — {user_row['city']} | Budget: ₹{user_row['expected_price_low']} - ₹{user_row['expected_price_high']}")
        recs = get_recommendations_for_user(user_row, df_products, top_n=8)
        for _, r in recs.iterrows():
            st.write(f"{r['title']} — ₹{r['price']:,.2f} — Score: {r['score']:.2f}")

    else:
        st.markdown('<div class="section-title">📋 Data Explorer</div>', unsafe_allow_html=True)
        t1, t2 = st.tabs(['Survey','Products'])
        with t1:
            st.dataframe(df_survey)
            st.download_button('Download survey CSV', df_survey.to_csv(index=False).encode('utf-8'), file_name='survey_static.csv')
        with t2:
            st.dataframe(df_products)
            st.download_button('Download products CSV', df_products.to_csv(index=False).encode('utf-8'), file_name='products_market.csv')

# ---------------------
# Minimal tests for core functions
# ---------------------

def _run_tests():
    print('Running unit-ish tests...')
    # Test calculate_score with simple values
    s1 = calculate_score(1000, 4.5, 100, 900, 1100)
    s2 = calculate_score(2000, 4.5, 100, 900, 1100)
    assert s1 > s2, 'Score should prefer price closer to mid price'

    # Test recommendations returns rows
    df_survey = generate_survey(5)
    df_products = pd.DataFrame([
        {'product_id':'p1','title':'Phone X','price':1000,'category':'electronics','rating':4.5,'rating_count':100},
        {'product_id':'p2','title':'Laptop Y','price':50000,'category':'electronics','rating':4.7,'rating_count':200}
    ])
    recs = get_recommendations_for_user(df_survey.iloc[0], df_products, top_n=2)
    assert isinstance(recs, pd.DataFrame), 'recommendations should return a DataFrame'
    print('All tests passed')

# ---------------------
# Entrypoint
# ---------------------

if __name__ == '__main__':
    try:
        # Prefer to run Streamlit app if available
        try:
            import streamlit as _st
            # If streamlit is available, ask user to run via `streamlit run`.
            print('Streamlit detected in environment. To run the interactive app use:')
            print('    streamlit run streamlit_app.py')
            # Also offer to start a local fallback server automatically if user runs python directly.
            # But to avoid starting Streamlit from within script (which is not recommended), we'll just exit.
            _st_available = True
        except Exception:
            _st_available = False

        if _st_available:
            # When streamlit exists, do not try to run it here; Streamlit must be launched with `streamlit run`.
            print('Exiting to allow running with `streamlit run` (recommended).')
            print('If you still want non-interactive outputs, run: python streamlit_app.py --fallback')
            # Provide helpful message and perform tests
            _run_tests()
            sys.exit(0)

        # Check for explicit fallback flag
        if '--fallback' in sys.argv:
            run_fallback(save_folder='output')
            _run_tests()
            sys.exit(0)

        # If streamlit not installed, automatically run fallback
        print('Streamlit not found in this environment. Running non-interactive fallback pipeline...')
        run_fallback(save_folder='output')
        _run_tests()

    except AssertionError as e:
        print('TEST FAILURE:', e)
        traceback.print_exc()
        sys.exit(2)
    except Exception as e:
        print('UNEXPECTED ERROR:', e)
        traceback.print_exc()
        sys.exit(3)
