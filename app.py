import streamlit as st
import http.client
import json
import os
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
import logging
import plotly.graph_objects as go
import plotly.express as px

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Chargement des variables d'environnement
load_dotenv()
AHREFS_API_KEY = os.getenv('AHREFS_API_KEY')

def analyze_dr_distribution(df):
    """
    Analyse la distribution des Domain Ratings
    """
    dr_ranges = {
        'DR 0-29': (0, 29),
        'DR 30-44': (30, 44),
        'DR 45-59': (45, 59),
        'DR 60-100': (60, 100)
    }
    
    distribution = {}
    for range_name, (min_dr, max_dr) in dr_ranges.items():
        count = len(df[(df['domain_rating_source'] >= min_dr) & 
                      (df['domain_rating_source'] <= max_dr)])
        distribution[range_name] = count
    
    return distribution

def analyze_yearly_distribution(df):
    """
    Analyse la distribution des backlinks par année
    """
    # Convertir first_seen en datetime
    df['year'] = pd.to_datetime(df['first_seen']).dt.year
    
    # Compter les backlinks par année
    yearly_counts = df['year'].value_counts().sort_index()
    
    # Calculer les cumuls
    cumulative_counts = yearly_counts.cumsum()
    
    # Créer un DataFrame avec les deux informations
    yearly_data = pd.DataFrame({
        'Année': yearly_counts.index,
        '# de liens': yearly_counts.values,
        'CUMULÉS': cumulative_counts.values
    })
    
    return yearly_data.sort_values('Année')

def analyze_tier_distribution(df):
    """
    Analyse la distribution des Tiers (basée sur le DR)
    """
    tier_ranges = {
        '0 Tier2': 0,
        '1-3 Tier2': (1, 3),
        '4-10 Tier2': (4, 10),
        '11+ Tier2': 11
    }
    
    # Simulation des tiers basée sur le DR pour cet exemple
    distribution = {name: 0 for name in tier_ranges.keys()}
    
    return distribution

def get_max_metrics(df):
    """
    Obtient les métriques maximales et identifie le backlink le plus puissant
    """
    if len(df) == 0:
        return {
            'max_dr': 0,
            'max_tier': 0,
            'max_dr_url': '',
            'max_dr_value': 0
        }
    
    # Trouve l'index du DR maximum
    max_dr_idx = df['domain_rating_source'].idxmax()
    
    return {
        'max_dr': df['domain_rating_source'].max(),
        'max_tier': 'N/A',  # À implémenter selon la logique de votre choix
        'max_dr_url': df.loc[max_dr_idx, 'url_from'],
        'max_dr_value': df.loc[max_dr_idx, 'domain_rating_source']
    }

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

def get_backlinks(target_url, limit=100):
    """
    Récupère les backlinks via l'API Ahrefs
    """
    try:
        conn = http.client.HTTPSConnection("api.ahrefs.com")
        
        headers = {
            'Accept': "application/json",
            'Authorization': f"Bearer {AHREFS_API_KEY}"
        }
        
        encoded_url = target_url.replace(':', '%3A').replace('/', '%2F')
        
        endpoint = (f"/v3/site-explorer/all-backlinks?"
                   f"limit={limit}&"
                   f"select=domain_rating_source,url_from,first_seen,link_type&"
                   f"target={encoded_url}&"
                   f"mode=subdomains&"
                   f"history=live&"
                   f"aggregation=all")
        
        logger.info(f"Envoi de la requête à l'API Ahrefs pour : {target_url}")
        conn.request("GET", endpoint, headers=headers)
        
        response = conn.getresponse()
        data = response.read()
        
        logger.info(f"Statut de la réponse : {response.status}")
        
        if response.status == 200:
            decoded_data = data.decode("utf-8")
            logger.info(f"Réponse de l'API: {decoded_data}")
            try:
                json_data = json.loads(decoded_data)
                return json_data
            except json.JSONDecodeError as e:
                logger.error(f"Erreur de décodage JSON: {str(e)}")
                return None
        else:
            logger.error(f"Erreur API: {data.decode('utf-8')}")
            return None
            
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des backlinks: {str(e)}")
        return None
    finally:
        conn.close()

# Interface Streamlit
st.title("📊 Analyse de la Puissance de Netlinking")

# Input pour l'URL
url_input = st.text_input(
    "Entrez l'URL ou le nom de domaine à analyser",
    placeholder="ex: https://example.com"
)

# Nombre de résultats
limit = st.slider("Nombre de backlinks à analyser", 10, 1000, 100)

if st.button("Analyser les backlinks"):
    if url_input:
        with st.spinner("Récupération et analyse des backlinks en cours..."):
            result = get_backlinks(url_input, limit)
            
            if result and 'backlinks' in result:
                df = pd.DataFrame(result['backlinks'])
                
                # Section 0: Total des backlinks
                st.header(f"📈 Total des Backlinks : {len(df)}")

                # Section 1: Distribution temporelle
                st.subheader("📅 Distribution temporelle des backlinks")
                
                # Analyse par année
                yearly_data = analyze_yearly_distribution(df)
                
                # Affichage du tableau des backlinks par année
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
                
                # Graphique de l'évolution
                st.plotly_chart(create_yearly_plot(yearly_data))

                # Section 2: Distribution des DR
                st.subheader("📊 Nombre de Backlinks en fonction du DR")
                dr_distribution = analyze_dr_distribution(df)
                col1, col2, col3, col4 = st.columns(4)
                cols = [col1, col2, col3, col4]
                for i, (range_name, count) in enumerate(dr_distribution.items()):
                    cols[i].metric(range_name, count)
                
                # Section 3: Distribution des Tiers
                st.subheader("🔗 Nombre de liens avec des liens de niveau 2")
                tier_distribution = analyze_tier_distribution(df)
                col1, col2, col3, col4 = st.columns(4)
                cols = [col1, col2, col3, col4]
                for i, (tier_name, count) in enumerate(tier_distribution.items()):
                    cols[i].metric(tier_name, count)

                # Section 4: Métriques maximales
                st.subheader("🏆 Métriques Maximales")
                max_metrics = get_max_metrics(df)
                col1, col2 = st.columns(2)
                col1.metric("MAX(Domain Rating)", max_metrics['max_dr'])
                col2.metric("MAX(Tier2)", max_metrics['max_tier'])
                
                # Affichage du backlink avec le DR le plus élevé
                st.markdown(f"### 🔗 Backlink le plus puissant (DR {max_metrics['max_dr_value']:.1f})")
                st.write(max_metrics['max_dr_url'])
                
                # Section 5: Tableau détaillé
                st.subheader("📋 Liste détaillée des Backlinks")
                st.dataframe(
                    df,
                    column_config={
                        "domain_rating_source": "DR Source",
                        "url_from": "URL Source",
                        "first_seen": "Première vue",
                        "link_type": "Type de lien"
                    },
                    hide_index=True
                )
                
                # Export CSV
                csv = df.to_csv(index=False)
                st.download_button(
                    "💾 Télécharger les données (CSV)",
                    csv,
                    f"backlinks_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    "text/csv"
                )
            else:
                st.error("Erreur lors de la récupération des données. Vérifiez l'URL et réessayez.")
    else:
        st.warning("Veuillez entrer une URL à analyser.")
