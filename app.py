import streamlit as st
import requests
import pandas as pd
import random
import unicodedata
import json
import os
import io
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Académie d'Échecs des Calanques", layout="wide", page_icon="♟️")

# --- CHARTE GRAPHIQUE ---
st.markdown("""
    <style>
    h1, h2, h3, h4, h5, h6 { color: #005b96 !important; font-weight: bold; }
    .stButton>button { background-color: #FF8C00 !important; color: white !important; border: none; font-weight: bold; width:100%; border-radius: 8px; transition: 0.3s; }
    .stButton>button:hover { background-color: #005b96 !important; color: white !important; }
    button[data-baseweb="tab"][aria-selected="true"] > div { color: #005b96 !important; font-weight: bold; }
    button[data-baseweb="tab"][aria-selected="true"] { border-bottom-color: #FF8C00 !important; }
    .recherche-rapide { background-color: #f4f6f9; padding: 15px; border-radius: 10px; margin-bottom: 20px; border-left: 6px solid #FF8C00; }
    div[data-baseweb="select"] { border: 2px solid #FF8C00 !important; border-radius: 6px !important; }
    </style>
""", unsafe_allow_html=True)

# --- VERROUILLAGE PAR MOT DE PASSE ---
if "authentifie" not in st.session_state: st.session_state["authentifie"] = False
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
            else: st.error("Mot de passe incorrect.")
    st.stop()

# --- CONNEXION GOOGLE SHEETS CLOUD ---
def get_gsheets_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

def get_or_create_worksheet(sh, name):
    try: return sh.worksheet(name)
    except Exception: return sh.add_worksheet(title=name, rows="1000", cols="50")

def initialiser_memoire_vierge():
    return {
        "elos_crevette": {}, "historique_appels": {}, "eleves_essai": [],
        "affectations_creneaux": {}, "cartes_membres": {},
        "validations_promo": {}, "sorties_manuelles": {},
        "eleves_deja_affectes": [], "identites_helloasso_connues": [],
        "dossiers_supprimes": []
    }

def charger_base_cloud():
    try:
        client = get_gsheets_client()
        sh = client.open("Base_Calanques_DB")
        ws = get_or_create_worksheet(sh, "DB_JSON")
        vals = ws.col_values(1)
        if vals:
            db = json.loads("".join(vals))
            return db
    except Exception as e:
        st.sidebar.error(f"❌ Erreur lecture DB : {e}")
    return initialiser_memoire_vierge()

def sauvegarder_base_cloud(db):
    try:
        client = get_gsheets_client()
        sh = client.open("Base_Calanques_DB")
        ws = get_or_create_worksheet(sh, "DB_JSON")
        json_str = json.dumps(db, ensure_ascii=False)
        chunks = [[json_str[i:i+40000]] for i in range(0, len(json_str), 40000)]
        ws.clear()
        try: ws.update(values=chunks, range_name="A1")
        except TypeError: ws.update("A1", chunks)
    except Exception as e:
        st.sidebar.error(f"❌ Erreur écriture DB : {e}")

def charger_adherents_cloud():
    try:
        client = get_gsheets_client()
        sh = client.open("Base_Calanques_DB")
        ws = get_or_create_worksheet(sh, "Adherents")
        data = ws.get_all_records()
        if data: return pd.DataFrame(data)
    except Exception as e:
        st.sidebar.error(f"❌ Erreur lecture Adhérents : {e}")
    return pd.DataFrame()

def sauvegarder_adherents_cloud(df):
    try:
        client = get_gsheets_client()
        sh = client.open("Base_Calanques_DB")
        ws = get_or_create_worksheet(sh, "Adherents")
        ws.clear()
        if not df.empty:
            data = [df.columns.values.tolist()] + df.fillna("").astype(str).values.tolist()
            try: ws.update(values=data, range_name="A1")
            except TypeError: ws.update("A1", data)
    except Exception as e:
        st.sidebar.error(f"❌ Erreur écriture Adhérents : {e}")

# --- CHARGEMENT SÉCURISÉ & AUTO-NETTOYAGE DES DOUBLONS ---
if 'db' not in st.session_state: 
    with st.spinner("Connexion sécurisée au Cloud Google..."):
        st.session_state['db'] = charger_base_cloud()

if 'df_adherents' not in st.session_state:
    with st.spinner("Récupération et nettoyage de la base adhérents..."):
        df_loaded = charger_adherents_cloud()
        if not df_loaded.empty: 
            len_avant = len(df_loaded)
            if 'ID_Dossier' in df_loaded.columns:
                df_loaded['ID_Dossier'] = df_loaded['ID_Dossier'].replace('', float('nan'))
                mask_valid_id = df_loaded['ID_Dossier'].notna() & (df_loaded['ID_Dossier'].astype(str) != 'nan') & (df_loaded['ID_Dossier'].astype(str).str.strip() != '')
                df_valid = df_loaded[mask_valid_id].drop_duplicates(subset=['ID_Dossier'], keep='last')
                df_invalid = df_loaded[~mask_valid_id]
                df_loaded = pd.concat([df_valid, df_invalid]).reset_index(drop=True)
                
            st.session_state['df_adherents'] = df_loaded
            if len(df_loaded) < len_avant:
                sauvegarder_adherents_cloud(df_loaded)

# --- BOUCLIER ANTI-KEYERROR ABSOLU ---
default_mem = initialiser_memoire_vierge()
for cle, val_defaut in default_mem.items():
    if cle not in st.session_state['db']:
        st.session_state['db'][cle] = val_defaut

col1, col2 = st.columns([1, 4])
with col1:
    try: st.image("logo.png", width=140)
    except: st.write("♟️ **ACC**")
with col2:
    st.title("Académie d'Échecs des Calanques")
    st.markdown("**Plateforme Globale : Administration, Écoles & Entraînements**")

# --- FONCTIONS UTILITAIRES ---
def calculer_nouveau_elo(r_a, r_b, score_a, k=40):
    e_a = 1.0 / (1.0 + 10.0 ** ((r_b - r_a) / 400.0))
    return max(100, round(r_a + k * (score_a - e_a)))

def normaliser_nom(nom):
    if pd.isna(nom): return ""
    return ''.join(c for c in unicodedata.normalize('NFD', str(nom).lower().strip().replace("*", "")) if unicodedata.category(c) != 'Mn')

def estimer_sexe(prenom):
    if not prenom: return "M"
    p = normaliser_nom(str(prenom).split("-")[0].split()[0])
    hommes_exceptions = ["baptiste", "alexandre", "pierre", "guillaume", "antoine", "maxime", "stephane", "rene", "jules", "charles", "georges", "luc", "emile", "philippe", "cyrille", "auguste", "aime", "gilles", "patrice", "eugene", "serge", "hippolyte", "nicolas", "theophile", "timothee", "jerome", "gregoire", "etienne", "matteo", "mathis", "louis", "sacha", "noa", "luca", "andrea", "ange", "aristide", "arsene", "barthelemy", "baudouin", "come", "ulysse", "gaspard", "theodore", "zacharie", "claude", "dominique"]
    femmes_exceptions = ["manon", "carmen", "iris", "margaux", "margot", "maud", "astrid", "sarah", "esther", "fleur", "marion", "lison", "ninon", "suzon", "lou", "alison", "myriam", "sharon", "eden", "ines", "anais", "agnes", "charlotte", "marianne"]
    if p in hommes_exceptions: return "M"
    if p in femmes_exceptions: return "F"
    if p.endswith(('a', 'e', 'ine', 'elle', 'ette', 'ie', 'ia')): return "F"
    if p.endswith(('i', 'y')):
        if p in ["anthony", "jeremy", "willy", "jimmy", "gregory", "remi", "henri", "dmitri", "ali", "mehdi", "valery", "thierry", "charley", "guy", "yuri", "tony", "johny", "jonny", "dany", "sami", "fadi"]: return "M"
        return "F"
    return "M"

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

def get_elo_actif(identite, df_adherents, db):
    try:
        row = df_adherents[df_adherents["Identité"] == identite].iloc[0]
        elo_ffe = int(row.get("Elo_FFE", 0))
        licence = str(row.get("Licence_FFE", "Non croisé"))
        elos_virtuels_ffe = [799, 899, 999, 1099, 1199, 1299, 1399, 1499]
        if licence != "Non croisé" and elo_ffe > 0 and elo_ffe not in elos_virtuels_ffe: 
            return elo_ffe, "⚡ FFE/FIDE"
    except: pass
    return db['elos_crevette'].get(identite, 400), "🦐 Crevette"

def affectations_automatiques(row):
    creneaux = []
    camp, form, classe = str(row.get("Campagne", "")).lower(), str(row.get("Formule", "")).lower(), str(row.get("Classe", "")).lower()
    ville_choisie = str(row.get("Dans quel ville sera votre créneaux principale", "")).lower()
    
    if "trinit" in camp:
        if "cp" in classe: creneaux.append("Lundi - Sainte-Trinité (CP)")
        elif "ce1" in classe: creneaux.append("Mardi - Sainte-Trinité (CE1)")
        elif any(c in classe for c in ["ce2", "cm1", "cm2", "cm"]): creneaux.append("Vendredi - Sainte-Trinité (CE2-CM2)")
        elif any(c in classe for c in ["coll", "6ème", "5ème", "4ème", "3ème"]): creneaux.append("Jeudi - Sainte-Trinité (Collège)")
    elif "augustin" in camp:
        if "cp" in classe or "ce1" in classe: creneaux.append("Mardi - Saint-Augustin (CP-CE1)")
        elif any(c in classe for c in ["ce2", "cm1", "cm2", "cm"]): creneaux.append("Vendredi - Saint-Augustin (CE2-CM2)")
    elif "bosco" in camp:
        if "coll" in form or "coll" in classe or any(c in classe for c in ["6ème", "5ème", "4ème", "3ème"]): creneaux.append("Jeudi - Don Bosco (Collège)")
        else: creneaux.append("Jeudi - Don Bosco (École)")
        
    if "club" in camp or "adhésion" in camp or "adhesion" in camp:
        if "cassis" in ville_choisie: creneaux.extend(["Lundi - Club Cassis", "Mercredi - Ceyreste / Cassis", "Jeudi - Cassis / La Ciotat", "Vendredi - Cassis"])
        if "marseille" in ville_choisie: creneaux.append("Mardi - Ceyreste / Marseille")
        if "ceyreste" in ville_choisie: creneaux.extend(["Mardi - Ceyreste / Marseille", "Mercredi - Ceyreste / Cassis"])
        if "ciotat" in ville_choisie: creneaux.extend(["Lundi - La Ciotat (École)", "Jeudi - Cassis / La Ciotat"])
        if "carnoux" in ville_choisie: creneaux.append("Lundi - Carnoux")
            
    if not creneaux:
        if "lundi" in form:
            if "trinit" in camp: creneaux.append("Lundi - Sainte-Trinité (CP)")
            else: creneaux.append("Lundi - La Ciotat (École)")
        elif "mardi" in form:
            if "trinit" in camp: creneaux.append("Mardi - Sainte-Trinité (CE1)")
            elif "augustin" in camp: creneaux.append("Mardi - Saint-Augustin (CP-CE1)")
            else: creneaux.append("Mardi - Ceyreste / Marseille")
        elif "mercredi" in form: creneaux.append("Mercredi - Ceyreste / Cassis")
        elif "jeudi" in form:
            if "trinit" in camp: creneaux.append("Jeudi - Sainte-Trinité (Collège)")
            elif "bosco" in camp: 
                if "coll" in form: creneaux.append("Jeudi - Don Bosco (Collège)")
                else: creneaux.append("Jeudi - Don Bosco (École)")
            else: creneaux.append("Jeudi - Cassis / La Ciotat")
        elif "vendredi" in form:
            if "augustin" in camp: creneaux.append("Vendredi - Saint-Augustin (CE2-CM2)")
            elif "trinit" in camp: creneaux.append("Vendredi - Sainte-Trinité (CE2-CM2)")
            else: creneaux.append("Vendredi - Cassis")
    
    return list(set(creneaux))

def get_helloasso_token(client_id, client_secret):
    url = "https://api.helloasso.com/oauth2/token"
    try:
        r = requests.post(url, data={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}, headers={"Content-Type": "application/x-www-form-urlencoded"})
        return r.json().get("access_token") if r.status_code == 200 else None
    except: return None

def fetch_campaign_items(token, form_type, form_slug, nom_campagne):
    url = f"https://api.helloasso.com/v5/organizations/echecs-cassis/forms/{form_type}/{form_slug}/items"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params={"pageSize": 100, "withDetails": "true"})
        items = r.json().get("data", [])
        rows = []
        for item in items:
            if item.get("type") == "Donation": continue
            nom_tarif = str(item.get("name", "")).strip()
            if "don " in nom_tarif.lower() or nom_tarif.lower() == "don": continue
                
            user, payer = item.get("user", {}), item.get("payer", {})
            
            discount = item.get("discount")
            if discount and isinstance(discount, dict): code_promo_utilise = discount.get("code", "")
            else: code_promo_utilise = ""
            if not code_promo_utilise and "amountDiscount" in item: code_promo_utilise = "Oui (Montant Réduit)"
            
            type_formule = "Club" if "club" in nom_campagne.lower() else "École"
            nom_propre = user.get("lastName", payer.get("lastName", "Inconnu")).replace("*", "").strip().upper()
            prenom_propre = user.get("firstName", payer.get("firstName", "Inconnu")).replace("*", "").strip().title()
            
            email_def = user.get("email", payer.get("email", ""))
            adresse_def = user.get("address", payer.get("address", ""))
            ville_def = user.get("city", payer.get("city", ""))
            naissance_def = user.get("birthDate", user.get("dateOfBirth", payer.get("dateOfBirth", "")))
            
            row = {
                "ID_Dossier": str(item.get("id", random.randint(1000000, 9999999))), 
                "Campagne": nom_campagne, "Nom": nom_propre, "Prénom": prenom_propre, "Identité": f"{prenom_propre} {nom_propre}",
                "Montant Payé": f"{item.get('amount', 0) / 100} €", "Code Promo": code_promo_utilise, "Allergies / Médical": "-",
                "Formule": nom_tarif, "Type": type_formule, "Licence_FFE": "Non croisé", "Nom payeur": payer.get("lastName", "").replace("*", "").strip(),
                "Prénom payeur": payer.get("firstName", "").replace("*", "").strip(), "Email payeur": email_def, "N° Portable": "",
                "N° Portable 2 (en cas d'urgence)": "", "EMail": email_def, "Adresse": adresse_def, "Ville": ville_def, "Nom et prénom du responsable légal": "",
                "Classe": "", "Date de naissance": naissance_def, "Taille du t-shirt": "", "Dans quel ville sera votre créneaux principale": "",
                "J'autorise le club à diffuser des photos de moi ou mon enfant en lien avec notre activité sur notre site et sur les réseaux sociaux (Facebook ; Instagram, Twitter):": "",
                "J’autorise le club à utiliser des images de moi ou mon enfant pour des objets publicitaires (prospectus de présentation du club, oriflamme, kakemono) :": "",
                "J’accepte de recevoir les informations sur l’actualité du club (soirée blitz, organisation de stages pendant les vacances…) ainsi que les annonces des prochains tournois par mail": "",
                "Sortie Seul": "-"
            }
            if row["Date de naissance"] and len(str(row["Date de naissance"])) >= 10: row["Date de naissance"] = str(row["Date de naissance"])[:10]
            
            for field in item.get("customFields", []):
                nom_champ = str(field.get("name", "")).strip() 
                reponse = str(field.get("answer", "")).strip()
                nom_lower = nom_champ.lower()
                
                row[nom_champ] = reponse
                if "promo" in nom_lower: row["Code Promo"] = reponse
                if any(mot in nom_lower for mot in ["allergie", "médical", "sante", "santé"]):
                    if row["Allergies / Médical"] == "-": row["Allergies / Médical"] = reponse
                    else: row["Allergies / Médical"] += f" | {reponse}"
                if "classe" in nom_lower or "niveau" in nom_lower: row["Classe"] = reponse
                if "portable 2" in nom_lower or "urgence" in nom_lower: row["N° Portable 2 (en cas d'urgence)"] = reponse
                elif "portable" in nom_lower or "téléphone" in nom_lower or "telephone" in nom_lower or "tel" in nom_lower: 
                    if not row["N° Portable"]: row["N° Portable"] = reponse
                if "responsable" in nom_lower or "légal" in nom_lower: row["Nom et prénom du responsable légal"] = reponse
                if "t-shirt" in nom_lower: row["Taille du t-shirt"] = reponse
                if "créneaux" in nom_lower and "principale" in nom_lower: row["Dans quel ville sera votre créneaux principale"] = reponse
                if "diffuser" in nom_lower and "photos" in nom_lower: row["J'autorise le club à diffuser des photos de moi ou mon enfant en lien avec notre activité sur notre site et sur les réseaux sociaux (Facebook ; Instagram, Twitter):"] = reponse
                if "publicitaires" in nom_lower or "prospectus" in nom_lower: row["J’autorise le club à utiliser des images de moi ou mon enfant pour des objets publicitaires (prospectus de présentation du club, oriflamme, kakemono) :"] = reponse
                if "actualité" in nom_lower or "blitz" in nom_lower: row["J’accepte de recevoir les informations sur l’actualité du club (soirée blitz, organisation de stages pendant les vacances…) ainsi que les annonces des prochains tournois par mail"] = reponse
                if "adresse" in nom_lower and len(reponse) > 2: row["Adresse"] = reponse
                if "ville" in nom_lower and "créneaux" not in nom_lower and len(reponse) > 1: row["Ville"] = reponse
                if "naissance" in nom_lower and len(reponse) > 2: row["Date de naissance"] = reponse
                if "email" in nom_lower or "courriel" in nom_lower: row["EMail"] = reponse
                if "quitter" in nom_lower and "seul" in nom_lower:
                    if type_formule == "École": row["Sortie Seul"] = "N/A (École)"
                    else:
                        if "oui" in reponse.lower() or reponse.lower() == "true": row["Sortie Seul"] = "✅ OUI"
                        elif "non" in reponse.lower() or reponse.lower() == "false": row["Sortie Seul"] = "❌ NON"
                        elif reponse == "": row["Sortie Seul"] = "-"
                        else: row["Sortie Seul"] = f"❓ {reponse}"
            rows.append(row)
        return rows
    except: return []

def analyser_fichier_ffe(fichier):
    FFE_LOCAL = "base_ffe_locale_tmp.csv"
    try:
        if not isinstance(fichier, str):
            with open(FFE_LOCAL, "wb") as f: f.write(fichier.getbuffer())
            fichier_a_lire = FFE_LOCAL
        else:
            fichier_a_lire = fichier
            
        try: df_ffe = pd.read_csv(fichier_a_lire, sep=None, engine='python', encoding='utf-8')
        except UnicodeDecodeError: df_ffe = pd.read_csv(fichier_a_lire, sep=None, engine='python', encoding='latin1')
            
        col_nom = next((c for c in df_ffe.columns if "nom" in str(c).lower() and "prenom" not in str(c).lower() and "prénom" not in str(c).lower()), None)
        col_prenom = next((c for c in df_ffe.columns if "prenom" in str(c).lower() or "prénom" in str(c).lower()), None)
        col_elo = next((c for c in df_ffe.columns if "rapide" in str(c).lower()), None)
        if not col_elo: col_elo = next((c for c in df_ffe.columns if "elo" in str(c).lower()), None)
        col_licence = next((c for c in df_ffe.columns if any(mot in str(c).lower() for mot in ["n° ffe", "licence", "code", "ref", "identifiant"])), None)
        col_dna = next((c for c in df_ffe.columns if any(mot in str(c).lower() for mot in ["dna", "né", "naissance"])), None)

        if col_nom and col_prenom:
            df_ffe['Nom_Norm'] = df_ffe[col_nom].apply(normaliser_nom)
            df_ffe['Prenom_Norm'] = df_ffe[col_prenom].apply(normaliser_nom)
            if col_dna: df_ffe['Annee_FFE'] = df_ffe[col_dna].astype(str).str.extract(r'(\d{4})')[0].fillna("")
            else: df_ffe['Annee_FFE'] = ""
            df_ffe['Cle_Forte'] = df_ffe['Nom_Norm'] + df_ffe['Prenom_Norm'] + df_ffe['Annee_FFE']
            df_ffe['Cle_Souple'] = df_ffe['Nom_Norm'] + df_ffe['Prenom_Norm']
            df_ffe['Elo_FFE'] = df_ffe[col_elo] if col_elo else 0
            df_ffe['Licence_FFE'] = df_ffe[col_licence].astype(str) if col_licence else "Non croisé"
            return df_ffe[['Cle_Forte', 'Cle_Souple', 'Elo_FFE', 'Licence_FFE']]
    except Exception as e: 
        st.sidebar.error(f"Erreur d'analyse du fichier FFE: {e}")
        return pd.DataFrame()
    return pd.DataFrame()

# --- BARRE LATÉRALE ---
st.sidebar.header("🔑 Espace de Travail")
module_choisi = st.sidebar.radio("", ["🛠️ Module Administration", "♟️ Module Entraîneur"])

st.sidebar.markdown("---")
st.sidebar.header("☁️ CLOUD & TEMPS RÉEL")
st.sidebar.info("La Base de données et les Adhérents sont synchronisés avec Google Sheets.")
if st.sidebar.button("🔄 Rafraîchir les données (Cloud)"):
    with st.spinner("Récupération des modifications des autres utilisateurs..."):
        st.session_state['db'] = charger_base_cloud()
        df_loaded = charger_adherents_cloud()
        if not df_loaded.empty: st.session_state['df_adherents'] = df_loaded
        
        for cle, val_defaut in initialiser_memoire_vierge().items():
            if cle not in st.session_state['db']: st.session_state['db'][cle] = val_defaut
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("1️⃣ Base FFE (Licences)")
fichier_ffe = st.sidebar.file_uploader("Fichier FFE (Glissez votre CSV ici)", type=['csv', 'xls', 'xlsx'])
if fichier_ffe:
    df_ffe = analyser_fichier_ffe(fichier_ffe)
    if not df_ffe.empty:
        st.session_state['df_ffe'] = df_ffe
        st.sidebar.success("Fichier FFE chargé en mémoire !")

if 'df_ffe' in st.session_state: 
    st.sidebar.info("✅ FFE en mémoire.")
    
    if st.sidebar.button("🔄 Recroiser les Licences FFE"):
        if 'df_adherents' in st.session_state and not st.session_state['df_adherents'].empty:
            with st.spinner("Recherche des correspondances dans la base FFE..."):
                df_base = st.session_state['df_adherents'].copy()
                
                df_base['Nom_Norm'] = df_base['Nom'].apply(normaliser_nom)
                df_base['Prenom_Norm'] = df_base['Prénom'].apply(normaliser_nom)
                df_base['Annee_HA'] = df_base['Date de naissance'].astype(str).str.extract(r'(\d{4})')[0].fillna("")
                
                df_base['Cle_Forte'] = df_base['Nom_Norm'] + df_base['Prenom_Norm'] + df_base['Annee_HA']
                df_base['Cle_Souple'] = df_base['Nom_Norm'] + df_base['Prenom_Norm']
                
                df_ffe_strict = st.session_state['df_ffe'].drop_duplicates(subset=['Cle_Forte'])
                df_ffe_souple = st.session_state['df_ffe'].drop_duplicates(subset=['Cle_Souple'])
                
                df_base = df_base.drop(columns=['Elo_FFE', 'Licence_FFE'], errors='ignore')
                df_base = pd.merge(df_base, df_ffe_strict[['Cle_Forte', 'Elo_FFE', 'Licence_FFE']], on='Cle_Forte', how='left')
                
                manquants = df_base['Licence_FFE'].isna() | (df_base['Licence_FFE'] == "Non croisé")
                if manquants.any():
                    df_base_m = df_base[manquants].drop(columns=['Elo_FFE', 'Licence_FFE'], errors='ignore')
                    df_base_m = pd.merge(df_base_m, df_ffe_souple[['Cle_Souple', 'Elo_FFE', 'Licence_FFE']], on='Cle_Souple', how='left')
                    df_base.loc[manquants, 'Elo_FFE'] = df_base_m['Elo_FFE'].values
                    df_base.loc[manquants, 'Licence_FFE'] = df_base_m['Licence_FFE'].values

                df_base['Elo_FFE'] = df_base['Elo_FFE'].fillna(0).astype(int)
                df_base['Licence_FFE'] = df_base['Licence_FFE'].fillna("Non croisé")
                df_base = df_base.drop(columns=['Cle_Forte', 'Cle_Souple', 'Nom_Norm', 'Prenom_Norm', 'Annee_HA'])
                
                st.session_state['df_adherents'] = df_base
                sauvegarder_adherents_cloud(df_base)
                st.sidebar.success("✅ Licences et Elos recroisés avec succès !")
                st.rerun()
        else:
            st.sidebar.warning("Aucun adhérent dans la base à croiser.")

st.sidebar.markdown("---")
st.sidebar.header("2️⃣ HelloAsso (Nouveaux Inscrits)")
saved_id = st.secrets["helloasso"]["client_id"] if "helloasso" in st.secrets else ""
saved_secret = st.secrets["helloasso"]["client_secret"] if "helloasso" in st.secrets else ""
client_id = st.sidebar.text_input("Client ID", value=saved_id, type="password")
client_secret = st.sidebar.text_input("Client Secret", value=saved_secret, type="password")

if st.sidebar.button("⬇️ Lancer la Synchronisation HelloAsso"):
    if client_id and client_secret:
        with st.spinner("Recherche de nouveaux inscrits HelloAsso..."):
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
                    df_new_fetch = pd.DataFrame(all_data)
                    df_local = st.session_state.get('df_adherents', pd.DataFrame())
                    ids_supprimes = [str(x) for x in st.session_state['db'].get('dossiers_supprimes', [])]
                    
                    def est_valide(r):
                        id_dos = str(r.get('ID_Dossier', ''))
                        if id_dos and id_dos != 'nan' and id_dos in ids_supprimes: return False
                        if not df_local.empty:
                            if 'ID_Dossier' in df_local.columns and id_dos in df_local['ID_Dossier'].dropna().astype(str).values: return False
                        return True
                        
                    nouveaux = df_new_fetch[df_new_fetch.apply(est_valide, axis=1)].copy()

                    if not nouveaux.empty:
                        if 'df_ffe' in st.session_state and not st.session_state['df_ffe'].empty:
                            nouveaux['Nom_Norm'] = nouveaux['Nom'].apply(normaliser_nom)
                            nouveaux['Prenom_Norm'] = nouveaux['Prénom'].apply(normaliser_nom)
                            nouveaux['Annee_HA'] = nouveaux['Date de naissance'].astype(str).str.extract(r'(\d{4})')[0].fillna("")
                            
                            nouveaux['Cle_Forte'] = nouveaux['Nom_Norm'] + nouveaux['Prenom_Norm'] + nouveaux['Annee_HA']
                            nouveaux['Cle_Souple'] = nouveaux['Nom_Norm'] + nouveaux['Prenom_Norm']
                            
                            df_ffe_strict = st.session_state['df_ffe'].drop_duplicates(subset=['Cle_Forte'])
                            df_ffe_souple = st.session_state['df_ffe'].drop_duplicates(subset=['Cle_Souple'])
                            
                            nouveaux = nouveaux.drop(columns=['Elo_FFE', 'Licence_FFE'], errors='ignore')
                            nouveaux = pd.merge(nouveaux, df_ffe_strict[['Cle_Forte', 'Elo_FFE', 'Licence_FFE']], on='Cle_Forte', how='left')
                            
                            manquants = nouveaux['Licence_FFE'].isna()
                            if manquants.any():
                                df_base_m = nouveaux[manquants].drop(columns=['Elo_FFE', 'Licence_FFE'])
                                df_base_m = pd.merge(df_base_m, df_ffe_souple[['Cle_Souple', 'Elo_FFE', 'Licence_FFE']], on='Cle_Souple', how='left')
                                nouveaux.loc[manquants, 'Elo_FFE'] = df_base_m['Elo_FFE'].values
                                nouveaux.loc[manquants, 'Licence_FFE'] = df_base_m['Licence_FFE'].values

                            nouveaux['Elo_FFE'] = nouveaux['Elo_FFE'].fillna(0).astype(int)
                            nouveaux['Licence_FFE'] = nouveaux['Licence_FFE'].fillna("Non croisé")
                            nouveaux = nouveaux.drop(columns=['Cle_Forte', 'Cle_Souple', 'Nom_Norm', 'Prenom_Norm', 'Annee_HA'])
                        else:
                            nouveaux['Elo_FFE'] = 0
                            nouveaux['Licence_FFE'] = "Non croisé"

                        for _, row in nouveaux.iterrows():
                            identite = row['Identité']
                            if identite not in st.session_state['db']['identites_helloasso_connues']: st.session_state['db']['identites_helloasso_connues'].append(identite)
                            if identite not in st.session_state['db']['elos_crevette']: st.session_state['db']['elos_crevette'][identite] = 400
                            if identite not in st.session_state['db'].get('eleves_deja_affectes', []):
                                creneaux_autos = affectations_automatiques(row)
                                for c_auto in creneaux_autos:
                                    if c_auto not in st.session_state['db']['affectations_creneaux']: st.session_state['db']['affectations_creneaux'][c_auto] = []
                                    if identite not in st.session_state['db']['affectations_creneaux'][c_auto]: st.session_state['db']['affectations_creneaux'][c_auto].append(identite)
                                st.session_state['db']['eleves_deja_affectes'].append(identite)
                                    
                        df_final = pd.concat([df_local, nouveaux], ignore_index=True)
                        st.session_state['df_adherents'] = df_final
                        sauvegarder_adherents_cloud(df_final)
                        sauvegarder_base_cloud(st.session_state['db'])
                        st.sidebar.success(f"Opération réussie ! {len(nouveaux)} nouveaux ajoutés dans le Cloud.")
                    else: st.sidebar.info("Aucun nouvel inscrit détecté.")
                else: st.sidebar.warning("Aucune donnée trouvée sur HelloAsso.")
            else: st.sidebar.error("Erreur API HelloAsso.")

if 'df_adherents' not in st.session_state or st.session_state['df_adherents'].empty:
    st.info("👋 **Bienvenue !** Cliquez sur **Lancer la Synchronisation HelloAsso** pour importer vos premiers élèves.")
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
            # --- DOSSIER ÉLÈVE DÉTAILLÉ ---
            st.markdown('<div class="recherche-rapide">', unsafe_allow_html=True)
            st.markdown("#### 🔍 Dossier Complet de l'Élève")
            recherche_nom = st.selectbox("Taper un nom/prénom pour ouvrir le dossier complet :", options=[""] + sorted(df["Identité"].tolist()), label_visibility="collapsed")
            
            if recherche_nom:
                contact = df[df["Identité"] == recherche_nom].iloc[0].copy()
                
                s_actuelle = st.session_state['db']['sorties_manuelles'].get(contact["Identité"], contact.get("Sortie Seul", "-"))
                elo_crev = st.session_state['db']['elos_crevette'].get(contact["Identité"], 400)
                promo_val = st.session_state['db']['validations_promo'].get(contact["Identité"], False)
                
                contact["Sortie Seul (Temps Réel)"] = s_actuelle
                contact["Elo Crevette 🦐"] = elo_crev
                contact["Promo Validée ✅"] = "Oui" if promo_val else "Non"
                
                st.markdown("---")
                c_info1, c_info2 = st.columns(2)
                
                infos = {k: v for k, v in contact.items() if k not in ["_orig_index", "Identité"] and str(v).strip() and str(v) != "nan"}
                items = list(infos.items())
                mid = (len(items) + 1) // 2
                
                for i, (k, v) in enumerate(items):
                    if i < mid: c_info1.markdown(f"**{k}:** {v}")
                    else: c_info2.markdown(f"**{k}:** {v}")
            st.markdown('</div>', unsafe_allow_html=True)

            col_ad1, col_ad2 = st.columns(2)
            with col_ad1: filtre_camp_admin = st.multiselect("Campagnes :", options=df["Campagne"].unique(), default=df["Campagne"].unique())
            with col_ad2: filtre_type_admin = st.multiselect("Types :", options=df["Type"].unique(), default=df["Type"].unique())
            
            st.markdown("##### ⚡ Filtres d'Action Rapide")
            c_f1, c_f2, c_f3, c_f4 = st.columns(4)
            with c_f1: filtre_licence = st.checkbox("🚫 Sans Licence")
            with c_f2: filtre_allergie = st.checkbox("🤧 Allergies / Médical")
            with c_f3: filtre_sortie = st.checkbox("🚶 Sorties Autorisées (OUI)")
            with c_f4: filtre_carte = st.checkbox("🎟️ Carte Cassis/Carnoux Manquante")
                
            df_admin = df[(df["Campagne"].isin(filtre_camp_admin)) & (df["Type"].isin(filtre_type_admin))].copy()
            
            if filtre_licence and "Licence_FFE" in df_admin.columns: df_admin = df_admin[(df_admin["Licence_FFE"] == "Non croisé") | (df_admin["Licence_FFE"] == "")]
            if filtre_allergie and "Allergies / Médical" in df_admin.columns:
                mots_sains = ["non", "ras", "rien", "néant", "neant", "aucun", "aucune", "-"]
                df_admin = df_admin[(df_admin["Allergies / Médical"] != "") & (~df_admin["Allergies / Médical"].str.lower().isin(mots_sains))]
            if filtre_sortie: df_admin = df_admin[df_admin.apply(lambda r: st.session_state['db']['sorties_manuelles'].get(r['Identité'], r['Sortie Seul']) == "✅ OUI", axis=1)]
            if filtre_carte:
                def is_carte_manquante(row):
                    identite, camp, ville = row["Identité"], str(row.get("Campagne", "")).lower(), str(row.get("Dans quel ville sera votre créneaux principale", "")).lower()
                    if ("cassis" in camp or "cassis" in ville) and not st.session_state['db']['cartes_membres'].get(identite, {}).get("Cassis", False): return True
                    if ("carnoux" in camp or "carnoux" in ville) and not st.session_state['db']['cartes_membres'].get(identite, {}).get("Carnoux", False): return True
                    return False
                df_admin = df_admin[df_admin.apply(is_carte_manquante, axis=1)]

            df_admin['Elo Crevette 🦐'] = df_admin['Identité'].apply(lambda x: st.session_state['db']['elos_crevette'].get(x, 400))
            df_admin['Promo Validée ✅'] = df_admin['Identité'].apply(lambda x: st.session_state['db']['validations_promo'].get(x, False))
            df_admin['Sortie Seul'] = df_admin.apply(lambda r: st.session_state['db']['sorties_manuelles'].get(r['Identité'], r['Sortie Seul']), axis=1)
            
            df_admin["_orig_index"] = df_admin.index
            noms_bruts = df_admin["Nom"] + " " + df_admin["Prénom"]
            s_counts = df_admin.groupby(noms_bruts).cumcount()
            index_names = noms_bruts + s_counts.apply(lambda x: f" ({x})" if x > 0 else "")
            
            df_admin.insert(0, "👤 Élève (Fige)", index_names)
            df_display = df_admin.set_index("👤 Élève (Fige)")
            
            # --- SÉLECTEUR DE COLONNES (ERGONOMIE) ---
            colonnes_a_cacher = ["Identité", "Nom payeur", "Prénom payeur", "Email payeur", "ID_Dossier", "_orig_index"]
            colonnes_possibles = [c for c in df_display.columns if c not in colonnes_a_cacher]
            
            ordre_prefere = ["Nom", "Prénom", "Licence_FFE", "Type", "Elo_FFE", "Elo Crevette 🦐", "Formule", "Campagne", "Sortie Seul", "Promo Validée ✅", "N° Portable", "EMail"]
            colonnes_possibles = sorted(colonnes_possibles, key=lambda x: ordre_prefere.index(x) if x in ordre_prefere else 999)

            colonnes_par_defaut = ["Licence_FFE", "Type", "Elo_FFE", "Elo Crevette 🦐", "Formule", "Campagne"]
            colonnes_par_defaut = [c for c in colonnes_par_defaut if c in colonnes_possibles]
            
            st.markdown("##### ⚙️ Affichage sur mesure")
            colonnes_choisies = st.multiselect(
                "Sélectionnez les colonnes à afficher (💡 Ajoutez 'Nom' et 'Prénom' si vous devez corriger une faute de frappe) :",
                options=colonnes_possibles,
                default=colonnes_par_defaut
            )
            
            st.metric("Dossiers affichés", len(df_display))
            
            # --- TABLEAU ÉDITABLE ---
            edited_df = st.data_editor(
                df_display[colonnes_choisies],
                use_container_width=True,
                column_config={
                    "Promo Validée ✅": st.column_config.CheckboxColumn("Promo Validée ✅"),
                    "Sortie Seul": st.column_config.SelectboxColumn("Sortie Seul", options=["✅ OUI", "❌ NON", "N/A (École)", "-"])
                }
            )
            
            # --- DETECTION DES MODIFICATIONS 100% SÉCURISÉE ---
            changement_detecte = False
            for index_fige in edited_df.index:
                if index_fige not in df_display.index:
                    continue
                    
                row_old = df_display.loc[index_fige]
                row_new = edited_df.loc[index_fige]
                
                if isinstance(row_old, pd.DataFrame): row_old = row_old.iloc[0]
                if isinstance(row_new, pd.DataFrame): row_new = row_new.iloc[0]
                
                changed_cols = [c for c in colonnes_choisies if str(row_old[c]) != str(row_new[c])]
                
                if changed_cols:
                    changement_detecte = True
                    identite = row_old["Identité"]
                    idx_main = row_old["_orig_index"]
                    
                    for col in changed_cols:
                        new_val = row_new[col]
                        if pd.isna(new_val): new_val = ""
                        
                        if col == "Promo Validée ✅": st.session_state['db']['validations_promo'][identite] = new_val
                        elif col == "Sortie Seul": st.session_state['db']['sorties_manuelles'][identite] = new_val
                        elif col == "Elo Crevette 🦐": st.session_state['db']['elos_crevette'][identite] = int(new_val) if str(new_val).isdigit() else 400
                        else: st.session_state['df_adherents'].at[idx_main, col] = new_val
                            
                    # Mécanique de Renommage Chirurgical (Impacte UNIQUEMENT la ligne modifiée)
                    if "Nom" in changed_cols or "Prénom" in changed_cols:
                        new_nom = str(st.session_state['df_adherents'].at[idx_main, "Nom"]).strip().upper()
                        new_prenom = str(st.session_state['df_adherents'].at[idx_main, "Prénom"]).strip().title()
                        new_identite = f"{new_prenom} {new_nom}"

                        if new_identite != identite:
                            st.session_state['df_adherents'].at[idx_main, "Identité"] = new_identite
                            
                            # On transfère l'expérience et le dossier vers la nouvelle soeur/le nouveau frère
                            if new_identite not in st.session_state['db']['elos_crevette']:
                                st.session_state['db']['elos_crevette'][new_identite] = st.session_state['db']['elos_crevette'].get(identite, 400)
                            if new_identite not in st.session_state['db']['validations_promo']:
                                st.session_state['db']['validations_promo'][new_identite] = st.session_state['db']['validations_promo'].get(identite, False)
                            if new_identite not in st.session_state['db']['sorties_manuelles']:
                                st.session_state['db']['sorties_manuelles'][new_identite] = st.session_state['db']['sorties_manuelles'].get(identite, "-")
                                
                            row_updated = st.session_state['df_adherents'].loc[idx_main]
                            creneaux_autos = affectations_automatiques(row_updated)
                            
                            for c_auto in creneaux_autos:
                                if c_auto not in st.session_state['db']['affectations_creneaux']:
                                    st.session_state['db']['affectations_creneaux'][c_auto] = []
                                if new_identite not in st.session_state['db']['affectations_creneaux'][c_auto]:
                                    st.session_state['db']['affectations_creneaux'][c_auto].append(new_identite)
                                    
                            if new_identite not in st.session_state['db'].get('eleves_deja_affectes', []):
                                st.session_state['db']['eleves_deja_affectes'].append(new_identite)
                            if new_identite not in st.session_state['db'].get('identites_helloasso_connues', []):
                                st.session_state['db']['identites_helloasso_connues'].append(new_identite)

            if changement_detecte:
                sauvegarder_base_cloud(st.session_state['db'])
                sauvegarder_adherents_cloud(st.session_state['df_adherents'])
                st.rerun()

            # --- OUTIL DE SUPPRESSION (ZONE DE DANGER) ---
            st.markdown("---")
            with st.expander("🗑️ Zone de Danger : Nettoyage et Suppressions"):
                st.warning("Les élèves supprimés n'apparaîtront plus. Leur identifiant de paiement est mis sur Liste Noire.")
                
                st.markdown("---")
                options_suppr = []
                mapping_suppr = {}
                for idx, row in df.iterrows():
                    id_dos = row.get('ID_Dossier', 'Sans ID')
                    texte = f"👤 {row['Nom']} {row['Prénom']} | 📋 {row.get('Campagne', '-')} | 💰 {row.get('Montant Payé', '-')} (Dossier: {id_dos})"
                    options_suppr.append(texte)
                    mapping_suppr[texte] = idx
                    
                eleve_a_supprimer = st.selectbox("Sélectionner la transaction à mettre sur Liste Noire :", [""] + sorted(options_suppr))
                if eleve_a_supprimer and st.button(f"🚨 Supprimer définitivement cette ligne"):
                    idx_to_delete = mapping_suppr[eleve_a_supprimer]
                    row_to_delete = df.loc[idx_to_delete]
                    
                    id_doss = row_to_delete.get('ID_Dossier')
                    if id_doss and str(id_doss) != "nan":
                        if str(id_doss) not in st.session_state['db']['dossiers_supprimes']: 
                            st.session_state['db']['dossiers_supprimes'].append(str(id_doss))
                            
                    identite = row_to_delete['Identité']
                    st.session_state['df_adherents'] = df.drop(idx_to_delete).reset_index(drop=True)
                    
                    if identite not in st.session_state['df_adherents']['Identité'].values:
                        for c in st.session_state['db']['affectations_creneaux']:
                            if identite in st.session_state['db']['affectations_creneaux'][c]:
                                st.session_state['db']['affectations_creneaux'][c].remove(identite)
                        if identite in st.session_state['db'].get('eleves_deja_affectes', []):
                            st.session_state['db']['eleves_deja_affectes'].remove(identite)
                            
                    sauvegarder_base_cloud(st.session_state['db'])
                    sauvegarder_adherents_cloud(st.session_state['df_adherents'])
                    st.success("✅ Transaction supprimée et mise sur Liste Noire avec succès !")
                    st.rerun()

            st.markdown("---")
            st.markdown("#### 📥 Exports & Licences FFE")
            col_ex1, col_ex2, col_ex3 = st.columns(3)
            
            nom_fich_admin = f"Administration_Club_{date_jour.replace('/', '-')}"
            csv_data_admin = df_display[colonnes_choisies].to_csv(index=True).encode('utf-8')
            col_ex1.download_button("📄 Export Tableau (CSV)", data=csv_data_admin, file_name=f"{nom_fich_admin}.csv", mime="text/csv")
            
            try:
                buffer_admin = io.BytesIO()
                with pd.ExcelWriter(buffer_admin, engine='xlsxwriter') as writer: df_display[colonnes_choisies].to_excel(writer, index=True, sheet_name='Base')
                col_ex2.download_button("📊 Export Tableau (Excel)", data=buffer_admin.getvalue(), file_name=f"{nom_fich_admin}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            except:
                try:
                    buffer_admin = io.BytesIO()
                    with pd.ExcelWriter(buffer_admin, engine='openpyxl') as writer: df_display[colonnes_choisies].to_excel(writer, index=True, sheet_name='Base')
                    col_ex2.download_button("📊 Export Tableau (Excel)", data=buffer_admin.getvalue(), file_name=f"{nom_fich_admin}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                except: pass

            df_ffe_export = pd.DataFrame()
            df_ffe_export['FFE Identifiant'] = ""
            df_ffe_export['Nom'], df_ffe_export['Prénom'] = df_admin['Nom'], df_admin['Prénom']
            df_ffe_export['Date de Naissance (AAAA-MM-JJ)'] = df_admin['Date de naissance']
            df_ffe_export['Sexe (M ou F)'] = df_admin['Prénom'].apply(estimer_sexe)
            df_ffe_export['Email'] = df_admin['EMail']
            df_ffe_export['Pays (ISO 3, FRA pour France)'] = "FRA"
            
            col_qs = 'e confirme avoir renseigné le questionnaire de santé "Sport" (mineurs) https://www.echecs.asso.fr/Actus/14098/questionnaire_mineur.pdf'
            if col_qs in df_admin.columns: df_ffe_export['Attestation Médicale (Oui/Non)'] = df_admin[col_qs].apply(lambda x: "Oui" if str(x).lower() in ['true', 'oui', 'yes', 'vrai', 'on', '1'] else "Non")
            else: df_ffe_export['Attestation Médicale (Oui/Non)'] = "Non"
            df_ffe_export['Licence (A ou B)'] = "B" 
            
            csv_ffe = df_ffe_export.to_csv(index=False, sep=";").encode('utf-8-sig')
            col_ex3.download_button("♟️ Fichier Prise de Licence FFE", data=csv_ffe, file_name=f"import_ffe_{date_jour.replace('/', '-')}.csv", mime="text/csv")
            
        with tab_ecoles:
            st.markdown("### 🏫 Pilotage des Établissements Scolaires")
            ecoles_dispos = [c for c in df["Campagne"].unique() if "club" not in c.lower() and "adhésion" not in c.lower() and "adhesion" not in c.lower()]
            if ecoles_dispos:
                ecole_choisie = st.selectbox("Sélectionnez l'établissement :", ecoles_dispos)
                df_ec_full = df[df["Campagne"] == ecole_choisie].copy()
                formules_dispos = ["Tous les créneaux"] + list(df_ec_full["Formule"].dropna().unique())
                formule_choisie = st.selectbox("Filtrer par Formule / Créneau :", formules_dispos)
                
                df_ec = df_ec_full[df_ec_full["Formule"] == formule_choisie].copy() if formule_choisie != "Tous les créneaux" else df_ec_full.copy()
                total_eleves = len(df_ec)
                if total_eleves > 0:
                    c1, c2, c3 = st.columns(3)
                    nb_club = len(df_ec[df_ec["Formule"].str.lower().str.contains("club", na=False)])
                    c1.metric("🎓 Total Élèves", total_eleves)
                    c2.metric("♟️ Formule Club", f"{nb_club}", f"{(nb_club / total_eleves) * 100:.1f}%" if total_eleves else "0%")
                    c3.metric("🏫 Formule Scolaire", total_eleves - nb_club)
                    
                    df_ec['Sortie Seul'] = df_ec.apply(lambda r: st.session_state['db']['sorties_manuelles'].get(r['Identité'], r['Sortie Seul']), axis=1)
                    df_ec.insert(0, "👤 Élève (Fige)", df_ec["Nom"] + " " + df_ec["Prénom"])
                    df_ec_display = df_ec.set_index("👤 Élève (Fige)")
                    colonnes_ecole = [c for c in ["Classe", "Formule", "Sortie Seul", "N° Portable", "N° Portable 2 (en cas d'urgence)"] if c in df_ec_display.columns]
                    st.dataframe(df_ec_display[colonnes_ecole], use_container_width=True)

                    st.markdown("---")
                    st.markdown("#### 📥 Exporter cette liste")
                    col_dl1, col_dl2 = st.columns(2)
                    nom_fich = f"Liste_{ecole_choisie}_{formule_choisie}".replace(" ", "_").replace("/", "-")
                    col_dl1.download_button("📄 Exporter en CSV", data=df_ec_display[colonnes_ecole].to_csv(index=True).encode('utf-8'), file_name=f"{nom_fich}.csv", mime="text/csv")
                    try:
                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer: df_ec_display[colonnes_ecole].to_excel(writer, index=True, sheet_name='Liste')
                        col_dl2.download_button("📊 Exporter en Excel", data=buffer.getvalue(), file_name=f"{nom_fich}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    except: pass

        with tab_cartes:
            st.markdown("### 🎟️ Suivi des Cartes de Centres (Cassis & Carnoux)")
            ville_carte = st.radio("Sélectionner la commune à vérifier :", ["Cassis (Carte Centre Culturel)", "Carnoux (Carte du Coq)"])
            ville_cle = "Cassis" if "Cassis" in ville_carte else "Carnoux"
            eleves_concernes = set()
            for cle, liste in st.session_state['db']['affectations_creneaux'].items():
                if ville_cle in cle: eleves_concernes.update(liste)
            if not eleves_concernes: st.info(f"Aucun élève n'est assigné à {ville_cle}.")
            else:
                for eleve in sorted(list(eleves_concernes)):
                    if eleve not in st.session_state['db']['cartes_membres']: st.session_state['db']['cartes_membres'][eleve] = {"Cassis": False, "Carnoux": False}
                    c1, c2 = st.columns([3, 1])
                    c1.write(f"👤 **{eleve}**")
                    est_coche = c2.checkbox("✅ Carte OK", value=st.session_state['db']['cartes_membres'][eleve][ville_cle], key=f"carte_{ville_cle}_{eleve}")
                    st.session_state['db']['cartes_membres'][eleve][ville_cle] = est_coche
                if st.button("💾 Sauvegarder l'état des cartes"):
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.success("Sauvegardé dans le Cloud !")

        with tab_historique:
            st.markdown("### 📅 Registre des présences")
            if not st.session_state['db']['historique_appels']: st.info("Aucun appel n'a été enregistré.")
            else:
                for date_appel, data_groupes in sorted(st.session_state['db']['historique_appels'].items(), reverse=True):
                    with st.expander(f"📁 Présences du {date_appel}"):
                        for groupe, infos in data_groupes.items(): st.write(f"**{groupe}** (par {infos.get('entraineur', 'Inconnu')}) : {len(infos.get('presents', []))} présents")

    elif module_choisi == "♟️ Module Entraîneur":
        st.subheader("♟️ Espace Entraîneur")
        tab_appel, tab_tournoi, tab_classement, tab_affectations = st.tabs(["📋 Faire l'Appel", "⚔️ Tournoi & Elo", "🏆 Classement", "⚙️ Affecter Élèves"])

        with tab_affectations:
            st.markdown("### ⚙️ Création Manuelle des listes de Créneaux")
            c_jour, c_lieu = st.columns(2)
            with c_jour: jour_aff = st.selectbox("Jour :", options=list(structure_creneaux.keys()), key="jour_aff")
            with c_lieu: lieu_aff = st.selectbox("Créneau :", options=structure_creneaux[jour_aff], key="lieu_aff")
            
            if lieu_aff not in st.session_state['db']['affectations_creneaux']: st.session_state['db']['affectations_creneaux'][lieu_aff] = []
            options_eleves = sorted(df["Identité"].tolist())
            eleves_sauvegardes = st.session_state['db']['affectations_creneaux'][lieu_aff]
            eleves_valides = [e for e in eleves_sauvegardes if e in options_eleves]
            nouveaux_eleves = st.multiselect(f"Élèves assignés à {lieu_aff} :", options=options_eleves, default=eleves_valides)
            
            if st.button("💾 Sauvegarder cette liste"):
                st.session_state['db']['affectations_creneaux'][lieu_aff] = nouveaux_eleves
                sauvegarder_base_cloud(st.session_state['db'])
                st.success(f"Liste de {lieu_aff} mise à jour dans le Cloud !")

        with tab_appel:
            st.markdown(f"### 📋 Appel du jour : **{date_jour}**")
            entraineur_appel = st.selectbox("Entraîneur responsable :", ["Quentin Massardo", "Alexandre Merenciano"])
            c_jour_ap, c_lieu_ap = st.columns(2)
            with c_jour_ap: jour_appel = st.selectbox("Sélectionner le Jour :", options=list(structure_creneaux.keys()), key="jour_ap")
            with c_lieu_ap: lieu_appel = st.selectbox("Créneau :", options=structure_creneaux[jour_appel], key="lieu_ap")
            
            liste_identites = st.session_state['db']['affectations_creneaux'].get(lieu_appel, [])
            if not liste_identites: st.info("Aucun élève assigné à ce créneau.")
            else:
                df_groupe = df[df["Identité"].isin(liste_identites)].drop_duplicates(subset=["Identité"])
                total_appel = len(df_groupe)
                st.markdown("---")
                presences = {}
                for idx, row in df_groupe.iterrows():
                    c1, c2 = st.columns([4, 1])
                    sortie_act = st.session_state['db']['sorties_manuelles'].get(row['Identité'], row.get('Sortie Seul', '-'))
                    c1.write(f"👤 **{row['Nom']}** {row['Prénom']} *(Sortie: {sortie_act})*")
                    presences[row['Identité']] = c2.checkbox("Présent", value=True, key=f"pres_{row['Identité']}")

                presents_count = sum(presences.values())
                absents_count = total_appel - presents_count
                
                st.markdown("---")
                c_m1, c_m2, c_m3 = st.columns(3)
                c_m1.metric("👥 Total Liste", total_appel)
                c_m2.metric("✅ Présents", presents_count)
                c_m3.metric("❌ Absents", absents_count)

                if st.button(f"💾 Enregistrer l'appel pour {lieu_appel}"):
                    liste_presents = [id_joueur for id_joueur, est_present in presences.items() if est_present]
                    if date_jour not in st.session_state['db']['historique_appels']: st.session_state['db']['historique_appels'][date_jour] = {}
                    st.session_state['db']['historique_appels'][date_jour][lieu_appel] = {"entraineur": entraineur_appel, "presents": liste_presents}
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.success("Appel enregistré dans le Cloud !")

                st.markdown("---")
                st.markdown("#### 📥 Exporter la liste d'appel")
                col_ap1, col_ap2 = st.columns(2)
                nom_fich_ap = f"Appel_{lieu_appel}".replace(" ", "_").replace("/", "-")
                df_appel_export = df_groupe[["Nom", "Prénom", "N° Portable", "N° Portable 2 (en cas d'urgence)", "Campagne"]].copy()
                df_appel_export['Sortie Seul'] = df_appel_export.apply(lambda r: st.session_state['db']['sorties_manuelles'].get(r['Nom']+" "+r['Prénom'], "-"), axis=1)
                
                col_ap1.download_button("📄 Exporter en CSV", data=df_appel_export.to_csv(index=False).encode('utf-8'), file_name=f"{nom_fich_ap}.csv", mime="text/csv")
                try:
                    buffer_ap = io.BytesIO()
                    with pd.ExcelWriter(buffer_ap, engine='xlsxwriter') as writer: df_appel_export.to_excel(writer, index=False, sheet_name='Appel')
                    col_ap2.download_button("📊 Exporter en Excel", data=buffer_ap.getvalue(), file_name=f"{nom_fich_ap}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                except: pass

        with tab_tournoi:
            st.markdown("### ⚔️ Tournoi Suisse & Elos")
            creneaux_remplis = [k for k, v in st.session_state['db']['affectations_creneaux'].items() if len(v) > 0]
            if not creneaux_remplis: st.info("Aucun créneau disponible.")
            else:
                creneau_tournoi = st.selectbox("Lancer le tournoi pour le créneau :", options=creneaux_remplis)
                joueurs_inscrits = list(set(st.session_state['db']['affectations_creneaux'][creneau_tournoi]))
                st.markdown("**Retirez les élèves absents :**")
                joueurs_presents = st.multiselect("", options=joueurs_inscrits, default=joueurs_inscrits)
                
                elos_actifs, types_elos = {}, {}
                for j in joueurs_presents:
                    e_val, e_type = get_elo_actif(j, df, st.session_state['db'])
                    elos_actifs[j], types_elos[j] = e_val, e_type

                if 'scores_tournoi' not in st.session_state or st.session_state.get('tournoi_en_cours') != creneau_tournoi:
                    st.session_state['scores_tournoi'] = {j: 0.0 for j in joueurs_presents}
                    st.session_state['historique_rencontres'] = set()
                    st.session_state['ronde_actuelle'] = 1
                    st.session_state['appariements_ronde'] = []
                    st.session_state['tournoi_en_cours'] = creneau_tournoi
                for j in joueurs_presents:
                    if j not in st.session_state['scores_tournoi']: st.session_state['scores_tournoi'][j] = 0.0

                st.markdown("---")
                col_t1, col_t2 = st.columns(2)
                with col_t1: st.metric("Ronde actuelle", st.session_state['ronde_actuelle'])
                with col_t2:
                    if st.button("🔄 Réinitialiser le tournoi"):
                        st.session_state['scores_tournoi'] = {}
                        st.session_state['historique_rencontres'] = set()
                        st.session_state['ronde_actuelle'] = 1
                        st.session_state['appariements_ronde'] = []
                        st.rerun()

                st.markdown("---")
                if st.button("🎲 Générer la Ronde"):
                    scores_actifs = {j: st.session_state['scores_tournoi'][j] for j in joueurs_presents}
                    pairs, exempt, st.session_state['historique_rencontres'] = generer_appariements_suisses(scores_actifs, elos_actifs, st.session_state['historique_rencontres'])
                    st.session_state['appariements_ronde'], st.session_state['exempt_ronde'] = pairs, exempt

                if st.session_state.get('appariements_ronde'):
                    st.subheader(f"♟️ Matchs — Ronde {st.session_state['ronde_actuelle']}")
                    resultats_saisis = []
                    for i, (j1, j2) in enumerate(st.session_state['appariements_ronde'], 1):
                        sym1, sym2 = "⚡" if "FIDE" in types_elos[j1] else "🦐", "⚡" if "FIDE" in types_elos[j2] else "🦐"
                        c_ech, c_res = st.columns([3, 2])
                        c_ech.markdown(f"**Échiquier {i} :** ⚪ **{j1}** ({elos_actifs[j1]} {sym1})  🆚  ⚫ **{j2}** ({elos_actifs[j2]} {sym2})")
                        res = c_res.selectbox(f"Résultat", ["Sélectionner...", "1 - 0 (Blancs)", "0 - 1 (Noirs)", "0.5 - 0.5 (Nulle)"], key=f"res_{i}", label_visibility="collapsed")
                        resultats_saisis.append((j1, j2, res))
                        
                    if st.session_state.get('exempt_ronde'): st.warning(f"👑 **Exempt (1 pt) :** {st.session_state['exempt_ronde']} ({elos_actifs[st.session_state['exempt_ronde']]} {types_elos[st.session_state['exempt_ronde']][:2]})")

                    st.markdown("---")
                    if st.button("💾 Valider les résultats"):
                        if any(r[2] == "Sélectionner..." for r in resultats_saisis): st.error("⚠️ Saisissez tous les résultats.")
                        else:
                            for j1, j2, res in resultats_saisis:
                                elo1, elo2 = elos_actifs[j1], elos_actifs[j2]
                                if res == "1 - 0 (Blancs)":
                                    st.session_state['scores_tournoi'][j1] += 1.0
                                    new_e1, new_e2 = calculer_nouveau_elo(elo1, elo2, 1.0), calculer_nouveau_elo(elo2, elo1, 0.0)
                                elif res == "0 - 1 (Noirs)":
                                    st.session_state['scores_tournoi'][j2] += 1.0
                                    new_e1, new_e2 = calculer_nouveau_elo(elo1, elo2, 0.0), calculer_nouveau_elo(elo2, elo1, 1.0)
                                else:
                                    st.session_state['scores_tournoi'][j1] += 0.5
                                    st.session_state['scores_tournoi'][j2] += 0.5
                                    new_e1, new_e2 = calculer_nouveau_elo(elo1, elo2, 0.5), calculer_nouveau_elo(elo2, elo1, 0.5)
                                    
                                if "Crevette" in types_elos[j1]: st.session_state['db']['elos_crevette'][j1] = new_e1
                                if "Crevette" in types_elos[j2]: st.session_state['db']['elos_crevette'][j2] = new_e2

                            if st.session_state.get('exempt_ronde'): st.session_state['scores_tournoi'][st.session_state['exempt_ronde']] += 1.0
                            sauvegarder_base_cloud(st.session_state['db'])
                            st.session_state['ronde_actuelle'] += 1
                            st.session_state['appariements_ronde'] = []
                            st.success("Résultats et Elos sauvegardés dans le Cloud !")
                            st.rerun()
                            
        with tab_classement:
            st.markdown("### 🏆 Classement Général (FIDE & Crevette)")
            creneaux_remplis_classement = [k for k, v in st.session_state['db']['affectations_creneaux'].items() if len(v) > 0]
            filtre_c = st.selectbox("Filtrer par liste / créneau :", ["Tous les élèves"] + sorted(creneaux_remplis_classement))
            
            joueurs_a_afficher = list(df["Identité"].unique()) if filtre_c == "Tous les élèves" else list(set(st.session_state['db']['affectations_creneaux'][filtre_c]))
            
            data_classement = [{"Élève": j, "Catégorie": get_elo_actif(j, df, st.session_state['db'])[1], "Elo ⚡🦐": get_elo_actif(j, df, st.session_state['db'])[0]} for j in joueurs_a_afficher]
            
            if data_classement:
                df_classement = pd.DataFrame(data_classement).sort_values(by="Elo ⚡🦐", ascending=False).reset_index(drop=True)
                df_classement.index += 1
                max_elo = max(1000, df_classement["Elo ⚡🦐"].max())
                st.dataframe(df_classement, use_container_width=True, column_config={"Elo ⚡🦐": st.column_config.ProgressColumn("Niveau de puissance", format="%d", min_value=100, max_value=int(max_elo))})
            else: st.info("Aucun élève à afficher.")
