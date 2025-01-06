import streamlit as st
import http.client
import json
import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import logging

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Chargement des variables d'environnement
load_dotenv()
AHREFS_API_KEY = os.getenv('AHREFS_API_KEY')

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
        
        # Encodage de l'URL cible
        encoded_url = target_url.replace(':', '%3A').replace('/', '%2F')
        
        endpoint = (f"/v3/site-explorer/all-backlinks?"
                   f"limit={limit}&"
                   f"select=domain_rating_source,url_from,first_seen,link_type&"
                   f"target={encoded_url}&"
                   f"mode=subdomains&"
                   f"aggregation=similar_links")
        
        logger.info(f"Envoi de la requête à l'API Ahrefs pour : {target_url}")
        conn.request("GET", endpoint, headers=headers)
        
        response = conn.getresponse()
        data = response.read()
        
        logger.info(f"Statut de la réponse : {response.status}")
        
        if response.status == 200:
            return json.loads(data.decode("utf-8"))
        else:
            logger.error(f"Erreur API: {data.decode('utf-8')}")
            return None
            
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des backlinks: {str(e)}")
        return None
    finally:
        conn.close()

def format_date(date_str):
    """
    Formate la date ISO en format plus lisible
    """
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
        return date_obj.strftime("%d/%m/%Y %H:%M")
    except:
        return date_str

# Interface Streamlit
st.title("📊 Analyseur de Backlinks Ahrefs")

# Input pour l'URL
url_input = st.text_input(
    "Entrez l'URL ou le nom de domaine à analyser",
    placeholder="ex: https://example.com"
)

# Nombre de résultats
limit = st.slider("Nombre de backlinks à afficher", 10, 1000, 100)

if st.button("Analyser les backlinks"):
    if url_input:
        with st.spinner("Récupération des backlinks en cours..."):
            result = get_backlinks(url_input, limit)
            
            if result and 'items' in result:
                # Création du DataFrame
                df = pd.DataFrame(result['items'])
                
                # Formatage des dates
                if 'first_seen' in df.columns:
                    df['first_seen'] = df['first_seen'].apply(format_date)
                
                # Affichage des statistiques
                st.subheader("📈 Statistiques")
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Nombre total de backlinks", len(df))
                with col2:
                    avg_dr = df['domain_rating_source'].mean()
                    st.metric("Domain Rating moyen", f"{avg_dr:.1f}")
                
                # Affichage du tableau
                st.subheader("🔗 Liste des Backlinks")
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
