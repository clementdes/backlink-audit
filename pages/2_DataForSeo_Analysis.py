import streamlit as st
import requests
import json
import pandas as pd
from datetime import datetime
import logging
import plotly.graph_objects as go
import base64

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration de la page
st.set_page_config(
    page_title="Analyse DataForSeo",
    page_icon="📊",
    layout="wide"
)

# Récupération des credentials depuis les secrets Streamlit
try:
    DATAFORSEO_LOGIN = st.secrets["DATAFORSEO_LOGIN"]
    DATAFORSEO_API_KEY = st.secrets["DATAFORSEO_API_KEY"]
    # Création des credentials encodés en base64
    credentials = base64.b64encode(f"{DATAFORSEO_LOGIN}:{DATAFORSEO_API_KEY}".encode()).decode()
except Exception as e:
    logger.error(f"Erreur lors de la récupération des credentials: {str(e)}")
    st.error("Les credentials DataForSeo ne sont pas configurés correctement. Veuillez configurer les secrets 'DATAFORSEO_LOGIN' et 'DATAFORSEO_API_KEY' dans Streamlit.")
    st.stop()

def create_yearly_plot(yearly_data):
    """
    Crée un graphique des backlinks par année
    """
    fig = go.Figure()
    
    # Ajouter les barres pour le nombre de backlinks
    fig.add_trace(
        go.Scatter(
            x=yearly_data['Année'],
            y=yearly_data['# de liens'],
            name='# de backlinks',
            mode='lines+markers'
        )
    )
    
    # Personnalisation du graphique
    fig.update_layout(
        title='Nombre de domaines Référents par années',
        xaxis_title='Année',
        yaxis_title='Nombre de backlinks',
        height=400,
        showlegend=True
    )
    
    return fig

def process_backlinks_data(data):
    """
    Traite les données de backlinks pour créer un DataFrame
    """
    if not data:
        return pd.DataFrame()
    
    backlinks = []
    for item in data.get('items', []):
        backlink = {
            'url_from': item.get('url_from'),
            'url_to': item.get('url_to'),
            'domain_from': item.get('domain_from'),
            'backlink_spam_score': item.get('backlink_spam_score', 0),
            'rank': item.get('rank', 0),
            'page_from_rank': item.get('page_from_rank', 0),
            'domain_from_rank': item.get('domain_from_rank', 0),
            'is_broken': item.get('is_broken', False),
            'dofollow': item.get('dofollow', False),
            'first_seen': item.get('first_seen'),
            'last_seen': item.get('last_seen'),
            'item_type': item.get('item_type'),
            'domain_from_country': item.get('domain_from_country'),
            'page_from_language': item.get('page_from_language'),
            'anchor': item.get('anchor'),
            'is_indirect_link': item.get('is_indirect_link', False),
            'url_to_status_code': item.get('url_to_status_code'),
            'page_from_external_links': item.get('page_from_external_links', 0),
            'page_from_internal_links': item.get('page_from_internal_links', 0),
            'keywords_top_3': item.get('ranked_keywords_info', {}).get('page_from_keywords_count_top_3', 0),
            'keywords_top_10': item.get('ranked_keywords_info', {}).get('page_from_keywords_count_top_10', 0),
            'keywords_top_100': item.get('ranked_keywords_info', {}).get('page_from_keywords_count_top_100', 0)
        }
        backlinks.append(backlink)
    
    return pd.DataFrame(backlinks)

def analyze_rank_distribution(df):
    """
    Analyse la distribution des Ranks
    """
    rank_ranges = {
        'Rank 0-100': (0, 100),
        'Rank 101-200': (101, 200),
        'Rank 201-300': (201, 300),
        'Rank 300+': (301, float('inf'))
    }
    
    distribution = {}
    for range_name, (min_rank, max_rank) in rank_ranges.items():
        count = len(df[(df['rank'] >= min_rank) & (df['rank'] <= max_rank)])
        distribution[range_name] = count
    
    return distribution

def analyze_spam_score_distribution(df):
    """
    Analyse la distribution des Spam Scores
    """
    spam_ranges = {
        'Spam Score 0-25': (0, 25),
        'Spam Score 26-50': (26, 50),
        'Spam Score 51-75': (51, 75),
        'Spam Score 76-100': (76, 100)
    }
    
    distribution = {}
    for range_name, (min_score, max_score) in spam_ranges.items():
        count = len(df[(df['backlink_spam_score'] >= min_score) & 
                      (df['backlink_spam_score'] <= max_score)])
        distribution[range_name] = count
    
    return distribution

def get_link_quality_metrics(df):
    """
    Obtient les métriques de qualité des liens
    """
    total_links = len(df)
    if total_links == 0:
        return {
            'total_links': 0,
            'dofollow_percent': 0,
            'broken_percent': 0,
            'indirect_percent': 0,
            'avg_spam_score': 0,
            'avg_rank': 0
        }
    
    return {
        'total_links': total_links,
        'dofollow_percent': (df['dofollow'].sum() / total_links) * 100,
        'broken_percent': (df['is_broken'].sum() / total_links) * 100,
        'indirect_percent': (df['is_indirect_link'].sum() / total_links) * 100,
        'avg_spam_score': df['backlink_spam_score'].mean(),
        'avg_rank': df['rank'].mean()
    }

def analyze_link_types(df):
    """
    Analyse la distribution des types de liens
    """
    return df['item_type'].value_counts().to_dict()

def get_keyword_visibility(df):
    """
    Analyse la visibilité des mots-clés
    """
    return {
        'keywords_top_3': df['keywords_top_3'].sum(),
        'keywords_top_10': df['keywords_top_10'].sum(),
        'keywords_top_100': df['keywords_top_100'].sum(),
    }

def analyze_yearly_distribution(df):
    """
    Analyse la distribution des backlinks par année
    """
    df['year'] = pd.to_datetime(df['first_seen']).dt.year
    yearly_counts = df['year'].value_counts().sort_index()
    cumulative_counts = yearly_counts.cumsum()
    
    yearly_data = pd.DataFrame({
        'Année': yearly_counts.index,
        '# de liens': yearly_counts.values,
        'CUMULÉS': cumulative_counts.values
    })
    
    return yearly_data.sort_values('Année')

def get_backlinks(target_url, limit=1000):
    """
    Récupère les backlinks via l'API DataForSeo
    """
    url = "https://api.dataforseo.com/v3/backlinks/backlinks/live"
    
    payload = json.dumps([{
        "target": target_url,
        "limit": limit,
        "internal_list_limit": 10,
        "backlinks_status_type": "live",
        "include_subdomains": True,
        "exclude_internal_backlinks": True,
        "include_indirect_links": True,
        "mode": "as_is"
    }])
    
    headers = {
        'Authorization': f'Basic {credentials}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()  # Lève une exception pour les codes d'erreur HTTP
        
        data = response.json()
        if data.get('status_code') == 20000:  # Code de succès de DataForSeo
            return data.get('tasks', [{}])[0].get('result', [])
        else:
            logger.error(f"Erreur API DataForSeo: {data}")
            return None
            
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des backlinks: {str(e)}")
        return None

# Interface Streamlit
st.title("📊 Analyse de la Puissance de Netlinking (DataForSeo)")

# Input pour l'URL
url_input = st.text_input(
    "Entrez l'URL ou le nom de domaine à analyser",
    placeholder="ex: https://example.com"
)

# Options d'analyse
col1, col2 = st.columns(2)
with col1:
    limit = st.slider("Nombre de backlinks à analyser", 10, 1000, 100)

if st.button("Analyser les backlinks"):
    if url_input:
        with st.spinner("Récupération et analyse des backlinks en cours..."):
            result = get_backlinks(url_input, limit)
            
            if result:
                df = process_backlinks_data(result)
                
                if len(df) > 0:
                    # Section 0: Total des backlinks et métriques générales
                    st.header("📈 Vue d'ensemble")
                    quality_metrics = get_link_quality_metrics(df)
                    
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Total Backlinks", quality_metrics['total_links'])
                    col1.metric("Liens Dofollow", f"{quality_metrics['dofollow_percent']:.1f}%")
                    
                    col2.metric("Rang Moyen", f"{quality_metrics['avg_rank']:.1f}")
                    col2.metric("Score Spam Moyen", f"{quality_metrics['avg_spam_score']:.1f}")
                    
                    col3.metric("Liens Cassés", f"{quality_metrics['broken_percent']:.1f}%")
                    col3.metric("Liens Indirects", f"{quality_metrics['indirect_percent']:.1f}%")

                    # Section 1: Distribution temporelle
                    st.subheader("📅 Distribution temporelle des backlinks")
                    yearly_data = analyze_yearly_distribution(df)
                    
                    st.markdown("### # de backlinks créés par année")
                    st.dataframe(
                        yearly_data,
                        hide_index=True,
                        column_config={
                            'Année': 'Année',
                            '# de liens': 'Nombre de liens',
                            'CUMULÉS': 'Cumulés'
                        }
                    )
                    
                    st.plotly_chart(create_yearly_plot(yearly_data))

                    # Section 2: Distribution des Ranks
                    st.subheader("📊 Distribution des Ranks")
                    rank_distribution = analyze_rank_distribution(df)
                    cols = st.columns(4)
                    for i, (range_name, count) in enumerate(rank_distribution.items()):
                        cols[i].metric(range_name, count)

                    # Section 3: Distribution des Spam Scores
                    st.subheader("🛡️ Distribution des Spam Scores")
                    spam_distribution = analyze_spam_score_distribution(df)
                    cols = st.columns(4)
                    for i, (range_name, count) in enumerate(spam_distribution.items()):
                        cols[i].metric(range_name, count)

                    # Section 4: Types de liens
                    st.subheader("🔗 Types de liens")
                    link_types = analyze_link_types(df)
                    cols = st.columns(len(link_types))
                    for i, (type_name, count) in enumerate(link_types.items()):
                        cols[i].metric(type_name.title(), count)

                    # Section 5: Visibilité des mots-clés
                    st.subheader("🎯 Visibilité des mots-clés")
                    keyword_visibility = get_keyword_visibility(df)
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Mots-clés Top 3", keyword_visibility['keywords_top_3'])
                    col2.metric("Mots-clés Top 10", keyword_visibility['keywords_top_10'])
                    col3.metric("Mots-clés Top 100", keyword_visibility['keywords_top_100'])

                    # Section 6: Tableau détaillé
                    st.subheader("📋 Liste détaillée des Backlinks")
                    st.dataframe(
                        df,
                        column_config={
                            "url_from": "URL Source",
                            "domain_from": "Domaine Source",
                            "rank": "Rank",
                            "backlink_spam_score": "Spam Score",
                            "domain_from_rank": "Rank du Domaine",
                            "page_from_rank": "Rank de la Page",
                            "first_seen": "Première vue",
                            "last_seen": "Dernière vue",
                            "item_type": "Type de lien",
                            "dofollow": "Dofollow",
                            "is_broken": "Lien Cassé",
                            "is_indirect_link": "Lien Indirect",
                            "anchor": "Texte d'ancrage",
                            "domain_from_country": "Pays",
                            "page_from_language": "Langue",
                            "keywords_top_100": "Mots-clés Top 100"
                        },
                        hide_index=True
                    )

                    # Export CSV
                    csv = df.to_csv(index=False)
                    st.download_button(
                        "💾 Télécharger les données (CSV)",
                        csv,
                        f"backlinks_dataforseo_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        "text/csv"
                    )
                else:
                    st.warning("Aucun backlink trouvé pour cette URL.")
            else:
                st.error("Erreur lors de la récupération des données. Vérifiez l'URL et réessayez.")
    else:
        st.warning("Veuillez entrer une URL à analyser.")
