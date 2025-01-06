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

def process_backlinks_data(data):
    """
    Traite les données de backlinks pour créer un DataFrame
    """
    if not data:
        return pd.DataFrame()
    
    # Extraction des données pertinentes
    backlinks = []
    for item in data:
        backlink = {
            'url_from': item.get('url_from'),
            'url_to': item.get('url_to'),
            'domain_from': item.get('domain_from'),
            'trust_flow': item.get('trust_flow', 0),
            'citation_flow': item.get('citation_flow', 0),
            'first_seen': item.get('first_seen'),
            'link_type': item.get('link_type'),
            'dofollow': item.get('dofollow', False)
        }
        backlinks.append(backlink)
    
    return pd.DataFrame(backlinks)

def analyze_tf_distribution(df):
    """
    Analyse la distribution des Trust Flow
    """
    tf_ranges = {
        'TF 0-29': (0, 29),
        'TF 30-44': (30, 44),
        'TF 45-59': (45, 59),
        'TF 60-100': (60, 100)
    }
    
    distribution = {}
    for range_name, (min_tf, max_tf) in tf_ranges.items():
        count = len(df[(df['trust_flow'] >= min_tf) & 
                      (df['trust_flow'] <= max_tf)])
        distribution[range_name] = count
    
    return distribution

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

def create_yearly_plot(yearly_data):
    """
    Crée un graphique des backlinks par année
    """
    fig = go.Figure()
    
    fig.add_trace(
        go.Scatter(
            x=yearly_data['Année'],
            y=yearly_data['# de liens'],
            name='# de backlinks',
            mode='lines+markers'
        )
    )
    
    fig.update_layout(
        title='Nombre de domaines Référents par années',
        xaxis_title='Année',
        yaxis_title='Nombre de backlinks',
        height=400,
        showlegend=True
    )
    
    return fig

# Interface Streamlit
st.title("📊 Analyse de la Puissance de Netlinking (DataForSeo)")

# Input pour l'URL
url_input = st.text_input(
    "Entrez l'URL ou le nom de domaine à analyser",
    placeholder="ex: https://example.com"
)

limit = st.slider("Nombre de backlinks à analyser", 10, 1000, 100)

if st.button("Analyser les backlinks"):
    if url_input:
        with st.spinner("Récupération et analyse des backlinks en cours..."):
            result = get_backlinks(url_input, limit)
            
            if result:
                df = process_backlinks_data(result)
                
                if len(df) > 0:
                    # Section 0: Total des backlinks
                    st.header(f"📈 Total des Backlinks : {len(df)}")

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

                    # Section 2: Distribution des Trust Flow
                    st.subheader("📊 Nombre de Backlinks en fonction du Trust Flow")
                    tf_distribution = analyze_tf_distribution(df)
                    col1, col2, col3, col4 = st.columns(4)
                    cols = [col1, col2, col3, col4]
                    for i, (range_name, count) in enumerate(tf_distribution.items()):
                        cols[i].metric(range_name, count)

                    # Section 3: Métriques maximales
                    st.subheader("🏆 Métriques Maximales")
                    max_tf = df['trust_flow'].max()
                    max_cf = df['citation_flow'].max()
                    col1, col2 = st.columns(2)
                    col1.metric("MAX(Trust Flow)", f"{max_tf:.1f}")
                    col2.metric("MAX(Citation Flow)", f"{max_cf:.1f}")
                    
                    # URL avec le TF le plus élevé
                    max_tf_url = df.loc[df['trust_flow'].idxmax(), 'url_from']
                    st.markdown(f"### 🔗 Backlink le plus puissant (TF {max_tf:.1f})")
                    st.write(max_tf_url)
                    
                    # Section 4: Tableau détaillé
                    st.subheader("📋 Liste détaillée des Backlinks")
                    st.dataframe(
                        df,
                        column_config={
                            "url_from": "URL Source",
                            "domain_from": "Domaine Source",
                            "trust_flow": "Trust Flow",
                            "citation_flow": "Citation Flow",
                            "first_seen": "Première vue",
                            "link_type": "Type de lien",
                            "dofollow": "Dofollow"
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
