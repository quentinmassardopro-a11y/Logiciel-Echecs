import streamlit as st
import requests
import pandas as pd
import random
import unicodedata
import json
import os
import io
import hashlib
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
        with st.form("form_connexion"):
            mdp = st.text_input("Veuillez saisir le mot de passe :", type="password")
            if st.form_submit_button("Se connecter"):
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
        "dossiers_supprimes": [],
        "tshirts_donnes": {},     
        "boutique_donnees": {},
        "interclubs": {"Adultes": {}, "Jeunes": {}}   # NOUVEAU MODULE
    }

def charger_base_cloud():
    try:
        client = get_gsheets_client()
        sh = client.open("Base_Calanques_DB")
        ws = get_or_create_worksheet(sh, "DB_JSON")
        vals = ws.col_values(1)
        if vals:
            return json.loads("".join(vals))
        return initialiser_memoire_vierge()
    except Exception as e:
        st.error(f"Erreur de connexion à Google Sheets (DB). Données protégées. Erreur: {e}")
        return None 

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
        st.error(f"Échec de la sauvegarde Cloud (DB): {e}")

def charger_adherents_cloud():
    try:
        client = get_gsheets_client()
        sh = client.open("Base_Calanques_DB")
        ws = get_or_create_worksheet(sh, "Adherents")
        data = ws.get_all_records()
        if data: return pd.DataFrame(data)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erreur de connexion à Google Sheets (Adhérents). Données protégées. Erreur: {e}")
        return None

def sauvegarder_adherents_cloud(df):
    try:
        if df is None or df.empty: return
        client = get_gsheets_client()
        sh = client.open("Base_Calanques_DB")
        ws = get_or_create_worksheet(sh, "Adherents")
        data = [df.columns.values.tolist()] + df.fillna("").astype(str).values.tolist()
        ws.clear() 
        try: ws.update(values=data, range_name="A1")
        except TypeError: ws.update("A1", data)
    except Exception as e:
        st.error(f"Échec de la sauvegarde Cloud (Adhérents): {e}")

def is_different(val1, val2):
    v1 = str(val1).strip().lower() if pd.notna(val1) and str(val1) != "nan" else ""
    v2 = str(val2).strip().lower() if pd.notna(val2) and str(val2) != "nan" else ""
    return v1 != v2

def nettoyer_id_dossier(val):
    val_str = str(val).strip()
    if val_str.endswith('.0'): return val_str[:-2]
    if val_str.lower() in ['nan', 'none', '']: return ""
    return val_str

def format_phone(tel):
    if pd.isna(tel) or str(tel).strip().lower() in ["nan", "none", ""]: return ""
    t = str(tel).strip().replace(" ", "").replace(".", "").replace("-", "")
    if t.startswith("+33"): t = "0" + t[3:]
    elif t.startswith("33") and len(t) == 11: t = "0" + t[2:]
    elif len(t) == 9 and not t.startswith("0"): t = "0" + t
    if len(t) == 10 and t.isdigit():
        return f"{t[0:2]}.{t[2:4]}.{t[4:6]}.{t[6:8]}.{t[8:10]}"
    return str(tel)

def generer_vcard(contact):
    vcard = "BEGIN:VCARD\nVERSION:3.0\n"
    nom = str(contact.get("Nom", "")).strip()
    prenom = str(contact.get("Prénom", "")).strip()
    vcard += f"N:{nom};{prenom};;;\n"
    vcard += f"FN:{prenom} {nom}\n"
    vcard += f"ORG:Académie d'Échecs des Calanques\n"
    tel1 = contact.get("N° Portable", "")
    if tel1: vcard += f"TEL;TYPE=CELL,VOICE:{tel1}\n"
    tel2 = contact.get("N° Portable 2 (en cas d'urgence)", "")
    if tel2: vcard += f"TEL;TYPE=HOME,VOICE:{tel2}\n"
    email = contact.get("EMail", "")
    if email: vcard += f"EMAIL;TYPE=PREF,INTERNET:{email}\n"
    vcard += "END:VCARD"
    return vcard.encode('utf-8')

# --- CHARGEMENT ---
if 'db' not in st.session_state: 
    with st.spinner("Connexion sécurisée au Cloud Google..."):
        db_loaded = charger_base_cloud()
        if db_loaded is None: st.stop() 
        st.session_state['db'] = db_loaded

if 'df_adherents' not in st.session_state:
    with st.spinner("Récupération de la base adhérents..."):
        df_loaded = charger_adherents_cloud()
        if df_loaded is None: st.stop() 
        
        if not df_loaded.empty: 
            len_avant = len(df_loaded)
            if 'N° Portable' in df_loaded.columns: df_loaded['N° Portable'] = df_loaded['N° Portable'].apply(format_phone)
            if "N° Portable 2 (en cas d'urgence)" in df_loaded.columns: df_loaded["N° Portable 2 (en cas d'urgence)"] = df_loaded["N° Portable 2 (en cas d'urgence)"].apply(format_phone)

            if 'ID_Dossier' in df_loaded.columns:
                df_loaded['ID_Dossier'] = df_loaded['ID_Dossier'].apply(nettoyer_id_dossier)
                mask_valid_id = df_loaded['ID_Dossier'] != ""
                df_valid = df_loaded[mask_valid_id].drop_duplicates(subset=['ID_Dossier'], keep='last')
                df_invalid = df_loaded[~mask_valid_id]
                df_loaded = pd.concat([df_valid, df_invalid]).reset_index(drop=True)

            def corriger_type_retroactif(row):
                camp = str(row.get("Campagne", "")).lower()
                form = str(row.get("Formule", "")).lower()
                if "boutique" in camp: return "Boutique"
                if "club" in camp or "club" in form: return "Club"
                return "École"
            
            if "Type" in df_loaded.columns: df_loaded["Type"] = df_loaded.apply(corriger_type_retroactif, axis=1)
                
            st.session_state['df_adherents'] = df_loaded
            sauvegarder_adherents_cloud(df_loaded)
        else:
            st.session_state['df_adherents'] = pd.DataFrame()

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
    st.markdown("**Plateforme Globale : Administration, Écoles, Boutique & Entraînements**")

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
    if p.endswith(('i', 'y')): return "M" if p in ["anthony", "jeremy", "willy", "jimmy", "gregory", "remi", "henri", "dmitri", "ali", "mehdi", "valery", "thierry", "charley", "guy", "yuri", "tony", "johny", "jonny", "dany", "sami", "fadi"] else "F"
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
        elo_ffe = int(float(row.get("Elo_FFE", 0)))
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
        if "cassis" in ville_choisie: creneaux.extend(["Lundi - Club Cassis", "Mercredi - Cassis", "Jeudi - Cassis", "Vendredi - Cassis"])
        if "marseille" in ville_choisie: creneaux.append("Mardi - Marseille")
        if "ceyreste" in ville_choisie: creneaux.extend(["Mardi - Ceyreste", "Mercredi - Ceyreste"])
        if "ciotat" in ville_choisie: creneaux.extend(["Lundi - La Ciotat", "Jeudi - La Ciotat"])
        if "carnoux" in ville_choisie: creneaux.append("Lundi - Carnoux")
            
    if not creneaux:
        if "lundi" in form:
            if "trinit" in camp: creneaux.append("Lundi - Sainte-Trinité (CP)")
            elif "ciotat" in form: creneaux.append("Lundi - La Ciotat")
            else: creneaux.append("Lundi - Club Cassis")
        elif "mardi" in form:
            if "trinit" in camp: creneaux.append("Mardi - Sainte-Trinité (CE1)")
            elif "augustin" in camp: creneaux.append("Mardi - Saint-Augustin (CP-CE1)")
            elif "marseille" in form: creneaux.append("Mardi - Marseille")
            else: creneaux.append("Mardi - Ceyreste")
        elif "mercredi" in form:
            if "ceyreste" in form: creneaux.append("Mercredi - Ceyreste")
            else: creneaux.append("Mercredi - Cassis")
        elif "jeudi" in form:
            if "trinit" in camp: creneaux.append("Jeudi - Sainte-Trinité (Collège)")
            elif "bosco" in camp: 
                if "coll" in form: creneaux.append("Jeudi - Don Bosco (Collège)")
                else: creneaux.append("Jeudi - Don Bosco (École)")
            elif "ciotat" in form: creneaux.append("Jeudi - La Ciotat")
            else: creneaux.append("Jeudi - Cassis")
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

def formater_donnees_helloasso(item, nom_campagne):
    if item.get("type") == "Donation": return None
    nom_tarif = str(item.get("name", "")).strip()
    if "don " in nom_tarif.lower() or nom_tarif.lower() == "don": return None
        
    order = item.get("order", {})
    user = item.get("user", {})
    payer = item.get("payer") or order.get("payer") or {}
    
    discount = item.get("discount")
    code_promo = discount.get("code", "") if isinstance(discount, dict) else ""
    if not code_promo and "amountDiscount" in item: code_promo = "Oui (Réduit)"
    
    last_name = user.get("lastName") or payer.get("lastName") or "Inconnu"
    first_name = user.get("firstName") or payer.get("firstName") or "Inconnu"
    nom_propre = str(last_name).replace("*", "").strip().upper()
    prenom_propre = str(first_name).replace("*", "").strip().title()
    
    montant_paye = item.get('amount', 0)
    item_id = item.get("id")
    
    if not item_id:
        chaine_unique = f"{nom_propre}{prenom_propre}{nom_campagne}{montant_paye}{random.randint(1,999999)}".encode('utf-8')
        item_id = f"HA_{hashlib.md5(chaine_unique).hexdigest()[:10]}"
    
    row = {
        "ID_Dossier": nettoyer_id_dossier(item_id), 
        "Campagne": nom_campagne, "Nom": nom_propre, "Prénom": prenom_propre, 
        "Identité": f"{prenom_propre} {nom_propre}",
        "Montant Payé": f"{montant_paye / 100} €", "Code Promo": code_promo, "Allergies / Médical": "-",
        "Formule": nom_tarif, "Licence_FFE": "Non croisé", 
        "Nom payeur": str(payer.get("lastName", "")).replace("*", "").strip(),
        "Prénom payeur": str(payer.get("firstName", "")).replace("*", "").strip(), 
        "Email payeur": str(user.get("email") or payer.get("email") or ""), 
        "N° Portable": "", "N° Portable 2 (en cas d'urgence)": "", 
        "EMail": str(user.get("email") or payer.get("email") or ""), 
        "Adresse": str(user.get("address") or payer.get("address") or ""), 
        "Ville": str(user.get("city") or payer.get("city") or ""), 
        "Nom et prénom du responsable légal": "", "Classe": "", 
        "Date de naissance": str(user.get("birthDate") or user.get("dateOfBirth") or payer.get("dateOfBirth") or "")[:10], 
        "Taille du t-shirt": "", "Dans quel ville sera votre créneaux principale": "",
        "Sortie Seul": "-"
    }
    
    for field in item.get("customFields", []):
        n_champ = str(field.get("name", "")).strip() 
        rep = str(field.get("answer", "")).strip()
        n_low = n_champ.lower()
        
        row[n_champ] = rep
        
        if "formule" in n_low or "choix" in n_low or "cours" in n_low or "créneau" in n_low or "creneau" in n_low:
            if rep.lower() not in row["Formule"].lower() and rep:
                row["Formule"] = f"{row['Formule']} | {rep}"
                
        if "promo" in n_low: row["Code Promo"] = rep
        elif any(m in n_low for m in ["allergie", "médical", "sante", "santé"]):
            row["Allergies / Médical"] = rep if row["Allergies / Médical"] == "-" else f"{row['Allergies / Médical']} | {rep}"
        elif "classe" in n_low or "niveau" in n_low: row["Classe"] = rep
        elif "portable 2" in n_low or "urgence" in n_low: row["N° Portable 2 (en cas d'urgence)"] = format_phone(rep)
        elif "portable" in n_low or "téléphone" in n_low or "tel" in n_low: 
            if not row["N° Portable"]: row["N° Portable"] = format_phone(rep)
        elif "responsable" in n_low or "légal" in n_low: row["Nom et prénom du responsable légal"] = rep
        elif "t-shirt" in n_low: row["Taille du t-shirt"] = rep
        elif "créneaux" in n_low and "principale" in n_low: row["Dans quel ville sera votre créneaux principale"] = rep
        elif "adresse" in n_low and len(rep) > 2: row["Adresse"] = rep
        elif "ville" in n_low and "créneaux" not in n_low and len(rep) > 1: row["Ville"] = rep
        elif "naissance" in n_low and len(rep) > 2: row["Date de naissance"] = rep
        elif "email" in n_low or "courriel" in n_low: row["EMail"] = rep
        elif "quitter" in n_low and "seul" in n_low:
            r_low = rep.lower()
            if "oui" in r_low or r_low == "true": row["Sortie Seul"] = "✅ OUI"
            elif "non" in r_low or r_low == "false": row["Sortie Seul"] = "❌ NON"
            elif rep == "": row["Sortie Seul"] = "-"
            else: row["Sortie Seul"] = f"❓ {rep}"

    camp_low = nom_campagne.lower()
    form_low = str(row.get("Formule", "")).lower()
    
    if "boutique" in camp_low:
        row["Type"] = "Boutique"
    elif "club" in camp_low or "club" in form_low:
        row["Type"] = "Club"
    else:
        row["Type"] = "École"
        if row["Sortie Seul"] == "-": row["Sortie Seul"] = "N/A (École)"
            
    return row

def fetch_campaign_items(token, form_type, form_slug, nom_campagne):
    url_base = f"https://api.helloasso.com/v5/organizations/echecs-cassis/forms/{form_type}/{form_slug}/items"
    rows = []
    continuation_token = None
    
    while True:
        params = {"pageSize": 100, "withDetails": "true"}
        if continuation_token: params["continuationToken"] = continuation_token
            
        try:
            r = requests.get(url_base, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=15)
            if r.status_code != 200: break
            
            data = r.json()
            items = data.get("data", [])
            if not items: break 
            
            for item in items:
                try: 
                    row = formater_donnees_helloasso(item, nom_campagne)
                    if row: rows.append(row)
                except Exception: continue
                    
            next_token = data.get("pagination", {}).get("continuationToken")
            if not next_token or next_token == continuation_token: break
            continuation_token = next_token
        except Exception: break
        
    return rows

def analyser_fichier_ffe(fichier):
    try:
        if not isinstance(fichier, str):
            with open("base_ffe_locale_tmp.csv", "wb") as f: f.write(fichier.getbuffer())
            fichier_a_lire = "base_ffe_locale_tmp.csv"
        else: fichier_a_lire = fichier
            
        try: df_ffe = pd.read_csv(fichier_a_lire, sep=None, engine='python', encoding='utf-8')
        except UnicodeDecodeError: df_ffe = pd.read_csv(fichier_a_lire, sep=None, engine='python', encoding='latin1')
            
        col_nom = next((c for c in df_ffe.columns if "nom" in str(c).lower() and "prenom" not in str(c).lower() and "prénom" not in str(c).lower()), None)
        col_prenom = next((c for c in df_ffe.columns if "prenom" in str(c).lower() or "prénom" in str(c).lower()), None)
        col_elo = next((c for c in df_ffe.columns if "rapide" in str(c).lower()), None)
        if not col_elo: col_elo = next((c for c in df_ffe.columns if "elo" in str(c).lower()), None)
        col_licence = next((c for c in df_ffe.columns if any(m in str(c).lower() for m in ["n° ffe", "licence", "code", "ref", "identifiant"])), None)
        col_dna = next((c for c in df_ffe.columns if any(m in str(c).lower() for m in ["dna", "né", "naissance"])), None)

        if col_nom and col_prenom:
            df_ffe['Nom_Norm'] = df_ffe[col_nom].astype(str).apply(normaliser_nom)
            df_ffe['Prenom_Norm'] = df_ffe[col_prenom].astype(str).apply(normaliser_nom)
            if col_dna: df_ffe['Annee_FFE'] = df_ffe[col_dna].astype(str).str.extract(r'(\d{4})')[0].fillna("")
            else: df_ffe['Annee_FFE'] = ""
            df_ffe['Cle_Forte'] = df_ffe['Nom_Norm'].astype(str) + df_ffe['Prenom_Norm'].astype(str) + df_ffe['Annee_FFE'].astype(str)
            df_ffe['Cle_Souple'] = df_ffe['Nom_Norm'].astype(str) + df_ffe['Prenom_Norm'].astype(str)
            df_ffe['Elo_FFE'] = df_ffe[col_elo] if col_elo else 0
            df_ffe['Licence_FFE'] = df_ffe[col_licence].astype(str) if col_licence else "Non croisé"
            return df_ffe[['Cle_Forte', 'Cle_Souple', 'Elo_FFE', 'Licence_FFE']]
    except Exception as e: 
        st.sidebar.error(f"Erreur d'analyse FFE: {e}")
        return pd.DataFrame()
    return pd.DataFrame()

# --- BARRE LATÉRALE ---
st.sidebar.header("🔑 Espace de Travail")
module_choisi = st.sidebar.radio("", ["🛠️ Module Administration", "♟️ Module Entraîneur", "🛒 Module Boutique", "🏆 Module Interclubs"])

st.sidebar.markdown("---")
st.sidebar.header("☁️ CLOUD & TEMPS RÉEL")
st.sidebar.info("La Base de données et les Adhérents sont synchronisés avec Google Sheets.")
if st.sidebar.button("🔄 Rafraîchir les données (Cloud)"):
    with st.spinner("Récupération des modifications..."):
        db_loaded = charger_base_cloud()
        if db_loaded: st.session_state['db'] = db_loaded
        
        df_loaded = charger_adherents_cloud()
        if df_loaded is not None and not df_loaded.empty: st.session_state['df_adherents'] = df_loaded
        
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
                
                df_base['Nom_Norm'] = df_base['Nom'].astype(str).apply(normaliser_nom)
                df_base['Prenom_Norm'] = df_base['Prénom'].astype(str).apply(normaliser_nom)
                df_base['Annee_HA'] = df_base['Date de naissance'].astype(str).str.extract(r'(\d{4})')[0].fillna("")
                
                df_base['Cle_Forte'] = df_base['Nom_Norm'].astype(str) + df_base['Prenom_Norm'].astype(str) + df_base['Annee_HA'].astype(str)
                df_base['Cle_Souple'] = df_base['Nom_Norm'].astype(str) + df_base['Prenom_Norm'].astype(str)
                
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
            st.sidebar.warning("Aucun adhérent dans la base.")

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
                    ("Don Bosco", "Event", "club-d-echecs-don-bosco"),
                    ("Boutique", "Shop", "objet-club")
                ]
                
                all_data = []
                for nom, type_camp, slug in campagnes:
                    all_data.extend(fetch_campaign_items(token, type_camp, slug, nom))
                all_data.extend(st.session_state['db']['eleves_essai'])
                
                if all_data:
                    df_new_fetch = pd.DataFrame(all_data)
                    df_local = st.session_state.get('df_adherents', pd.DataFrame()).copy()
                    ids_supprimes = [str(x) for x in st.session_state['db'].get('dossiers_supprimes', [])]
                    
                    def est_valide(r):
                        id_dos = nettoyer_id_dossier(r.get('ID_Dossier', ''))
                        if id_dos and id_dos != 'nan' and id_dos in ids_supprimes: return False
                        if not df_local.empty and 'ID_Dossier' in df_local.columns:
                            if id_dos in df_local['ID_Dossier'].dropna().astype(str).values: return False
                        return True
                        
                    nouveaux = df_new_fetch[df_new_fetch.apply(est_valide, axis=1)].copy()

                    if not nouveaux.empty:
                        if 'df_ffe' in st.session_state and not st.session_state['df_ffe'].empty:
                            nouveaux['Nom_Norm'] = nouveaux['Nom'].astype(str).apply(normaliser_nom)
                            nouveaux['Prenom_Norm'] = nouveaux['Prénom'].astype(str).apply(normaliser_nom)
                            nouveaux['Annee_HA'] = nouveaux['Date de naissance'].astype(str).str.extract(r'(\d{4})')[0].fillna("")
                            
                            nouveaux['Cle_Forte'] = nouveaux['Nom_Norm'].astype(str) + nouveaux['Prenom_Norm'].astype(str) + nouveaux['Annee_HA'].astype(str)
                            nouveaux['Cle_Souple'] = nouveaux['Nom_Norm'].astype(str) + nouveaux['Prenom_Norm'].astype(str)
                            
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
                        st.sidebar.success(f"Opération réussie ! {len(nouveaux)} nouveaux ajoutés.")
                    else: st.sidebar.info("Aucun nouvel inscrit détecté.")
                else: st.sidebar.warning("Aucune donnée trouvée sur HelloAsso.")
            else: st.sidebar.error("Erreur API HelloAsso.")

if 'df_adherents' not in st.session_state or st.session_state['df_adherents'].empty:
    st.info("👋 **Bienvenue !** Cliquez sur **Lancer la Synchronisation HelloAsso** pour importer vos premiers élèves.")
else:
    df = st.session_state['df_adherents']
    date_jour = datetime.now().strftime("%d/%m/%Y")
    
    structure_creneaux = {
        "Lundi": ["Lundi - Sainte-Trinité (CP)", "Lundi - La Ciotat", "Lundi - Carnoux", "Lundi - Club Cassis"],
        "Mardi": ["Mardi - Sainte-Trinité (CE1)", "Mardi - Saint-Augustin (CP-CE1)", "Mardi - Ceyreste", "Mardi - Marseille"],
        "Mercredi": ["Mercredi - Ceyreste", "Mercredi - Cassis"],
        "Jeudi": ["Jeudi - Sainte-Trinité (Collège)", "Jeudi - Don Bosco (École)", "Jeudi - Don Bosco (Collège)", "Jeudi - Cassis", "Jeudi - La Ciotat"],
        "Vendredi": ["Vendredi - Saint-Augustin (CE2-CM2)", "Vendredi - Sainte-Trinité (CE2-CM2)", "Vendredi - Cassis"]
    }

    if module_choisi == "🛠️ Module Administration":
        st.subheader("🛠️ Espace Administration du Club")
        tab_admin, tab_ecoles, tab_cartes, tab_historique = st.tabs(["📊 Base Adhérents", "🏫 Écoles", "🎟️ Cartes de Centres", "📅 Historique Appels"])
        
        with tab_admin:
            c_tools1, c_tools2 = st.columns(2)
            
            with c_tools1:
                st.markdown("##### ➕ Inscription Manuelle")
                with st.expander("Créer un dossier d'élève (Chèque, Espèces...)"):
                    with st.form("form_ajout_manuel"):
                        st.write("Dossier pour un élève qui n'est pas passé par HelloAsso.")
                        c_m1, c_m2 = st.columns(2)
                        nv_nom = c_m1.text_input("Nom de l'élève").upper()
                        nv_prenom = c_m2.text_input("Prénom de l'élève").title()
                        nv_campagne = st.selectbox("Établissement / Campagne", ["Adhésions Club", "Sainte Trinité", "Saint Augustin", "Don Bosco", "Autre"])
                        nv_formule = st.text_input("Formule / Cours (ex: Lundi, Créneau collège...)")
                        nv_tel = format_phone(st.text_input("Téléphone parent"))
                        nv_mail = st.text_input("Email parent")
                        
                        if st.form_submit_button("Créer le dossier de l'élève"):
                            if nv_nom and nv_prenom:
                                nv_identite = f"{nv_prenom} {nv_nom}"
                                id_unique = f"MANUEL-{int(datetime.now().timestamp())}-{random.randint(100,999)}"
                                nouvelle_ligne = {
                                    "ID_Dossier": id_unique,
                                    "Campagne": nv_campagne, "Nom": nv_nom, "Prénom": nv_prenom, "Identité": nv_identite,
                                    "Montant Payé": "0 € (Manuel)", "Code Promo": "", "Allergies / Médical": "-",
                                    "Formule": nv_formule, "Type": "Club" if "Club" in nv_campagne else "École", "Licence_FFE": "Non croisé",
                                    "Nom payeur": nv_nom, "Prénom payeur": nv_prenom, "Email payeur": nv_mail, "N° Portable": nv_tel,
                                    "N° Portable 2 (en cas d'urgence)": "", "EMail": nv_mail, "Adresse": "", "Ville": "", 
                                    "Nom et prénom du responsable légal": "", "Classe": "", "Date de naissance": "", 
                                    "Taille du t-shirt": "", "Dans quel ville sera votre créneaux principale": "",
                                    "J'autorise le club à diffuser des photos de moi ou mon enfant en lien avec notre activité sur notre site et sur les réseaux sociaux (Facebook ; Instagram, Twitter):": "",
                                    "J’autorise le club à utiliser des images de moi ou mon enfant pour des objets publicitaires (prospectus de présentation du club, oriflamme, kakemono) :": "",
                                    "J’accepte de recevoir les informations sur l’actualité du club (soirée blitz, organisation de stages pendant les vacances…) ainsi que les annonces des prochains tournois par mail": "",
                                    "Sortie Seul": "-"
                                }
                                st.session_state['df_adherents'] = pd.concat([st.session_state['df_adherents'], pd.DataFrame([nouvelle_ligne])], ignore_index=True)
                                st.session_state['db']['elos_crevette'][nv_identite] = 400
                                st.session_state['db']['validations_promo'][nv_identite] = False
                                st.session_state['db']['sorties_manuelles'][nv_identite] = "-"
                                st.session_state['db']['tshirts_donnes'][nv_identite] = False
                                sauvegarder_adherents_cloud(st.session_state['df_adherents'])
                                sauvegarder_base_cloud(st.session_state['db'])
                                st.success(f"✅ {nv_identite} a été ajouté avec succès !")
                                st.rerun()
                            else:
                                st.error("Le Nom et le Prénom sont obligatoires.")

            with c_tools2:
                st.markdown("##### ✏️ Correction d'Identité")
                with st.expander("Corriger une faute dans un Nom / Prénom"):
                    st.write("Sélectionnez la transaction de l'élève pour corriger son nom :")
                    
                    df_correction = df[df["Type"] != "Boutique"]
                    
                    options_renommage = []
                    mapping_renommage = {}
                    for idx, row in df_correction.iterrows():
                        id_dos = row.get('ID_Dossier', 'Sans ID')
                        texte_ren = f"👤 {row['Nom']} {row['Prénom']} | 📋 {row.get('Campagne', '-')} (Dossier: {id_dos}) - Ligne {idx}"
                        options_renommage.append(texte_ren)
                        mapping_renommage[texte_ren] = idx
                        
                    eleve_a_renommer = st.selectbox("Élève à corriger :", [""] + sorted(options_renommage))
                    
                    if eleve_a_renommer:
                        idx_cible = mapping_renommage[eleve_a_renommer]
                        row_cible = df.loc[idx_cible]
                        identite_cible = row_cible['Identité']
                        
                        c_r1, c_r2 = st.columns(2)
                        nv_nom = c_r1.text_input("Corriger le Nom", value=row_cible['Nom']).strip().upper()
                        nv_prenom = c_r2.text_input("Corriger le Prénom", value=row_cible['Prénom']).strip().title()
                        
                        if st.button("✅ Valider la correction du nom"):
                            nv_identite = f"{nv_prenom} {nv_nom}"
                            if nv_nom and nv_prenom and nv_identite != identite_cible:
                                st.session_state['df_adherents'].at[idx_cible, 'Nom'] = nv_nom
                                st.session_state['df_adherents'].at[idx_cible, 'Prénom'] = nv_prenom
                                st.session_state['df_adherents'].at[idx_cible, 'Identité'] = nv_identite
                                
                                if nv_identite not in st.session_state['db']['elos_crevette']:
                                    st.session_state['db']['elos_crevette'][nv_identite] = st.session_state['db']['elos_crevette'].get(identite_cible, 400)
                                if nv_identite not in st.session_state['db']['validations_promo']:
                                    st.session_state['db']['validations_promo'][nv_identite] = st.session_state['db']['validations_promo'].get(identite_cible, False)
                                if nv_identite not in st.session_state['db']['sorties_manuelles']:
                                    st.session_state['db']['sorties_manuelles'][nv_identite] = st.session_state['db']['sorties_manuelles'].get(identite_cible, "-")
                                if nv_identite not in st.session_state['db']['tshirts_donnes']:
                                    st.session_state['db']['tshirts_donnes'][nv_identite] = st.session_state['db']['tshirts_donnes'].get(identite_cible, False)
                                    
                                row_updated = st.session_state['df_adherents'].loc[idx_cible]
                                creneaux_autos = affectations_automatiques(row_updated)
                                
                                for c_auto in creneaux_autos:
                                    if c_auto not in st.session_state['db']['affectations_creneaux']:
                                        st.session_state['db']['affectations_creneaux'][c_auto] = []
                                    if nv_identite not in st.session_state['db']['affectations_creneaux'][c_auto]:
                                        st.session_state['db']['affectations_creneaux'][c_auto].append(nv_identite)
                                        
                                if nv_identite not in st.session_state['db'].get('eleves_deja_affectes', []):
                                    st.session_state['db']['eleves_deja_affectes'].append(nv_identite)
                                if nv_identite not in st.session_state['db'].get('identites_helloasso_connues', []):
                                    st.session_state['db']['identites_helloasso_connues'].append(nv_identite)
                                    
                                if identite_cible not in st.session_state['df_adherents']['Identité'].values:
                                    for c in st.session_state['db']['affectations_creneaux']:
                                        if identite_cible in st.session_state['db']['affectations_creneaux'][c]:
                                            st.session_state['db']['affectations_creneaux'][c].remove(identite_cible)
                                    if identite_cible in st.session_state['db'].get('eleves_deja_affectes', []):
                                        st.session_state['db']['eleves_deja_affectes'].remove(identite_cible)
                                    st.session_state['db']['elos_crevette'].pop(identite_cible, None)
                                    st.session_state['db']['validations_promo'].pop(identite_cible, None)
                                    st.session_state['db']['sorties_manuelles'].pop(identite_cible, None)
                                    st.session_state['db']['tshirts_donnes'].pop(identite_cible, None)

                                sauvegarder_base_cloud(st.session_state['db'])
                                sauvegarder_adherents_cloud(st.session_state['df_adherents'])
                                st.success(f"✅ L'élève s'appelle maintenant {nv_identite} !")
                                st.rerun()
                            elif nv_identite == identite_cible:
                                st.info("Le nom est identique, aucune modification n'a été faite.")
                            else:
                                st.error("Les champs ne peuvent pas être vides.")

            st.markdown("---")
            
            df_sans_boutique = df[df["Type"] != "Boutique"].copy()

            st.markdown('<div class="recherche-rapide">', unsafe_allow_html=True)
            st.markdown("#### 🔍 Dossier Complet de l'Élève")
            recherche_nom = st.selectbox("Taper un nom/prénom pour ouvrir le dossier complet :", options=[""] + sorted(df_sans_boutique["Identité"].tolist()), label_visibility="collapsed")
            
            if recherche_nom:
                contact = df_sans_boutique[df_sans_boutique["Identité"] == recherche_nom].iloc[0].copy()
                
                s_actuelle = st.session_state['db']['sorties_manuelles'].get(contact["Identité"], contact.get("Sortie Seul", "-"))
                contact["Sortie Seul (Temps Réel)"] = s_actuelle
                contact["Elo Crevette 🦐"] = st.session_state['db']['elos_crevette'].get(contact["Identité"], 400)
                contact["Promo Validée ✅"] = "Oui" if st.session_state['db']['validations_promo'].get(contact["Identité"], False) else "Non"
                contact["T-shirt Offert Donné 👕"] = "Oui" if st.session_state['db']['tshirts_donnes'].get(contact["Identité"], False) else "Non"
                
                st.markdown("---")
                c_info1, c_info2 = st.columns(2)
                infos = {k: v for k, v in contact.items() if k not in ["_orig_index", "Identité"] and str(v).strip() and str(v) != "nan"}
                items = list(infos.items())
                mid = (len(items) + 1) // 2
                for i, (k, v) in enumerate(items):
                    if i < mid: c_info1.markdown(f"**{k}:** {v}")
                    else: c_info2.markdown(f"**{k}:** {v}")
                    
                st.markdown("---")
                vcard_data = generer_vcard(contact)
                st.download_button(
                    label=f"📱 Enregistrer {contact.get('Prénom', '')} dans mes contacts (vCard)",
                    data=vcard_data,
                    file_name=f"{contact.get('Prénom', '')}_{contact.get('Nom', '')}.vcf",
                    mime="text/vcard",
                    use_container_width=True
                )
            st.markdown('</div>', unsafe_allow_html=True)

            col_ad1, col_ad2 = st.columns(2)
            with col_ad1: filtre_camp_admin = st.multiselect("Campagnes :", options=df_sans_boutique["Campagne"].unique(), default=df_sans_boutique["Campagne"].unique())
            with col_ad2: filtre_type_admin = st.multiselect("Types :", options=df_sans_boutique["Type"].unique(), default=df_sans_boutique["Type"].unique())
            
            st.markdown("##### ⚡ Filtres d'Action Rapide")
            c_f1, c_f2, c_f3, c_f4 = st.columns(4)
            with c_f1: filtre_licence = st.checkbox("🚫 Sans Licence")
            with c_f2: filtre_allergie = st.checkbox("🤧 Allergies / Médical")
            with c_f3: filtre_sortie = st.checkbox("🚶 Sorties Autorisées (OUI)")
            with c_f4: filtre_carte = st.checkbox("🎟️ Carte Cassis/Carnoux Manquante")
                
            df_admin = df_sans_boutique[(df_sans_boutique["Campagne"].isin(filtre_camp_admin)) & (df_sans_boutique["Type"].isin(filtre_type_admin))].copy()
            
            if filtre_licence and "Licence_FFE" in df_admin.columns: 
                df_admin = df_admin[(df_admin["Licence_FFE"] == "Non croisé") | (df_admin["Licence_FFE"] == "")]
            if filtre_allergie and "Allergies / Médical" in df_admin.columns:
                mots_sains = ["non", "ras", "rien", "néant", "neant", "aucun", "aucune", "-"]
                df_admin = df_admin[(df_admin["Allergies / Médical"] != "") & (~df_admin["Allergies / Médical"].astype(str).str.lower().isin(mots_sains))]
            if filtre_sortie: 
                df_admin = df_admin[df_admin.apply(lambda r: st.session_state['db']['sorties_manuelles'].get(r['Identité'], r['Sortie Seul']) == "✅ OUI", axis=1)]
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
            df_admin['T-shirt donné 👕'] = df_admin['Identité'].apply(lambda x: st.session_state['db']['tshirts_donnes'].get(x, False))
            
            df_admin["_orig_index"] = df_admin.index 
            
            noms_bruts = df_admin["Nom"].fillna("Inconnu").astype(str) + " " + df_admin["Prénom"].fillna("").astype(str)
            s_counts = df_admin.groupby(noms_bruts, dropna=False).cumcount()
            index_names = noms_bruts.astype(str) + s_counts.apply(lambda x: f" ({x})" if x > 0 else "").astype(str)
            
            df_admin.insert(0, "👤 Élève (Fige)", index_names)
            df_display = df_admin.set_index("_orig_index")
            
            colonnes_a_cacher = ["Identité", "Nom payeur", "Prénom payeur", "Email payeur", "ID_Dossier", "_orig_index"]
            colonnes_possibles = [c for c in df_display.columns if c not in colonnes_a_cacher]
            
            ordre_prefere = ["👤 Élève (Fige)", "T-shirt donné 👕", "Promo Validée ✅", "Nom", "Prénom", "Licence_FFE", "Type", "Elo_FFE", "Elo Crevette 🦐", "Formule", "Campagne", "Sortie Seul", "N° Portable", "EMail"]
            colonnes_possibles = sorted(colonnes_possibles, key=lambda x: ordre_prefere.index(x) if x in ordre_prefere else 999)

            colonnes_par_defaut = ["👤 Élève (Fige)", "T-shirt donné 👕", "Promo Validée ✅", "Licence_FFE", "Type", "Elo_FFE", "Elo Crevette 🦐", "Formule", "Campagne"]
            colonnes_par_defaut = [c for c in colonnes_par_defaut if c in colonnes_possibles]
            
            st.markdown("##### ⚙️ Affichage sur mesure")
            colonnes_choisies = st.multiselect(
                "Sélectionnez les colonnes à afficher :",
                options=[c for c in colonnes_possibles if c != "👤 Élève (Fige)"],
                default=[c for c in colonnes_par_defaut if c != "👤 Élève (Fige)"]
            )
            
            colonnes_finales = ["👤 Élève (Fige)"] + colonnes_choisies
            st.metric("Dossiers affichés", len(df_display))
            
            st.info("✏️ Modifiez le tableau ci-dessous, puis cliquez impérativement sur le bouton d'enregistrement en bas.")
            edited_df = st.data_editor(
                df_display[colonnes_finales],
                use_container_width=True,
                column_config={
                    "👤 Élève (Fige)": st.column_config.Column("👤 Élève (Bloqué pour la sécurité)", disabled=True),
                    "Promo Validée ✅": st.column_config.CheckboxColumn("Promo Validée ✅"),
                    "T-shirt donné 👕": st.column_config.CheckboxColumn("T-shirt donné 👕"),
                    "Sortie Seul": st.column_config.SelectboxColumn("Sortie Seul", options=["✅ OUI", "❌ NON", "N/A (École)", "-"])
                }
            )
            
            bouton_sauvegarde = st.button("💾 Enregistrer toutes les modifications du tableau", use_container_width=True)

            if bouton_sauvegarde:
                with st.spinner("Sauvegarde en cours..."):
                    changement_detecte = False
                    for idx_main in edited_df.index:
                        if idx_main not in df_display.index: continue
                            
                        row_old = df_display.loc[idx_main]
                        row_new = edited_df.loc[idx_main]
                        
                        if isinstance(row_old, pd.DataFrame): row_old = row_old.iloc[0]
                        if isinstance(row_new, pd.DataFrame): row_new = row_new.iloc[0]
                        
                        changed_cols = [c for c in colonnes_finales if is_different(row_old[c], row_new[c]) and c != "👤 Élève (Fige)"]
                        
                        if changed_cols:
                            changement_detecte = True
                            identite_actuelle = row_old["Identité"]
                            
                            for col in changed_cols:
                                new_val = row_new[col]
                                if pd.isna(new_val): new_val = ""
                                
                                if col == "Promo Validée ✅": st.session_state['db']['validations_promo'][identite_actuelle] = bool(new_val)
                                elif col == "Sortie Seul": st.session_state['db']['sorties_manuelles'][identite_actuelle] = new_val
                                elif col == "T-shirt donné 👕": st.session_state['db']['tshirts_donnes'][identite_actuelle] = bool(new_val)
                                elif col in ["N° Portable", "N° Portable 2 (en cas d'urgence)"]: 
                                    new_val = format_phone(new_val)
                                    st.session_state['df_adherents'].at[idx_main, col] = new_val
                                elif col == "Elo Crevette 🦐": 
                                    try: st.session_state['db']['elos_crevette'][identite_actuelle] = int(float(new_val))
                                    except ValueError: st.session_state['db']['elos_crevette'][identite_actuelle] = 400
                                else: st.session_state['df_adherents'].at[idx_main, col] = new_val
                                    
                            if any(c in changed_cols for c in ["Formule", "Campagne", "Dans quel ville sera votre créneaux principale", "Classe"]):
                                row_updated = st.session_state['df_adherents'].loc[idx_main]
                                nouveaux_creneaux = affectations_automatiques(row_updated)
                                for c_auto in nouveaux_creneaux:
                                    if c_auto not in st.session_state['db']['affectations_creneaux']:
                                        st.session_state['db']['affectations_creneaux'][c_auto] = []
                                    if identite_actuelle not in st.session_state['db']['affectations_creneaux'][c_auto]:
                                        st.session_state['db']['affectations_creneaux'][c_auto].append(identite_actuelle)

                    if changement_detecte:
                        sauvegarder_base_cloud(st.session_state['db'])
                        sauvegarder_adherents_cloud(st.session_state['df_adherents'])
                        st.success("✅ Modifications enregistrées et ancrées dans le Cloud !")
                        st.rerun()
                    else:
                        st.info("Aucune modification détectée.")

            st.markdown("---")
            with st.expander("🗑️ Zone de Danger : Suppressions"):
                st.warning("Les transactions supprimées n'apparaîtront plus. L'identifiant de paiement est mis sur Liste Noire.")
                
                options_suppr = []
                mapping_suppr = {}
                for idx, row in df.iterrows():
                    id_dos = nettoyer_id_dossier(row.get('ID_Dossier', 'Sans ID'))
                    texte = f"👤 {row['Nom']} {row['Prénom']} | 📋 {row.get('Campagne', '-')} | 💰 {row.get('Montant Payé', '-')} (Dossier: {id_dos})"
                    options_suppr.append(texte)
                    mapping_suppr[texte] = idx
                    
                eleve_a_supprimer = st.selectbox("Sélectionner la transaction à mettre sur Liste Noire :", [""] + sorted(options_suppr))
                if eleve_a_supprimer and st.button(f"🚨 Supprimer définitivement cette ligne"):
                    idx_to_delete = mapping_suppr[eleve_a_supprimer]
                    row_to_delete = df.loc[idx_to_delete]
                    
                    id_doss = nettoyer_id_dossier(row_to_delete.get('ID_Dossier'))
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
            csv_data_admin = df_display[colonnes_finales].to_csv(index=True).encode('utf-8')
            col_ex1.download_button("📄 Export Tableau (CSV)", data=csv_data_admin, file_name=f"{nom_fich_admin}.csv", mime="text/csv")
            
            try:
                buffer_admin = io.BytesIO()
                with pd.ExcelWriter(buffer_admin, engine='xlsxwriter') as writer: df_display[colonnes_finales].to_excel(writer, index=True, sheet_name='Base')
                col_ex2.download_button("📊 Export Tableau (Excel)", data=buffer_admin.getvalue(), file_name=f"{nom_fich_admin}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            except:
                try:
                    buffer_admin = io.BytesIO()
                    with pd.ExcelWriter(buffer_admin, engine='openpyxl') as writer: df_display[colonnes_finales].to_excel(writer, index=True, sheet_name='Base')
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
            ecoles_dispos = [c for c in df["Campagne"].unique() if "club" not in c.lower() and "adhésion" not in c.lower() and "adhesion" not in c.lower() and "boutique" not in c.lower()]
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
                    
                    noms_bruts_ec = df_ec["Nom"].fillna("Inconnu").astype(str) + " " + df_ec["Prénom"].fillna("").astype(str)
                    s_counts_ec = df_ec.groupby(noms_bruts_ec, dropna=False).cumcount()
                    index_names_ec = noms_bruts_ec.astype(str) + s_counts_ec.apply(lambda x: f" ({x})" if x > 0 else "").astype(str)
                    
                    df_ec.insert(0, "👤 Élève (Fige)", index_names_ec)
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

    elif module_choisi == "🛒 Module Boutique":
        st.subheader("🛒 Suivi des Achats Boutique")
        st.write("Ce module liste uniquement les transactions liées à votre campagne HelloAsso 'Boutique'. Cochez la case une fois l'article remis à l'élève.")
        
        df_boutique = df[df['Campagne'].str.contains("boutique", case=False, na=False)].copy()
        
        if df_boutique.empty:
            st.info("Aucun achat boutique détecté pour le moment. (Vérifiez le nom de la campagne dans le code si vous venez de la créer !)")
        else:
            df_boutique['ID_Dossier_Clean'] = df_boutique['ID_Dossier'].apply(nettoyer_id_dossier)
            df_boutique['Article Donné 🎁'] = df_boutique['ID_Dossier_Clean'].apply(lambda x: st.session_state['db']['boutique_donnees'].get(x, False))
            
            df_boutique["_orig_index"] = df_boutique.index
            df_display_boutique = df_boutique.set_index("_orig_index")
            
            colonnes_de_base = ["Nom", "Prénom", "Formule", "Montant Payé", "Article Donné 🎁"]
            colonnes_a_exclure = ["ID_Dossier", "ID_Dossier_Clean", "Campagne", "Identité", "Type", "Licence_FFE", "Nom payeur", "Prénom payeur", "Email payeur", "N° Portable", "N° Portable 2 (en cas d'urgence)", "EMail", "Adresse", "Ville", "Nom et prénom du responsable légal", "Classe", "Date de naissance", "Dans quel ville sera votre créneaux principale", "Sortie Seul", "Allergies / Médical", "Code Promo", "_orig_index"]
            colonnes_a_exclure.extend([c for c in df_display_boutique.columns if "autorise" in c.lower() or "accepte" in c.lower()])
            
            colonnes_supp_boutique = []
            for c in df_display_boutique.columns:
                if c not in colonnes_de_base and c not in colonnes_a_exclure:
                    valeurs_reelles = [str(v).strip() for v in df_display_boutique[c].dropna() if str(v).strip() not in ["", "nan", "None", "-"]]
                    if valeurs_reelles:
                        colonnes_supp_boutique.append(c)
                        
            colonnes_a_afficher = ["Article Donné 🎁", "Nom", "Prénom", "Formule"] + colonnes_supp_boutique + ["Montant Payé"]
            
            col_config = {
                "Article Donné 🎁": st.column_config.CheckboxColumn("Article Donné 🎁"),
                "Nom": st.column_config.Column(disabled=True),
                "Prénom": st.column_config.Column(disabled=True),
                "Formule": st.column_config.Column("Article Commandé", disabled=True),
                "Montant Payé": st.column_config.Column(disabled=True)
            }
            for c in colonnes_supp_boutique:
                col_config[c] = st.column_config.Column(disabled=True)
                
            st.info("Cochez la case 'Article Donné 🎁' pour valider la remise en main propre, puis enregistrez.")
            edited_boutique = st.data_editor(
                df_display_boutique[colonnes_a_afficher],
                use_container_width=True,
                column_config=col_config
            )
            
            if st.button("💾 Enregistrer les remises boutique", use_container_width=True):
                with st.spinner("Sauvegarde de la boutique en cours..."):
                    changement_b = False
                    for idx_b in edited_boutique.index:
                        if idx_b not in df_display_boutique.index: continue
                        old_val = df_display_boutique.loc[idx_b, "Article Donné 🎁"]
                        new_val = edited_boutique.loc[idx_b, "Article Donné 🎁"]
                        
                        if is_different(old_val, new_val):
                            changement_b = True
                            id_doss = nettoyer_id_dossier(df_display_boutique.loc[idx_b, "ID_Dossier"])
                            st.session_state['db']['boutique_donnees'][id_doss] = bool(new_val)
                    
                    if changement_b:
                        sauvegarder_base_cloud(st.session_state['db'])
                        st.success("✅ État de la boutique enregistré avec succès !")
                        st.rerun()
                    else:
                        st.info("Aucun changement détecté.")

    elif module_choisi == "🏆 Module Interclubs":
        st.subheader("🏆 Gestion des Équipes & Interclubs")
        st.info("Ce module gère les compositions d'équipes et vérifie automatiquement les règles FFE (Écarts Elo et Brûlage).")
        
        pdf_ready = True
        try:
            import PyPDF2
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
        except ImportError:
            pdf_ready = False
            st.warning("⚠️ Pour générer les PDF, vous devez installer `PyPDF2` et `reportlab` sur le serveur (via requirements.txt). Vous pouvez tout de même gérer vos équipes librement.")
            
        tab_adultes, tab_jeunes, tab_brulage = st.tabs(["🏅 Interclubs Adultes", "👦👧 Interclubs Jeunes", "🔥 Suivi & Brûlage"])
        
        liste_joueurs = sorted(df["Identité"].unique().tolist())
        
        def afficher_gestion_equipes(categorie, nb_echiquiers_defaut):
            c1, c2 = st.columns([3, 1])
            nv_equipe = c1.text_input(f"Nom de la nouvelle équipe ({categorie})", key=f"nv_eq_{categorie}")
            if c2.button("➕ Ajouter l'équipe", key=f"btn_add_{categorie}") and nv_equipe:
                if nv_equipe not in st.session_state['db']['interclubs'][categorie]:
                    st.session_state['db']['interclubs'][categorie][nv_equipe] = {f"Ronde {i}": ["" for _ in range(nb_echiquiers_defaut)] for i in range(1, 8)}
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.rerun()
            
            st.markdown("---")
            
            equipes = st.session_state['db']['interclubs'].get(categorie, {})
            if not equipes:
                st.info(f"Aucune équipe {categorie} créée.")
                return
                
            for nom_equipe, data in equipes.items():
                st.markdown(f"#### 🛡️ Équipe : {nom_equipe}")
                df_grid = pd.DataFrame(data, index=[f"Échiquier {i+1}" for i in range(len(data["Ronde 1"]))])
                
                col_config = {f"Ronde {i}": st.column_config.SelectboxColumn(options=[""] + liste_joueurs) for i in range(1, 8)}
                
                edited_grid = st.data_editor(df_grid, use_container_width=True, column_config=col_config, key=f"grid_{nom_equipe}")
                
                if st.button(f"💾 Sauvegarder la composition de {nom_equipe}", key=f"save_{nom_equipe}"):
                    for col in edited_grid.columns:
                        st.session_state['db']['interclubs'][categorie][nom_equipe][col] = edited_grid[col].fillna("").tolist()
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.success("Équipe sauvegardée !")
                    st.rerun()
                
                # VERIFICATION DES REGLES D'ELO
                erreurs_trouvees = False
                for col in edited_grid.columns:
                    joueurs_ronde = edited_grid[col].fillna("").tolist()
                    for i in range(len(joueurs_ronde) - 1):
                        for j in range(i+1, len(joueurs_ronde)):
                            j1 = joueurs_ronde[i]
                            j2 = joueurs_ronde[j]
                            if j1 and j2:
                                elo1 = get_elo_actif(j1, df, st.session_state['db'])[0]
                                elo2 = get_elo_actif(j2, df, st.session_state['db'])[0]
                                if elo1 < elo2 - 100:
                                    st.error(f"🚨 **{col}** : Inversion interdite ! **{j1}** (Échiquier {i+1}, {elo1} Elo) a plus de 100 points d'écart avec **{j2}** (Échiquier {j+1}, {elo2} Elo). Différence : {elo2 - elo1} pts.")
                                    erreurs_trouvees = True
                if not erreurs_trouvees:
                    st.success("✅ Ordre des Elos respecté pour toutes les rondes.")
                
                # GENERATION PDF
                if pdf_ready:
                    with st.expander("📄 Remplir la Feuille de Match (PDF FFE)"):
                        c_p1, c_p2, c_p3 = st.columns(3)
                        r_choisie = c_p1.selectbox("Ronde", [f"Ronde {i}" for i in range(1, 8)], key=f"sel_r_{nom_equipe}")
                        date_match = c_p2.text_input("Date", key=f"date_{nom_equipe}")
                        lieu_match = c_p3.text_input("Lieu", key=f"lieu_{nom_equipe}")
                        
                        pdf_vierge = st.file_uploader("Importer le PDF FFE Vierge", type=['pdf'], key=f"up_{nom_equipe}")
                        if pdf_vierge and st.button("🖨️ Générer la Feuille", key=f"gen_{nom_equipe}"):
                            try:
                                import PyPDF2
                                from reportlab.pdfgen import canvas
                                from reportlab.lib.pagesizes import A4
                                import io
                                
                                packet = io.BytesIO()
                                c = canvas.Canvas(packet, pagesize=A4)
                                
                                # Coordonnées FFE Approximatives (Ajustables)
                                c.drawString(100, 770, str(date_match))
                                c.drawString(250, 770, str(lieu_match))
                                c.drawString(450, 770, str(r_choisie))
                                c.drawString(100, 750, str(nom_equipe))
                                
                                y_start = 610
                                y_step = 28
                                compo = st.session_state['db']['interclubs'][categorie][nom_equipe][r_choisie]
                                for idx, joueur in enumerate(compo):
                                    if joueur:
                                        c.drawString(70, y_start - (idx * y_step), str(joueur))
                                        row_joueur = df[df['Identité'] == joueur]
                                        if not row_joueur.empty:
                                            code_ffe = str(row_joueur.iloc[0].get('Licence_FFE', ''))
                                            if code_ffe != "Non croisé":
                                                c.drawString(220, y_start - (idx * y_step), code_ffe)
                                        elo = get_elo_actif(joueur, df, st.session_state['db'])[0]
                                        c.drawString(280, y_start - (idx * y_step), str(elo))
                                
                                c.save()
                                packet.seek(0)
                                
                                new_pdf = PyPDF2.PdfReader(packet)
                                existing_pdf = PyPDF2.PdfReader(pdf_vierge)
                                output = PyPDF2.PdfWriter()
                                
                                page = existing_pdf.pages[0]
                                page.merge_page(new_pdf.pages[0])
                                output.add_page(page)
                                
                                output_stream = io.BytesIO()
                                output.write(output_stream)
                                
                                st.download_button("⬇️ Télécharger la feuille remplie", data=output_stream.getvalue(), file_name=f"Match_{nom_equipe}_{r_choisie}.pdf", mime="application/pdf", key=f"dl_{nom_equipe}")
                            except Exception as e:
                                st.error(f"Erreur de génération PDF: {e}")
                st.markdown("---")

        with tab_adultes:
            afficher_gestion_equipes("Adultes", 8)
            
        with tab_jeunes:
            afficher_gestion_equipes("Jeunes", 5)
            
        with tab_brulage:
            st.markdown("### 🔥 Suivi des Brûlages")
            st.write("Règle : Un joueur ayant joué 4 fois dans une équipe est définitivement 'brûlé' et ne peut plus redescendre de division.")
            
            joueurs_stats = {j: {} for j in liste_joueurs}
            for cat, equipes in st.session_state['db']['interclubs'].items():
                for nom_equipe, rondes in equipes.items():
                    for r_nom, compo in rondes.items():
                        for j in compo:
                            if j:
                                if nom_equipe not in joueurs_stats[j]:
                                    joueurs_stats[j][nom_equipe] = 0
                                joueurs_stats[j][nom_equipe] += 1
                                
            data_brulage = []
            for j, stats in joueurs_stats.items():
                if stats:
                    details = " | ".join([f"{eq}: {c} matchs" for eq, c in stats.items()])
                    est_brule = any(c >= 4 for c in stats.values())
                    data_brulage.append({
                        "Joueur": j,
                        "Statut": "🔥 BRÛLÉ (>= 4 matchs)" if est_brule else "✅ OK",
                        "Détails des matchs": details
                    })
            if data_brulage:
                df_brulage = pd.DataFrame(data_brulage).sort_values(by="Statut", ascending=False)
                st.dataframe(df_brulage, use_container_width=True)
            else:
                st.info("Aucun match joué pour le moment dans les équipes.")

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
                df_groupe = df[df["Identité"].isin(liste_identites)].drop_duplicates(subset=["ID_Dossier"])
                total_appel = len(df_groupe)
                st.markdown("---")
                presences = {}
                for idx, row in df_groupe.iterrows():
                    c1, c2 = st.columns([4, 1])
                    sortie_act = st.session_state['db']['sorties_manuelles'].get(row['Identité'], row.get('Sortie Seul', '-'))
                    
                    nom_aff = row['Nom'] + " " + row['Prénom']
                    if len(df_groupe[df_groupe['Identité'] == row['Identité']]) > 1:
                        nom_aff += f" ({idx})"
                        
                    c1.write(f"👤 **{nom_aff}** *(Sortie: {sortie_act})*")
                    presences[idx] = c2.checkbox("Présent", value=True, key=f"pres_{idx}")

                presents_count = sum(presences.values())
                absents_count = total_appel - presents_count
                
                st.markdown("---")
                c_m1, c_m2, c_m3 = st.columns(3)
                c_m1.metric("👥 Total Liste", total_appel)
                c_m2.metric("✅ Présents", presents_count)
                c_m3.metric("❌ Absents", absents_count)

                if st.button(f"💾 Enregistrer l'appel pour {lieu_appel}"):
                    liste_presents = [df_groupe.loc[idx_app, 'Identité'] for idx_app, est_present in presences.items() if est_present]
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
