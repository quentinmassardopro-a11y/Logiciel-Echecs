import streamlit as st
import requests
import pandas as pd
import random
import unicodedata
import json
import os
import io
import hashlib
import zipfile
import re
from datetime import datetime
import urllib.parse
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
    .match-card { background-color: #ffffff; padding: 15px; border-radius: 8px; border-left: 5px solid #005b96; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
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
        "elos_crevette": {}, "etats_tournois": {}, "historique_appels": {}, "eleves_essai": [],
        "affectations_creneaux": {}, "cartes_membres": {},
        "validations_promo": {}, "sorties_manuelles": {},
        "eleves_deja_affectes": [], "identites_helloasso_connues": [],
        "dossiers_supprimes": [],
        "tshirts_donnes": {},     
        "boutique_donnees": {},
        "equipes_interclubs": {},
        "ffe_joueurs": []
    }

def charger_base_cloud():
    try:
        client = get_gsheets_client()
        sh = client.open("Base_Calanques_DB")
        ws = get_or_create_worksheet(sh, "DB_JSON")
        vals = ws.col_values(1)
        if vals: return json.loads("".join(vals))
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
        if df is None: return
        client = get_gsheets_client()
        sh = client.open("Base_Calanques_DB")
        ws = get_or_create_worksheet(sh, "Adherents")
        if df.empty:
            data = [df.columns.values.tolist()]
        else:
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

def normaliser_nom(nom):
    if pd.isna(nom): return ""
    return ''.join(c for c in unicodedata.normalize('NFD', str(nom).lower().strip().replace("*", "")) if unicodedata.category(c) != 'Mn')

def estimer_sexe(prenom):
    if not prenom: return "M"
    p = normaliser_nom(str(prenom).split("-")[0].split()[0])
    femmes = ["manon", "carmen", "iris", "margaux", "margot", "maud", "astrid", "sarah", "esther", "fleur", "marion", "lison", "ninon", "suzon", "lou", "alison", "myriam", "sharon", "eden", "ines", "anais", "agnes", "charlotte", "marianne"]
    if p in femmes or p.endswith(('a', 'e', 'ine', 'elle', 'ette', 'ie', 'ia')): return "F"
    return "M"

# --- MOTEUR ELO INTELLIGENT (HIÉRARCHIE FFE & CREVETTE) ---
ELOS_ESTIMES = {799, 999, 1099, 1199, 1299, 1399}

def extract_elo_val(val):
    """Extrait le score et détermine s'il est FIDE ou National."""
    val_str = str(val).upper().strip()
    match = re.search(r'(\d{3,4})', val_str)
    if match:
        score = int(match.group(1))
        is_fide = 'F' in val_str
        is_nat = 'N' in val_str or 'E' in val_str
        # S'il n'y a ni F ni N mais qu'on a un score, on le considère National par défaut (système FFE)
        if not is_fide and not is_nat:
            is_nat = True
        return score, is_fide, is_nat
    return 0, False, False

def est_elo_estime(score, chaine_brute=""):
    """Vérifie si un score correspond à un Elo estimé (799, 999, 1099, 1199, 1299, 1399 ou 'E')."""
    if not score or score <= 0:
        return False
    if score in ELOS_ESTIMES:
        return True
    if 700 <= score <= 1399 and score % 100 == 99:
        return True
    if 'E' in str(chaine_brute).upper() and score < 1400:
        return True
    return False

def get_elo_actif(identite, df_adherents, db):
    """
    Hiérarchie stricte avec priorité aux Élos RAPIDES pour les appariements :
    1. Rapide FIDE (si réel et non estimé)
    2. Rapide National (si réel et non estimé)
    3. Lent FIDE (si réel et non estimé)
    4. Lent National (si réel et non estimé)
    5. Blitz FIDE (si réel et non estimé)
    6. Blitz National (si réel et non estimé)
    7. Si Élo estimé (799, 999, 1099, 1199, 1299, 1399) ou aucun Élo officiel :
       -> Utiliser l'Élo Crevette (initialisé à la valeur estimée ou 400).
    """
    elo_estime_trouve = None
    try:
        if not df_adherents.empty and "Identité" in df_adherents.columns:
            match = df_adherents[df_adherents["Identité"] == identite]
            if not match.empty:
                row = match.iloc[0]
                
                raw_r = str(row.get("Elo_Rapide", ""))
                raw_l = str(row.get("Elo_Lent", ""))
                raw_b = str(row.get("Elo_Blitz", ""))
                
                r_val, r_f, r_n = extract_elo_val(raw_r)
                l_val, l_f, l_n = extract_elo_val(raw_l)
                b_val, b_f, b_n = extract_elo_val(raw_b)
                
                # Détecter si l'élève a un élo estimé dans l'une des colonnes
                for val, raw in [(r_val, raw_r), (l_val, raw_l), (b_val, raw_b)]:
                    if est_elo_estime(val, raw):
                        if elo_estime_trouve is None:
                            elo_estime_trouve = val

                # 1. Priorité absolue aux Élos RAPIDES (cadence du tournoi)
                if r_f and r_val > 0 and not est_elo_estime(r_val, raw_r):
                    return r_val, "⚡ Rapide FIDE"
                if (r_n or r_val > 0) and r_val > 0 and not est_elo_estime(r_val, raw_r):
                    return r_val, "🇫🇷 Rapide National"

                # 2. Puis les Élos LENTS (Standard)
                if l_f and l_val > 0 and not est_elo_estime(l_val, raw_l):
                    return l_val, "⚡ Lent FIDE"
                if (l_n or l_val > 0) and l_val > 0 and not est_elo_estime(l_val, raw_l):
                    return l_val, "🇫🇷 Lent National"

                # 3. Puis les Élos BLITZ
                if b_f and b_val > 0 and not est_elo_estime(b_val, raw_b):
                    return b_val, "⚡ Blitz FIDE"
                if (b_n or b_val > 0) and b_val > 0 and not est_elo_estime(b_val, raw_b):
                    return b_val, "🇫🇷 Blitz National"
    except Exception:
        pass

    # 4. Élo Crevette (pour les estimés 799/999/1099/1199/1299/1399 ou sans licence/élo)
    if 'elos_crevette' not in db:
        db['elos_crevette'] = {}

    if identite in db['elos_crevette']:
        return db['elos_crevette'][identite], "🦐 Crevette"
    else:
        # Initialisation : on utilise toujours 400 comme base pour l'élo crevette
        db['elos_crevette'][identite] = 400
        return 400, "🦐 Crevette"

def calculer_nouveau_elo(r_a, r_b, score_a, k=40):
    """Calcul du nouveau Elo FIDE officiel (K=40 pour les jeunes/scolaires)."""
    e_a = 1.0 / (1.0 + 10.0 ** ((r_b - r_a) / 400.0))
    return max(100, round(r_a + k * (score_a - e_a)))

# --- LE VRAI SYSTÈME SUISSE OFFICIEL FIDE (Règles complètes) ---
def generer_appariements_suisses(joueurs_scores, elos_dict, historique_rencontres, couleurs_historique=None, exempts_precedents=None, ronde=1):
    """
    Système Suisse Officiel FIDE (Système Hollandais) :
    1. Interdiction stricte de rematch (deux joueurs ne se rencontrent qu'une seule fois).
    2. Gestion stricte de l'Exempt (Bye) :
       - Attribué au joueur ayant le score le plus faible qui n'a JAMAIS été exempt.
       - Aucun joueur ne peut recevoir deux exempts dans le même tournoi.
    3. Groupes de points homogènes (Score Brackets).
    4. Moitié Haute contre Moitié Basse (Top Half vs Bottom Half) dans chaque groupe.
    5. Downfloating du joueur au plus faible Élo si un groupe a un effectif impair.
    6. Alternance et équilibre officiel des couleurs (Blancs / Noirs) :
       - Pas 3 fois consécutives la même couleur.
       - Équilibre de la balance Blancs/Noirs.
       - Ronde 1 : alternance par échiquier (Table 1: Blanc au favori, Table 2: Noir, etc.)
    7. Solveur récursif (Backtracking) garantissant de toujours trouver une solution valide sans blocage.
    """
    if couleurs_historique is None:
        couleurs_historique = {}
    if exempts_precedents is None:
        exempts_precedents = set()
        
    rencontres_connues = set(historique_rencontres)
    joueurs_liste = list(joueurs_scores.keys())
    exempt = None

    # 1. Sélection de l'Exempt si nombre impair de joueurs
    if len(joueurs_liste) % 2 != 0:
        candidats_exempt = [j for j in joueurs_liste if j not in exempts_precedents]
        if not candidats_exempt:
            candidats_exempt = list(joueurs_liste)
            
        # Règle FIDE : score le plus faible, puis Élo le plus faible
        candidats_exempt.sort(key=lambda j: (joueurs_scores.get(j, 0.0), elos_dict.get(j, 400)))
        exempt = candidats_exempt[0]
        joueurs_liste = [j for j in joueurs_liste if j != exempt]

    if not joueurs_liste:
        return [], exempt, rencontres_connues

    # 2. Tri général : par score décroissant, puis par Élo actif décroissant
    joueurs_liste.sort(key=lambda j: (joueurs_scores.get(j, 0.0), elos_dict.get(j, 400)), reverse=True)

    # 3. Fonction de préférence de couleur
    def preference_couleur(j):
        hist = couleurs_historique.get(j, [])
        b = sum(1 for c in hist if c == 'B')
        n = sum(1 for c in hist if c == 'N')
        diff = b - n
        
        streak_b = (len(hist) >= 2 and hist[-1] == 'B' and hist[-2] == 'B')
        streak_n = (len(hist) >= 2 and hist[-1] == 'N' and hist[-2] == 'N')
        
        # 2 = interdiction 3e Blanc (veut absolument Noir)
        # -2 = interdiction 3e Noir (veut absolument Blanc)
        if streak_b: return 2
        if streak_n: return -2
        if diff > 0: return 1   # plus de Blancs que de Noirs -> veut Noir
        if diff < 0: return -1  # plus de Noirs que de Blancs -> veut Blanc
        if hist and hist[-1] == 'B': return 1
        if hist and hist[-1] == 'N': return -1
        return 0

    def choisir_couleurs(j1, j2, table_no):
        # j1 a un meilleur rang/élo que j2
        pref1 = preference_couleur(j1)
        pref2 = preference_couleur(j2)
        
        # Ronde 1 : alternance par échiquier
        if not couleurs_historique.get(j1) and not couleurs_historique.get(j2):
            if table_no % 2 == 1:
                return j1, j2  # j1 Blanc, j2 Noir
            else:
                return j2, j1  # j2 Blanc, j1 Noir
                
        # Contraintes absolues (streak de 2)
        if pref1 == 2 or pref2 == -2:
            return j2, j1  # j2 Blanc, j1 Noir
        if pref1 == -2 or pref2 == 2:
            return j1, j2  # j1 Blanc, j2 Noir
            
        # Préférences opposées
        if pref1 == -1 and pref2 == 1:
            return j1, j2
        if pref1 == 1 and pref2 == -1:
            return j2, j1
            
        # Préférence du joueur ayant le plus fort déséquilibre
        if abs(pref1) > abs(pref2):
            return (j2, j1) if pref1 > 0 else (j1, j2)
        if abs(pref2) > abs(pref1):
            return (j1, j2) if pref2 > 0 else (j2, j1)
            
        # Par défaut, alternance selon la table
        if table_no % 2 == 1:
            return j1, j2
        else:
            return j2, j1

    # 4. Appariement par groupes de score (Moitié Haute vs Moitié Basse avec backtracking)
    def apparier_groupe(joueurs_du_groupe, paires_deja_faites):
        n = len(joueurs_du_groupe)
        if n == 0:
            return []
        if n % 2 != 0:
            return None
            
        demi = n // 2
        s1 = joueurs_du_groupe[:demi]
        s2 = joueurs_du_groupe[demi:]
        
        def backtrack(idx, s2_dispos, current_pairs):
            if idx == demi:
                return current_pairs
                
            j1 = s1[idx]
            # Prioriser le vis-à-vis naturel S1[i] vs S2[i]
            candidats = sorted(s2_dispos, key=lambda c: abs(s2.index(c) - idx))
            
            for j2 in candidats:
                paire_cle = (min(j1, j2), max(j1, j2))
                if paire_cle not in rencontres_connues and paire_cle not in paires_deja_faites:
                    res = backtrack(idx + 1, [c for c in s2_dispos if c != j2], current_pairs + [(j1, j2)])
                    if res is not None:
                        return res
            return None

        return backtrack(0, list(s2), [])

    scores_uniques = sorted(list(set(joueurs_scores.get(j, 0.0) for j in joueurs_liste)), reverse=True)
    groupes_par_score = []
    for sc in scores_uniques:
        grp = [j for j in joueurs_liste if joueurs_scores.get(j, 0.0) == sc]
        grp.sort(key=lambda j: elos_dict.get(j, 400), reverse=True)
        groupes_par_score.append(grp)
        
    paires_finales = []
    restants = []
    
    for grp in groupes_par_score:
        pool = restants + grp
        if len(pool) % 2 == 1:
            downfloater = pool.pop()
            restants = [downfloater]
        else:
            restants = []
            
        paires_grp = apparier_groupe(pool, set(paires_finales))
        if paires_grp is not None:
            paires_finales.extend(paires_grp)
        else:
            restants = pool

    if restants:
        # Solveur de secours sur les restants
        def solve_reste(dispos, acc):
            if not dispos:
                return acc
            j1 = dispos[0]
            candidats = dispos[1:]
            candidats.sort(key=lambda c: (abs(joueurs_scores.get(j1, 0) - joueurs_scores.get(c, 0)), -elos_dict.get(c, 400)))
            for j2 in candidats:
                paire_cle = (min(j1, j2), max(j1, j2))
                if paire_cle not in rencontres_connues and paire_cle not in acc:
                    suite = [x for x in candidats if x != j2]
                    res = solve_reste(suite, acc + [(j1, j2)])
                    if res is not None:
                        return res
            return None
            
        paires_extra = solve_reste(restants, [])
        if paires_extra:
            paires_finales.extend(paires_extra)
        else:
            while len(restants) >= 2:
                paires_finales.append((restants[0], restants[1]))
                restants = restants[2:]

    # 5. Détermination finale des couleurs Blanc / Noir
    appariements_finaux = []
    for i, (p1, p2) in enumerate(paires_finales, 1):
        if elos_dict.get(p1, 400) < elos_dict.get(p2, 400):
            p1, p2 = p2, p1
        blanc, noir = choisir_couleurs(p1, p2, i)
        appariements_finaux.append((blanc, noir))
        rencontres_connues.add((min(p1, p2), max(p1, p2)))
        
    return appariements_finaux, exempt, rencontres_connues

# --- MOTEUR DE SCRAPING FFE ---
@st.cache_data(ttl=3600)
def fetch_ffe_team_calendar(team_url):
    if not team_url: return []
    if not team_url.startswith("http"): team_url = f"https://www.echecs.asso.fr/{team_url}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    rondes = []
    
    html_content = ""
    try:
        r = requests.get(team_url, headers=headers, timeout=5)
        html_content = r.text
    except:
        try: # Contournement de Cloudflare via AllOrigins
            url_proxy = f"https://api.allorigins.win/get?url={urllib.parse.quote(team_url)}"
            r = requests.get(url_proxy, timeout=10)
            html_content = r.json()['contents']
        except: pass

    if html_content:
        try:
            lignes = re.findall(r'<tr[^>]*>(.*?)</tr>', html_content, re.IGNORECASE | re.DOTALL)
            current_ronde = "Ronde inconnue"
            for ligne in lignes:
                cols = re.findall(r'<td[^>]*>(.*?)</td>', ligne, re.IGNORECASE | re.DOTALL)
                if len(cols) >= 5:
                    textes = [re.sub(r'<[^>]+>', '', c).replace("&nbsp;", " ").strip() for c in cols]
                    if re.search(r'\d{2}/\d{2}/\d{4}', textes[0]): # Ligne de date
                        date = textes[0]
                        eq1 = textes[2]
                        score = textes[3]
                        eq2 = textes[4]
                        lieu = textes[5] if len(textes) > 5 else ""
                        ronde = f"Ronde {len(rondes) + 1}"
                        rondes.append({"Ronde": ronde, "Date": date, "Equipe domicile": eq1, "Score": score, "Equipe extérieur": eq2, "Lieu": lieu})
                
                # Format page Groupe
                elif len(cols) >= 1 and "Ronde" in cols[0] and len(cols) < 5:
                    current_ronde = re.sub(r'<[^>]+>', '', cols[0]).replace("&nbsp;", " ").strip()
                elif len(cols) >= 5 and current_ronde != "Ronde inconnue":
                    eq1 = re.sub(r'<[^>]+>', '', cols[0]).replace("&nbsp;", " ").strip()
                    score = re.sub(r'<[^>]+>', '', cols[2]).replace("&nbsp;", " ").strip()
                    eq2 = re.sub(r'<[^>]+>', '', cols[4]).replace("&nbsp;", " ").strip()
                    if eq1 and eq2:
                        rondes.append({"Ronde": current_ronde, "Date": "-", "Match": f"{eq1} - {eq2}", "Score": score})
        except: pass
    return rondes

def analyser_fichier_ffe(fichier):
    """ Analyse le CSV de la FFE et extrait les 3 colonnes d'Elos. """
    try:
        if not isinstance(fichier, str):
            with open("base_ffe_locale_tmp.csv", "wb") as f: f.write(fichier.getbuffer())
            fichier_a_lire = "base_ffe_locale_tmp.csv"
        else: fichier_a_lire = fichier
            
        try: df_ffe = pd.read_csv(fichier_a_lire, sep=None, engine='python', encoding='utf-8')
        except UnicodeDecodeError: df_ffe = pd.read_csv(fichier_a_lire, sep=None, engine='python', encoding='latin1')
            
        col_nom = next((c for c in df_ffe.columns if "nom" in str(c).lower() and "prenom" not in str(c).lower() and "prénom" not in str(c).lower()), None)
        col_prenom = next((c for c in df_ffe.columns if "prenom" in str(c).lower() or "prénom" in str(c).lower()), None)
        
        col_lent = next((c for c in df_ffe.columns if "elo" in str(c).lower() and "rapide" not in str(c).lower() and "blitz" not in str(c).lower()), None)
        col_rapide = next((c for c in df_ffe.columns if "rapide" in str(c).lower()), None)
        col_blitz = next((c for c in df_ffe.columns if "blitz" in str(c).lower()), None)
        col_licence = next((c for c in df_ffe.columns if any(m in str(c).lower() for m in ["n° ffe", "licence", "code", "ref", "identifiant"])), None)
        col_dna = next((c for c in df_ffe.columns if any(m in str(c).lower() for m in ["dna", "né", "naissance"])), None)

        if col_nom and col_prenom:
            df_ffe['Nom_Norm'] = df_ffe[col_nom].astype(str).apply(normaliser_nom)
            df_ffe['Prenom_Norm'] = df_ffe[col_prenom].astype(str).apply(normaliser_nom)
            if col_dna: df_ffe['Annee_FFE'] = df_ffe[col_dna].astype(str).str.extract(r'(\d{4})')[0].fillna("")
            else: df_ffe['Annee_FFE'] = ""
            df_ffe['Cle_Forte'] = df_ffe['Nom_Norm'].astype(str) + df_ffe['Prenom_Norm'].astype(str) + df_ffe['Annee_FFE'].astype(str)
            df_ffe['Cle_Souple'] = df_ffe['Nom_Norm'].astype(str) + df_ffe['Prenom_Norm'].astype(str)
            
            df_ffe['Elo_Lent'] = df_ffe[col_lent].astype(str) if col_lent else ""
            df_ffe['Elo_Rapide'] = df_ffe[col_rapide].astype(str) if col_rapide else ""
            df_ffe['Elo_Blitz'] = df_ffe[col_blitz].astype(str) if col_blitz else ""
            df_ffe['Licence_FFE'] = df_ffe[col_licence].astype(str) if col_licence else "Non croisé"
            
            return df_ffe[['Cle_Forte', 'Cle_Souple', 'Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']]
    except Exception as e: 
        st.sidebar.error(f"Erreur d'analyse FFE: {e}")
        return pd.DataFrame()
    return pd.DataFrame()

# --- HELLOASSO LOGIC ---
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

# --- CHARGEMENT INITIALISATION ---
if 'db' not in st.session_state: 
    with st.spinner("Connexion sécurisée au Cloud Google..."):
        db_loaded = charger_base_cloud()
        if db_loaded is None: st.stop() 
        
        # --- FIX ELO CREVETTE (Migration) ---
        modified = False
        for identite, elo in list(db_loaded.get('elos_crevette', {}).items()):
            if elo in [799, 999, 1099, 1199, 1299, 1399]:
                db_loaded['elos_crevette'][identite] = 400
                modified = True
                
        for creneau, state in db_loaded.get('etats_tournois', {}).items():
            if 'elos' in state:
                for j, e in state['elos'].items():
                    if e in [799, 999, 1099, 1199, 1299, 1399]:
                        state['elos'][j] = db_loaded['elos_crevette'].get(j, 400)
                        modified = True
                        if 'elos_type' in state:
                            state['elos_type'][j] = "🦐 Crevette"
                            
        if modified:
            sauvegarder_base_cloud(db_loaded)
        # ------------------------------------
        
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

# --- NAVIGATION DES MODULES ---
df = st.session_state['df_adherents']
date_jour = datetime.now().strftime("%d/%m/%Y")

structure_creneaux = {
    "Lundi": ["Lundi - Sainte-Trinité (CP)", "Lundi - La Ciotat", "Lundi - Carnoux", "Lundi - Club Cassis"],
    "Mardi": ["Mardi - Sainte-Trinité (CE1)", "Mardi - Saint-Augustin (CP-CE1)", "Mardi - Ceyreste", "Mardi - Marseille"],
    "Mercredi": ["Mercredi - Ceyreste", "Mercredi - Cassis"],
    "Jeudi": ["Jeudi - Sainte-Trinité (Collège)", "Jeudi - Don Bosco (École)", "Jeudi - Don Bosco (Collège)", "Jeudi - Cassis", "Jeudi - La Ciotat"],
    "Vendredi": ["Vendredi - Saint-Augustin (CE2-CM2)", "Vendredi - Sainte-Trinité (CE2-CM2)", "Vendredi - Cassis"]
}

# =========================================================================================
# ECRAN GEANT D'APPARIEMENTS (Doit bloquer l'affichage du reste)
# =========================================================================================
if st.session_state.get('plein_ecran_ronde'):
    st.markdown("""
        <style>
        [data-testid="stSidebar"] {display: none;}
        header {display: none;}
        .block-container {padding-top: 1rem; max-width: 100%;}
        table {font-size: 2.5rem !important; width: 100%; text-align: center; border-collapse: collapse; margin-top: 20px;}
        th {background-color: #005b96; color: white; padding: 20px; border: 3px solid #005b96;}
        td {padding: 20px; border: 2px solid #ddd; font-weight: bold;}
        tr:nth-child(even) {background-color: #f2f2f2;}
        .pts {font-size: 1.5rem; color: #555; font-weight: normal;}
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown(f"<h1 style='text-align:center; font-size:4rem; color:#FF8C00; margin-bottom: 30px;'>🏆 Appariements - Ronde {st.session_state.get('ronde_actuelle', 1)}</h1>", unsafe_allow_html=True)
    
    html_table = "<table><tr><th>Table</th><th>⚪ Blancs</th><th>Score</th><th>⚫ Noirs</th></tr>"
    for i, (j1, j2) in enumerate(st.session_state.get('appariements_ronde', []), 1):
        pts1 = st.session_state['scores_tournoi'].get(j1, 0)
        pts2 = st.session_state['scores_tournoi'].get(j2, 0)
        html_table += f"<tr><td>{i}</td><td>{j1} <br><span class='pts'>({pts1} pts)</span></td><td>... - ...</td><td>{j2} <br><span class='pts'>({pts2} pts)</span></td></tr>"
        
    if st.session_state.get('exempt_ronde'):
        ex = st.session_state['exempt_ronde']
        pts_ex = st.session_state['scores_tournoi'].get(ex, 0)
        html_table += f"<tr><td colspan='4' style='background-color:#ffe4b5;'>👑 <b>Exempt :</b> {ex} <span class='pts'>({pts_ex} pts)</span></td></tr>"
    if st.session_state.get('forfaits_actuels'):
        forf_txt = ', '.join(st.session_state['forfaits_actuels'])
        html_table += f"<tr><td colspan='4' style='background-color:#ffebee; color:#c62828; font-size:1.3rem;'>ðŸš« <b>Forfaits pour cette ronde :</b> {forf_txt}</td></tr>"
    html_table += "</table>"
    
    st.markdown(html_table, unsafe_allow_html=True)
    
    st.write("")
    st.write("")
    if st.button("🔙 Retour à l'écran de gestion", use_container_width=True):
        st.session_state['plein_ecran_ronde'] = False
        st.rerun()
    st.stop()


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
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("1️⃣ Base FFE (Licences)")
fichier_ffe = st.sidebar.file_uploader("Fichier FFE (Glissez CSV ici)", type=['csv', 'xls', 'xlsx'])
if fichier_ffe:
    df_ffe = analyser_fichier_ffe(fichier_ffe)
    if not df_ffe.empty:
        st.session_state['df_ffe'] = df_ffe
        st.sidebar.success("Fichier FFE chargé en mémoire !")

if 'df_ffe' in st.session_state: 
    st.sidebar.info("✅ FFE en mémoire.")
    if st.sidebar.button("🔄 Recroiser les Licences FFE"):
        if 'df_adherents' in st.session_state and not st.session_state['df_adherents'].empty:
            with st.spinner("Recherche des correspondances dans la base FFE (3 Elos)..."):
                df_base = st.session_state['df_adherents'].copy()
                df_base['Nom_Norm'] = df_base['Nom'].astype(str).apply(normaliser_nom)
                df_base['Prenom_Norm'] = df_base['Prénom'].astype(str).apply(normaliser_nom)
                df_base['Annee_HA'] = df_base['Date de naissance'].astype(str).str.extract(r'(\d{4})')[0].fillna("")
                df_base['Cle_Forte'] = df_base['Nom_Norm'].astype(str) + df_base['Prenom_Norm'].astype(str) + df_base['Annee_HA'].astype(str)
                df_base['Cle_Souple'] = df_base['Nom_Norm'].astype(str) + df_base['Prenom_Norm'].astype(str)
                
                df_ffe_strict = st.session_state['df_ffe'].drop_duplicates(subset=['Cle_Forte'])
                df_ffe_souple = st.session_state['df_ffe'].drop_duplicates(subset=['Cle_Souple'])
                
                colonnes_a_supprimer = ['Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE', 'Elo_FFE']
                df_base = df_base.drop(columns=[c for c in colonnes_a_supprimer if c in df_base.columns], errors='ignore')
                
                df_base = pd.merge(df_base, df_ffe_strict[['Cle_Forte', 'Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']], on='Cle_Forte', how='left')
                
                manquants = df_base['Licence_FFE'].isna() | (df_base['Licence_FFE'] == "Non croisé")
                if manquants.any():
                    df_base_m = df_base[manquants].drop(columns=['Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE'], errors='ignore')
                    df_base_m = pd.merge(df_base_m, df_ffe_souple[['Cle_Souple', 'Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']], on='Cle_Souple', how='left')
                    df_base.loc[manquants, 'Elo_Lent'] = df_base_m['Elo_Lent'].values
                    df_base.loc[manquants, 'Elo_Rapide'] = df_base_m['Elo_Rapide'].values
                    df_base.loc[manquants, 'Elo_Blitz'] = df_base_m['Elo_Blitz'].values
                    df_base.loc[manquants, 'Licence_FFE'] = df_base_m['Licence_FFE'].values

                df_base['Licence_FFE'] = df_base['Licence_FFE'].fillna("Non croisé")
                df_base = df_base.drop(columns=['Cle_Forte', 'Cle_Souple', 'Nom_Norm', 'Prenom_Norm', 'Annee_HA'])
                
                st.session_state['df_adherents'] = df_base
                sauvegarder_adherents_cloud(df_base)
                st.sidebar.success("✅ Licences et Elos recroisés avec succès !")
                st.rerun()

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
                            
                            nouveaux = nouveaux.drop(columns=['Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE', 'Elo_FFE'], errors='ignore')
                            nouveaux = pd.merge(nouveaux, df_ffe_strict[['Cle_Forte', 'Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']], on='Cle_Forte', how='left')
                            
                            manquants = nouveaux['Licence_FFE'].isna()
                            if manquants.any():
                                df_base_m = nouveaux[manquants].drop(columns=['Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE'], errors='ignore')
                                df_base_m = pd.merge(df_base_m, df_ffe_souple[['Cle_Souple', 'Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']], on='Cle_Souple', how='left')
                                nouveaux.loc[manquants, 'Elo_Lent'] = df_base_m['Elo_Lent'].values
                                nouveaux.loc[manquants, 'Elo_Rapide'] = df_base_m['Elo_Rapide'].values
                                nouveaux.loc[manquants, 'Elo_Blitz'] = df_base_m['Elo_Blitz'].values
                                nouveaux.loc[manquants, 'Licence_FFE'] = df_base_m['Licence_FFE'].values

                            nouveaux['Licence_FFE'] = nouveaux['Licence_FFE'].fillna("Non croisé")
                            nouveaux = nouveaux.drop(columns=['Cle_Forte', 'Cle_Souple', 'Nom_Norm', 'Prenom_Norm', 'Annee_HA'])
                        else:
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

st.sidebar.markdown("---")
st.sidebar.header("3️⃣ Sauvegarde Locale")
st.sidebar.info("Téléchargez une copie complète du logiciel et de vos données (en cas de pépin).")

buffer_zip = io.BytesIO()
with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as zip_file:
    for f_name in ["app.py", "requirements.txt", "logo.png"]:
        if os.path.exists(f_name):
            with open(f_name, "rb") as f: zip_file.writestr(f_name, f.read())
    
    if 'db' in st.session_state:
        zip_file.writestr("base_calanques_db.json", json.dumps(st.session_state['db'], ensure_ascii=False, indent=2))
        
    if 'df_adherents' in st.session_state and not st.session_state['df_adherents'].empty:
        zip_file.writestr("adherents_db.csv", st.session_state['df_adherents'].to_csv(index=False).encode('utf-8'))

st.sidebar.download_button(
    label="📦 Télécharger Sauvegarde Complète",
    data=buffer_zip.getvalue(),
    file_name=f"Sauvegarde_Echecs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
    mime="application/zip",
    use_container_width=True
)

if df.empty:
    st.info("👋 **Bienvenue !** Cliquez sur **Lancer la Synchronisation HelloAsso** pour importer vos premiers élèves.")
else:
    if module_choisi == "🛠️ Module Administration":
        st.subheader("🛠️ Espace Administration du Club")
        tab_admin, tab_ecoles, tab_cartes, tab_historique = st.tabs(["📊 Base Adhérents", "🏫 Écoles", "🎟️ Cartes de Centres", "📅 Historique Appels"])
        
        with tab_admin:
            c_tools1, c_tools2 = st.columns(2)
            
            with c_tools1:
                st.markdown("##### ➕ Inscription Manuelle")
                with st.expander("Créer un dossier d'élève (Chèque, Espèces...)"):
                    with st.form("form_ajout_manuel"):
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
                                    "ID_Dossier": id_unique, "Campagne": nv_campagne, "Nom": nv_nom, "Prénom": nv_prenom, "Identité": nv_identite,
                                    "Montant Payé": "0 € (Manuel)", "Code Promo": "", "Allergies / Médical": "-", "Formule": nv_formule, 
                                    "Type": "Club" if "club" in nv_campagne.lower() or "club" in nv_formule.lower() else "École", 
                                    "Licence_FFE": "Non croisé", "Nom payeur": nv_nom, "Prénom payeur": nv_prenom, "Email payeur": nv_mail, 
                                    "N° Portable": nv_tel, "N° Portable 2 (en cas d'urgence)": "", "EMail": nv_mail, "Adresse": "", "Ville": "", 
                                    "Nom et prénom du responsable légal": "", "Classe": "", "Date de naissance": "", "Taille du t-shirt": "", 
                                    "Dans quel ville sera votre créneaux principale": "", "Sortie Seul": "-"
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

            with c_tools2:
                st.markdown("##### ✏️ Correction d'Identité")
                with st.expander("Corriger une faute dans un Nom / Prénom"):
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
                                
                                if nv_identite not in st.session_state['db']['elos_crevette']: st.session_state['db']['elos_crevette'][nv_identite] = st.session_state['db']['elos_crevette'].get(identite_cible, 400)
                                if nv_identite not in st.session_state['db']['validations_promo']: st.session_state['db']['validations_promo'][nv_identite] = st.session_state['db']['validations_promo'].get(identite_cible, False)
                                if nv_identite not in st.session_state['db']['sorties_manuelles']: st.session_state['db']['sorties_manuelles'][nv_identite] = st.session_state['db']['sorties_manuelles'].get(identite_cible, "-")
                                if nv_identite not in st.session_state['db']['tshirts_donnes']: st.session_state['db']['tshirts_donnes'][nv_identite] = st.session_state['db']['tshirts_donnes'].get(identite_cible, False)
                                    
                                row_updated = st.session_state['df_adherents'].loc[idx_cible]
                                creneaux_autos = affectations_automatiques(row_updated)
                                
                                for c_auto in creneaux_autos:
                                    if c_auto not in st.session_state['db']['affectations_creneaux']: st.session_state['db']['affectations_creneaux'][c_auto] = []
                                    if nv_identite not in st.session_state['db']['affectations_creneaux'][c_auto]: st.session_state['db']['affectations_creneaux'][c_auto].append(nv_identite)
                                        
                                if nv_identite not in st.session_state['db'].get('eleves_deja_affectes', []): st.session_state['db']['eleves_deja_affectes'].append(nv_identite)
                                if nv_identite not in st.session_state['db'].get('identites_helloasso_connues', []): st.session_state['db']['identites_helloasso_connues'].append(nv_identite)
                                    
                                if identite_cible not in st.session_state['df_adherents']['Identité'].values:
                                    for c in st.session_state['db']['affectations_creneaux']:
                                        if identite_cible in st.session_state['db']['affectations_creneaux'][c]: st.session_state['db']['affectations_creneaux'][c].remove(identite_cible)
                                    if identite_cible in st.session_state['db'].get('eleves_deja_affectes', []): st.session_state['db']['eleves_deja_affectes'].remove(identite_cible)
                                    st.session_state['db']['elos_crevette'].pop(identite_cible, None)
                                    st.session_state['db']['validations_promo'].pop(identite_cible, None)
                                    st.session_state['db']['sorties_manuelles'].pop(identite_cible, None)
                                    st.session_state['db']['tshirts_donnes'].pop(identite_cible, None)

                                sauvegarder_base_cloud(st.session_state['db'])
                                sauvegarder_adherents_cloud(st.session_state['df_adherents'])
                                st.success(f"✅ L'élève s'appelle maintenant {nv_identite} !")
                                st.rerun()

            st.markdown("---")
            df_sans_boutique = df[df["Type"] != "Boutique"].copy()

            st.markdown('<div class="recherche-rapide">', unsafe_allow_html=True)
            st.markdown("#### 🔍 Dossier Complet de l'Élève")
            recherche_nom = st.selectbox("Taper un nom/prénom pour ouvrir le dossier complet :", options=[""] + sorted(df_sans_boutique["Identité"].tolist()), label_visibility="collapsed")
            
            if recherche_nom:
                contact = df_sans_boutique[df_sans_boutique["Identité"] == recherche_nom].iloc[0].copy()
                s_actuelle = st.session_state['db']['sorties_manuelles'].get(contact["Identité"], contact.get("Sortie Seul", "-"))
                contact["Sortie Seul (Temps Réel)"] = s_actuelle
                
                # Récupération de l'Elo Intelligent
                elo_val, elo_type = get_elo_actif(contact["Identité"], df_sans_boutique, st.session_state['db'])
                contact["Niveau Échiquéen"] = f"{elo_val} ({elo_type})"
                
                contact["Promo Validée ✅"] = "Oui" if st.session_state['db']['validations_promo'].get(contact["Identité"], False) else "Non"
                contact["T-shirt Offert Donné 👕"] = "Oui" if st.session_state['db']['tshirts_donnes'].get(contact["Identité"], False) else "Non"
                
                st.markdown("---")
                c_info1, c_info2 = st.columns(2)
                infos = {k: v for k, v in contact.items() if k not in ["_orig_index", "Identité", "Elo_Lent", "Elo_Rapide", "Elo_Blitz", "Elo_FFE"] and str(v).strip() and str(v) != "nan"}
                items = list(infos.items())
                mid = (len(items) + 1) // 2
                for i, (k, v) in enumerate(items):
                    if i < mid: c_info1.markdown(f"**{k}:** {v}")
                    else: c_info2.markdown(f"**{k}:** {v}")
                    
                st.markdown("---")
                vcard_data = generer_vcard(contact)
                st.download_button(
                    label=f"📱 Enregistrer {contact.get('Prénom', '')} dans mes contacts (vCard)", data=vcard_data,
                    file_name=f"{contact.get('Prénom', '')}_{contact.get('Nom', '')}.vcf", mime="text/vcard", use_container_width=True
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
            
            # Affichage correct de l'Elo dans le tableau
            df_admin['Elo Actif ⚡'] = df_admin['Identité'].apply(lambda x: get_elo_actif(x, df_admin, st.session_state['db'])[0])
            df_admin['Catégorie Elo'] = df_admin['Identité'].apply(lambda x: get_elo_actif(x, df_admin, st.session_state['db'])[1])
            
            df_admin['Promo Validée ✅'] = df_admin['Identité'].apply(lambda x: st.session_state['db']['validations_promo'].get(x, False))
            df_admin['Sortie Seul'] = df_admin.apply(lambda r: st.session_state['db']['sorties_manuelles'].get(r['Identité'], r['Sortie Seul']), axis=1)
            df_admin['T-shirt donné 👕'] = df_admin['Identité'].apply(lambda x: st.session_state['db']['tshirts_donnes'].get(x, False))
            
            df_admin["_orig_index"] = df_admin.index 
            
            noms_bruts = df_admin["Nom"].fillna("Inconnu").astype(str) + " " + df_admin["Prénom"].fillna("").astype(str)
            s_counts = df_admin.groupby(noms_bruts, dropna=False).cumcount()
            index_names = noms_bruts.astype(str) + s_counts.apply(lambda x: f" ({x})" if x > 0 else "").astype(str)
            
            df_admin.insert(0, "👤 Élève (Fige)", index_names)
            df_display = df_admin.set_index("_orig_index")
            
            colonnes_a_cacher = ["Identité", "Nom payeur", "Prénom payeur", "Email payeur", "ID_Dossier", "_orig_index", "Elo_Lent", "Elo_Rapide", "Elo_Blitz", "Elo_FFE"]
            colonnes_possibles = [c for c in df_display.columns if c not in colonnes_a_cacher]
            ordre_prefere = ["👤 Élève (Fige)", "T-shirt donné 👕", "Promo Validée ✅", "Nom", "Prénom", "Licence_FFE", "Type", "Elo Actif ⚡", "Catégorie Elo", "Formule", "Campagne", "Sortie Seul", "N° Portable", "EMail"]
            colonnes_possibles = sorted(colonnes_possibles, key=lambda x: ordre_prefere.index(x) if x in ordre_prefere else 999)
            colonnes_par_defaut = [c for c in ["👤 Élève (Fige)", "T-shirt donné 👕", "Promo Validée ✅", "Licence_FFE", "Type", "Elo Actif ⚡", "Catégorie Elo", "Formule", "Campagne"] if c in colonnes_possibles]
            
            st.markdown("##### ⚙️ Affichage sur mesure")
            colonnes_choisies = st.multiselect("Sélectionnez les colonnes à afficher :", options=[c for c in colonnes_possibles if c != "👤 Élève (Fige)"], default=[c for c in colonnes_par_defaut if c != "👤 Élève (Fige)"])
            colonnes_finales = ["👤 Élève (Fige)"] + colonnes_choisies
            
            st.info("✏️ Modifiez le tableau ci-dessous, puis cliquez impérativement sur le bouton d'enregistrement en bas.")
            edited_df = st.data_editor(
                df_display[colonnes_finales], use_container_width=True,
                column_config={
                    "👤 Élève (Fige)": st.column_config.Column("👤 Élève (Bloqué)", disabled=True),
                    "Promo Validée ✅": st.column_config.CheckboxColumn("Promo Validée ✅"),
                    "T-shirt donné 👕": st.column_config.CheckboxColumn("T-shirt donné 👕"),
                    "Sortie Seul": st.column_config.SelectboxColumn("Sortie Seul", options=["✅ OUI", "❌ NON", "N/A (École)", "-"]),
                    "Elo Actif ⚡": st.column_config.Column(disabled=True),
                    "Catégorie Elo": st.column_config.Column(disabled=True)
                }
            )
            
            if st.button("💾 Enregistrer toutes les modifications du tableau", use_container_width=True):
                with st.spinner("Sauvegarde en cours..."):
                    changement_detecte = False
                    for idx_main in edited_df.index:
                        if idx_main not in df_display.index: continue
                        row_old = df_display.loc[idx_main]
                        row_new = edited_df.loc[idx_main]
                        if isinstance(row_old, pd.DataFrame): row_old = row_old.iloc[0]
                        if isinstance(row_new, pd.DataFrame): row_new = row_new.iloc[0]
                        changed_cols = [c for c in colonnes_finales if is_different(row_old[c], row_new[c]) and c != "👤 Élève (Fige)" and "Elo" not in c]
                        
                        if changed_cols:
                            changement_detecte = True
                            identite_actuelle = row_old["Identité"]
                            for col in changed_cols:
                                new_val = row_new[col]
                                if pd.isna(new_val): new_val = ""
                                if col == "Promo Validée ✅": st.session_state['db']['validations_promo'][identite_actuelle] = bool(new_val)
                                elif col == "Sortie Seul": st.session_state['db']['sorties_manuelles'][identite_actuelle] = new_val
                                elif col == "T-shirt donné 👕": st.session_state['db']['tshirts_donnes'][identite_actuelle] = bool(new_val)
                                elif col in ["N° Portable", "N° Portable 2 (en cas d'urgence)"]: st.session_state['df_adherents'].at[idx_main, col] = format_phone(new_val)
                                else: st.session_state['df_adherents'].at[idx_main, col] = new_val
                                    
                            if any(c in changed_cols for c in ["Formule", "Campagne", "Dans quel ville sera votre créneaux principale", "Classe"]):
                                nouveaux_creneaux = affectations_automatiques(st.session_state['df_adherents'].loc[idx_main])
                                for c_auto in nouveaux_creneaux:
                                    if c_auto not in st.session_state['db']['affectations_creneaux']: st.session_state['db']['affectations_creneaux'][c_auto] = []
                                    if identite_actuelle not in st.session_state['db']['affectations_creneaux'][c_auto]: st.session_state['db']['affectations_creneaux'][c_auto].append(identite_actuelle)

                    if changement_detecte:
                        sauvegarder_base_cloud(st.session_state['db'])
                        sauvegarder_adherents_cloud(st.session_state['df_adherents'])
                        st.success("✅ Modifications enregistrées !")
                        st.rerun()

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
                        db_remote = charger_base_cloud()
                        if db_remote and 'dossiers_supprimes' in db_remote:
                            remote_suppr = db_remote['dossiers_supprimes']
                            if str(id_doss) not in remote_suppr:
                                remote_suppr.append(str(id_doss))
                            st.session_state['db']['dossiers_supprimes'] = remote_suppr
                        else:
                            if str(id_doss) not in st.session_state['db']['dossiers_supprimes']: 
                                st.session_state['db']['dossiers_supprimes'].append(str(id_doss))
                            
                    identite = row_to_delete['Identité']
                    st.session_state['df_adherents'] = df.drop(idx_to_delete).reset_index(drop=True)
                    if identite not in st.session_state['df_adherents']['Identité'].values:
                        for c in st.session_state['db']['affectations_creneaux']:
                            if identite in st.session_state['db']['affectations_creneaux'][c]: st.session_state['db']['affectations_creneaux'][c].remove(identite)
                        if identite in st.session_state['db'].get('eleves_deja_affectes', []): st.session_state['db']['eleves_deja_affectes'].remove(identite)
                            
                    sauvegarder_base_cloud(st.session_state['db'])
                    sauvegarder_adherents_cloud(st.session_state['df_adherents'])
                    st.success("✅ Transaction supprimée !")
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
                    st.markdown("#### 📱 Exporter pour WhatsApp / Téléphone")
                    st.write("Ce fichier CSV est spécialement formaté pour être importé dans Google Contacts et créer vos groupes WhatsApp.")
                    
                    df_wa = pd.DataFrame()
                    df_wa["Name"] = df_ec["Identité"]
                    df_wa["Given Name"] = df_ec["Prénom"]
                    df_wa["Family Name"] = df_ec["Nom"]
                    df_wa["Group Membership"] = ecole_choisie
                    df_wa["Phone 1 - Type"] = "Mobile"
                    df_wa["Phone 1 - Value"] = df_ec["N° Portable"]
                    if "Nom payeur" in df_ec.columns: df_wa["Notes"] = "Parent: " + df_ec["Nom payeur"].astype(str) + " " + df_ec["Prénom payeur"].astype(str)
                    
                    # Nettoyage des numéros vides
                    df_wa = df_wa[df_wa["Phone 1 - Value"].astype(str).str.strip() != ""] 
                    df_wa = df_wa[df_wa["Phone 1 - Value"].astype(str).str.strip() != "nan"]
                    
                    nom_fich_wa = f"WhatsApp_{ecole_choisie}_{formule_choisie}".replace(" ", "_").replace("/", "-")
                    csv_wa = df_wa.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(f"📥 Télécharger Contacts ({len(df_wa)} numéros valides)", data=csv_wa, file_name=f"{nom_fich_wa}.csv", mime="text/csv")

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
                    st.session_state['db']['cartes_membres'][eleve][ville_cle] = c2.checkbox("✅ Carte OK", value=st.session_state['db']['cartes_membres'][eleve][ville_cle], key=f"carte_{ville_cle}_{eleve}")
                if st.button("💾 Sauvegarder l'état des cartes"):
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.success("Sauvegardé dans le Cloud !")

        with tab_historique:
            st.markdown("### 📅 Registre des présences & Suivi des absents")
            if not st.session_state['db']['historique_appels']:
                st.info("Aucun appel n'a été enregistré.")
            else:
                st.write("Consultez l'historique des présences par date et créneau, visualisez immédiatement les élèves absents et accédez à toutes les coordonnées pour contacter leurs parents.")
                
                col_f1, col_f2 = st.columns([2, 1])
                with col_f1:
                    filtre_absents_seuls = st.checkbox("🔍 Afficher uniquement les séances avec des élèves absents", value=False)
                with col_f2:
                    recherche_eleve = st.text_input("Rechercher un élève :", placeholder="Nom ou prénom...", key="rech_abs_hist").strip().lower()

                dates_triees = sorted(st.session_state['db']['historique_appels'].items(), reverse=True)
                appels_affiches = 0

                for date_appel, data_groupes in dates_triees:
                    lignes_groupes = []
                    tot_presents_jour = 0
                    tot_absents_jour = 0

                    for groupe, infos in data_groupes.items():
                        presents = infos.get('presents', [])
                        if 'absents' in infos and infos['absents'] is not None:
                            absents = infos['absents']
                        else:
                            inscrits = st.session_state['db'].get('affectations_creneaux', {}).get(groupe, [])
                            absents = [e for e in inscrits if e not in presents]

                        if filtre_absents_seuls and len(absents) == 0:
                            continue
                        if recherche_eleve:
                            tous_eleves = [str(e).lower() for e in (presents + absents)]
                            if not any(recherche_eleve in e for e in tous_eleves):
                                continue

                        tot_presents_jour += len(presents)
                        tot_absents_jour += len(absents)
                        lignes_groupes.append((groupe, infos, presents, absents))

                    if not lignes_groupes:
                        continue

                    appels_affiches += 1
                    statut_abs = f"❌ **{tot_absents_jour} absent(s)**" if tot_absents_jour > 0 else "✅ **0 absent**"
                    titre_expander = f"📅 Appel du {date_appel} — {statut_abs} | ✅ {tot_presents_jour} présent(s)"

                    with st.expander(titre_expander, expanded=(tot_absents_jour > 0 and appels_affiches <= 3)):
                        for groupe, infos, presents, absents in lignes_groupes:
                            st.markdown(f"#### 📍 {groupe}")
                            st.caption(f"Entraîneur responsable : **{infos.get('entraineur', 'Inconnu')}**")

                            c_met1, c_met2, c_met3 = st.columns(3)
                            c_met1.metric("Effectif Total", len(presents) + len(absents))
                            c_met2.metric("✅ Présents", len(presents))
                            c_met3.metric("❌ Absents", len(absents))

                            if absents:
                                st.error(f"🚨 **{len(absents)} élève(s) absent(s)** — Coordonnées des parents à contacter :")

                                liste_donnees_absents = []
                                for eleve_abs in absents:
                                    match = df[df["Identité"] == eleve_abs] if (not df.empty and "Identité" in df.columns) else pd.DataFrame()
                                    if not match.empty:
                                        row_abs = match.iloc[0]
                                        nom_e = str(row_abs.get("Nom", "")).strip()
                                        prenom_e = str(row_abs.get("Prénom", "")).strip()
                                        parent_leg = str(row_abs.get("Nom et prénom du responsable légal", "")).strip()
                                        if not parent_leg or parent_leg.lower() in ["nan", "none", "-", ""]:
                                            payeur = f"{str(row_abs.get('Prénom payeur', '')).strip()} {str(row_abs.get('Nom payeur', '')).strip()}".strip()
                                            parent_e = payeur if payeur else "Non renseigné"
                                        else:
                                            parent_e = parent_leg
                                        tel1_e = str(row_abs.get("N° Portable", "")).strip()
                                        if tel1_e.lower() in ["nan", "none", "-"]: tel1_e = ""
                                        tel2_e = str(row_abs.get("N° Portable 2 (en cas d'urgence)", "")).strip()
                                        if tel2_e.lower() in ["nan", "none", "-"]: tel2_e = ""
                                        mail_e = str(row_abs.get("EMail", "")).strip()
                                        if not mail_e or mail_e.lower() in ["nan", "none", "-"]:
                                            mail_e = str(row_abs.get("Email payeur", "")).strip()
                                        if mail_e.lower() in ["nan", "none", "-"]: mail_e = ""
                                        sortie_e = st.session_state['db'].get('sorties_manuelles', {}).get(eleve_abs, str(row_abs.get("Sortie Seul", "-")).strip())
                                        medical_e = str(row_abs.get("Allergies / Médical", "-")).strip()
                                        if medical_e.lower() in ["nan", "none"]: medical_e = "-"
                                        row_valide = row_abs
                                    else:
                                        nom_e, prenom_e = eleve_abs, ""
                                        parent_e = "Non renseigné"
                                        tel1_e, tel2_e, mail_e = "", "", ""
                                        sortie_e = st.session_state['db'].get('sorties_manuelles', {}).get(eleve_abs, "-")
                                        medical_e = "-"
                                        row_valide = None

                                    liste_donnees_absents.append({
                                        "Identité": eleve_abs,
                                        "Nom": nom_e,
                                        "Prénom": prenom_e,
                                        "Parent": parent_e,
                                        "Portable": tel1_e,
                                        "Urgence": tel2_e,
                                        "Email": mail_e,
                                        "Sortie": sortie_e,
                                        "Medical": medical_e,
                                        "row": row_valide
                                    })

                                for info_abs in liste_donnees_absents:
                                    with st.container(border=True):
                                        col_a, col_b, col_c, col_d = st.columns([3, 3, 3, 2])
                                        with col_a:
                                            st.markdown(f"👤 **{info_abs['Identité']}**")
                                            if info_abs['Sortie'] != "-":
                                                st.caption(f"Sortie seul : {info_abs['Sortie']}")
                                            if info_abs['Medical'] != "-":
                                                st.caption(f"⚠️ Médical : {info_abs['Medical']}")
                                        with col_b:
                                            st.markdown("👨‍👩‍👧 **Parent / Tuteur :**")
                                            st.write(info_abs['Parent'])
                                            if info_abs['Email']:
                                                st.markdown(f"✉️ [{info_abs['Email']}](mailto:{info_abs['Email']})")
                                        with col_c:
                                            st.markdown("📞 **Téléphones :**")
                                            if info_abs['Portable']:
                                                t1_clean = info_abs['Portable'].replace(" ", "").replace(".", "").replace("-", "")
                                                st.markdown(f"📱 [{info_abs['Portable']}](tel:{t1_clean}) · [💬 SMS](sms:{t1_clean})")
                                            if info_abs['Urgence']:
                                                t2_clean = info_abs['Urgence'].replace(" ", "").replace(".", "").replace("-", "")
                                                st.markdown(f"🚨 Urgence : [{info_abs['Urgence']}](tel:{t2_clean})")
                                            if not info_abs['Portable'] and not info_abs['Urgence']:
                                                st.caption("Aucun numéro renseigné")
                                        with col_d:
                                            if info_abs['row'] is not None:
                                                vcard_b = generer_vcard(info_abs['row'])
                                                st.download_button(
                                                    label="📇 vCard Parent",
                                                    data=vcard_b,
                                                    file_name=f"Parent_{info_abs['Identité']}.vcf".replace(" ", "_"),
                                                    mime="text/vcard",
                                                    key=f"vcf_{date_appel}_{groupe}_{info_abs['Identité']}",
                                                    use_container_width=True
                                                )

                                df_exp_abs = pd.DataFrame([
                                    {
                                        "Élève": d["Identité"],
                                        "Parent / Responsable": d["Parent"],
                                        "N° Portable": d["Portable"],
                                        "N° Urgence": d["Urgence"],
                                        "Email": d["Email"],
                                        "Sortie Seul": d["Sortie"],
                                        "Médical": d["Medical"]
                                    }
                                    for d in liste_donnees_absents
                                ])
                                nom_fich_abs = f"Absents_{groupe}_{date_appel}".replace(" ", "_").replace("/", "-")
                                st.download_button(
                                    label=f"📥 Télécharger la liste des absents ({len(liste_donnees_absents)}) en CSV",
                                    data=df_exp_abs.to_csv(index=False).encode('utf-8-sig'),
                                    file_name=f"{nom_fich_abs}.csv",
                                    mime="text/csv",
                                    key=f"dl_csv_{date_appel}_{groupe}"
                                )
                            else:
                                st.success("✅ Aucun absent sur ce créneau (100% de présence) !")

                            with st.expander(f"👁️ Voir la liste des {len(presents)} présents"):
                                if presents:
                                    st.write(", ".join(sorted(presents)))
                                else:
                                    st.info("Aucun élève noté présent.")

                            st.markdown("---")

                if appels_affiches == 0:
                    st.info("Aucun appel ne correspond aux filtres sélectionnés.")

    elif module_choisi == "🛒 Module Boutique":
        st.subheader("🛒 Suivi des Achats Boutique")
        st.write("Cochez la case une fois l'article remis à l'élève.")
        df_boutique = df[df['Campagne'].str.contains("boutique", case=False, na=False)].copy()
        if df_boutique.empty: st.info("Aucun achat boutique détecté.")
        else:
            df_boutique['ID_Dossier_Clean'] = df_boutique['ID_Dossier'].apply(nettoyer_id_dossier)
            df_boutique['Article Donné 🎁'] = df_boutique['ID_Dossier_Clean'].apply(lambda x: st.session_state['db']['boutique_donnees'].get(x, False))
            df_boutique["_orig_index"] = df_boutique.index
            df_display_boutique = df_boutique.set_index("_orig_index")
            colonnes_de_base = ["Nom", "Prénom", "Formule", "Montant Payé", "Article Donné 🎁"]
            colonnes_a_exclure = ["ID_Dossier", "ID_Dossier_Clean", "Campagne", "Identité", "Type", "Licence_FFE", "Nom payeur", "Prénom payeur", "Email payeur", "N° Portable", "N° Portable 2 (en cas d'urgence)", "EMail", "Adresse", "Ville", "Nom et prénom du responsable légal", "Classe", "Date de naissance", "Dans quel ville sera votre créneaux principale", "Sortie Seul", "Allergies / Médical", "Code Promo", "_orig_index"]
            colonnes_a_exclure.extend([c for c in df_display_boutique.columns if "autorise" in c.lower() or "accepte" in c.lower()])
            colonnes_supp_boutique = [c for c in df_display_boutique.columns if c not in colonnes_de_base and c not in colonnes_a_exclure and any(str(v).strip() not in ["", "nan", "None", "-"] for v in df_display_boutique[c].dropna())]
            colonnes_a_afficher = ["Article Donné 🎁", "Nom", "Prénom", "Formule"] + colonnes_supp_boutique + ["Montant Payé"]
            
            col_config = {"Article Donné 🎁": st.column_config.CheckboxColumn("Article Donné 🎁")}
            for c in colonnes_a_afficher:
                if c != "Article Donné 🎁": col_config[c] = st.column_config.Column(disabled=True)
                
            edited_boutique = st.data_editor(df_display_boutique[colonnes_a_afficher], use_container_width=True, column_config=col_config)
            
            if st.button("💾 Enregistrer les remises boutique", use_container_width=True):
                changement_b = False
                for idx_b in edited_boutique.index:
                    if idx_b not in df_display_boutique.index: continue
                    if is_different(df_display_boutique.loc[idx_b, "Article Donné 🎁"], edited_boutique.loc[idx_b, "Article Donné 🎁"]):
                        changement_b = True
                        st.session_state['db']['boutique_donnees'][nettoyer_id_dossier(df_display_boutique.loc[idx_b, "ID_Dossier"])] = bool(edited_boutique.loc[idx_b, "Article Donné 🎁"])
                if changement_b:
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.success("✅ État de la boutique enregistré !")
                    st.rerun()

    elif module_choisi == "🏆 Module Interclubs":
        st.subheader("🏆 Gestion des Équipes & Interclubs (Mode Manager)")
        st.info("Interface Stratégique : Gestion des bassins de joueurs, calcul des disponibilités FFE et génération des compositions.")
        
        pdf_ready = True
        try:
            import PyPDF2
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
            import io
        except ImportError:
            pdf_ready = False
            
        def get_rank_division(div_str):
            d = str(div_str).lower()
            if 'top' in d: return 1
            if '1' in d: return 2
            if '2' in d: return 3
            if '3' in d: return 4
            if '4' in d: return 5
            if 'reg' in d or 'rég' in d: return 6
            if 'dep' in d or 'dép' in d: return 7
            return 99

        def get_elo_lent_interclubs(identite, df_adh):
            try:
                row = df_adh[df_adh["Identité"] == identite]
                if not row.empty:
                    row = row.iloc[0]
                    # 1. Lent (FIDE ou National)
                    l_val, _, _ = extract_elo_val(row.get("Elo_Lent", ""))
                    if l_val > 0: return l_val
                    # 2. Rapide
                    r_val, _, _ = extract_elo_val(row.get("Elo_Rapide", ""))
                    if r_val > 0: return r_val
                    # 3. Blitz
                    b_val, _, _ = extract_elo_val(row.get("Elo_Blitz", ""))
                    if b_val > 0: return b_val
            except: pass
            return 1000

        liste_totale_joueurs = df["Identité"].unique().tolist()
        dict_elo_global = {j: get_elo_lent_interclubs(j, df) for j in liste_totale_joueurs}
        liste_totale_joueurs.sort(key=lambda j: dict_elo_global.get(j, 1000), reverse=True)
            
        with st.expander("🔄 Synchroniser les équipes depuis la FFE", expanded=False):
            st.write("Récupérez automatiquement toutes les équipes du club (Noms, Divisions, Liens de groupes).")
            lien_club = st.text_input("Lien FFE du club (ListeEquipes.aspx)", value="https://www.echecs.asso.fr/ListeEquipes.aspx?ClubRef=2705")
            if st.button("Lancer la synchronisation FFE", use_container_width=True):
                with st.spinner("Récupération des équipes..."):
                    try:
                        from bs4 import BeautifulSoup
                        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                        r = requests.get(lien_club, headers=headers, timeout=10)
                        soup = BeautifulSoup(r.text, 'html.parser')
                        table = soup.find('table')
                        
                        count = 0
                        if table:
                            if 'equipes_interclubs' not in st.session_state['db']: st.session_state['db']['equipes_interclubs'] = {}
                            
                            for tr in table.find_all('tr'):
                                if 'liste_clair' in tr.get('class', []) or 'liste_fonce' in tr.get('class', []):
                                    tds = tr.find_all('td')
                                    if len(tds) >= 4:
                                        a_name = tds[0].find('a')
                                        if not a_name: continue
                                        name = a_name.text.strip()
                                        comp = tds[1].text.strip()
                                        div = tds[2].text.strip()
                                        a_group = tds[3].find('a')
                                        group_link = a_group['href'] if a_group else ''
                                        
                                        cat = 'Jeunes' if 'jeune' in comp.lower() or ' j ' in f" {comp.lower()} " or 'jeune' in div.lower() else 'Adultes'
                                        nb_ech = 4 if cat == 'Jeunes' else 8
                                        if "duo" in div.lower(): nb_ech = 4
                                        elif "provence" in div.lower() and "i" in div.lower(): nb_ech = 6
                                        
                                        lien_complet = f"https://www.echecs.asso.fr/{group_link}" if group_link else ""
                                        
                                        if name not in st.session_state['db']['equipes_interclubs']:
                                            st.session_state['db']['equipes_interclubs'][name] = {
                                                "Categorie": cat, "Division": div, "Nb_Echiquiers": nb_ech, "Lien": lien_complet,
                                                "roster": [], "compo": {}, "couleurs": {}
                                            }
                                        else:
                                            st.session_state['db']['equipes_interclubs'][name]["Division"] = div
                                            st.session_state['db']['equipes_interclubs'][name]["Lien"] = lien_complet
                                            st.session_state['db']['equipes_interclubs'][name]["Nb_Echiquiers"] = nb_ech
                                            st.session_state['db']['equipes_interclubs'][name]["Categorie"] = cat
                                        count += 1
                                        
                            sauvegarder_base_cloud(st.session_state['db'])
                            st.success(f"✅ {count} équipes synchronisées avec succès !")
                        else:
                            st.error("Aucune table trouvée. Vérifiez le lien.")
                    except Exception as e:
                        st.error(f"Erreur lors de la synchronisation : {e}")

        tab_adultes, tab_jeunes = st.tabs(["🏅 Interclubs Adultes", "👦👧 Interclubs Jeunes"])
        
        def afficher_gestion_equipes(categorie):
            with st.expander(f"⚙️ Paramétrer une équipe {categorie} (Roster & Division)", expanded=False):
                with st.form(f"form_{categorie}"):
                    c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
                    nv_nom = c1.text_input("Nom de l'équipe (ex: Cassis 1)")
                    nv_div = c2.text_input("Division (ex: N2, N3...)")
                    nb_ech_defaut = 8 if categorie == "Adultes" else 4
                    nv_nb_ech = c3.number_input("Nb d'échiquiers", min_value=2, max_value=16, value=nb_ech_defaut)
                    nv_lien = c4.text_input("Lien FFE (ex: Equipe.aspx?EquipeRef=21406)")
                    
                    if st.form_submit_button("Sauvegarder l'équipe"):
                        if nv_nom:
                            if nv_nom not in st.session_state['db']['equipes_interclubs']:
                                st.session_state['db']['equipes_interclubs'][nv_nom] = {
                                    "Categorie": categorie, "Division": nv_div, "Nb_Echiquiers": int(nv_nb_ech), "Lien": nv_lien,
                                    "roster": [], "compo": {}, "couleurs": {}
                                }
                            else:
                                st.session_state['db']['equipes_interclubs'][nv_nom]["Division"] = nv_div
                                st.session_state['db']['equipes_interclubs'][nv_nom]["Nb_Echiquiers"] = int(nv_nb_ech)
                                st.session_state['db']['equipes_interclubs'][nv_nom]["Lien"] = nv_lien
                            sauvegarder_base_cloud(st.session_state['db'])
                            st.rerun()

            equipes_db = st.session_state['db'].get('equipes_interclubs', {})
            equipes_cat = {k: v for k, v in equipes_db.items() if v.get("Categorie") == categorie}
            
            if not equipes_cat:
                st.info(f"Ouvrez le menu ci-dessus pour initialiser vos équipes {categorie}.")
                return
                
            st.markdown("---")
            c_sel1, c_sel2 = st.columns([3, 1])
            equipe_choisie = c_sel1.selectbox(f"🎯 Manager l'équipe :", [""] + sorted(list(equipes_cat.keys())))
            
            if equipe_choisie:
                if c_sel2.button("🗑️ Supprimer l'équipe", key=f"del_{equipe_choisie}"):
                    del st.session_state['db']['equipes_interclubs'][equipe_choisie]
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.success(f"Équipe '{equipe_choisie}' supprimée !")
                    st.rerun()
            
            if equipe_choisie:
                eq_data = equipes_db[equipe_choisie]
                nb_ech_equipe = eq_data.get("Nb_Echiquiers", 8 if categorie == "Adultes" else 4)
                current_team_rank = get_rank_division(eq_data.get("Division", ""))
                url_equipe = eq_data.get("Lien", "")
                if url_equipe and not url_equipe.startswith("http"): url_equipe = f"https://www.echecs.asso.fr/{url_equipe}"
                
                st.markdown(f"""<div class="match-card">
                            <h3 style="margin-bottom:0; color:#005b96;">🛡️ {equipe_choisie}</h3>
                            <span style='font-size:16px; color:#FF8C00; font-weight:bold;'>{eq_data.get('Division', 'Division non précisée')} — {nb_ech_equipe} Échiquiers</span>
                            </div>""", unsafe_allow_html=True)

                # --- TELECHARGEMENT EN DIRECT (AVEC PROXY ALLORIGINS ANTI-BLOCAGE) ---
                df_classement = pd.DataFrame()
                df_calendrier = pd.DataFrame()
                if url_equipe:
                    with st.spinner("Recherche du calendrier FFE en direct (Contournement Proxy activé)..."):
                        def extraire_donnees(html_content):
                            dfs = pd.read_html(io.StringIO(html_content))
                            df_cla, df_cal = pd.DataFrame(), pd.DataFrame()
                            for t in dfs:
                                if t.empty: continue
                                first_row = [str(c).lower() for c in t.iloc[0].values]
                                if any('pl' in str(c) for c in first_row) and any('pts' in str(c) for c in first_row):
                                    t.columns = t.iloc[0]
                                    df_cla = t[1:].reset_index(drop=True)
                                    continue
                                
                                cols = [str(c).lower() for c in t.columns]
                                if any('pl' in c for c in cols) and any('pts' in c for c in cols): df_cla = t
                                if any('date' in c for c in cols) and any('score' in c for c in cols): df_cal = t
                            return df_cla, df_cal

                        try:
                            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                            r_html = requests.get(url_equipe, headers=headers, timeout=5)
                            df_classement, df_calendrier = extraire_donnees(r_html.text)
                        except: pass
                        
                        if df_calendrier.empty:
                            try:
                                url_proxy = f"https://api.allorigins.win/get?url={urllib.parse.quote(url_equipe)}"
                                r_proxy = requests.get(url_proxy, timeout=10)
                                html_proxy = r_proxy.json()['contents']
                                df_classement, df_calendrier = extraire_donnees(html_proxy)
                            except: pass

                        if df_calendrier.empty:
                            cal_fallback = fetch_ffe_team_calendar(url_equipe)
                            if cal_fallback: 
                                df_calendrier = pd.DataFrame(cal_fallback)
                                # Filter calendar to only show current team matches if possible
                                if not df_calendrier.empty:
                                    mots_equipe = equipe_choisie.split(" ")[0].lower()
                                    mask = df_calendrier["Match"].str.lower().str.contains(mots_equipe)
                                    if mask.any(): df_calendrier = df_calendrier[mask]

                if not df_classement.empty or not df_calendrier.empty:
                    c_c1, c_c2 = st.columns([1, 1.5])
                    with c_c1:
                        with st.expander("🏆 Voir le Classement FFE"):
                            if not df_classement.empty: st.dataframe(df_classement, hide_index=True)
                    with c_c2:
                        with st.expander("📅 Voir le Calendrier FFE"):
                            if not df_calendrier.empty: st.dataframe(df_calendrier, hide_index=True)

                # --- 1. BASSIN DE JOUEURS ---
                st.markdown("#### 👥 1. Bassin de joueurs (Roster prévu)")
                joueurs_roster = eq_data.get("roster", [])
                nouveau_roster = st.multiselect(
                    f"Quels joueurs sont prévus pour jouer dans l'équipe {equipe_choisie} cette saison ?", 
                    options=liste_totale_joueurs, default=[j for j in joueurs_roster if j in liste_totale_joueurs], key=f"rost_{equipe_choisie}"
                )
                if st.button(f"💾 Figer le Bassin de {equipe_choisie}", key=f"sv_rost_{equipe_choisie}"):
                    st.session_state['db']['equipes_interclubs'][equipe_choisie]["roster"] = nouveau_roster
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.success("Bassin verrouillé !")
                    st.rerun()

                st.markdown("---")
                st.markdown(f"#### ⚔️ 2. Établir la Composition")
                
                rondes_dispos = []
                idx_prochaine = 0
                dict_adversaires = {}
                
                if not df_calendrier.empty:
                    col_ronde = next((c for c in df_calendrier.columns if 'ronde' in str(c).lower() or 'match' in str(c).lower()), None)
                    col_score = next((c for c in df_calendrier.columns if 'score' in str(c).lower()), None)
                    if col_ronde:
                        def get_team_keywords(name):
                            nl = name.lower()
                            if "cassis" in nl: return "cassis"
                            return name.split(" ")[0].lower()
                        
                        mots_equipe = get_team_keywords(equipe_choisie)
                        if 'Match' in df_calendrier.columns:
                            matchs_eq = df_calendrier[df_calendrier["Match"].str.lower().str.contains(mots_equipe, na=False)]
                        else:
                            matchs_eq = df_calendrier[df_calendrier.apply(lambda r: mots_equipe in str(r.values).lower(), axis=1)]
                            
                        if not matchs_eq.empty:
                            rondes_dispos = matchs_eq[col_ronde].astype(str).tolist()
                            for i, r in matchs_eq.iterrows():
                                r_name = str(r[col_ronde])
                                sc = str(r.get(col_score, "")).strip()
                                
                                # Extraire l'adversaire de façon robuste
                                match_text = str(r.get("Match", ""))
                                adv = match_text.lower()
                                for t_name in match_text.split("-"):
                                    if mots_equipe in t_name.lower():
                                        adv = adv.replace(t_name.lower().strip(), "")
                                adv = adv.replace("-", "").replace("vs", "").strip()
                                
                                if adv: dict_adversaires[r_name] = f"{r_name} (vs {adv.title()})"
                                
                                if sc in ["", "nan", "None"] or " - " not in sc or "X" in sc:
                                    if idx_prochaine == 0: idx_prochaine = rondes_dispos.index(str(r[col_ronde]))
                
                if not rondes_dispos: rondes_dispos = [f"Ronde {i}" for i in range(1, 12)]

                c_r1, c_r2 = st.columns([1, 2])
                ronde_choisie = c_r1.selectbox("Sélectionnez la ronde :", rondes_dispos, index=idx_prochaine if idx_prochaine < len(rondes_dispos) else 0, key=f"sel_r_{equipe_choisie}", format_func=lambda x: dict_adversaires.get(x, x))
                
                if "couleurs" not in st.session_state['db']['equipes_interclubs'][equipe_choisie]: st.session_state['db']['equipes_interclubs'][equipe_choisie]["couleurs"] = {}
                couleur_saved = st.session_state['db']['equipes_interclubs'][equipe_choisie]["couleurs"].get(ronde_choisie, "⚪ Blancs")
                couleur_ech1 = c_r2.radio("Couleur au 1er échiquier :", ["⚪ Blancs", "⚫ Noirs"], index=0 if couleur_saved == "⚪ Blancs" else 1, horizontal=True, key=f"coul_{equipe_choisie}")

                date_match = "Inconnue"
                if not df_calendrier.empty and col_ronde and 'Date' in df_calendrier.columns:
                    try: date_match = df_calendrier[df_calendrier[col_ronde] == ronde_choisie]['Date'].values[0]
                    except: pass

                # CALCUL DES DISPONIBILITÉS FFE (Intelligence)
                joueurs_etats = {}
                for p in liste_totale_joueurs: 
                    joueurs_etats[p] = {"statut": "✅", "raison": "Disponible"}

                    # Vérification Licence FFE valide
                    row_j = df[df["Identité"] == p]
                    if not row_j.empty:
                        lic = str(row_j.iloc[0].get("Licence_FFE", "")).strip()
                        if not lic or lic.lower() in ["nan", "non croisé"] or len(lic) < 4:
                            joueurs_etats[p] = {"statut": "🚫", "raison": "Non licencié / Licence invalide"}

                for other_eq_name, other_eq_data in equipes_db.items():
                    if other_eq_name != equipe_choisie:
                        for p in other_eq_data.get("compo", {}).get(ronde_choisie, []):
                            if p in joueurs_etats and joueurs_etats[p]["statut"] != "🚫":
                                joueurs_etats[p] = {"statut": "⛔", "raison": f"Joue en {other_eq_name}"}

                for p in liste_totale_joueurs:
                    if joueurs_etats[p]["statut"] == "✅":
                        matches_higher = 0
                        for eq_n, eq_d in equipes_db.items():
                            if get_rank_division(eq_d.get("Division", "")) < current_team_rank:
                                for r_n, comp in eq_d.get("compo", {}).items():
                                    if p in comp: matches_higher += 1
                        if matches_higher >= 4:
                            joueurs_etats[p] = {"statut": "🚫", "raison": f"Brûlé (a joué {matches_higher} matchs en div. sup.)"}

                options_affichees = [""]
                map_options_vers_nom = {"": ""}
                
                for p in liste_totale_joueurs:
                    etat = joueurs_etats[p]["statut"]
                    raison = joueurs_etats[p]["raison"]
                    elo = dict_elo_global.get(p, 1000)
                    
                    if etat == "✅":
                        if p in nouveau_roster: label = f"✅ {p} ({elo})"
                        else: label = f"{p} ({elo}) - Hors bassin" # Retrait du panneau attention pour le hors bassin
                    else:
                        label = f"{etat} {p} ({elo}) - {raison}"
                        
                    options_affichees.append(label)
                    map_options_vers_nom[label] = p

                if "compo" not in st.session_state['db']['equipes_interclubs'][equipe_choisie]: st.session_state['db']['equipes_interclubs'][equipe_choisie]["compo"] = {}
                compo_actuelle = st.session_state['db']['equipes_interclubs'][equipe_choisie]["compo"].get(ronde_choisie, [""]*nb_ech_equipe)
                while len(compo_actuelle) < nb_ech_equipe: compo_actuelle.append("")

                nouvelle_compo = []
                blocage_sauvegarde = False
                erreurs_bloquantes = []
                
                st.markdown("""<div style='background-color:#f8f9fa; padding:20px; border-radius:10px; border:1px solid #e0e0e0;'>""", unsafe_allow_html=True)
                
                if categorie == "Jeunes":
                    st.info("RAPPEL FFE : Échiquiers ordonnés par âge strict (1er: U16, 2e: U14...). L'Elo ne sert qu'à départager un même âge.")
                
                c_echs = st.columns(2)
                for i in range(nb_ech_equipe):
                    val_saved_name = compo_actuelle[i]
                    
                    idx_defaut = 0
                    if val_saved_name:
                        for idx, opt in enumerate(options_affichees):
                            if map_options_vers_nom[opt] == val_saved_name:
                                idx_defaut = idx
                                break
                    
                    icon_couleur = "⚪" if (i % 2 == 0 and couleur_ech1 == "⚪ Blancs") or (i % 2 != 0 and couleur_ech1 != "⚪ Blancs") else "⚫"
                    choix = st.selectbox(f"Échiquier {i+1} {icon_couleur}", options_affichees, index=idx_defaut, key=f"ech_{i}_{equipe_choisie}")
                    
                    joueur_selectionne = map_options_vers_nom[choix]
                    nouvelle_compo.append(joueur_selectionne)
                    
                    if choix.startswith("⛔") or choix.startswith("🚫"):
                        blocage_sauvegarde = True
                        erreurs_bloquantes.append(f"Échiquier {i+1} : Vous ne pouvez pas aligner {joueur_selectionne} ({joueurs_etats[joueur_selectionne]['raison']})")
                
                st.markdown("</div>", unsafe_allow_html=True)

                if categorie == "Adultes":
                    for i in range(len(nouvelle_compo) - 1):
                        for j in range(i+1, len(nouvelle_compo)):
                            j1, j2 = nouvelle_compo[i], nouvelle_compo[j]
                            if j1 and j2:
                                elo1, elo2 = dict_elo_global.get(j1, 1000), dict_elo_global.get(j2, 1000)
                                if elo1 < elo2 - 100:
                                    blocage_sauvegarde = True
                                    erreurs_bloquantes.append(f"Règle des 100 points enfreinte entre l'échiquier {i+1} ({j1}, {elo1}) et l'échiquier {j+1} ({j2}, {elo2}).")

                st.write("")
                if erreurs_bloquantes:
                    for err in erreurs_bloquantes: st.error(err)
                elif any(nouvelle_compo): 
                    st.success("✅ Équipe réglementaire. Vous pouvez sauvegarder.")

                if st.button("💾 Enregistrer la Composition", use_container_width=True, disabled=blocage_sauvegarde):
                    st.session_state['db']['equipes_interclubs'][equipe_choisie]["compo"][ronde_choisie] = nouvelle_compo[:nb_ech_equipe]
                    st.session_state['db']['equipes_interclubs'][equipe_choisie]["couleurs"][ronde_choisie] = couleur_ech1
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.success(f"Composition enregistrée pour la {ronde_choisie} !")
                    st.rerun()

                # --- 3. GÉNÉRATION DU PDF ---
                if pdf_ready:
                    st.markdown("---")
                    with st.expander("📄 3. Générer la Feuille de Match (PDF)"):
                        c_p1, c_p2 = st.columns(2)
                        date_pdf = c_p1.text_input("Date du match", value=date_match, key=f"date_{equipe_choisie}")
                        lieu_pdf = c_p2.text_input("Lieu de rencontre", value="Domicile" if "cassis" in equipe_choisie.lower() else "", key=f"lieu_{equipe_choisie}")
                        
                        pdf_vierge = st.file_uploader("Importer la feuille FFE vierge (PDF)", type=['pdf'], key=f"up_{equipe_choisie}")
                        if pdf_vierge:
                            try:
                                packet = io.BytesIO()
                                c = canvas.Canvas(packet, pagesize=A4)
                                c.drawString(100, 770, str(date_pdf))
                                c.drawString(250, 770, str(lieu_pdf))
                                c.drawString(450, 770, str(ronde_choisie))
                                
                                x_offset = 0 if couleur_ech1 == "⚪ Blancs" else 280
                                c.drawString(80 + x_offset, 750, str(equipe_choisie))
                                
                                y_start = 615
                                y_step = 28
                                compo = st.session_state['db']['equipes_interclubs'][equipe_choisie]["compo"].get(ronde_choisie, [])
                                for idx, joueur in enumerate(compo):
                                    if joueur:
                                        c.drawString(70 + x_offset, y_start - (idx * y_step), str(joueur))
                                        row_joueur = df[df['Identité'] == joueur]
                                        if not row_joueur.empty:
                                            code_ffe = str(row_joueur.iloc[0].get('Licence_FFE', ''))
                                            if code_ffe != "Non croisé": c.drawString(240 + x_offset, y_start - (idx * y_step), code_ffe)
                                        c.drawString(300 + x_offset, y_start - (idx * y_step), str(dict_elo_global.get(joueur, "")))
                                
                                c.save()
                                packet.seek(0)
                                new_pdf = PyPDF2.PdfReader(packet)
                                
                                # Reset file pointer for the uploaded file just in case
                                pdf_vierge.seek(0)
                                existing_pdf = PyPDF2.PdfReader(pdf_vierge)
                                
                                output = PyPDF2.PdfWriter()
                                page = existing_pdf.pages[0]
                                page.merge_page(new_pdf.pages[0])
                                output.add_page(page)
                                
                                output_stream = io.BytesIO()
                                output.write(output_stream)
                                st.download_button("🖨️ Télécharger le PDF complété", data=output_stream.getvalue(), file_name=f"Feuille_{equipe_choisie}_{ronde_choisie}.pdf", mime="application/pdf", key=f"dl_pdf_{equipe_choisie}")
                            except Exception as e:
                                st.error(f"Impossible de dessiner sur le PDF : {e}")

        with tab_adultes: afficher_gestion_equipes("Adultes")
        with tab_jeunes: afficher_gestion_equipes("Jeunes")

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
                    if len(df_groupe[df_groupe['Identité'] == row['Identité']]) > 1: nom_aff += f" ({idx})"
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
                    liste_absents = [df_groupe.loc[idx_app, 'Identité'] for idx_app, est_present in presences.items() if not est_present]
                    if date_jour not in st.session_state['db']['historique_appels']: st.session_state['db']['historique_appels'][date_jour] = {}
                    st.session_state['db']['historique_appels'][date_jour][lieu_appel] = {
                        "entraineur": entraineur_appel,
                        "presents": liste_presents,
                        "absents": liste_absents
                    }
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
            if not creneaux_remplis:
                st.info("Aucun créneau disponible.")
            else:
                creneau_tournoi = st.selectbox("Lancer le tournoi pour le créneau :", options=creneaux_remplis, key="sel_creneau_tournoi")
                joueurs_inscrits = sorted(list(set(st.session_state['db']['affectations_creneaux'][creneau_tournoi])))

                # --- 1. LIAISON AUTOMATIQUE AVEC L'APPEL DU JOUR ---
                appel_du_jour = st.session_state['db'].get('historique_appels', {}).get(date_jour, {}).get(creneau_tournoi)
                
                if appel_du_jour is not None:
                    presents_appel = [e for e in appel_du_jour.get('presents', []) if e in joueurs_inscrits]
                    absents_appel = [e for e in appel_du_jour.get('absents', []) if e in joueurs_inscrits]
                    # Élèves non pointés
                    for j in joueurs_inscrits:
                        if j not in presents_appel and j not in absents_appel:
                            absents_appel.append(j)
                            
                    st.success(f"📋 **Appel du jour ({date_jour}) pris en compte pour {creneau_tournoi} :** {len(presents_appel)} présent(s), {len(absents_appel)} absent(s).")
                    if absents_appel:
                        st.warning(f"🚫 **Élèves absents placés en FORFAIT pour la ronde en cours (0 pt) :** " + ", ".join(absents_appel))
                    default_selection = presents_appel
                else:
                    st.info(f"ℹ️ Aucun appel n'a encore été enregistré aujourd'hui ({date_jour}) pour **{creneau_tournoi}** dans l'onglet **'📋 Faire l'Appel'**. Les élèves retirés ci-dessous seront considérés en forfait.")
                    default_selection = joueurs_inscrits

                c_part1, c_part2 = st.columns([3, 1])
                with c_part1:
                    joueurs_presents = st.multiselect(
                        "Élèves participant à la ronde (les absents non sélectionnés sont en forfait) :",
                        options=joueurs_inscrits,
                        default=default_selection,
                        key=f"presents_tournoi_{creneau_tournoi}"
                    )
                with c_part2:
                    joueurs_forfaits = [j for j in joueurs_inscrits if j not in joueurs_presents]
                    st.metric("Élèves en Forfait", len(joueurs_forfaits))

                # Calcul des Elos actifs pour tous les inscrits (hiérarchie FIDE > National > Crevette)
                elos_actifs, types_elos = {}, {}
                for j in joueurs_inscrits:
                    e_val, e_type = get_elo_actif(j, df, st.session_state['db'])
                    elos_actifs[j], types_elos[j] = e_val, e_type

                # --- 2. GESTION ET PERSISTANCE DU TOURNOI ---
                if 'etats_tournois' not in st.session_state['db']:
                    st.session_state['db']['etats_tournois'] = {}
                etat_sauve = st.session_state['db']['etats_tournois'].get(creneau_tournoi)

                if 'tournoi_en_cours' not in st.session_state or st.session_state.get('tournoi_en_cours') != creneau_tournoi:
                    if etat_sauve:
                        st.session_state['scores_tournoi'] = etat_sauve.get('scores', {j: 0.0 for j in joueurs_inscrits})
                        st.session_state['adversaires_tournoi'] = etat_sauve.get('adversaires', {j: [] for j in joueurs_inscrits})
                        st.session_state['couleurs_tournoi'] = etat_sauve.get('couleurs', {j: [] for j in joueurs_inscrits})
                        st.session_state['historique_rencontres'] = set(tuple(p) for p in etat_sauve.get('rencontres', []))
                        st.session_state['exempts_passes'] = set(etat_sauve.get('exempts', []))
                        st.session_state['ronde_actuelle'] = etat_sauve.get('ronde', 1)
                        st.session_state['appariements_ronde'] = etat_sauve.get('appariements', [])
                        st.session_state['exempt_ronde'] = etat_sauve.get('exempt_ronde', None)
                        st.session_state['tournoi_en_cours'] = creneau_tournoi
                    else:
                        st.session_state['scores_tournoi'] = {j: 0.0 for j in joueurs_inscrits}
                        st.session_state['adversaires_tournoi'] = {j: [] for j in joueurs_inscrits}
                        st.session_state['couleurs_tournoi'] = {j: [] for j in joueurs_inscrits}
                        st.session_state['historique_rencontres'] = set()
                        st.session_state['exempts_passes'] = set()
                        st.session_state['ronde_actuelle'] = 1
                        st.session_state['appariements_ronde'] = []
                        st.session_state['exempt_ronde'] = None
                        st.session_state['tournoi_en_cours'] = creneau_tournoi

                # Sécurité sur les clés
                for j in joueurs_inscrits:
                    if j not in st.session_state['scores_tournoi']: st.session_state['scores_tournoi'][j] = 0.0
                    if j not in st.session_state['adversaires_tournoi']: st.session_state['adversaires_tournoi'][j] = []
                    if j not in st.session_state['couleurs_tournoi']: st.session_state['couleurs_tournoi'][j] = []

                # --- 3. GRILLE AMÉRICAINE DU TOURNOI ---
                with st.expander(f"📊 Voir la Grille Américaine (Classement en direct — Ronde {st.session_state['ronde_actuelle']})"):
                    data_grille = []
                    for j in joueurs_inscrits:
                        pts = st.session_state['scores_tournoi'].get(j, 0.0)
                        advs = st.session_state['adversaires_tournoi'].get(j, [])
                        buchholz = sum(st.session_state['scores_tournoi'].get(adv, 0.0) for adv in advs)
                        nb_matchs = len(advs) + (1 if j in st.session_state.get('exempts_passes', set()) else 0)
                        
                        if j in joueurs_forfaits:
                            statut_actuel = "🚫 Forfait (0 pt)"
                        elif j == st.session_state.get('exempt_ronde'):
                            statut_actuel = "👑 Exempt (+1 pt)"
                        else:
                            adv_app = "En attente"
                            for b, n in st.session_state.get('appariements_ronde', []):
                                if b == j: adv_app = f"⚪ vs {n}"
                                elif n == j: adv_app = f"⚫ vs {b}"
                            statut_actuel = adv_app

                        data_grille.append({
                            "Élève": j,
                            "Points": pts,
                            "Buchholz": buchholz,
                            "Matchs": nb_matchs,
                            "Ronde en cours": statut_actuel,
                            "Elo Actif": elos_actifs.get(j, 400),
                            "Catégorie": types_elos.get(j, "Crevette")
                        })
                    if data_grille:
                        df_grille = pd.DataFrame(data_grille).sort_values(by=["Points", "Buchholz", "Elo Actif"], ascending=[False, False, False]).reset_index(drop=True)
                        df_grille.index += 1
                        st.dataframe(df_grille, use_container_width=True)

                st.markdown("---")
                col_t1, col_t2 = st.columns(2)
                with col_t1:
                    st.metric("Ronde actuelle", st.session_state['ronde_actuelle'])
                with col_t2:
                    if st.button("🔄 Réinitialiser le tournoi"):
                        st.session_state['scores_tournoi'] = {j: 0.0 for j in joueurs_inscrits}
                        st.session_state['adversaires_tournoi'] = {j: [] for j in joueurs_inscrits}
                        st.session_state['couleurs_tournoi'] = {j: [] for j in joueurs_inscrits}
                        st.session_state['historique_rencontres'] = set()
                        st.session_state['exempts_passes'] = set()
                        st.session_state['ronde_actuelle'] = 1
                        st.session_state['appariements_ronde'] = []
                        st.session_state['exempt_ronde'] = None
                        if 'etats_tournois' in st.session_state['db'] and creneau_tournoi in st.session_state['db']['etats_tournois']:
                            del st.session_state['db']['etats_tournois'][creneau_tournoi]
                            sauvegarder_base_cloud(st.session_state['db'])
                        st.success("Tournoi réinitialisé !")
                        st.rerun()

                st.markdown("---")
                # --- 4. GÉNÉRATION DE LA RONDE (SYSTÈME SUISSE OFFICIEL FIDE) ---
                if st.button("🎲 Générer la Ronde (Système Suisse)"):
                    if len(joueurs_presents) < 2:
                        st.error("⚠️ Au moins 2 élèves présents sont nécessaires pour générer une ronde.")
                    else:
                        scores_actifs = {j: st.session_state['scores_tournoi'][j] for j in joueurs_presents}
                        elos_presents = {j: elos_actifs[j] for j in joueurs_presents}
                        
                        pairs, exempt, st.session_state['historique_rencontres'] = generer_appariements_suisses(
                            joueurs_scores=scores_actifs,
                            elos_dict=elos_presents,
                            historique_rencontres=st.session_state['historique_rencontres'],
                            couleurs_historique=st.session_state['couleurs_tournoi'],
                            exempts_precedents=st.session_state['exempts_passes'],
                            ronde=st.session_state['ronde_actuelle']
                        )
                        st.session_state['appariements_ronde'] = pairs
                        st.session_state['exempt_ronde'] = exempt
                        if exempt:
                            st.session_state['exempts_passes'].add(exempt)

                        # Enregistrer l'état dans la base Cloud
                        st.session_state['db']['etats_tournois'][creneau_tournoi] = {
                            'scores': st.session_state['scores_tournoi'],
                            'adversaires': st.session_state['adversaires_tournoi'],
                            'couleurs': st.session_state['couleurs_tournoi'],
                            'rencontres': [list(p) for p in st.session_state['historique_rencontres']],
                            'exempts': list(st.session_state['exempts_passes']),
                            'ronde': st.session_state['ronde_actuelle'],
                            'appariements': st.session_state['appariements_ronde'],
                            'exempt_ronde': st.session_state['exempt_ronde']
                        }
                        sauvegarder_base_cloud(st.session_state['db'])
                        st.rerun()

                # --- 5. SAISIE DES RÉSULTATS ET MISE À JOUR DE L'ÉLO CREVETTE ---
                if st.session_state.get('appariements_ronde'):
                    st.subheader(f"♟️ Matchs — Ronde {st.session_state['ronde_actuelle']}")
                    
                    if joueurs_forfaits:
                        st.caption(f"🚫 **Forfaits cette ronde :** {', '.join(joueurs_forfaits)} *(0 pt attribué)*")

                    if st.button("📺 Afficher en Plein Écran (Pour vidéoprojecteur)"):
                        st.session_state['plein_ecran_ronde'] = True
                        st.rerun()
                        
                    resultats_saisis = []
                    for i, (j1, j2) in enumerate(st.session_state['appariements_ronde'], 1):
                        sym1 = "⚡" if "FIDE" in types_elos[j1] else ("🇫🇷" if "National" in types_elos[j1] else "🦐")
                        sym2 = "⚡" if "FIDE" in types_elos[j2] else ("🇫🇷" if "National" in types_elos[j2] else "🦐")
                        c_ech, c_res = st.columns([3, 2])
                        c_ech.markdown(f"**Échiquier {i} :** ⚪ **{j1}** ({elos_actifs[j1]} {sym1})  🆚  ⚫ **{j2}** ({elos_actifs[j2]} {sym2})")
                        res = c_res.selectbox(f"Résultat", ["Sélectionner...", "1 - 0 (Blancs)", "0 - 1 (Noirs)", "0.5 - 0.5 (Nulle)"], key=f"res_{creneau_tournoi}_{st.session_state['ronde_actuelle']}_{i}", label_visibility="collapsed")
                        resultats_saisis.append((j1, j2, res))
                        
                    if st.session_state.get('exempt_ronde'):
                        ex = st.session_state['exempt_ronde']
                        sym_ex = "⚡" if "FIDE" in types_elos[ex] else ("🇫🇷" if "National" in types_elos[ex] else "🦐")
                        st.warning(f"👑 **Exempt (+1 pt) :** {ex} ({elos_actifs[ex]} {sym_ex})")

                    st.markdown("---")
                    if st.button("💾 Valider les résultats & Mettre à jour les Elos"):
                        if any(r[2] == "Sélectionner..." for r in resultats_saisis):
                            st.error("⚠️ Veuillez renseigner le résultat de tous les échiquiers avant de valider.")
                        else:
                            variations_crevette = []
                            for j1, j2, res in resultats_saisis:
                                st.session_state['adversaires_tournoi'][j1].append(j2)
                                st.session_state['adversaires_tournoi'][j2].append(j1)
                                st.session_state['couleurs_tournoi'][j1].append('B')
                                st.session_state['couleurs_tournoi'][j2].append('N')
                                
                                elo1, elo2 = elos_actifs[j1], elos_actifs[j2]
                                type1, type2 = types_elos[j1], types_elos[j2]
                                
                                if res == "1 - 0 (Blancs)":
                                    st.session_state['scores_tournoi'][j1] += 1.0
                                    s1, s2 = 1.0, 0.0
                                elif res == "0 - 1 (Noirs)":
                                    st.session_state['scores_tournoi'][j2] += 1.0
                                    s1, s2 = 0.0, 1.0
                                else:
                                    st.session_state['scores_tournoi'][j1] += 0.5
                                    st.session_state['scores_tournoi'][j2] += 0.5
                                    s1, s2 = 0.5, 0.5
                                    
                                new_e1 = calculer_nouveau_elo(elo1, elo2, s1)
                                new_e2 = calculer_nouveau_elo(elo2, elo1, s2)
                                
                                # Mise à jour de l'Élo Crevette pour les joueurs concernés (estimé ou crevette)
                                if "Crevette" in type1:
                                    st.session_state['db']['elos_crevette'][j1] = new_e1
                                    diff1 = new_e1 - elo1
                                    variations_crevette.append(f"🦐 **{j1}** : {elo1} ➔ **{new_e1}** ({'+' if diff1 >= 0 else ''}{diff1})")
                                if "Crevette" in type2:
                                    st.session_state['db']['elos_crevette'][j2] = new_e2
                                    diff2 = new_e2 - elo2
                                    variations_crevette.append(f"🦐 **{j2}** : {elo2} ➔ **{new_e2}** ({'+' if diff2 >= 0 else ''}{diff2})")

                            if st.session_state.get('exempt_ronde'):
                                st.session_state['scores_tournoi'][st.session_state['exempt_ronde']] += 1.0

                            # Sauvegarde dans le Cloud Google Sheets
                            st.session_state['db']['etats_tournois'][creneau_tournoi] = {
                                'scores': st.session_state['scores_tournoi'],
                                'adversaires': st.session_state['adversaires_tournoi'],
                                'couleurs': st.session_state['couleurs_tournoi'],
                                'rencontres': [list(p) for p in st.session_state['historique_rencontres']],
                                'exempts': list(st.session_state['exempts_passes']),
                                'ronde': st.session_state['ronde_actuelle'] + 1,
                                'appariements': [],
                                'exempt_ronde': None
                            }
                            sauvegarder_base_cloud(st.session_state['db'])

                            st.session_state['ronde_actuelle'] += 1
                            st.session_state['appariements_ronde'] = []
                            st.session_state['exempt_ronde'] = None
                            
                            if variations_crevette:
                                st.session_state['msg_variations_crevette'] = " | ".join(variations_crevette)
                            st.success("Résultats enregistrés et Elos Crevette mis à jour dans le Cloud !")
                            st.rerun()

                if st.session_state.get('msg_variations_crevette'):
                    st.info(f"📈 **Mise à jour des Elos Crevette de la ronde précédente :** {st.session_state['msg_variations_crevette']}")
                    del st.session_state['msg_variations_crevette']

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
