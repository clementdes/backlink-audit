import streamlit as st
import http.client
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor
import time
from tenacity import retry, stop_after_attempt, wait_exponential
from threading import Lock
from urllib.parse import quote

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def encode_url_for_ahrefs(url):
    """Encode correctement une URL pour l'API Ahrefs"""
    # Supprime les espaces avant et après
    url = url.strip()
    
    # S'assure que l'URL commence par http:// ou https://
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Encode l'URL correctement
    return quote(url, safe='')

# Récupération de la clé API depuis les secrets Streamlit
try:
    AHREFS_API_KEY = st.secrets["AHREFS_API_KEY"]
except Exception as e:
    logger.error(f"Erreur lors de la récupération de la clé API: {str(e)}")
    st.error("La clé API Ahrefs n'est pas configurée correctement.")
    st.stop()

class RateLimiter:
    """Classe pour gérer les limites de taux de requêtes API"""
    def __init__(self, requests_per_second=5):
        self.requests_per_second = requests_per_second
        self.requests = []
        self._lock = Lock()
    
    def wait(self):
        with self._lock:
            now = datetime.now()
            self.requests = [req for req in self.requests 
                           if now - req < timedelta(seconds=1)]
            
            if len(self.requests) >= self.requests_per_second:
                sleep_time = 1.0 - (now - self.requests[0]).total_seconds()
                if sleep_time > 0:
                    time.sleep(sleep_time)
            
            self.requests.append(now)

rate_limiter = RateLimiter()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def make_ahrefs_request(endpoint, headers):
    """Fonction générique pour faire des requêtes à l'API Ahrefs avec retry"""
    conn = None
    try:
        logger.info(f"Tentative de requête API Ahrefs - Endpoint: {endpoint}")
        rate_limiter.wait()
        conn = http.client.HTTPSConnection("api.ahrefs.com", timeout=30)
        
        logger.info(f"Envoi de la requête avec headers: {headers}")
        conn.request("GET", endpoint, headers=headers)
        
        logger.info("Attente de la réponse...")
        response = conn.getresponse()
        data = response.read()
        
        logger.info(f"Statut de la réponse: {response.status}")
        logger.info(f"Headers de réponse: {response.getheaders()}")
        
        if response.status == 200:
            decoded_data = data.decode("utf-8")
            logger.info(f"Début des données décodées: {decoded_data[:200]}...")
            return json.loads(decoded_data)
        else:
            error_msg = data.decode("utf-8")
            logger.error(f"Erreur API (Status {response.status}): {error_msg}")
            raise Exception(f"Erreur API (Status {response.status}): {error_msg}")
            
    except http.client.HTTPException as e:
        logger.error(f"Erreur HTTP lors de la requête: {str(e)}")
        raise Exception(f"Erreur HTTP: {str(e)}")
    except json.JSONDecodeError as e:
        logger.error(f"Erreur de décodage JSON: {str(e)}")
        raise Exception(f"Erreur de décodage JSON: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        raise
    finally:
        if conn:
            conn.close()

@st.cache_data(ttl=3600)
def get_backlinks_cached(target_url, limit=100, mode="subdomains", aggregation="all"):
    """Version mise en cache de la requête de backlinks"""
    try:
        logger.info(f"Début de get_backlinks_cached pour URL: {target_url}")
        
        headers = {
            'Accept': "application/json",
            'Authorization': f"Bearer {AHREFS_API_KEY}"
        }
        
        encoded_url = encode_url_for_ahrefs(target_url)
        logger.info(f"URL encodée: {encoded_url}")
        
        endpoint = (f"/v3/site-explorer/all-backlinks?"
                   f"limit={limit}&"
                   f"select=domain_rating_source,url_from,first_seen,link_type&"
                   f"target={encoded_url}&"
                   f"mode={mode}&"
                   f"history=live&"
                   f"aggregation={aggregation}")
        
        logger.info(f"Endpoint construit: {endpoint}")
        
        result = make_ahrefs_request(endpoint, headers)
        
        if not result:
            raise Exception("Aucun résultat retourné par l'API")
            
        logger.info(f"Résultat reçu avec {len(result.get('backlinks', []))} backlinks")
        return result
        
    except Exception as e:
        logger.error(f"Erreur dans get_backlinks_cached: {str(e)}")
        raise Exception(f"Erreur lors de la récupération des backlinks: {str(e)}")

@st.cache_data(ttl=3600)
def get_our_domain_backlinks(our_domain, mode="subdomains"):
    """Récupère tous les backlinks déjà analysés pour notre domaine"""
    headers = {
        'Accept': "application/json",
        'Authorization': f"Bearer {AHREFS_API_KEY}"
    }
    
    encoded_url = our_domain.replace(':', '%3A').replace('/', '%2F')
    endpoint = (f"/v3/site-explorer/backlinks?"
               f"select=domain_rating_source,url_from,first_seen,link_type,url_to&"
               f"target={encoded_url}&"
               f"mode={mode}&"
               f"history=live")
    
    return make_ahrefs_request(endpoint, headers)

@st.cache_data(ttl=3600)
def get_tier2_stats_cached(url):
    """Version mise en cache des statistiques de niveau 2"""
    try:
        headers = {
            'Accept': "application/json",
            'Authorization': f"Bearer {AHREFS_API_KEY}"
        }
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        encoded_url = url.replace(':', '%3A').replace('/', '%2F')
        endpoint = f"/v3/site-explorer/backlinks-stats?target={encoded_url}&mode=exact&date={current_date}"
        
        stats = make_ahrefs_request(endpoint, headers)
        
        if not stats or 'metrics' not in stats:
            logger.warning(f"Pas de métriques trouvées pour {url}")
            return 0, 0
            
        live_backlinks = stats['metrics'].get('live', 0)
        live_refdomains = stats['metrics'].get('live_refdomains', 0)
        
        return live_backlinks, live_refdomains
        
    except Exception as e:
        logger.error(f"Erreur lors de l'analyse Tier 2 pour {url}: {str(e)}")
        return 0, 0

def analyze_tier2_links_parallel(df, progress_bar, status_text):
    """Analyse parallèle des liens de niveau 2"""
    tier2_results = []
    total_urls = len(df)
    
    processed_lock = Lock()
    processed_count = 0
    
    def process_url(url):
        nonlocal processed_count
        try:
            result = get_tier2_stats_cached(url)
            
            with processed_lock:
                nonlocal processed_count
                processed_count += 1
                
            return result
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse de {url}: {str(e)}")
            return (0, 0)
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_url, url) for url in df['url_from']]
        
        while any(not f.done() for f in futures):
            current_progress = processed_count / total_urls
            progress_bar.progress(current_progress)
            status_text.text(f"Analyse de l'URL {processed_count}/{total_urls}")
            time.sleep(0.1)
        
        tier2_results = [f.result() for f in futures]
    
    progress_bar.progress(1.0)
    status_text.text(f"Analyse terminée! {total_urls}/{total_urls} URLs traitées")
    
    tier2_live_links, tier2_live_refdomains = zip(*tier2_results)
    return list(tier2_live_links), list(tier2_live_refdomains)

def analyze_dr_distribution(df):
    """Analyse la distribution des Domain Ratings"""
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
    """Analyse la distribution des backlinks par année"""
    df['year'] = pd.to_datetime(df['first_seen']).dt.year
    yearly_counts = df['year'].value_counts().sort_index()
    cumulative_counts = yearly_counts.cumsum()
    
    yearly_data = pd.DataFrame({
        'Année': yearly_counts.index,
        '# de liens': yearly_counts.values,
        'CUMULÉS': cumulative_counts.values
    })
    
    return yearly_data.sort_values('Année')

def analyze_tier_distribution(df, column_name):
    """Analyse la distribution des Tiers"""
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
            count = len(df[(df[column_name] >= min_links) & 
                         (df[column_name] <= max_links)])
        distribution[range_name] = count
    
    return distribution

def get_max_metrics(df):
    """Obtient les métriques maximales"""
    if len(df) == 0:
        return {
            'max_dr': 0,
            'max_tier': 0,
            'max_dr_url': '',
            'max_dr_value': 0
        }
    
    max_dr_idx = df['domain_rating_source'].idxmax()
    
    return {
        'max_dr': df['domain_rating_source'].max(),
        'max_tier': df.get('tier2_live_links', [0]).max() if 'tier2_live_links' in df.columns else 0,
        'max_dr_url': df.loc[max_dr_idx, 'url_from'],
        'max_dr_value': df.loc[max_dr_idx, 'domain_rating_source']
    }

def create_yearly_plot(yearly_data, title="Nombre de domaines Référents par années"):
    """Crée un graphique des backlinks par année"""
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
        title=title,
        xaxis_title='Année',
        yaxis_title='Nombre de backlinks',
        height=400,
        showlegend=True
    )
    
    return fig

def analyze_domain_overlap(current_backlinks, our_backlinks):
    """Analyse le chevauchement entre les backlinks"""
    current_df = pd.DataFrame(current_backlinks)
    our_df = pd.DataFrame(our_backlinks)
    
    current_domains = set(current_df['url_from'])
    our_domains = set(our_df['url_from'])
    
    shared_domains = current_domains.intersection(our_domains)
    unique_to_target = current_domains - our_domains
    unique_to_us = our_domains - current_domains
    
    # Calcul des métriques moyennes pour les domaines partagés
    shared_df = current_df[current_df['url_from'].isin(shared_domains)]
    avg_dr = shared_df['domain_rating_source'].mean() if len(shared_df) > 0 else 0
    
    return {
        'shared_count': len(shared_domains),
        'unique_to_target': len(unique_to_target),
        'unique_to_us': len(unique_to_us),
        'shared_domains': list(shared_domains),
        'avg_dr_shared': avg_dr,
        'shared_df': shared_df
    }

def main():
    st.title("📊 Analyse de la Puissance de Netlinking")

    # Input pour notre domaine
    our_domain = st.text_input(
        "Votre domaine de référence",
        placeholder="ex: https://votresite.com",
        help="Ce domaine sera utilisé pour comparer les backlinks"
    )
    
    # Input pour l'URL à analyser
    url_input = st.text_input(
        "Entrez l'URL ou le domaine à analyser",
        placeholder="ex: https://example.com"
    )

    # Options d'analyse
    col1, col2 = st.columns(2)
    with col1:
        aggregation = st.selectbox(
            "Mode d'agrégation des backlinks",
            options=["all", "similar_links", "1_per_domain"],
            index=0,
            help="all: Tous les backlinks\nsimilar_links: Regroupe les liens similaires\n1_per_domain: Un seul lien par domaine"
        )
        limit = st.slider("Nombre de backlinks à analyser", 10, 1000, 100)

    with col2:
        mode = st.selectbox(
            "Mode de recherche",
            options=["subdomains", "exact", "prefix", "domain"],
            index=0,
            help="subdomains: Inclut tous les sous-domaines\nexact: URL exacte uniquement\nprefix: URLs commençant par la cible\ndomain: Domaine entier"
        )
        check_tier2 = st.checkbox("Analyser les liens de Niveau 2", value=False)

    if st.button("Analyser les backlinks"):
        if url_input:
            try:
                with st.spinner("Récupération et analyse des backlinks en cours..."):
                    # Récupération des backlinks de la cible
                    target_result = get_backlinks_cached(url_input, limit, mode, aggregation)
                    
                    # Si un domaine de référence est fourni, récupération de ses backlinks
                    if our_domain:
                        our_result = get_our_domain_backlinks(our_domain, mode)
                        
                        if our_result and target_result:
                            overlap_analysis = analyze_domain_overlap(
                                target_result['backlinks'],
                                our_result['backlinks']
                            )
                            
                            # Affichage de l'analyse comparative
                            st.header("🔄 Analyse Comparative des Backlinks")
                            
                            # Métriques de chevauchement
                            col1, col2, col3 = st.columns(3)
                            col1.metric(
                                "Backlinks communs",
                                overlap_analysis['shared_count']
                            )
                            col2.metric(
                                f"Uniques à {url_input}",
                                overlap_analysis['unique_to_target']
                            )
                            col3.metric(
                                f"Uniques à {our_domain}",
                                overlap_analysis['unique_to_us']
                            )
                            
                            # Analyse des DR moyens pour les domaines partagés
                            if overlap_analysis['shared_count'] > 0:
                                st.subheader("🎯 Analyse des domaines communs")
                                st.metric(
                                    "DR moyen des domaines communs",
                                    f"{overlap_analysis['avg_dr_shared']:.1f}"
                                )
                                
                                # Liste des domaines communs avec leurs métriques
                                st.subheader("🤝 Liste des domaines en commun")
                                shared_df = overlap_analysis['shared_df'].copy()
                                shared_df = shared_df.sort_values('domain_rating_source', ascending=False)
                                
                                st.dataframe(
                                    shared_df,
                                    column_config={
                                        "domain_rating_source": "DR Source",
                                        "url_from": "URL Source",
                                        "first_seen": "Première vue",
                                        "link_type": "Type de lien"
                                    },
                                    hide_index=True
                                )

                    # Analyse des backlinks de la cible
                    if target_result and 'backlinks' in target_result:
                        df = pd.DataFrame(target_result['backlinks'])
                        
                        # Analyse des liens Tier 2 si demandé
                        if check_tier2 and len(df) > 0:
                            st.info("Analyse des liens de Niveau 2 en cours...")
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            tier2_live_links, tier2_live_refdomains = analyze_tier2_links_parallel(
                                df, progress_bar, status_text
                            )
                            
                            df['tier2_live_links'] = tier2_live_links
                            df['tier2_live_refdomains'] = tier2_live_refdomains
                            status_text.text("Analyse des liens de Niveau 2 terminée!")
                        
                        # Total des backlinks
                        st.header(f"📈 Total des Backlinks : {len(df)}")

                        # Distribution temporelle
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

                        # Distribution des DR
                        st.subheader("📊 Nombre de Backlinks en fonction du DR")
                        dr_distribution = analyze_dr_distribution(df)
                        cols = st.columns(4)
                        for i, (range_name, count) in enumerate(dr_distribution.items()):
                            cols[i].metric(range_name, count)
                        
                        # Distribution des Tiers
                        if 'tier2_live_links' in df.columns:
                            st.subheader("🔗 Distribution des liens de niveau 2")
                            
                            # Backlinks
                            links_distribution = analyze_tier_distribution(df, 'tier2_live_links')
                            cols = st.columns(4)
                            for i, (range_name, count) in enumerate(links_distribution.items()):
                                cols[i].metric(
                                    range_name.replace('tier2_live_links', 'Live backlinks Tier2'),
                                    count
                                )
                            
                            # Referring domains
                            st.subheader("🔗 Distribution des domaines référents de niveau 2")
                            refdomains_distribution = analyze_tier_distribution(df, 'tier2_live_refdomains')
                            cols = st.columns(4)
                            for i, (range_name, count) in enumerate(refdomains_distribution.items()):
                                cols[i].metric(
                                    range_name.replace('tier2_live_refdomains', 'RD Tier2'),
                                    count
                                )

                        # Métriques maximales
                        st.subheader("🏆 Métriques Maximales")
                        max_metrics = get_max_metrics(df)
                        col1, col2 = st.columns(2)
                        col1.metric("MAX(Domain Rating)", f"{max_metrics['max_dr']:.1f}")
                        col2.metric("MAX(Tier2)", max_metrics['max_tier'])
                        
                        # Backlink le plus puissant
                        st.markdown(f"### 🔗 Backlink le plus puissant (DR {max_metrics['max_dr_value']:.1f})")
                        st.write(max_metrics['max_dr_url'])
                        
                        # Tableau détaillé
                        st.subheader("📋 Liste détaillée des Backlinks")
                        
                        column_config = {
                            "domain_rating_source": "DR Source",
                            "url_from": "URL Source",
                            "first_seen": "Première vue",
                            "link_type": "Type de lien"
                        }
                        
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

if __name__ == "__main__":
    main()
