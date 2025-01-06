import streamlit as st
import http.client
import json
import pandas as pd
from datetime import datetime, timedelta
import logging
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor
import time
from tenacity import retry, stop_after_attempt, wait_exponential

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Récupération de la clé API depuis les secrets Streamlit
try:
    AHREFS_API_KEY = st.secrets["AHREFS_API_KEY"]
except Exception as e:
    logger.error(f"Erreur lors de la récupération de la clé API: {str(e)}")
    st.error("La clé API Ahrefs n'est pas configurée correctement.")
    st.stop()

class RateLimiter:
    def __init__(self, requests_per_second=5):
        self.requests_per_second = requests_per_second
        self.requests = []
    
    def wait(self):
        now = datetime.now()
        # Nettoyer les anciennes requêtes
        self.requests = [req for req in self.requests 
                        if now - req < timedelta(seconds=1)]
        
        # Si trop de requêtes, attendre
        if len(self.requests) >= self.requests_per_second:
            sleep_time = 1.0 - (now - self.requests[0]).total_seconds()
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        self.requests.append(now)

rate_limiter = RateLimiter()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def make_ahrefs_request(endpoint, headers):
    """
    Fonction générique pour faire des requêtes à l'API Ahrefs avec retry
    """
    try:
        rate_limiter.wait()  # Respecter le rate limit
        conn = http.client.HTTPSConnection("api.ahrefs.com")
        
        logger.info(f"Requête API Ahrefs - Endpoint: {endpoint}")
        conn.request("GET", endpoint, headers=headers)
        
        response = conn.getresponse()
        data = response.read()
        
        logger.info(f"Statut de la réponse: {response.status}")
        
        if response.status == 200:
            return json.loads(data.decode("utf-8"))
        else:
            error_msg = data.decode("utf-8")
            logger.error(f"Erreur API: {error_msg}")
            raise Exception(f"Erreur API: {error_msg}")
    finally:
        conn.close()

@st.cache_data(ttl=3600)  # Cache valide pendant 1 heure
def get_backlinks_cached(target_url, limit, mode, aggregation):
    """
    Version mise en cache de get_backlinks
    """
    headers = {
        'Accept': "application/json",
        'Authorization': f"Bearer {AHREFS_API_KEY}"
    }
    
    encoded_url = target_url.replace(':', '%3A').replace('/', '%2F')
    endpoint = (f"/v3/site-explorer/all-backlinks?"
               f"limit={limit}&"
               f"select=domain_rating_source,url_from,first_seen,link_type&"
               f"target={encoded_url}&"
               f"mode={mode}&"
               f"history=live&"
               f"aggregation={aggregation}")
    
    return make_ahrefs_request(endpoint, headers)

@st.cache_data(ttl=3600)
def get_tier2_stats_cached(url):
    """
    Version mise en cache de get_tier2_stats
    """
    headers = {
        'Accept': "application/json",
        'Authorization': f"Bearer {AHREFS_API_KEY}"
    }
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    encoded_url = url.replace(':', '%3A').replace('/', '%2F')
    endpoint = f"/v3/site-explorer/backlinks-stats?target={encoded_url}&mode=exact&date={current_date}"
    
    try:
        stats = make_ahrefs_request(endpoint, headers)
        live_backlinks = stats.get('metrics', {}).get('live', 0)
        live_refdomains = stats.get('metrics', {}).get('live_refdomains', 0)
        return live_backlinks, live_refdomains
    except Exception as e:
        logger.error(f"Erreur lors de l'analyse Tier 2 pour {url}: {str(e)}")
        return 0, 0

def analyze_tier2_links_parallel(df, progress_bar, status_text):
    """
    Analyse parallèle des liens de niveau 2
    """
    tier2_results = []
    total_urls = len(df)
    processed = 0
    
    def process_url(url):
        nonlocal processed
        result = get_tier2_stats_cached(url)
        processed += 1
        progress = processed / total_urls
        progress_bar.progress(progress)
        status_text.text(f"Analyse de l'URL {processed}/{total_urls}")
        return result
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        tier2_results = list(executor.map(process_url, df['url_from']))
    
    tier2_live_links, tier2_live_refdomains = zip(*tier2_results)
    return list(tier2_live_links), list(tier2_live_refdomains)

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

def analyze_tier_distribution(df, column_name):
    """
    Analyse la distribution des Tiers (basée sur le nombre de backlinks ou refdomains)
    """
    if column_name not in df.columns:
        return {
            f'0 {column_name}': 0,
            f'1-3 {column_name}': 0,
            f'4-10 {column_name}': 0,
            f'11+ {column_name}': 0
        }
    
    tier_ranges = {
        f'0 {column_name}': (0, 0),
        f'1-3 {column_name}': (1, 3),
        f'4-10 {column_name}': (4, 10),
        f'11+ {column_name}': (11, float('inf'))
    }
    
    distribution = {}
    for range_name, (min_links, max_links) in tier_ranges.items():
        if min_links == max_links:
            count = len(df[df[column_name] == min_links])
        elif max_links == float('inf'):
            count = len(df[df[column_name] >= min_links])
        else:
            count = len(df[(df[column_name] >= min_links) & (df[column_name] <= max_links)])
        distribution[range_name] = count
    
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

def get_tier2_stats(url):
    """
    Récupère les statistiques des backlinks pour une URL donnée
    Retourne un tuple (live_backlinks, live_refdomains)
    """
    logger.info("="*50)
    logger.info("LIENS TIER 2 - DÉBUT ANALYSE")
    logger.info(f"LIENS TIER 2 - Analyse de l'URL: {url}")
    
    try:
        conn = http.client.HTTPSConnection("api.ahrefs.com")
        
        headers = {
            'Accept': "application/json",
            'Authorization': f"Bearer {AHREFS_API_KEY}"
        }
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        encoded_url = url.replace(':', '%3A').replace('/', '%2F')
        endpoint = f"/v3/site-explorer/backlinks-stats?target={encoded_url}&mode=exact&date={current_date}"
        
        logger.info(f"LIENS TIER 2 - Endpoint appelé: {endpoint}")
        conn.request("GET", endpoint, headers=headers)
        response = conn.getresponse()
        data = response.read()
        
        logger.info(f"LIENS TIER 2 - Statut de la réponse: {response.status}")
        
        if response.status == 200:
            decoded_data = data.decode("utf-8")
            logger.info(f"LIENS TIER 2 - Réponse brute: {decoded_data}")
            
            try:
                stats = json.loads(decoded_data)
                logger.info(f"LIENS TIER 2 - Stats complètes: {json.dumps(stats, indent=2)}")
                
                # Extraire les métriques live
                live_backlinks = stats.get('metrics', {}).get('live', 0)
                live_refdomains = stats.get('metrics', {}).get('live_refdomains', 0)
                
                logger.info(f"LIENS TIER 2 - Backlinks live: {live_backlinks}, Refdomains live: {live_refdomains}")
                return live_backlinks, live_refdomains
                
            except json.JSONDecodeError as e:
                logger.error(f"LIENS TIER 2 - Erreur JSON: {e}")
                return 0, 0
        else:
            logger.error(f"LIENS TIER 2 - Erreur API: {data.decode('utf-8')}")
            return 0, 0
    except Exception as e:
        logger.error(f"LIENS TIER 2 - Erreur lors de la récupération pour {url}: {str(e)}")
        return 0, 0
    finally:
        conn.close()
        logger.info("LIENS TIER 2 - FIN ANALYSE")
        logger.info("="*50)

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
                   f"mode={mode}&"
                   f"history=live&"
                   f"aggregation={aggregation}")
        
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

# Options d'analyse
col1, col2 = st.columns(2)
with col1:
    # Sélecteur pour l'agrégation
    aggregation = st.selectbox(
        "Mode d'agrégation des backlinks",
        options=["all", "similar_links", "1_per_domain"],
        index=0,  # "all" par défaut
        help="all: Tous les backlinks\nsimilar_links: Regroupe les liens similaires\n1_per_domain: Un seul lien par domaine"
    )
    
    limit = st.slider("Nombre de backlinks à analyser", 10, 1000, 100)

with col2:
    # Sélecteur pour le mode de recherche
    mode = st.selectbox(
        "Mode de recherche",
        options=["subdomains", "exact", "prefix", "domain"],
        index=0,  # "subdomains" par défaut
        help="subdomains: Inclut tous les sous-domaines\nexact: URL exacte uniquement\nprefix: URLs commençant par la cible\ndomain: Domaine entier"
    )
    
    check_tier2 = st.checkbox("Analyser les liens de Niveau 2", value=False)

if st.button("Analyser les backlinks"):
    if url_input:
        try:
            with st.spinner("Récupération et analyse des backlinks en cours..."):
                # Utilisation de la version cachée
                result = get_backlinks_cached(url_input, limit, mode, aggregation)
                
                if result and 'backlinks' in result:
                    df = pd.DataFrame(result['backlinks'])
                    
                    # Analyse des liens Tier 2 si l'option est cochée
                    if check_tier2 and len(df) > 0:
                        st.info("Analyse des liens de Niveau 2 en cours... Cette opération peut prendre quelques minutes.")
                        
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        # Utilisation de l'analyse parallèle
                        tier2_live_links, tier2_live_refdomains = analyze_tier2_links_parallel(
                            df, progress_bar, status_text
                        )
                        
                        df['tier2_live_links'] = tier2_live_links
                        df['tier2_live_refdomains'] = tier2_live_refdomains
                        status_text.text("Analyse des liens de Niveau 2 terminée!")
                    
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

                    # Section 2: Distribution des DR
                    st.subheader("📊 Nombre de Backlinks en fonction du DR")
                    dr_distribution = analyze_dr_distribution(df)
                    col1, col2, col3, col4 = st.columns(4)
                    cols = [col1, col2, col3, col4]
                    for i, (range_name, count) in enumerate(dr_distribution.items()):
                        cols[i].metric(range_name, count)

                    # Section 3: Distribution des Tiers
                    if 'tier2_live_links' in df.columns:
                        st.subheader("🔗 Nombre de liens avec des liens de niveau 2")
                        links_distribution = analyze_tier_distribution(df, 'tier2_live_links')
                        col1, col2, col3, col4 = st.columns(4)
                        cols = [col1, col2, col3, col4]
                        for i, (range_name, count) in enumerate(links_distribution.items()):
                            cols[i].metric(range_name.replace('tier2_live_links', 'Live backlinks Tier2'), count)
                        
                        st.subheader("🔗 Nombre de liens avec des refering_domains de niveau 2")
                        refdomains_distribution = analyze_tier_distribution(df, 'tier2_live_refdomains')
                        col1, col2, col3, col4 = st.columns(4)
                        cols = [col1, col2, col3, col4]
                        for i, (range_name, count) in enumerate(refdomains_distribution.items()):
                            cols[i].metric(range_name.replace('tier2_live_refdomains', 'RD Tier2'), count)

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
                    column_config = {
                        "domain_rating_source": "DR Source",
                        "url_from": "URL Source",
                        "first_seen": "Première vue",
                        "link_type": "Type de lien"
                    }
                    
                    # Ajouter les colonnes Tier2 si elles existent
                    if 'tier2_live_links' in df.columns:
                        column_config.update({
                            "tier2_live_links": "Backlinks live de niveau 2",
                            "tier2_live_refdomains": "Refering domains live de niveau 2"
                        })
                    
                    st.dataframe(
                        df,
                        column_config=column_config,
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
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse: {str(e)}")
            st.error(f"Une erreur s'est produite: {str(e)}")
    else:
        st.warning("Veuillez entrer une URL à analyser.")