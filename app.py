import streamlit as st

st.set_page_config(
    page_title="Analyse de Backlinks",
    page_icon="🔗",
    layout="wide"
)

st.title("🔗 Analyse de Backlinks Multi-Sources")

st.markdown("""
## Bienvenue dans l'outil d'analyse de backlinks

Cet outil vous permet d'analyser vos backlinks à partir de différentes sources :

### 📊 Sources disponibles

1. **Ahrefs**
   - Analyse détaillée des backlinks
   - Métriques de Domain Rating
   - Analyse des liens de niveau 2

2. **DataForSeo**
   - Analyse en temps réel des backlinks
   - Métriques de Trust Flow
   - Analyse détaillée des domaines référents

Choisissez une source dans le menu de gauche pour commencer votre analyse.
""")
