import streamlit as st
import requests
import pandas as pd
import random
import unicodedata
import json
import os
from datetime import datetime

st.set_page_config(page_title="Académie d'Échecs des Calanques", layout="wide", page_icon="♟️")

# --- VERROUILLAGE PAR MOT DE PASSE ---
if "authentifie" not in st.session_state:
    st.session_state["authentifie"] = False

if not st.session_state["authentifie"]:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try: st.image("logo.png", width=150)
        except: pass
        st.markdown("**🔒 Accès Restreint - Académie d'Échecs des Calanques**")
        mdp = st.text_input("Veuillez saisir le mot de passe :", type="password")
        if st.button("Se connecter"):
            if mdp == "cassisechecs":
                st.session_state["authentifie"] = True
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")
    st.stop()

st.markdown("""
    <style>
    h1, h2, h3 { color: #4682B4 !important; }
    .stButton>button { background-color: #FF8C00; color: white; border: none; font-weight: bold; width:100%;}
    .stButton>button:hover { background-color: #e67e22; color: white; }
    div[data-testid="stSidebarNav"] { font-weight: bold; }
    .recherche-rapide { background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin-bottom: 20px; border-left: 5px solid #FF8C00; }
    </style>
""", unsafe_allow_html=True)

DB_FILE = "base_calanques.json"

def charger_base():
    default_db = {
        "elos_crevette": {}, "historique_appels": {}, "eleves_essai": [],
        "affectations_creneaux": {}, "cartes_membres": {} 
    }
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            try:
                db_chargee = json.load(f)
                for cle in default_db:
                    if cle not in db_chargee: db_chargee[cle] = default_db[cle]
                return db_chargee
            except: return default_db
    return default_db

def sauvegarder_base(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

if 'db' not in st.session_state: st.session_state['db'] = charger_base()

col1, col2 = st.columns([1, 4])
with col1:
    try: st.image("logo.png", width=140)
    except: st.write("♟️ **ACC**")
with col2:
    st.title("Académie d'Échecs des Calanques")
    st.markdown("**Plateforme Globale : Administration, Écoles & Entraînements**")

def calculer_nouveau_elo(r_a, r_b, score_a, k=40):
    e_a = 1.0 / (1.0 + 10.0 ** ((r_b - r_a) / 400.0))
    nouveau_r_a = r_a + k * (score_a - e_a)
    return max(100, round(nouveau_r_a))

def normaliser_nom(nom):
    if pd.isna(nom): return ""
    nom = str(nom).lower().strip().replace("*", "")
    return ''.join(c for c in unicodedata.normalize('NFD', nom) if unicodedata.category(c) != 'Mn')

def generer_appariements_suisses(joueurs_scores, elos_dict, historique_rencontres):
    joueurs_tries = sorted(joueurs_scores.keys(), key=lambda j: (joueurs_scores[j], elos_dict.get(j, 400), random.random()), reverse=True)
    appariements, non_apparies, exempt = [], list(joueurs_tries), None
    if len(non_apparies) % 2 != 0: exempt = non_apparies.pop()
    while len(non_apparies) > 1:
        j1 = non_apparies.pop(0)
        j2_trouve = None
        for idx, j2 in enumerate(non_apparies):
            pair = (min(j1, j2), max(j1, j2))
            if pair not in historique_rencontres:
                j2_trouve = non_apparies.pop(idx)
                historique_rencontres.add(pair)
                appariements.append((j1, j2_trouve))
                break
        if not j2_trouve and non_apparies:
            j2_trouve = non_apparies.pop(0)
            historique_rencontres.add((min(j1, j2_trouve), max(j1, j2_trouve)))
            appariements.append((j1, j2_trouve))
    return appariements, exempt, historique_rencontres

def auto_affecter_creneau(campagne, formule):
    camp, form = str(campagne).lower(), str(formule).lower()
    if "lundi" in form:
        if "trinit" in camp: return "Lundi - Sainte-Trinité (CP)"
        return "Lundi - La Ciotat (École)"
    if "mardi" in form:
        if "trinit" in camp: return "Mardi - Sainte-Trinité (CE1)"
        if "augustin" in camp: return "Mardi - Saint-Augustin (CP-CE1)"
        return "Mardi - Ceyreste / Marseille"
    if "mercredi" in form: return "Mercredi - Ceyreste / Cassis"
    if "jeudi" in form:
        if "trinit" in camp: return "Jeudi - Sainte-Trinité (Collège)"
        if "bosco" in camp: 
            if "collège" in form or "college" in form: return "Jeudi - Don Bosco (Collège)"
            return "Jeudi - Don Bosco (École)"
        return "Jeudi - Cassis / La Ciotat"
    if "vendredi" in form:
        if "augustin" in camp: return "Vendredi - Saint-Augustin (CE2-CM2)"
        if "trinit" in camp: return "Vendredi - Sainte-Trinité (CE2-CM2)"
        return "Vendredi - Cassis"
    return None

def get_helloasso_token(client_id, client_secret):
    url = "https://api.helloasso.com/oauth2/token"
    try:
        r = requests.post(url, data={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}, headers={"Content-Type": "application/x-www-form-urlencoded"})
        return r.json().get("access_token") if r.status_code == 200 else None
    except: return None

def fetch_campaign_items(token, form_type, form_slug, nom_campagne):
    url = f"https://api.helloasso.com/v5/organizations/echecs-cassis/forms/{form_type}/{form_slug}/items"
    try:
        # LE CŒUR DU CORRECTIF : L'ajout de withDetails=true oblige HelloAsso à cracher les réponses aux questions
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params={"pageSize": 100, "withDetails": "true"})
        items = r.json().get("data", [])
        rows = []
        for item in items:
            user, payer = item.get("user", {}), item.get("payer", {})
            nom_tarif = str(item.get("name", ""))
            
            type_formule = "Club" if "club" in nom_campagne.lower() else "École"
            nom_propre = user.get("lastName", payer.get("lastName", "Inconnu")).replace("*", "").strip().upper()
            prenom_propre = user.get("firstName", payer.get("firstName", "Inconnu")).replace("*", "").strip().title()
            
            email_def = user.get("email", payer.get("email", ""))
            adresse_def = user.get("address", payer.get("address", ""))
            ville_def = user.get("city", payer.get("city", ""))
            naissance_def = user.get("birthDate", user.get("dateOfBirth", payer.get("dateOfBirth", "")))
            
            row = {
                "Campagne": nom_campagne,
                "Nom": nom_propre,
                "Prénom": prenom_propre,
                "Identité": f"{prenom_propre} {nom_propre}",
                "Montant Payé": f"{item.get('amount', 0) / 100} €",
                "Formule": nom_tarif,
                "Type": type_formule,
                "Licence_FFE": "Non croisé",
                "Nom payeur": payer.get("lastName", "").replace("*", "").strip(),
                "Prénom payeur": payer.get("firstName", "").replace("*", "").strip(),
                "Email payeur": email_def,
                
                "N° Portable": "",
                "N° Portable 2 (en cas d'urgence)": "",
                "EMail": email_def,
                "Adresse": adresse_def,
                "Ville": ville_def,
                "Nom et prénom du responsable légal": "",
                "Classe": "",
                "Date de naissance": naissance_def,
                "Taille du t-shirt": "",
                "Dans quel ville sera votre créneaux principale ": "",
                "J'autorise le club à diffuser des photos de moi ou mon enfant en lien avec notre activité sur notre site et sur les réseaux sociaux (Facebook ; Instagram, Twitter):": "",
                "J’autorise le club à utiliser des images de moi ou mon enfant pour des objets publicitaires (prospectus de présentation du club, oriflamme, kakemono) :": "",
                "J’accepte de recevoir les informations sur l’actualité du club (soirée blitz, organisation de stages pendant les vacances…) ainsi que les annonces des prochains tournois par mail": "",
                "J’autorise mon enfant à quitter le club seul": "-",
                'e confirme avoir renseigné le questionnaire de santé "Sport" (mineurs) https://www.echecs.asso.fr/Actus/14098/questionnaire_mineur.pdf': "",
                
                "Sortie Seul": "-",
                "Classe Déduite": "-"
            }
            
            if row["Date de naissance"] and len(str(row["Date de naissance"])) >= 10:
                row["Date de naissance"] = str(row["Date de naissance"])[:10]
            
            for field in item.get("customFields", []):
                nom_champ = str(field.get("name", ""))
                reponse = str(field.get("answer", "")).strip()
                nom_lower = nom_champ.lower()
                
                row[nom_champ] = reponse
                
                if "classe" in nom_lower or "niveau" in nom_lower: 
                    row["Classe"] = reponse
                    row["Classe Déduite"] = reponse
                if "portable 2" in nom_lower or "urgence" in nom_lower: 
                    row["N° Portable 2 (en cas d'urgence)"] = reponse
                elif "portable" in nom_lower or "téléphone" in nom_lower or "telephone" in nom_lower or "tel" in nom_lower: 
                    if not row["N° Portable"]: row["N° Portable"] = reponse
                if "responsable" in nom_lower or "légal" in nom_lower: 
                    row["Nom et prénom du responsable légal"] = reponse
                if "t-shirt" in nom_lower: 
                    row["Taille du t-shirt"] = reponse
                if "créneaux" in nom_lower and "principale" in nom_lower: 
                    row["Dans quel ville sera votre créneaux principale "] = reponse
                
                if "diffuser" in nom_lower and "photos" in nom_lower: 
                    row["J'autorise le club à diffuser des photos de moi ou mon enfant en lien avec notre activité sur notre site et sur les réseaux sociaux (Facebook ; Instagram, Twitter):"] = reponse
                if "publicitaires" in nom_lower or "prospectus" in nom_lower: 
                    row["J’autorise le club à utiliser des images de moi ou mon enfant pour des objets publicitaires (prospectus de présentation du club, oriflamme, kakemono) :"] = reponse
                if "actualité" in nom_lower or "blitz" in nom_lower: 
                    row["J’accepte de recevoir les informations sur l’actualité du club (soirée blitz, organisation de stages pendant les vacances…) ainsi que les annonces des prochains tournois par mail"] = reponse
                if "questionnaire" in nom_lower and "mineurs" in nom_lower: 
                    row['e confirme avoir renseigné le questionnaire de santé "Sport" (mineurs) https://www.echecs.asso.fr/Actus/14098/questionnaire_mineur.pdf'] = reponse
                    
                if "adresse" in nom_lower and len(reponse) > 2: row["Adresse"] = reponse
                if "ville" in nom_lower and "créneaux" not in nom_lower and len(reponse) > 1: row["Ville"] = reponse
                if "naissance" in nom_lower and len(reponse) > 2: row["Date de naissance"] = reponse
                if "email" in nom_lower or "courriel" in nom_lower: row["EMail"] = reponse
                
                if "quitter" in nom_lower and "seul" in nom_lower:
                    if type_formule == "École":
                        row["J’autorise mon enfant à quitter le club seul"] = "N/A (École)"
                        row["Sortie Seul"] = "N/A (École)"
                    else:
                        if "oui" in reponse.lower() or reponse.lower() == "true": 
                            row["J’autorise mon enfant à quitter le club seul"] = "✅ OUI"
                            row["Sortie Seul"] = "✅ OUI"
                        elif "non" in reponse.lower() or reponse.lower() == "false": 
                            row["J’autorise mon enfant à quitter le club seul"] = "❌ NON"
                            row["Sortie Seul"] = "❌ NON"
                        elif reponse == "": 
                            row["J’autorise mon enfant à quitter le club seul"] = "-"
                            row["Sortie Seul"] = "-"
                        else: 
                            row["J’autorise mon enfant à quitter le club seul"] = f"❓ {reponse}"
                            row["Sortie Seul"] = f"❓ {reponse}"
                            
            rows.append(row)
        return rows
    except: return []

def analyser_fichier_ffe(fichier):
    try:
        if fichier.name.endswith('.csv'): df_ffe = pd.read_csv(fichier, sep=None, engine='python')
        else: df_ffe = pd.read_excel(fichier)
        col_nom = next((c for c in df_ffe.columns if "nom" in c.lower() and "prenom" not in c.lower()), None)
        col_prenom = next((c for c in df_ffe.columns if "prenom" in str(c).lower() or "prénom" in str(c).lower()), None)
        col_elo = next((c for c in df_ffe.columns if "elo" in str(c).lower() or "rapide" in str(c).lower()), None)
        col_licence = next((c for c in df_ffe.columns if "licence" in str(c).lower() or "code" in str(c).lower() or "ref" in str(c).lower()), None)

        if col_nom and col_prenom:
            df_ffe['Cle_Croisement'] = df_ffe[col_nom].apply(normaliser_nom) + df_ffe[col_prenom].apply(normaliser_nom)
            df_ffe['Elo_FFE'] = df_ffe[col_elo] if col_elo else 1000
            df_ffe['Licence_FFE'] = df_ffe[col_licence] if col_licence else "Inconnue"
            return df_ffe[['Cle_Croisement', 'Elo_FFE', 'Licence_FFE']]
    except: return pd.DataFrame()
    return pd.DataFrame()

st.sidebar.header("🔑 Espace de Travail")
module_choisi = st.sidebar.radio("", ["🛠️ Module Administration", "♟️ Module Entraîneur"])

st.sidebar.markdown("---")
st.sidebar.header("1️⃣ Base FFE (Licences)")
fichier_ffe = st.sidebar.file_uploader("Fichier FFE pour croisement", type=['csv', 'xls', 'xlsx'])
if fichier_ffe:
    df_ffe = analyser_fichier_ffe(fichier_ffe)
    if not df_ffe.empty:
        st.session_state['df_ffe'] = df_ffe
        st.sidebar.success("Fichier FFE chargé !")

st.sidebar.markdown("---")
st.sidebar.header("2️⃣ Synchronisation Data")
saved_id = st.secrets["helloasso"]["client_id"] if "helloasso" in st.secrets else ""
saved_secret = st.secrets["helloasso"]["client_secret"] if "helloasso" in st.secrets else ""
client_id = st.sidebar.text_input("Client ID", value=saved_id, type="password")
client_secret = st.sidebar.text_input("Client Secret", value=saved_secret, type="password")

if st.sidebar.button("🔄 Lancer la Synchronisation"):
    if client_id and client_secret:
        with st.spinner("Téléchargement des données..."):
            token = get_helloasso_token(client_id, client_secret)
            if token:
                campagnes = [
                    ("Adhésions Club", "Membership", "cotisations-et-adhesion-club-d-echecs-2026-2027"),
                    ("Sainte Trinité", "Event", "club-d-echecs-sainte-trinitie"),
                    ("Saint Augustin", "Event", "club-d-echecs-saint-augustin"),
                    ("Don Bosco", "Event", "club-d-echecs-don-bosco")
                ]
                all_data = []
                for nom, type_camp, slug in campagnes:
                    all_data.extend(fetch_campaign_items(token, type_camp, slug, nom))
                all_data.extend(st.session_state['db']['eleves_essai'])
                
                if all_data:
                    df_base = pd.DataFrame(all_data)
                    
                    if 'df_ffe' in st.session_state and not st.session_state['df_ffe'].empty:
                        df_base['Cle_Croisement'] = df_base['Nom'].apply(normaliser_nom) + df_base['Prénom'].apply(normaliser_nom)
                        df_base = pd.merge(df_base, st.session_state['df_ffe'], on='Cle_Croisement', how='left')
                        df_base['Elo_FFE'] = df_base['Elo_FFE'].fillna(1000).astype(int)
                        df_base['Licence_FFE'] = df_base['Licence_FFE'].fillna("Non croisé")
                        df_base = df_base.drop(columns=['Cle_Croisement'])
                    else:
                        df_base['Elo_FFE'], df_base['Licence_FFE'] = 1000, "Non croisé"

                    for _, row in df_base.iterrows():
                        identite = row['Identité']
                        if identite not in st.session_state['db']['elos_crevette']:
                            st.session_state['db']['elos_crevette'][identite] = 400
                        
                        creneau_auto = auto_affecter_creneau(row['Campagne'], row['Formule'])
                        if creneau_auto:
                            if creneau_auto not in st.session_state['db']['affectations_creneaux']:
                                st.session_state['db']['affectations_creneaux'][creneau_auto] = []
                            if identite not in st.session_state['db']['affectations_creneaux'][creneau_auto]:
                                st.session_state['db']['affectations_creneaux'][creneau_auto].append(identite)
                                
                    sauvegarder_base(st.session_state['db'])
                    st.session_state['df_adherents'] = df_base
                    st.sidebar.success(f"Base à jour ! {len(all_data)} dossiers.")
                else: st.sidebar.warning("Aucune donnée trouvée.")
            else: st.sidebar.error("Erreur API HelloAsso.")

if 'df_adherents' not in st.session_state:
    st.info("👈 Cliquez sur **Lancer la Synchronisation** dans le menu de gauche pour démarrer.")
else:
    df = st.session_state['df_adherents']
    date_jour = datetime.now().strftime("%d/%m/%Y")
    
    structure_creneaux = {
        "Lundi": ["Lundi - Sainte-Trinité (CP)", "Lundi - La Ciotat (École)", "Lundi - Carnoux", "Lundi - Club Cassis"],
        "Mardi": ["Mardi - Sainte-Trinité (CE1)", "Mardi - Saint-Augustin (CP-CE1)", "Mardi - Ceyreste / Marseille"],
        "Mercredi": ["Mercredi - Ceyreste / Cassis"],
        "Jeudi": ["Jeudi - Sainte-Trinité (Collège)", "Jeudi - Don Bosco (École)", "Jeudi - Don Bosco (Collège)", "Jeudi - Cassis / La Ciotat"],
        "Vendredi": ["Vendredi - Saint-Augustin (CE2-CM2)", "Vendredi - Sainte-Trinité (CE2-CM2)", "Vendredi - Cassis"]
    }

    if module_choisi == "🛠️ Module Administration":
        st.subheader("🛠️ Espace Administration du Club")
        tab_admin, tab_ecoles, tab_cartes, tab_historique = st.tabs(["📊 Base Adhérents", "🏫 Écoles", "🎟️ Cartes de Centres", "📅 Historique Appels"])
        
        with tab_admin:
            st.markdown('<div class="recherche-rapide">', unsafe_allow_html=True)
            st.markdown("#### 🔍 Recherche rapide de contact")
            recherche_nom = st.selectbox("Taper un nom/prénom pour obtenir ses coordonnées :", options=[""] + sorted(df["Identité"].tolist()))
            if recherche_nom:
                contact = df[df["Identité"] == recherche_nom].iloc[0]
                tel = contact.get('N° Portable', contact.get('EMail', 'Non renseigné'))
                st.write(f"📞 **Contact :** {tel} | 🚨 **Sortie :** {contact.get('J’autorise mon enfant à quitter le club seul', '-')} | 🏫 **Campagne :** {contact.get('Campagne', '-')}")
            st.markdown('</div>', unsafe_allow_html=True)

            col_ad1, col_ad2, col_ad3 = st.columns(3)
            with col_ad1: filtre_camp_admin = st.multiselect("Campagnes :", options=df["Campagne"].unique(), default=df["Campagne"].unique())
            with col_ad2: filtre_type_admin = st.multiselect("Types :", options=df["Type"].unique(), default=df["Type"].unique())
            with col_ad3: sans_licence = st.checkbox("🚨 Afficher UNIQUEMENT les sans-licence", value=False)
                
            df_admin = df[(df["Campagne"].isin(filtre_camp_admin)) & (df["Type"].isin(filtre_type_admin))].copy()
            if sans_licence and "Licence_FFE" in df_admin.columns: df_admin = df_admin[df_admin["Licence_FFE"] == "Non croisé"]

            df_admin['Elo Crevette 🦐'] = df_admin['Identité'].apply(lambda x: st.session_state['db']['elos_crevette'].get(x, 400))
            
            colonnes_prioritaires = [
                "Nom", "Prénom", "Nom payeur", "Prénom payeur", "Email payeur", 
                "Montant Payé", "Formule", "Licence_FFE", "Campagne",
                "Nom et prénom du responsable légal", "N° Portable", "N° Portable 2 (en cas d'urgence)", 
                "EMail", "Adresse", "Ville", "Classe", "Date de naissance", "Taille du t-shirt", 
                "Dans quel ville sera votre créneaux principale ",
                "J'autorise le club à diffuser des photos de moi ou mon enfant en lien avec notre activité sur notre site et sur les réseaux sociaux (Facebook ; Instagram, Twitter):",
                "J’autorise le club à utiliser des images de moi ou mon enfant pour des objets publicitaires (prospectus de présentation du club, oriflamme, kakemono) :",
                "J’accepte de recevoir les informations sur l’actualité du club (soirée blitz, organisation de stages pendant les vacances…) ainsi que les annonces des prochains tournois par mail",
                "J’autorise mon enfant à quitter le club seul",
                'e confirme avoir renseigné le questionnaire de santé "Sport" (mineurs) https://www.echecs.asso.fr/Actus/14098/questionnaire_mineur.pdf'
            ]
            
            colonnes_presentes = [c for c in colonnes_prioritaires if c in df_admin.columns]
            colonnes_a_exclure = ["Identité", "Type", "Elo_FFE", "Sortie Seul", "Classe Déduite", "Elo Crevette 🦐"]
            autres_colonnes = [c for c in df_admin.columns if c not in colonnes_presentes and c not in colonnes_a_exclure]
            
            colonnes_finales = colonnes_presentes + autres_colonnes + ["Elo Crevette 🦐"]
            colonnes_finales = list(dict.fromkeys(colonnes_finales))
            
            st.metric("Dossiers affichés", len(df_admin))
            st.dataframe(df_admin[colonnes_finales], use_container_width=True, hide_index=True)
            
        with tab_ecoles:
            st.markdown("### 🏫 Pilotage des Établissements Scolaires")
            ecoles_dispos = [c for c in df["Campagne"].unique() if "Club" not in c and "Adhésions" not in c]
            if ecoles_dispos:
                ecole_choisie = st.selectbox("Sélectionnez l'établissement :", ecoles_dispos)
                df_ec = df[df["Campagne"] == ecole_choisie].copy()
                total_eleves = len(df_ec)
                if total_eleves > 0:
                    c1, c2, c3 = st.columns(3)
                    nb_club = len(df_ec[df_ec["Type"] == "Club"])
                    c1.metric("🎓 Total Élèves", total_eleves)
                    c2.metric("♟️ Formule Club", f"{nb_club}", f"{(nb_club / total_eleves) * 100:.1f}%")
                    c3.metric("🏫 Formule Scolaire", total_eleves - nb_club)
                    
                    colonnes_ecole = ["Nom", "Prénom", "Classe Déduite", "Formule", "J’autorise mon enfant à quitter le club seul", "N° Portable", "N° Portable 2 (en cas d'urgence)"]
                    colonnes_ecole = [c for c in colonnes_ecole if c in df_ec.columns]
                    st.dataframe(df_ec[colonnes_ecole], use_container_width=True, hide_index=True)

        with tab_cartes:
            st.markdown("### 🎟️ Suivi des Cartes de Centres (Cassis & Carnoux)")
            ville_carte = st.radio("Sélectionner la commune à vérifier :", ["Cassis (Carte Centre Culturel)", "Carnoux (Carte du Coq)"])
            ville_cle = "Cassis" if "Cassis" in ville_carte else "Carnoux"
            eleves_concernes = set()
            for cle, liste in st.session_state['db']['affectations_creneaux'].items():
                if ville_cle in cle: eleves_concernes.update(liste)
            if not eleves_concernes: st.info(f"Aucun élève n'est encore assigné à {ville_cle}.")
            else:
                for eleve in sorted(list(eleves_concernes)):
                    if eleve not in st.session_state['db']['cartes_membres']: st.session_state['db']['cartes_membres'][eleve] = {"Cassis": False, "Carnoux": False}
                    c1, c2 = st.columns([3, 1])
                    c1.write(f"👤 **{eleve}**")
                    est_coche = c2.checkbox("✅ Carte OK", value=st.session_state['db']['cartes_membres'][eleve][ville_cle], key=f"carte_{ville_cle}_{eleve}")
                    st.session_state['db']['cartes_membres'][eleve][ville_cle] = est_coche
                if st.button("💾 Sauvegarder l'état des cartes"):
                    sauvegarder_base(st.session_state['db'])
                    st.success("Mise à jour des cartes enregistrée avec succès !")

        with tab_historique:
            st.markdown("### 📅 Registre des présences")
            if not st.session_state['db']['historique_appels']: st.info("Aucun appel n'a encore été enregistré.")
            else:
                for date_appel, data_groupes in sorted(st.session_state['db']['historique_appels'].items(), reverse=True):
                    with st.expander(f"📁 Présences du {date_appel}"):
                        for groupe, infos in data_groupes.items():
                            st.write(f"**{groupe}** (par {infos.get('entraineur', 'Inconnu')}) : {len(infos.get('presents', []))} présents")

    elif module_choisi == "♟️ Module Entraîneur":
        st.subheader("♟️ Espace Entraîneur")
        tab_appel, tab_tournoi, tab_affectations = st.tabs(["📋 Faire l'Appel", "⚔️ Tournoi & Elo", "⚙️ Affecter Élèves (Manuel)"])

        with tab_affectations:
            st.markdown("### ⚙️ Création Manuelle des listes de Créneaux")
            c_jour, c_lieu = st.columns(2)
            with c_jour: jour_aff = st.selectbox("Jour :", options=list(structure_creneaux.keys()), key="jour_aff")
            with c_lieu: lieu_aff = st.selectbox("Créneau :", options=structure_creneaux[jour_aff], key="lieu_aff")
            
            if lieu_aff not in st.session_state['db']['affectations_creneaux']: 
                st.session_state['db']['affectations_creneaux'][lieu_aff] = []
                
            options_eleves = sorted(df["Identité"].tolist())
            eleves_sauvegardes = st.session_state['db']['affectations_creneaux'][lieu_aff]
            eleves_valides = [e for e in eleves_sauvegardes if e in options_eleves]
            
            nouveaux_eleves = st.multiselect(
                f"Élèves assignés à {lieu_aff} :", 
                options=options_eleves, 
                default=eleves_valides
            )
            
            if st.button("💾 Sauvegarder cette liste d'appel"):
                st.session_state['db']['affectations_creneaux'][lieu_aff] = nouveaux_eleves
                sauvegarder_base(st.session_state['db'])
                st.success(f"Liste de {lieu_aff} mise à jour !")

        with tab_appel:
            st.markdown(f"### 📋 Appel du jour : **{date_jour}**")
            entraineur_appel = st.selectbox("Entraîneur responsable :", ["Quentin Massardo", "Alexandre Merenciano"])
            c_jour_ap, c_lieu_ap = st.columns(2)
            with c_jour_ap: jour_appel = st.selectbox("Sélectionner le Jour :", options=list(structure_creneaux.keys()), key="jour_ap")
            with c_lieu_ap: lieu_appel = st.selectbox("Créneau :", options=structure_creneaux[jour_appel], key="lieu_ap")
            
            liste_identites = st.session_state['db']['affectations_creneaux'].get(lieu_appel, [])
            if not liste_identites: st.info("Aucun élève assigné à ce créneau.")
            else:
                df_groupe = df[df["Identité"].isin(liste_identites)]
                presences = {}
                st.markdown("---")
                for idx, row in df_groupe.iterrows():
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"👤 **{row['Nom']}** {row['Prénom']} *(Sortie: {row.get('J’autorise mon enfant à quitter le club seul', '-')})*")
                    presences[row['Identité']] = c2.checkbox("Présent", value=True, key=f"pres_{row['Identité']}")

                if st.button(f"💾 Enregistrer l'appel pour {lieu_appel}"):
                    liste_presents = [id_joueur for id_joueur, est_present in presences.items() if est_present]
                    if date_jour not in st.session_state['db']['historique_appels']: st.session_state['db']['historique_appels'][date_jour] = {}
                    st.session_state['db']['historique_appels'][date_jour][lieu_appel] = {"entraineur": entraineur_appel, "presents": liste_presents}
                    sauvegarder_base(st.session_state['db'])
                    st.success("Appel enregistré !")

        with tab_tournoi:
            st.markdown("### ⚔️ Tournoi Suisse & Elo Crevette 🦐")
            creneaux_remplis = [k for k, v in st.session_state['db']['affectations_creneaux'].items() if len(v) > 0]
            if not creneaux_remplis: st.info("Aucun créneau disponible pour lancer un tournoi.")
            else:
                creneau_tournoi = st.selectbox("Lancer le tournoi pour le créneau :", options=creneaux_remplis)
                joueurs_inscrits = st.session_state['db']['affectations_creneaux'][creneau_tournoi]
                
                if 'scores_tournoi' not in st.session_state:
                    st.session_state['scores_tournoi'] = {j: 0.0 for j in joueurs_inscrits}
                    st.session_state['historique_rencontres'] = set()
                    st.session_state['ronde_actuelle'] = 1
                    st.session_state['appariements_ronde'] = []

                col_t1, col_t2 = st.columns(2)
                with col_t1: st.metric("Ronde actuelle", st.session_state['ronde_actuelle'])
                with col_t2:
                    if st.button("🔄 Réinitialiser le tournoi"):
                        st.session_state['scores_tournoi'] = {j: 0.0 for j in joueurs_inscrits}
                        st.session_state['historique_rencontres'] = set()
                        st.session_state['ronde_actuelle'] = 1
                        st.session_state['appariements_ronde'] = []
                        st.rerun()

                st.markdown("---")
                if st.button("🎲 Générer la Ronde"):
                    pairs, exempt, st.session_state['historique_rencontres'] = generer_appariements_suisses(
                        st.session_state['scores_tournoi'], st.session_state['db']['elos_crevette'], st.session_state['historique_rencontres']
                    )
                    st.session_state['appariements_ronde'], st.session_state['exempt_ronde'] = pairs, exempt

                if st.session_state.get('appariements_ronde'):
                    st.subheader(f"♟️ Matchs — Ronde {st.session_state['ronde_actuelle']}")
                    resultats_saisis = []
                    for i, (j1, j2) in enumerate(st.session_state['appariements_ronde'], 1):
                        elo1 = st.session_state['db']['elos_crevette'].get(j1, 400)
                        elo2 = st.session_state['db']['elos_crevette'].get(j2, 400)
                        c_ech, c_res = st.columns([3, 2])
                        c_ech.markdown(f"**Échiquier {i} :** ⚪ **{j1}** ({elo1}🦐)  🆚  ⚫ **{j2}** ({elo2}🦐)")
                        res = c_res.selectbox(f"Résultat", ["Sélectionner...", "1 - 0 (Blancs)", "0 - 1 (Noirs)", "0.5 - 0.5 (Nulle)"], key=f"res_{i}", label_visibility="collapsed")
                        resultats_saisis.append((j1, j2, res))
                    if st.session_state.get('exempt_ronde'): st.warning(f"👑 **Exempt (1 pt) :** {st.session_state['exempt_ronde']}")

                    st.markdown("---")
                    if st.button("💾 Valider les résultats et sauvegarder les Elo Crevette"):
                        if any(r[2] == "Sélectionner..." for r in resultats_saisis): st.error("⚠️ Saisissez tous les résultats.")
                        else:
                            for j1, j2, res in resultats_saisis:
                                elo1 = st.session_state['db']['elos_crevette'].get(j1, 400)
                                elo2 = st.session_state['db']['elos_crevette'].get(j2, 400)
                                if res == "1 - 0 (Blancs)":
                                    st.session_state['scores_tournoi'][j1] += 1.0
                                    st.session_state['db']['elos_crevette'][j1] = calculer_nouveau_elo(elo1, elo2, 1.0)
                                    st.session_state['db']['elos_crevette'][j2] = calculer_nouveau_elo(elo2, elo1, 0.0)
                                elif res == "0 - 1 (Noirs)":
                                    st.session_state['scores_tournoi'][j2] += 1.0
                                    st.session_state['db']['elos_crevette'][j1] = calculer_nouveau_elo(elo1, elo2, 0.0)
                                    st.session_state['db']['elos_crevette'][j2] = calculer_nouveau_elo(elo2, elo1, 1.0)
                                else:
                                    st.session_state['scores_tournoi'][j1] += 0.5
                                    st.session_state['scores_tournoi'][j2] += 0.5
                                    st.session_state['db']['elos_crevette'][j1] = calculer_nouveau_elo(elo1, elo2, 0.5)
                                    st.session_state['db']['elos_crevette'][j2] = calculer_nouveau_elo(elo2, elo1, 0.5)

                            if st.session_state.get('exempt_ronde'): st.session_state['scores_tournoi'][st.session_state['exempt_ronde']] += 1.0
                            sauvegarder_base(st.session_state['db'])
                            st.session_state['ronde_actuelle'] += 1
                            st.session_state['appariements_ronde'] = []
                            st.success("Résultats et Elos Crevette sauvegardés !")
                            st.rerun()
