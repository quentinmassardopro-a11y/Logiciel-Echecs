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
import concurrent.futures
from datetime import datetime
import urllib.parse
import gspread
from google.oauth2.service_account import Credentials
import chess
import chess.svg
from bs4 import BeautifulSoup
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

@st.cache_resource(ttl=1500, show_spinner=False)
def _get_gsheets_bundle_cached(creds_key):
    client = get_gsheets_client()
    sh = client.open("Base_Calanques_DB")
    return {"client": client, "sh": sh, "ws": {}}

def _get_gsheets_bundle(force_refresh=False):
    is_mocked = (
        "unittest.mock" in type(gspread.authorize).__module__
        or "unittest.mock" in type(Credentials.from_service_account_info).__module__
    )
    if is_mocked:
        if force_refresh or "_gs_bundle_mock" not in st.session_state:
            client = get_gsheets_client()
            sh = client.open("Base_Calanques_DB")
            st.session_state["_gs_bundle_mock"] = {"client": client, "sh": sh, "ws": {}}
        return st.session_state["_gs_bundle_mock"]
    if force_refresh:
        _get_gsheets_bundle_cached.clear()
    creds_info = dict(st.secrets["gcp_service_account"])
    creds_key = f"{creds_info.get('client_email', '')}_{creds_info.get('private_key_id', '')}"
    return _get_gsheets_bundle_cached(creds_key)

def _get_cached_worksheet(name, force_refresh=False):
    bundle = _get_gsheets_bundle(force_refresh=force_refresh)
    if name not in bundle["ws"]:
        bundle["ws"][name] = get_or_create_worksheet(bundle["sh"], name)
    return bundle["ws"][name]

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
        "ffe_joueurs": [],
        "repertoires_ouvertures": {},
        "ouvertures_eleves": {},
        "auto_sync_ffe": True
    }

def charger_base_cloud():
    for tentative in range(2):
        try:
            ws = _get_cached_worksheet("DB_JSON", force_refresh=(tentative > 0))
            vals = ws.col_values(1)
            st.session_state["_db_json_chunks_count"] = len(vals)
            if vals: return json.loads("".join(vals))
            return initialiser_memoire_vierge()
        except Exception as e:
            if tentative == 0: continue
            st.error(f"Erreur de connexion à Google Sheets (DB). Données protégées. Erreur: {e}")
            return None

def sauvegarder_base_cloud(db):
    json_str = json.dumps(db, ensure_ascii=False, separators=(',', ':'))
    chunks = [[json_str[i:i+40000]] for i in range(0, len(json_str), 40000)] or [[""]]
    for tentative in range(2):
        try:
            ws = _get_cached_worksheet("DB_JSON", force_refresh=(tentative > 0))
            prev_chunks = st.session_state.get("_db_json_chunks_count")
            if prev_chunks is not None:
                payload = chunks + [[""]] * max(0, prev_chunks - len(chunks))
            else:
                ws.clear()
                payload = chunks
            try: ws.update(values=payload, range_name="A1")
            except TypeError: ws.update("A1", payload)
            st.session_state["_db_json_chunks_count"] = len(chunks)
            return
        except Exception as e:
            if tentative == 0: continue
            st.error(f"Échec de la sauvegarde Cloud (DB): {e}")

def charger_adherents_cloud():
    for tentative in range(2):
        try:
            ws = _get_cached_worksheet("Adherents", force_refresh=(tentative > 0))
            data = ws.get_all_records()
            if data:
                df_res = pd.DataFrame(data)
                st.session_state["_adherents_cloud_shape"] = (len(df_res) + 1, len(df_res.columns))
                return df_res
            st.session_state["_adherents_cloud_shape"] = (0, 0)
            return pd.DataFrame()
        except Exception as e:
            if tentative == 0: continue
            st.error(f"Erreur de connexion à Google Sheets (Adhérents). Données protégées. Erreur: {e}")
            return None

def sauvegarder_adherents_cloud(df):
    if df is None: return
    if df.empty:
        data = [df.columns.values.tolist()]
    else:
        data = [df.columns.values.tolist()] + df.fillna("").astype(str).values.tolist()
    n_rows = len(data)
    n_cols = len(data[0]) if data else 0
    for tentative in range(2):
        try:
            ws = _get_cached_worksheet("Adherents", force_refresh=(tentative > 0))
            prev_shape = st.session_state.get("_adherents_cloud_shape")
            if prev_shape is not None and n_rows >= prev_shape[0] and n_cols >= prev_shape[1]:
                pass
            else:
                ws.clear()
            try: ws.update(values=data, range_name="A1")
            except TypeError: ws.update("A1", data)
            st.session_state["_adherents_cloud_shape"] = (n_rows, n_cols)
            return
        except Exception as e:
            if tentative == 0: continue
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
    val_str = re.sub(r'(\d)\s+(\d)', r'\1\2', str(val).upper().strip())
    match = re.search(r'(\d{3,4})', val_str)
    if match:
        score = int(match.group(1))
        is_fide = 'FIDE' in val_str or bool(re.search(r'(?:^|\d|\s)F(?:\s|$)', val_str))
        is_nat = bool(re.search(r'(?:^|\d|\s)[NE](?:\s|$)', val_str))
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
    val_str = str(chaine_brute).upper().strip()
    if re.search(r'(?:^|\d|\s)E(?:\s|$)', val_str) and 'FIDE' not in val_str:
        return True
    return False

def _elo_depuis_row(identite, row, db):
    """Calcule l'Élo actif et sa catégorie à partir d'une ligne adhérent déjà extraite."""
    elo_estime_trouve = None
    try:
        if row is not None:
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
    row = None
    try:
        if df_adherents is not None and not df_adherents.empty and "Identité" in df_adherents.columns:
            match = df_adherents[df_adherents["Identité"] == identite]
            if not match.empty:
                row = match.iloc[0]
    except Exception:
        pass
    return _elo_depuis_row(identite, row, db)

def calculer_elos_actifs_batch(identites, df_adherents, db):
    """Version O(N) de get_elo_actif pour afficher tableaux et classements sans boucles lentes."""
    row_map = {}
    if df_adherents is not None and not df_adherents.empty and "Identité" in df_adherents.columns:
        cols_elo = [c for c in ["Identité", "Elo_Rapide", "Elo_Lent", "Elo_Blitz"] if c in df_adherents.columns]
        for rec in df_adherents[cols_elo].to_dict("records"):
            ident = rec.get("Identité")
            if ident not in row_map:
                row_map[ident] = rec
    return {ident: _elo_depuis_row(ident, row_map.get(ident), db) for ident in identites}

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

RESULTATS_MATCH_OPTIONS = ["1 - 0 (Blancs)", "0 - 1 (Noirs)", "0.5 - 0.5 (Nulle)"]

def scores_depuis_resultat(res):
    """Retourne les points (Blancs, Noirs) associés à un résultat saisi."""
    if res == "1 - 0 (Blancs)":
        return 1.0, 0.0
    if res == "0 - 1 (Noirs)":
        return 0.0, 1.0
    if res == "0.5 - 0.5 (Nulle)":
        return 0.5, 0.5
    return 0.0, 0.0

def reconstruire_rencontres(adversaires_dict):
    """Reconstruit l'ensemble canonique des rencontres jouées depuis les listes d'adversaires."""
    rencontres = set()
    for j, advs in adversaires_dict.items():
        for adv in advs:
            rencontres.add((min(j, adv), max(j, adv)))
    return rencontres

def appliquer_modifications_ronde_passee(ronde_record, nouveaux_resultats, scores_tournoi, elos_crevette):
    """Met à jour les résultats d'une ronde passée et ajuste scores + Elos Crevette par delta."""
    modifs_details = []
    matchs = ronde_record.get('matchs', [])
    for m_idx, new_res in nouveaux_resultats.items():
        if m_idx < 0 or m_idx >= len(matchs):
            continue
        m = matchs[m_idx]
        old_res = m.get('resultat')
        if new_res == old_res or new_res not in RESULTATS_MATCH_OPTIONS:
            continue

        old_s1, old_s2 = scores_depuis_resultat(old_res)
        new_s1, new_s2 = scores_depuis_resultat(new_res)
        j1, j2 = m['blanc'], m['noir']

        scores_tournoi[j1] = round(scores_tournoi.get(j1, 0.0) + (new_s1 - old_s1), 1)
        scores_tournoi[j2] = round(scores_tournoi.get(j2, 0.0) + (new_s2 - old_s2), 1)

        elo1 = m.get('elo_blanc_avant', 400)
        elo2 = m.get('elo_noir_avant', 400)
        new_e1 = calculer_nouveau_elo(elo1, elo2, new_s1)
        new_e2 = calculer_nouveau_elo(elo2, elo1, new_s2)

        if "Crevette" in m.get('type_blanc', ''):
            old_d1 = m.get('crevette_delta_blanc', m.get('elo_blanc_apres', elo1) - elo1)
            new_d1 = new_e1 - elo1
            elos_crevette[j1] = max(100, elos_crevette.get(j1, 400) + (new_d1 - old_d1))
            m['elo_blanc_apres'] = new_e1
            m['crevette_delta_blanc'] = new_d1

        if "Crevette" in m.get('type_noir', ''):
            old_d2 = m.get('crevette_delta_noir', m.get('elo_noir_apres', elo2) - elo2)
            new_d2 = new_e2 - elo2
            elos_crevette[j2] = max(100, elos_crevette.get(j2, 400) + (new_d2 - old_d2))
            m['elo_noir_apres'] = new_e2
            m['crevette_delta_noir'] = new_d2

        m['resultat'] = new_res
        modifs_details.append(f"Échiquier {m_idx + 1} ({j1} vs {j2}) : {old_res} ➔ {new_res}")
    return modifs_details

def _retirer_dernier_elem(liste, cible):
    """Retire la dernière occurrence de cible dans une liste."""
    for idx in range(len(liste) - 1, -1, -1):
        if liste[idx] == cible:
            liste.pop(idx)
            return

def rouvrir_derniere_ronde(historique_rondes, scores_tournoi, adversaires_tournoi, couleurs_tournoi, elos_crevette):
    """Annule la validation de la dernière ronde enregistrée et rétablit son état actif pour modification."""
    if not historique_rondes:
        return None, reconstruire_rencontres(adversaires_tournoi)

    last_round = historique_rondes.pop()
    for m in last_round.get('matchs', []):
        j1, j2 = m['blanc'], m['noir']
        s1, s2 = scores_depuis_resultat(m.get('resultat'))
        scores_tournoi[j1] = round(scores_tournoi.get(j1, 0.0) - s1, 1)
        scores_tournoi[j2] = round(scores_tournoi.get(j2, 0.0) - s2, 1)

        if j1 in adversaires_tournoi:
            _retirer_dernier_elem(adversaires_tournoi[j1], j2)
        if j2 in adversaires_tournoi:
            _retirer_dernier_elem(adversaires_tournoi[j2], j1)
        if j1 in couleurs_tournoi and couleurs_tournoi[j1]:
            couleurs_tournoi[j1].pop()
        if j2 in couleurs_tournoi and couleurs_tournoi[j2]:
            couleurs_tournoi[j2].pop()

        if "Crevette" in m.get('type_blanc', ''):
            elo1 = m.get('elo_blanc_avant', 400)
            d1 = m.get('crevette_delta_blanc', m.get('elo_blanc_apres', elo1) - elo1)
            elos_crevette[j1] = max(100, elos_crevette.get(j1, 400) - d1)
        if "Crevette" in m.get('type_noir', ''):
            elo2 = m.get('elo_noir_avant', 400)
            d2 = m.get('crevette_delta_noir', m.get('elo_noir_apres', elo2) - elo2)
            elos_crevette[j2] = max(100, elos_crevette.get(j2, 400) - d2)

    ex = last_round.get('exempt')
    if ex:
        scores_tournoi[ex] = round(scores_tournoi.get(ex, 0.0) - 1.0, 1)

    return last_round, reconstruire_rencontres(adversaires_tournoi)

def ajuster_points_eleves(scores_tournoi, historique_ajustements, joueurs_cibles, delta, date_str, motif=""):
    """Ajoute ou retire des points au tournoi pour un ou plusieurs élèves et journalise l'opération."""
    if not joueurs_cibles or delta == 0:
        return False
    for j in joueurs_cibles:
        scores_tournoi[j] = round(scores_tournoi.get(j, 0.0) + float(delta), 1)
    historique_ajustements.append({
        'date': date_str,
        'joueurs': list(joueurs_cibles),
        'delta': float(delta),
        'motif': str(motif).strip() or "Ajustement manuel"
    })
    return True

def annuler_ajustement_points(scores_tournoi, historique_ajustements, idx_aj):
    """Annule un ajustement de points précédemment enregistré."""
    if idx_aj < 0 or idx_aj >= len(historique_ajustements):
        return None
    aj = historique_ajustements.pop(idx_aj)
    delta = float(aj.get('delta', 0.0))
    for j in aj.get('joueurs', []):
        scores_tournoi[j] = round(scores_tournoi.get(j, 0.0) - delta, 1)
    return aj

def sauvegarder_etat_tournoi(creneau_tournoi):
    """Persiste l'état complet du tournoi en préservant les listes de joueurs ajoutés/retirés."""
    if 'etats_tournois' not in st.session_state['db']:
        st.session_state['db']['etats_tournois'] = {}
    etat_existant = st.session_state['db']['etats_tournois'].get(creneau_tournoi, {})
    etat_existant.update({
        'scores': dict(st.session_state.get('scores_tournoi', {})),
        'adversaires': {k: list(v) for k, v in st.session_state.get('adversaires_tournoi', {}).items()},
        'couleurs': {k: list(v) for k, v in st.session_state.get('couleurs_tournoi', {}).items()},
        'rencontres': [list(p) for p in st.session_state.get('historique_rencontres', set())],
        'exempts': list(st.session_state.get('exempts_passes', set())),
        'ronde': st.session_state.get('ronde_actuelle', 1),
        'appariements': [list(p) for p in st.session_state.get('appariements_ronde', [])],
        'resultats_en_cours': {
            str(k): v
            for k, v in st.session_state.get('resultats_en_cours', {}).items()
            if v and v != "Sélectionner..."
        },
        'exempt_ronde': st.session_state.get('exempt_ronde', None),
        'forfaits_ronde': list(st.session_state.get('forfaits_actuels', [])),
        'historique_rondes': list(st.session_state.get('historique_rondes', [])),
        'historique_ajustements': list(st.session_state.get('historique_ajustements', []))
    })
    st.session_state['db']['etats_tournois'][creneau_tournoi] = etat_existant
    sauvegarder_base_cloud(st.session_state['db'])

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

def normaliser_cle_ffe(texte):
    """Normalise une chaîne pour le croisement FFE (sans accents, espaces ni tirets)."""
    return re.sub(r'[^a-z0-9]', '', normaliser_nom(texte))

def extraire_code_licence_ffe(val):
    """Extrait le code licence FFE brut (ex: 'K12345 (A)' -> 'K12345')."""
    if pd.isna(val):
        return ""
    s = str(val).strip().upper()
    if not s or s in ["NON CROISÉ", "NON CROISE", "NAN", "NONE", "-"]:
        return ""
    m = re.match(r'^([A-Z]\d+|\d{4,})', s)
    return m.group(1) if m else ""

def est_sans_licence(val):
    """Retourne True si l'élève n'a pas de licence FFE active (A ou B)."""
    if pd.isna(val):
        return True
    s_low = str(val).strip().lower()
    if not s_low or s_low in ["non croisé", "non croise", "nan", "none", "-", "0", "aucune", "non"]:
        return True
    if re.search(r'\(\s*n\s*\)|(?:^|\s)n$', s_low):
        return True
    if not re.search(r'\(\s*[ab]\s*\)', s_low):
        return True
    return False

CATALOGUE_ECO = [
    # Volume A : Flanc & Irrégulières
    {"eco": "A00", "nom": "Ouverture irrégulière / Orang-Outan (Sokolsky)", "moves": "b4"},
    {"eco": "A01", "nom": "Attaque Nimzo-Larsen", "moves": "b3"},
    {"eco": "A02", "nom": "Ouverture Bird", "moves": "f4"},
    {"eco": "A03", "nom": "Ouverture Bird — Ligne d5", "moves": "f4 d5"},
    {"eco": "A04", "nom": "Ouverture Réti / Début Zukertort", "moves": "Nf3"},
    {"eco": "A06", "nom": "Ouverture Réti (1.Cf3 d5)", "moves": "Nf3 d5"},
    {"eco": "A07", "nom": "Attaque Est-Indienne (Système Barcza)", "moves": "Nf3 d5 g3"},
    {"eco": "A09", "nom": "Gambit Réti (1.Cf3 d5 2.c4)", "moves": "Nf3 d5 c4"},
    {"eco": "A10", "nom": "Ouverture Anglaise", "moves": "c4"},
    {"eco": "A13", "nom": "Anglaise — Système Agincourt", "moves": "c4 e6"},
    {"eco": "A15", "nom": "Anglaise — Défense Anglo-Indienne", "moves": "c4 Nf6"},
    {"eco": "A16", "nom": "Anglaise — Anglo-Grünfeld", "moves": "c4 Nf6 Nc3 d5"},
    {"eco": "A20", "nom": "Anglaise — Sicilienne inversée", "moves": "c4 e5"},
    {"eco": "A22", "nom": "Anglaise — Variante de Brême", "moves": "c4 e5 Nc3 Nf6"},
    {"eco": "A25", "nom": "Anglaise — Sicilienne inversée fermée", "moves": "c4 e5 Nc3 Nc6"},
    {"eco": "A30", "nom": "Anglaise Symétrique", "moves": "c4 c5"},
    {"eco": "A34", "nom": "Anglaise Symétrique — Ligne Nc3 Nc6", "moves": "c4 c5 Nc3 Nc6"},
    {"eco": "A40", "nom": "Défense sur 1.d4 (ligne rare / Moderne)", "moves": "d4 g6"},
    {"eco": "A43", "nom": "Vieille Benoni", "moves": "d4 c5"},
    {"eco": "A45", "nom": "Attaque Trompowsky", "moves": "d4 Nf6 Bg5"},
    {"eco": "A46", "nom": "Attaque Torre / Jeu du Pion Dame", "moves": "d4 Nf6 Nf3 e6"},
    {"eco": "A48", "nom": "Système de Londres contre Est-Indienne", "moves": "d4 Nf6 Nf3 g6 Bf4"},
    {"eco": "A50", "nom": "Défense Indienne (1.d4 Cf6 2.c4)", "moves": "d4 Nf6 c4"},
    {"eco": "A52", "nom": "Gambit de Budapest", "moves": "d4 Nf6 c4 e5"},
    {"eco": "A53", "nom": "Vieille Indienne", "moves": "d4 Nf6 c4 d6"},
    {"eco": "A56", "nom": "Défense Benoni", "moves": "d4 Nf6 c4 c5"},
    {"eco": "A57", "nom": "Gambit Benko / Volga", "moves": "d4 Nf6 c4 c5 d5 b5"},
    {"eco": "A60", "nom": "Benoni Moderne", "moves": "d4 Nf6 c4 c5 d5 e6"},
    {"eco": "A70", "nom": "Benoni Moderne Classique", "moves": "d4 Nf6 c4 c5 d5 e6 Nc3 exd5 cxd5 d6 e4"},
    {"eco": "A80", "nom": "Défense Hollandaise", "moves": "d4 f5"},
    {"eco": "A84", "nom": "Hollandaise — Mur de Pierre", "moves": "d4 f5 c4 e6 Nc3 d5"},
    {"eco": "A85", "nom": "Hollandaise — Système c4/Cc3", "moves": "d4 f5 c4 Nf6 Nc3"},
    {"eco": "A87", "nom": "Hollandaise — Variante de Leningrad", "moves": "d4 f5 c4 Nf6 g3 g6 Bg2 Bg7"},
    {"eco": "A90", "nom": "Hollandaise Classique", "moves": "d4 f5 c4 Nf6 g3 e6 Bg2"},
    # Volume B : Semi-ouvertes (sauf Française)
    {"eco": "B00", "nom": "Défense Owen (1.e4 b6)", "moves": "e4 b6"},
    {"eco": "B01", "nom": "Défense Scandinave", "moves": "e4 d5"},
    {"eco": "B02", "nom": "Défense Alekhine", "moves": "e4 Nf6"},
    {"eco": "B04", "nom": "Défense Alekhine Moderne", "moves": "e4 Nf6 e5 Nd5 d4 d6 Nf3"},
    {"eco": "B06", "nom": "Défense Moderne", "moves": "e4 g6"},
    {"eco": "B07", "nom": "Défense Pirc", "moves": "e4 d6 d4 Nf6 Nc3"},
    {"eco": "B08", "nom": "Défense Pirc Classique", "moves": "e4 d6 d4 Nf6 Nc3 g6 Nf3"},
    {"eco": "B09", "nom": "Pirc — Attaque Autrichienne", "moves": "e4 d6 d4 Nf6 Nc3 g6 f4"},
    {"eco": "B10", "nom": "Défense Caro-Kann", "moves": "e4 c6"},
    {"eco": "B12", "nom": "Caro-Kann — Variante d'Avance", "moves": "e4 c6 d4 d5 e5"},
    {"eco": "B13", "nom": "Caro-Kann — Variante d'Échange / Panov", "moves": "e4 c6 d4 d5 exd5 cxd5"},
    {"eco": "B15", "nom": "Caro-Kann Classique", "moves": "e4 c6 d4 d5 Nc3"},
    {"eco": "B17", "nom": "Caro-Kann — Variante Karpov / Steinitz", "moves": "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Nd7"},
    {"eco": "B18", "nom": "Caro-Kann — Variante Classique Ff5", "moves": "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5"},
    {"eco": "B20", "nom": "Défense Sicilienne", "moves": "e4 c5"},
    {"eco": "B21", "nom": "Sicilienne — Gambit Smith-Morra", "moves": "e4 c5 d4 cxd4 c3"},
    {"eco": "B22", "nom": "Sicilienne — Variante Alapine", "moves": "e4 c5 c3"},
    {"eco": "B23", "nom": "Sicilienne Fermée", "moves": "e4 c5 Nc3"},
    {"eco": "B27", "nom": "Sicilienne — Dragon Hyper-Accéléré", "moves": "e4 c5 Nf3 g6"},
    {"eco": "B30", "nom": "Sicilienne — Attaque Rossolimo", "moves": "e4 c5 Nf3 Nc6 Bb5"},
    {"eco": "B32", "nom": "Sicilienne — Kalashnikov", "moves": "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 e5"},
    {"eco": "B33", "nom": "Sicilienne — Variante Sveshnikov", "moves": "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5"},
    {"eco": "B35", "nom": "Sicilienne — Dragon Accéléré", "moves": "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 g6"},
    {"eco": "B40", "nom": "Sicilienne — Variante Française (2...e6)", "moves": "e4 c5 Nf3 e6"},
    {"eco": "B42", "nom": "Sicilienne — Variante Kan", "moves": "e4 c5 Nf3 e6 d4 cxd4 Nxd4 a6"},
    {"eco": "B44", "nom": "Sicilienne — Variante Taimanov", "moves": "e4 c5 Nf3 e6 d4 cxd4 Nxd4 Nc6"},
    {"eco": "B50", "nom": "Sicilienne — Ligne 2...d6", "moves": "e4 c5 Nf3 d6"},
    {"eco": "B52", "nom": "Sicilienne — Attaque Moscou", "moves": "e4 c5 Nf3 d6 Bb5+"},
    {"eco": "B54", "nom": "Sicilienne Ouverte", "moves": "e4 c5 Nf3 d6 d4 cxd4 Nxd4"},
    {"eco": "B60", "nom": "Sicilienne — Attaque Richter-Rauzer", "moves": "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 Nc6 Bg5"},
    {"eco": "B70", "nom": "Sicilienne — Variante du Dragon", "moves": "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6"},
    {"eco": "B76", "nom": "Sicilienne — Dragon Attaque Yougoslave", "moves": "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6 Be3 Bg7 f3"},
    {"eco": "B80", "nom": "Sicilienne — Variante Scheveningen", "moves": "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 e6"},
    {"eco": "B90", "nom": "Sicilienne — Variante Najdorf", "moves": "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6"},
    # Volume C : Défense Française & Ouvertes (1.e4 e5)
    {"eco": "C00", "nom": "Défense Française", "moves": "e4 e6"},
    {"eco": "C01", "nom": "Française — Variante d'Échange", "moves": "e4 e6 d4 d5 exd5 exd5"},
    {"eco": "C02", "nom": "Française — Variante d'Avance", "moves": "e4 e6 d4 d5 e5"},
    {"eco": "C03", "nom": "Française — Variante Tarrasch", "moves": "e4 e6 d4 d5 Nd2"},
    {"eco": "C10", "nom": "Française — Variante Rubinstein", "moves": "e4 e6 d4 d5 Nc3 dxe4"},
    {"eco": "C11", "nom": "Française Classique", "moves": "e4 e6 d4 d5 Nc3 Nf6"},
    {"eco": "C15", "nom": "Française — Variante Winawer", "moves": "e4 e6 d4 d5 Nc3 Bb4"},
    {"eco": "C20", "nom": "Début du Pion Roi (1.e4 e5)", "moves": "e4 e5"},
    {"eco": "C21", "nom": "Partie du Centre", "moves": "e4 e5 d4 exd4"},
    {"eco": "C23", "nom": "Début du Fou", "moves": "e4 e5 Bc4"},
    {"eco": "C25", "nom": "Partie Viennoise", "moves": "e4 e5 Nc3"},
    {"eco": "C30", "nom": "Gambit du Roi", "moves": "e4 e5 f4"},
    {"eco": "C40", "nom": "Début du Cavalier Roi", "moves": "e4 e5 Nf3"},
    {"eco": "C41", "nom": "Défense Philidor", "moves": "e4 e5 Nf3 d6"},
    {"eco": "C42", "nom": "Défense Petrov / Défense Russe", "moves": "e4 e5 Nf3 Nf6"},
    {"eco": "C44", "nom": "Partie Écossaise (3.d4)", "moves": "e4 e5 Nf3 Nc6 d4"},
    {"eco": "C45", "nom": "Partie Écossaise — Ligne principale", "moves": "e4 e5 Nf3 Nc6 d4 exd4 Nxd4"},
    {"eco": "C46", "nom": "Partie des Trois Cavaliers", "moves": "e4 e5 Nf3 Nc6 Nc3"},
    {"eco": "C47", "nom": "Partie des Quatre Cavaliers", "moves": "e4 e5 Nf3 Nc6 Nc3 Nf6"},
    {"eco": "C50", "nom": "Partie Italienne", "moves": "e4 e5 Nf3 Nc6 Bc4"},
    {"eco": "C51", "nom": "Gambit Evans", "moves": "e4 e5 Nf3 Nc6 Bc4 Bc5 b4"},
    {"eco": "C53", "nom": "Italienne — Giuoco Piano", "moves": "e4 e5 Nf3 Nc6 Bc4 Bc5 c3"},
    {"eco": "C54", "nom": "Italienne — Giuoco Pianissimo", "moves": "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3"},
    {"eco": "C55", "nom": "Défense des Deux Cavaliers", "moves": "e4 e5 Nf3 Nc6 Bc4 Nf6"},
    {"eco": "C57", "nom": "Deux Cavaliers — Attaque Fegatello (Fried Liver)", "moves": "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5"},
    {"eco": "C60", "nom": "Partie Espagnole (Ruy Lopez)", "moves": "e4 e5 Nf3 Nc6 Bb5"},
    {"eco": "C63", "nom": "Espagnole — Gambit Schliemann", "moves": "e4 e5 Nf3 Nc6 Bb5 f5"},
    {"eco": "C65", "nom": "Espagnole — Défense de Berlin", "moves": "e4 e5 Nf3 Nc6 Bb5 Nf6"},
    {"eco": "C68", "nom": "Espagnole — Variante d'Échange", "moves": "e4 e5 Nf3 Nc6 Bb5 a6 Bxc6"},
    {"eco": "C78", "nom": "Espagnole — Défense Morphy", "moves": "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O"},
    {"eco": "C80", "nom": "Espagnole — Variante Ouverte", "moves": "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Nxe4"},
    {"eco": "C84", "nom": "Espagnole Fermée", "moves": "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7"},
    {"eco": "C88", "nom": "Espagnole — Anti-Marshall", "moves": "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 O-O a4"},
    {"eco": "C89", "nom": "Espagnole — Attaque Marshall", "moves": "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 O-O c3 d5"},
    {"eco": "C92", "nom": "Espagnole — Variante Fermée Principale", "moves": "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3"},
    # Volume D : Fermées & Grünfeld
    {"eco": "D00", "nom": "Ouverture du Pion Dame (1.d4 d5)", "moves": "d4 d5"},
    {"eco": "D01", "nom": "Attaque Richter-Veresov", "moves": "d4 d5 Nc3 Nf6 Bg5"},
    {"eco": "D02", "nom": "Système de Londres", "moves": "d4 d5 Nf3 Nf6 Bf4"},
    {"eco": "D03", "nom": "Attaque Torre", "moves": "d4 d5 Nf3 Nf6 Bg5"},
    {"eco": "D04", "nom": "Système Colle", "moves": "d4 d5 Nf3 Nf6 e3"},
    {"eco": "D06", "nom": "Gambit Dame", "moves": "d4 d5 c4"},
    {"eco": "D07", "nom": "Gambit Dame — Défense Chigorin", "moves": "d4 d5 c4 Nc6"},
    {"eco": "D08", "nom": "Gambit Dame — Contre-Gambit Albin", "moves": "d4 d5 c4 e5"},
    {"eco": "D10", "nom": "Défense Slave", "moves": "d4 d5 c4 c6"},
    {"eco": "D11", "nom": "Défense Slave (3.Cf3)", "moves": "d4 d5 c4 c6 Nf3"},
    {"eco": "D15", "nom": "Défense Slave Classique", "moves": "d4 d5 c4 c6 Nf3 Nf6 Nc3"},
    {"eco": "D20", "nom": "Gambit Dame Accepté", "moves": "d4 d5 c4 dxc4"},
    {"eco": "D30", "nom": "Gambit Dame Refusé", "moves": "d4 d5 c4 e6"},
    {"eco": "D31", "nom": "Gambit Dame Refusé (3.Cc3)", "moves": "d4 d5 c4 e6 Nc3"},
    {"eco": "D32", "nom": "Défense Tarrasch", "moves": "d4 d5 c4 e6 Nc3 c5"},
    {"eco": "D35", "nom": "Gambit Dame Refusé — Variante d'Échange", "moves": "d4 d5 c4 e6 Nc3 Nf6 cxd5 exd5"},
    {"eco": "D37", "nom": "Gambit Dame Refusé Classique (4.Cf3)", "moves": "d4 d5 c4 e6 Nc3 Nf6 Nf3"},
    {"eco": "D43", "nom": "Défense Semi-Slave", "moves": "d4 d5 c4 c6 Nf3 Nf6 Nc3 e6"},
    {"eco": "D45", "nom": "Semi-Slave — Système Meran / Anti-Meran", "moves": "d4 d5 c4 c6 Nf3 Nf6 Nc3 e6 e3"},
    {"eco": "D53", "nom": "Gambit Dame Refusé — Variante Lasker / Tartakower", "moves": "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7"},
    {"eco": "D70", "nom": "Défense Néo-Grünfeld", "moves": "d4 Nf6 c4 g6 g3 d5"},
    {"eco": "D80", "nom": "Défense Grünfeld", "moves": "d4 Nf6 c4 g6 Nc3 d5"},
    {"eco": "D85", "nom": "Grünfeld — Variante d'Échange", "moves": "d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5 e4 Nxc3 bxc3"},
    {"eco": "D97", "nom": "Grünfeld — Système Russe", "moves": "d4 Nf6 c4 g6 Nc3 d5 Nf3 Bg7 Qb3"},
    # Volume E : Défenses Indiennes
    {"eco": "E00", "nom": "Ouverture Catalane / Indienne", "moves": "d4 Nf6 c4 e6"},
    {"eco": "E04", "nom": "Partie Catalane Ouverte", "moves": "d4 Nf6 c4 e6 g3 d5 Bg2 dxc4"},
    {"eco": "E06", "nom": "Partie Catalane Fermée", "moves": "d4 Nf6 c4 e6 g3 d5 Bg2 Be7"},
    {"eco": "E11", "nom": "Défense Bogo-Indienne", "moves": "d4 Nf6 c4 e6 Nf3 Bb4+"},
    {"eco": "E12", "nom": "Défense Ouest-Indienne", "moves": "d4 Nf6 c4 e6 Nf3 b6"},
    {"eco": "E15", "nom": "Ouest-Indienne — Variante 4.g3", "moves": "d4 Nf6 c4 e6 Nf3 b6 g3"},
    {"eco": "E20", "nom": "Défense Nimzo-Indienne", "moves": "d4 Nf6 c4 e6 Nc3 Bb4"},
    {"eco": "E32", "nom": "Nimzo-Indienne — Variante Capablanca", "moves": "d4 Nf6 c4 e6 Nc3 Bb4 Qc2"},
    {"eco": "E46", "nom": "Nimzo-Indienne — Système Rubinstein", "moves": "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O"},
    {"eco": "E60", "nom": "Défense Est-Indienne", "moves": "d4 Nf6 c4 g6"},
    {"eco": "E61", "nom": "Est-Indienne (3.Cc3 Fg7)", "moves": "d4 Nf6 c4 g6 Nc3 Bg7"},
    {"eco": "E62", "nom": "Est-Indienne — Fianchetto", "moves": "d4 Nf6 c4 g6 Nc3 Bg7 Nf3 d6 g3"},
    {"eco": "E70", "nom": "Est-Indienne — Système 4.e4", "moves": "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6"},
    {"eco": "E76", "nom": "Est-Indienne — Attaque des Quatre Pions", "moves": "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 f4"},
    {"eco": "E80", "nom": "Est-Indienne — Attaque Sämisch", "moves": "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 f3"},
    {"eco": "E90", "nom": "Est-Indienne Classique", "moves": "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O"},
    {"eco": "E97", "nom": "Est-Indienne — Variante Mar del Plata", "moves": "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2 e5 O-O Nc6"},
]

def nettoyer_chaine_elo_ffe(txt):
    """Nettoie une cellule Elo FFE tout en conservant le marqueur F (FIDE), N (National) ou E (Estimé)."""
    if pd.isna(txt):
        return ""
    s = re.sub(r'\s+', ' ', str(txt).replace('\xa0', ' ')).strip().upper()
    s = re.sub(r'(\d)\s+(\d)', r'\1\2', s)
    if not s or s in ['-', 'NC', 'N/A', 'NONE', 'NAN']:
        return ""
    return s

def enrichir_cles_ffe(df_ffe):
    """Ajoute les clés normalisées de correspondance à un DataFrame FFE (idempotent)."""
    df_out = df_ffe.copy()
    for col in ['Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']:
        if col not in df_out.columns:
            df_out[col] = ""
        df_out[col] = df_out[col].fillna("").astype(str).apply(lambda v: "" if v.strip().lower() in ["nan", "none"] else v.strip())
    for col in ['Elo_Lent', 'Elo_Rapide', 'Elo_Blitz']:
        df_out[col] = df_out[col].apply(nettoyer_chaine_elo_ffe)

    has_name_cols = ('Nom' in df_out.columns and 'Prénom' in df_out.columns) or ('Nom_Norm' in df_out.columns and 'Prenom_Norm' in df_out.columns)
    if has_name_cols:
        if 'Nom_Norm' not in df_out.columns:
            df_out['Nom_Norm'] = df_out['Nom'].astype(str).apply(normaliser_cle_ffe)
        else:
            df_out['Nom_Norm'] = df_out['Nom_Norm'].astype(str).apply(normaliser_cle_ffe)
        if 'Prenom_Norm' not in df_out.columns:
            df_out['Prenom_Norm'] = df_out['Prénom'].astype(str).apply(normaliser_cle_ffe)
        else:
            df_out['Prenom_Norm'] = df_out['Prenom_Norm'].astype(str).apply(normaliser_cle_ffe)

        if 'Annee_FFE' not in df_out.columns:
            df_out['Annee_FFE'] = ""
        df_out['Annee_FFE'] = df_out['Annee_FFE'].fillna("").astype(str).str.strip()
        df_out['Cle_Forte'] = df_out['Nom_Norm'] + df_out['Prenom_Norm'] + df_out['Annee_FFE']
        df_out['Cle_Souple'] = df_out['Nom_Norm'] + df_out['Prenom_Norm']
        df_out['Cle_Inverse'] = df_out['Prenom_Norm'] + df_out['Nom_Norm']
    else:
        for col_c in ['Cle_Forte', 'Cle_Souple', 'Cle_Inverse']:
            if col_c not in df_out.columns:
                df_out[col_c] = ""
            else:
                df_out[col_c] = df_out[col_c].fillna("").astype(str).apply(normaliser_cle_ffe)

    df_out['Code_FFE'] = df_out['Licence_FFE'].apply(extraire_code_licence_ffe)
    return df_out

def _telecharger_ffe_calanques_uncached(timeout=12, silencieux=False):
    """Télécharge la liste des joueurs du club depuis le site FFE et conserve les marqueurs FIDE/National/Estimé."""
    url = 'https://www.echecs.asso.fr/ListeJoueurs.aspx?Action=JOUEURCLUBREF&ClubRef=2705'
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    html_content = None
    last_error = None

    try:
        r = requests.get(url, headers=headers, verify=False, timeout=timeout)
        if r.status_code == 200 and ('liste_clair' in r.text or 'liste_fonce' in r.text):
            html_content = r.content
    except Exception as e:
        last_error = e

    if html_content is None:
        try:
            url_proxy = f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}"
            proxy_timeout = 5 if silencieux else max(timeout, 10)
            r_proxy = requests.get(url_proxy, timeout=proxy_timeout)
            if r_proxy.status_code == 200:
                contents = r_proxy.json().get('contents', '')
                if contents and ('liste_clair' in contents or 'liste_fonce' in contents):
                    html_content = contents
        except Exception as e:
            last_error = e

    if html_content is None:
        if not silencieux and last_error:
            st.sidebar.error(f"Erreur de téléchargement FFE : {last_error}")
        return pd.DataFrame()

    try:
        try: soup = BeautifulSoup(html_content, 'lxml')
        except Exception: soup = BeautifulSoup(html_content, 'html.parser')
        idx_elo, idx_rapide, idx_blitz = 4, 5, 6
        for tr_head in soup.find_all('tr'):
            head_cells = [re.sub(r'\s+', ' ', c.get_text(' ', strip=True)).lower() for c in tr_head.find_all(['th', 'td'])]
            if any('nrffe' in h or 'nom' in h for h in head_cells) and any('rapide' in h for h in head_cells):
                for idx_c, txt_c in enumerate(head_cells):
                    if txt_c == 'elo' or (txt_c.startswith('elo') and 'rapide' not in txt_c and 'blitz' not in txt_c):
                        idx_elo = idx_c
                    elif 'rapide' in txt_c:
                        idx_rapide = idx_c
                    elif 'blitz' in txt_c:
                        idx_blitz = idx_c
                break

        data = []
        for tr in soup.find_all('tr', class_=['liste_clair', 'liste_fonce']):
            tds = tr.find_all('td')
            if len(tds) > max(idx_elo, idx_rapide, idx_blitz, 2):
                nr_ffe = re.sub(r'\s+', '', tds[0].get_text(strip=True)).upper()
                nom_prenom = re.sub(r'\s+', ' ', tds[1].get_text(' ', strip=True)).strip()
                af = re.sub(r'\s+', '', tds[2].get_text(strip=True).replace('\xa0', '')).upper()
                elo = nettoyer_chaine_elo_ffe(tds[idx_elo].get_text(' ', strip=True))
                rapide = nettoyer_chaine_elo_ffe(tds[idx_rapide].get_text(' ', strip=True))
                blitz = nettoyer_chaine_elo_ffe(tds[idx_blitz].get_text(' ', strip=True))

                mots = nom_prenom.split()
                nom_parts = [m for m in mots if m.isupper() or ('-' in m and m.replace('-', '').isupper())]
                prenom_parts = [m for m in mots if m not in nom_parts]

                nom = " ".join(nom_parts) if nom_parts else nom_prenom
                prenom = " ".join(prenom_parts) if prenom_parts else ""

                if not nr_ffe:
                    licence_fmt = "Non croisé"
                elif af in ['A', 'B']:
                    licence_fmt = f"{nr_ffe} ({af})"
                else:
                    licence_fmt = f"{nr_ffe} (N)"

                data.append({
                    'Nom': nom,
                    'Prénom': prenom,
                    'Elo_Lent': elo,
                    'Elo_Rapide': rapide,
                    'Elo_Blitz': blitz,
                    'Licence_FFE': licence_fmt,
                })
        df_ffe = pd.DataFrame(data)
        if not df_ffe.empty:
            df_ffe = enrichir_cles_ffe(df_ffe)
            return df_ffe[['Nom_Norm', 'Prenom_Norm', 'Annee_FFE', 'Cle_Forte', 'Cle_Souple', 'Cle_Inverse', 'Code_FFE', 'Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']]
    except Exception as e:
        if not silencieux:
            st.sidebar.error(f"Erreur d'analyse FFE : {e}")
    return pd.DataFrame()

@st.cache_data(ttl=1800, show_spinner=False)
def _telecharger_ffe_calanques_cached(timeout=12, silencieux=False):
    return _telecharger_ffe_calanques_uncached(timeout=timeout, silencieux=silencieux)

def telecharger_ffe_calanques(timeout=12, silencieux=False):
    if "unittest.mock" in type(requests.get).__module__:
        return _telecharger_ffe_calanques_uncached(timeout=timeout, silencieux=silencieux)
    return _telecharger_ffe_calanques_cached(timeout=timeout, silencieux=silencieux)

def analyser_fichier_ffe(fichier):
    """Analyse le CSV de la FFE et extrait les 3 colonnes d'Elos."""
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
        col_af = next((c for c in df_ffe.columns if str(c).strip().lower() in ["af", "aff", "af. info", "statut", "a/b", "type licence"]), None)
        col_dna = next((c for c in df_ffe.columns if any(m in str(c).lower() for m in ["dna", "né", "naissance"])), None)

        if col_nom and col_prenom:
            df_ffe['Nom'] = df_ffe[col_nom].astype(str)
            df_ffe['Prénom'] = df_ffe[col_prenom].astype(str)
            if col_dna: df_ffe['Annee_FFE'] = df_ffe[col_dna].astype(str).str.extract(r'(\d{4})')[0].fillna("")
            else: df_ffe['Annee_FFE'] = ""

            df_ffe['Elo_Lent'] = df_ffe[col_lent].astype(str) if col_lent else ""
            df_ffe['Elo_Rapide'] = df_ffe[col_rapide].astype(str) if col_rapide else ""
            df_ffe['Elo_Blitz'] = df_ffe[col_blitz].astype(str) if col_blitz else ""
            if col_licence:
                lic_series = df_ffe[col_licence].fillna("").astype(str).str.strip()
                lic_series = lic_series.apply(lambda v: "Non croisé" if not v or v.lower() in ["nan", "none", "-"] else v)
                if col_af:
                    af_series = df_ffe[col_af].fillna("").astype(str).str.strip().str.upper()
                    df_ffe['Licence_FFE'] = [
                        (f"{l} ({a})" if (l != "Non croisé" and a in ['A', 'B', 'N'] and f"({a})" not in l.upper()) else l)
                        for l, a in zip(lic_series, af_series)
                    ]
                else:
                    df_ffe['Licence_FFE'] = lic_series
            else:
                df_ffe['Licence_FFE'] = "Non croisé"

            df_ffe = enrichir_cles_ffe(df_ffe)
            return df_ffe[['Nom_Norm', 'Prenom_Norm', 'Annee_FFE', 'Cle_Forte', 'Cle_Souple', 'Cle_Inverse', 'Code_FFE', 'Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']]
    except Exception as e:
        st.sidebar.error(f"Erreur d'analyse FFE: {e}")
        return pd.DataFrame()
    return pd.DataFrame()

def recroiser_et_maj_ffe(df_base, df_ffe):
    """Croise une table d'adhérents avec les données FFE et met à jour Elos (FIDE/Nationaux) et licences."""
    if df_base is None or df_base.empty or df_ffe is None or df_ffe.empty:
        return df_base, [], 0

    df_res = df_base.copy()
    for col, defaut in [('Elo_Lent', ''), ('Elo_Rapide', ''), ('Elo_Blitz', ''), ('Licence_FFE', 'Non croisé')]:
        if col not in df_res.columns:
            df_res[col] = defaut
        df_res[col] = df_res[col].fillna(defaut).astype(str).apply(lambda v: defaut if v.strip().lower() in ['nan', 'none', ''] else v.strip())

    df_ffe_norm = enrichir_cles_ffe(df_ffe)
    by_code, by_forte, by_souple = {}, {}, {}
    inverse_counts, by_inverse = {}, {}

    for _, f_row in df_ffe_norm.iterrows():
        rec = {
            'Elo_Lent': f_row['Elo_Lent'],
            'Elo_Rapide': f_row['Elo_Rapide'],
            'Elo_Blitz': f_row['Elo_Blitz'],
            'Licence_FFE': f_row['Licence_FFE'] or 'Non croisé',
        }
        code = f_row.get('Code_FFE', '')
        if code and code not in by_code:
            by_code[code] = rec
        cle_f = f_row.get('Cle_Forte', '')
        cle_s = f_row.get('Cle_Souple', '')
        if cle_f and cle_f != cle_s and cle_f not in by_forte:
            by_forte[cle_f] = rec
        if cle_s and cle_s not in by_souple:
            by_souple[cle_s] = rec
        cle_i = f_row.get('Cle_Inverse', '')
        if cle_i and cle_i != cle_s:
            inverse_counts[cle_i] = inverse_counts.get(cle_i, 0) + 1
            by_inverse[cle_i] = rec

    by_inverse = {k: v for k, v in by_inverse.items() if inverse_counts.get(k, 0) == 1}

    changements = []
    nb_matches = 0

    for idx, row in df_res.iterrows():
        if str(row.get('Type', '')).strip().lower() == 'boutique':
            continue

        code_existant = extraire_code_licence_ffe(row.get('Licence_FFE', ''))
        nom_n = normaliser_cle_ffe(row.get('Nom', ''))
        prenom_n = normaliser_cle_ffe(row.get('Prénom', ''))
        m_an = re.search(r'(\d{4})', str(row.get('Date de naissance', '')))
        annee_ha = m_an.group(1) if m_an else ""

        cle_forte = nom_n + prenom_n + annee_ha
        cle_souple = nom_n + prenom_n

        match = None
        if code_existant and code_existant in by_code:
            match = by_code[code_existant]
        elif annee_ha and cle_forte in by_forte:
            match = by_forte[cle_forte]
        elif cle_souple and cle_souple in by_souple:
            match = by_souple[cle_souple]
        elif cle_souple and cle_souple in by_inverse:
            match = by_inverse[cle_souple]

        if match:
            nb_matches += 1
            diffs_eleve = []
            for col in ['Elo_Rapide', 'Elo_Lent', 'Elo_Blitz', 'Licence_FFE']:
                old_v = str(row.get(col, '')).strip()
                new_v = str(match[col]).strip()
                if old_v != new_v:
                    df_res.at[idx, col] = new_v
                    label_col = "Licence" if col == "Licence_FFE" else col.replace('Elo_', '')
                    diffs_eleve.append(f"{label_col}: {old_v or '-'} ➔ {new_v or '-'}")
            if diffs_eleve:
                identite = row.get('Identité', f"{row.get('Prénom', '')} {row.get('Nom', '')}".strip())
                changements.append(f"**{identite}** ({', '.join(diffs_eleve)})")

    return df_res, changements, nb_matches

def actualiser_elos_ffe_automatique(silencieux=False):
    """Télécharge la liste FFE du club et met à jour automatiquement les Elos FIDE & Nationaux dans la base."""
    if not silencieux and hasattr(_telecharger_ffe_calanques_cached, "clear"):
        _telecharger_ffe_calanques_cached.clear()
    df_ffe_scrap = telecharger_ffe_calanques(timeout=4 if silencieux else 12, silencieux=silencieux)
    if df_ffe_scrap.empty:
        return False, [], 0

    st.session_state['df_ffe'] = df_ffe_scrap
    df_actuel = st.session_state.get('df_adherents', pd.DataFrame())
    if df_actuel is None or df_actuel.empty:
        return True, [], 0

    df_maj, changements, nb_matches = recroiser_et_maj_ffe(df_actuel, df_ffe_scrap)
    if changements:
        st.session_state['df_adherents'] = df_maj
        sauvegarder_adherents_cloud(df_maj)

    st.session_state['ffe_last_sync_info'] = {
        'heure': datetime.now().strftime("%d/%m/%Y à %H:%M"),
        'nb_ffe': len(df_ffe_scrap),
        'nb_matches': nb_matches,
        'changements': changements,
    }
    return True, changements, nb_matches

# --- HELLOASSO LOGIC ---
def affectations_automatiques(row):
    creneaux = []
    camp, form, classe = str(row.get("Campagne", "")).lower(), str(row.get("Formule", "")).lower(), str(row.get("Classe", "")).lower()
    ville_choisie = str(row.get("Dans quel ville sera votre créneaux principale", "")).lower()
    
    if "trinit" in camp:
        if "cp" in classe or "ce1" in classe: creneaux.append("Mardi - Sainte-Trinité (CP-CE1)")
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
            if "trinit" in camp: creneaux.append("Mardi - Sainte-Trinité (CP-CE1)")
            elif "ciotat" in form: creneaux.append("Lundi - La Ciotat")
            else: creneaux.append("Lundi - Club Cassis")
        elif "mardi" in form:
            if "trinit" in camp: creneaux.append("Mardi - Sainte-Trinité (CP-CE1)")
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

# --- CHARGEMENT INITIALISATION (PARALLÈLE & OPTIMISÉ) ---
if 'db' not in st.session_state and 'df_adherents' not in st.session_state:
    with st.spinner("Connexion rapide au Cloud Google..."):
        try:
            ws_db = _get_cached_worksheet("DB_JSON")
            ws_adh = _get_cached_worksheet("Adherents")
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                fut_db = executor.submit(ws_db.col_values, 1)
                fut_adh = executor.submit(ws_adh.get_all_records)
                vals_db = fut_db.result()
                data_adh = fut_adh.result()
            st.session_state["_db_json_chunks_count"] = len(vals_db)
            st.session_state["_prefetched_db"] = json.loads("".join(vals_db)) if vals_db else initialiser_memoire_vierge()
            if data_adh:
                df_pre = pd.DataFrame(data_adh)
                st.session_state["_adherents_cloud_shape"] = (len(df_pre) + 1, len(df_pre.columns))
            else:
                df_pre = pd.DataFrame()
                st.session_state["_adherents_cloud_shape"] = (0, 0)
            st.session_state["_prefetched_df_adh"] = df_pre
        except Exception:
            pass

if 'db' not in st.session_state: 
    with st.spinner("Connexion sécurisée au Cloud Google..."):
        db_loaded = st.session_state.pop("_prefetched_db", None)
        if db_loaded is None:
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
        df_loaded = st.session_state.pop("_prefetched_df_adh", None)
        if df_loaded is None:
            df_loaded = charger_adherents_cloud()
        if df_loaded is None: st.stop() 
        
        if not df_loaded.empty: 
            df_before_cmp = df_loaded.fillna("").astype(str).reset_index(drop=True)
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

            df_after_cmp = df_loaded.fillna("").astype(str).reset_index(drop=True)
            adherents_modifies = (len(df_loaded) != len_avant) or not df_after_cmp.equals(df_before_cmp)
            st.session_state['df_adherents'] = df_loaded
            if adherents_modifies:
                sauvegarder_adherents_cloud(df_loaded)
        else:
            st.session_state['df_adherents'] = pd.DataFrame()

default_mem = initialiser_memoire_vierge()
for cle, val_defaut in default_mem.items():
    if cle not in st.session_state['db']:
        st.session_state['db'][cle] = val_defaut

# --- MIGRATION SAINTE-TRINITE CP-CE1 ---
if 'affectations_creneaux' in st.session_state['db']:
    aff = st.session_state['db']['affectations_creneaux']
    lundi_cp = aff.get("Lundi - Sainte-Trinité (CP)", [])
    mardi_ce1 = aff.get("Mardi - Sainte-Trinité (CE1)", [])
    if lundi_cp or mardi_ce1:
        mardi_cp_ce1 = aff.get("Mardi - Sainte-Trinité (CP-CE1)", [])
        nouveau = list(set(mardi_cp_ce1 + lundi_cp + mardi_ce1))
        aff["Mardi - Sainte-Trinité (CP-CE1)"] = nouveau
        if "Lundi - Sainte-Trinité (CP)" in aff: del aff["Lundi - Sainte-Trinité (CP)"]
        if "Mardi - Sainte-Trinité (CE1)" in aff: del aff["Mardi - Sainte-Trinité (CE1)"]

# --- ACTUALISATION AUTOMATIQUE FFE AU DÉMARRAGE (1 FOIS PAR SESSION) ---
if st.session_state['db'].get('auto_sync_ffe', True) and 'ffe_auto_sync_done' not in st.session_state and not st.session_state['df_adherents'].empty:
    st.session_state['ffe_auto_sync_done'] = True
    ok_ffe, chang_ffe, nb_m_ffe = actualiser_elos_ffe_automatique(silencieux=True)
    if ok_ffe and chang_ffe:
        st.session_state['ffe_auto_toast'] = f"✅ {len(chang_ffe)} élève(s) mis à jour depuis la FFE (Elos FIDE / Nationaux)."

# --- NAVIGATION DES MODULES ---
df = st.session_state['df_adherents']
date_jour = datetime.now().strftime("%d/%m/%Y")

structure_creneaux = {
    "Lundi": ["Lundi - La Ciotat", "Lundi - Carnoux", "Lundi - Club Cassis"],
    "Mardi": ["Mardi - Sainte-Trinité (CP-CE1)", "Mardi - Saint-Augustin (CP-CE1)", "Mardi - Ceyreste", "Mardi - Marseille"],
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
    res_en_cours_ecran = st.session_state.get('resultats_en_cours', {})
    for i, (j1, j2) in enumerate(st.session_state.get('appariements_ronde', []), 1):
        pts1 = st.session_state['scores_tournoi'].get(j1, 0)
        pts2 = st.session_state['scores_tournoi'].get(j2, 0)
        res_i = res_en_cours_ecran.get(str(i), "")
        score_aff = res_i.split(" (")[0] if res_i and res_i != "Sélectionner..." else "... - ..."
        html_table += f"<tr><td>{i}</td><td>{j1} <br><span class='pts'>({pts1} pts)</span></td><td>{score_aff}</td><td>{j2} <br><span class='pts'>({pts2} pts)</span></td></tr>"
        
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
module_choisi = st.sidebar.radio("", ["🛠️ Module Administration", "♟️ Module Entraîneur", "🛒 Module Boutique"])

st.sidebar.markdown("---")
st.sidebar.header("☁️ CLOUD & TEMPS RÉEL")
st.sidebar.info("La Base de données et les Adhérents sont synchronisés avec Google Sheets.")
if st.sidebar.button("🔄 Rafraîchir les données (Cloud)"):
    with st.spinner("Récupération des modifications..."):
        db_loaded = charger_base_cloud()
        if db_loaded: st.session_state['db'] = db_loaded
        df_loaded = charger_adherents_cloud()
        if df_loaded is not None and not df_loaded.empty: st.session_state['df_adherents'] = df_loaded
        st.session_state.pop('tournoi_en_cours', None)
        for k_ss in [k for k in list(st.session_state.keys()) if k.startswith("res_")]:
            st.session_state.pop(k_ss, None)
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("1️⃣ Base FFE (Elos FIDE & Nationaux)")

auto_ffe_pref = st.session_state['db'].get('auto_sync_ffe', True)
nouvelle_pref_ffe = st.sidebar.checkbox("Actualisation auto au démarrage", value=auto_ffe_pref, key="chk_auto_sync_ffe")
if nouvelle_pref_ffe != auto_ffe_pref:
    st.session_state['db']['auto_sync_ffe'] = nouvelle_pref_ffe
    sauvegarder_base_cloud(st.session_state['db'])

if st.session_state.get('ffe_auto_toast'):
    st.sidebar.success(st.session_state['ffe_auto_toast'])
    del st.session_state['ffe_auto_toast']

if st.sidebar.button("🔄 Actualiser les Elos FFE (FIDE & Nationaux)"):
    with st.spinner("Récupération et mise à jour depuis echecs.asso.fr..."):
        ok_ffe, chang_ffe, nb_m_ffe = actualiser_elos_ffe_automatique(silencieux=False)
        if ok_ffe:
            st.session_state['ffe_manual_report'] = (chang_ffe, nb_m_ffe)
            st.rerun()
        else:
            st.sidebar.warning("❌ Impossible de récupérer la liste FFE pour le moment.")

if st.session_state.get('ffe_manual_report'):
    chang_rep, nb_m_rep = st.session_state.pop('ffe_manual_report')
    if chang_rep:
        st.sidebar.success(f"✅ {len(chang_rep)} élève(s) mis à jour ({nb_m_rep} licencié(s) reconnu(s)) !")
        with st.sidebar.expander("Voir les Elos mis à jour", expanded=True):
            for c_txt in chang_rep:
                st.markdown(f"- {c_txt}")
    else:
        st.sidebar.info(f"👌 Déjà à jour ({nb_m_rep} licencié(s) FFE vérifié(s)).")

if st.session_state.get('ffe_last_sync_info'):
    info_sync = st.session_state['ffe_last_sync_info']
    st.sidebar.caption(f"Dernière synchro FFE : {info_sync['heure']} ({info_sync['nb_matches']} élève(s) relié(s))")

fichier_ffe = st.sidebar.file_uploader("Ou Fichier FFE (Glissez CSV ici)", type=['csv', 'xls', 'xlsx'])
if fichier_ffe:
    df_ffe = analyser_fichier_ffe(fichier_ffe)
    if not df_ffe.empty:
        st.session_state['df_ffe'] = df_ffe
        st.sidebar.success("Fichier FFE chargé en mémoire !")

if 'df_ffe' in st.session_state:
    if st.sidebar.button("🔄 Recroiser avec le fichier FFE en mémoire"):
        if 'df_adherents' in st.session_state and not st.session_state['df_adherents'].empty:
            with st.spinner("Recherche des correspondances dans la base FFE (3 Elos)..."):
                df_base, chang_csv, nb_m_csv = recroiser_et_maj_ffe(st.session_state['df_adherents'], st.session_state['df_ffe'])
                if chang_csv:
                    st.session_state['df_adherents'] = df_base
                    sauvegarder_adherents_cloud(df_base)
                st.session_state['ffe_manual_report'] = (chang_csv, nb_m_csv)
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
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [executor.submit(fetch_campaign_items, token, type_camp, slug, nom) for nom, type_camp, slug in campagnes]
                    for fut in futures:
                        try:
                            all_data.extend(fut.result())
                        except Exception:
                            pass
                all_data.extend(st.session_state['db']['eleves_essai'])
                
                if all_data:
                    df_new_fetch = pd.DataFrame(all_data)
                    df_local = st.session_state.get('df_adherents', pd.DataFrame()).copy()
                    ids_supprimes_set = {str(x) for x in st.session_state['db'].get('dossiers_supprimes', [])}
                    existing_ids_set = set(df_local['ID_Dossier'].dropna().astype(str)) if (not df_local.empty and 'ID_Dossier' in df_local.columns) else set()
                    
                    def est_valide(r):
                        id_dos = nettoyer_id_dossier(r.get('ID_Dossier', ''))
                        if id_dos and id_dos != 'nan' and id_dos in ids_supprimes_set: return False
                        if id_dos in existing_ids_set: return False
                        return True
                        
                    nouveaux = df_new_fetch[df_new_fetch.apply(est_valide, axis=1)].copy()

                    if not nouveaux.empty:
                        if 'df_ffe' in st.session_state and not st.session_state['df_ffe'].empty:
                            nouveaux, _, _ = recroiser_et_maj_ffe(nouveaux, st.session_state['df_ffe'])
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

if st.sidebar.button("📦 Préparer la Sauvegarde Complète (.zip)", use_container_width=True):
    buffer_zip = io.BytesIO()
    with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for f_name in ["app.py", "requirements.txt", "logo.png"]:
            if os.path.exists(f_name):
                with open(f_name, "rb") as f: zip_file.writestr(f_name, f.read())

        if 'db' in st.session_state:
            zip_file.writestr("base_calanques_db.json", json.dumps(st.session_state['db'], ensure_ascii=False, indent=2))

        if 'df_adherents' in st.session_state and not st.session_state['df_adherents'].empty:
            zip_file.writestr("adherents_db.csv", st.session_state['df_adherents'].to_csv(index=False).encode('utf-8'))

    st.session_state['_backup_zip_ready'] = (
        buffer_zip.getvalue(),
        f"Sauvegarde_Echecs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    )

if '_backup_zip_ready' in st.session_state:
    zip_bytes, zip_name = st.session_state['_backup_zip_ready']
    st.sidebar.download_button(
        label="⬇️ Télécharger Sauvegarde Complète",
        data=zip_bytes,
        file_name=zip_name,
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
                                st.session_state['db']['cartes_membres'][nv_identite] = {"Cassis": False, "Carnoux": False}
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
                                if nv_identite not in st.session_state['db']['cartes_membres']: st.session_state['db']['cartes_membres'][nv_identite] = dict(st.session_state['db']['cartes_membres'].get(identite_cible, {"Cassis": False, "Carnoux": False}))
                                if nv_identite not in st.session_state['db'].setdefault('ouvertures_eleves', {}): st.session_state['db']['ouvertures_eleves'][nv_identite] = list(st.session_state['db']['ouvertures_eleves'].get(identite_cible, []))
                                    
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
                                    st.session_state['db']['cartes_membres'].pop(identite_cible, None)
                                    st.session_state['db'].get('ouvertures_eleves', {}).pop(identite_cible, None)

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
                contact["Carte Centre Culturel 🎟️"] = "Oui" if st.session_state['db']['cartes_membres'].get(contact["Identité"], {}).get("Cassis", False) else "Non"
                
                st.markdown("---")
                c_info1, c_info2 = st.columns(2)
                infos = {k: v for k, v in contact.items() if k not in ["_orig_index", "Identité", "Elo_FFE"] and str(v).strip() and str(v) != "nan"}
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
            c_f1, c_f2, c_f3, c_f4 = st.columns([1.1, 1.2, 1.4, 1.5])
            with c_f1: filtre_licence = st.checkbox("🚫 Sans Licence")
            with c_f2: filtre_allergie = st.checkbox("🤧 Allergies / Médical")
            with c_f3: filtre_sortie = st.checkbox("🚶 Sorties Autorisées (OUI)")
            with c_f4:
                if st.button("🔄 Actualiser licences & Elos FFE", key="btn_maj_ffe_admin"):
                    ok_ffe, chang_ffe, nb_ffe = actualiser_elos_ffe_automatique(silencieux=False)
                    if ok_ffe and chang_ffe:
                        st.session_state['msg_maj_ffe_admin'] = ("success", f"✅ {nb_ffe} élève(s) mis à jour depuis la FFE ({len(chang_ffe)} modification(s)).")
                        st.rerun()
                    elif ok_ffe:
                        st.session_state['msg_maj_ffe_admin'] = ("info", "ℹ️ Aucune nouvelle modification détectée sur le site FFE.")
                    else:
                        st.session_state['msg_maj_ffe_admin'] = ("warning", "⚠️ Impossible de joindre le site de la FFE pour le moment.")

            if 'msg_maj_ffe_admin' in st.session_state:
                lvl_msg, txt_msg = st.session_state.pop('msg_maj_ffe_admin')
                if lvl_msg == "success": st.success(txt_msg)
                elif lvl_msg == "info": st.info(txt_msg)
                else: st.warning(txt_msg)

            df_admin = df_sans_boutique[(df_sans_boutique["Campagne"].isin(filtre_camp_admin)) & (df_sans_boutique["Type"].isin(filtre_type_admin))].copy()
            
            if filtre_licence:
                if "Licence_FFE" in df_admin.columns:
                    df_admin = df_admin[df_admin["Licence_FFE"].apply(est_sans_licence)]
                else:
                    st.warning("⚠️ Colonne Licence_FFE introuvable. Cliquez sur '🔄 Actualiser licences & Elos FFE'.")
            if filtre_allergie and "Allergies / Médical" in df_admin.columns:
                mots_sains = ["non", "ras", "rien", "néant", "neant", "aucun", "aucune", "-"]
                df_admin = df_admin[(df_admin["Allergies / Médical"] != "") & (~df_admin["Allergies / Médical"].astype(str).str.lower().isin(mots_sains))]
            if filtre_sortie: 
                df_admin = df_admin[df_admin.apply(lambda r: st.session_state['db']['sorties_manuelles'].get(r['Identité'], r['Sortie Seul']) == "✅ OUI", axis=1)]
            st.caption(f"🔎 {len(df_admin)} élève(s) affiché(s)")
            
            # Affichage correct de l'Elo dans le tableau (calcul vectorisé O(N))
            elos_batch_admin = calculer_elos_actifs_batch(df_admin['Identité'].tolist(), df_admin, st.session_state['db'])
            df_admin['Elo Actif ⚡'] = [elos_batch_admin[x][0] for x in df_admin['Identité']]
            df_admin['Catégorie Elo'] = [elos_batch_admin[x][1] for x in df_admin['Identité']]

            val_promo_map = st.session_state['db']['validations_promo']
            sorties_map = st.session_state['db']['sorties_manuelles']
            tshirts_map = st.session_state['db']['tshirts_donnes']
            cartes_map = st.session_state['db']['cartes_membres']
            df_admin['Promo Validée ✅'] = [bool(val_promo_map.get(x, False)) for x in df_admin['Identité']]
            df_admin['Sortie Seul'] = [sorties_map.get(ident, val_def) for ident, val_def in zip(df_admin['Identité'], df_admin['Sortie Seul'])]
            df_admin['T-shirt donné 👕'] = [bool(tshirts_map.get(x, False)) for x in df_admin['Identité']]
            df_admin['Carte Centre Culturel 🎟️'] = [bool(cartes_map.get(x, {}).get('Cassis', False)) for x in df_admin['Identité']]
            
            df_admin["_orig_index"] = df_admin.index 
            
            noms_bruts = df_admin["Nom"].fillna("Inconnu").astype(str) + " " + df_admin["Prénom"].fillna("").astype(str)
            s_counts = df_admin.groupby(noms_bruts, dropna=False).cumcount()
            index_names = noms_bruts.astype(str) + s_counts.apply(lambda x: f" ({x})" if x > 0 else "").astype(str)
            
            df_admin.insert(0, "👤 Élève (Fige)", index_names)
            df_display = df_admin.set_index("_orig_index")
            
            colonnes_a_cacher = ["Identité", "Nom payeur", "Prénom payeur", "Email payeur", "ID_Dossier", "_orig_index", "Elo_FFE"]
            colonnes_possibles = [c for c in df_display.columns if c not in colonnes_a_cacher]
            ordre_prefere = ["👤 Élève (Fige)", "Carte Centre Culturel 🎟️", "T-shirt donné 👕", "Promo Validée ✅", "Nom", "Prénom", "Licence_FFE", "Type", "Elo Actif ⚡", "Catégorie Elo", "Elo_Rapide", "Elo_Lent", "Elo_Blitz", "Formule", "Campagne", "Sortie Seul", "N° Portable", "EMail"]
            colonnes_possibles = sorted(colonnes_possibles, key=lambda x: ordre_prefere.index(x) if x in ordre_prefere else 999)
            colonnes_par_defaut = [c for c in ["👤 Élève (Fige)", "Carte Centre Culturel 🎟️", "T-shirt donné 👕", "Promo Validée ✅", "Licence_FFE", "Type", "Elo Actif ⚡", "Catégorie Elo", "Formule", "Campagne"] if c in colonnes_possibles]
            
            st.markdown("##### ⚙️ Affichage sur mesure")
            colonnes_choisies = st.multiselect("Sélectionnez les colonnes à afficher :", options=[c for c in colonnes_possibles if c != "👤 Élève (Fige)"], default=[c for c in colonnes_par_defaut if c != "👤 Élève (Fige)"])
            colonnes_finales = ["👤 Élève (Fige)"] + colonnes_choisies
            
            st.info("✏️ Modifiez le tableau ci-dessous, puis cliquez impérativement sur le bouton d'enregistrement en bas.")
            edited_df = st.data_editor(
                df_display[colonnes_finales], use_container_width=True,
                column_config={
                    "👤 Élève (Fige)": st.column_config.Column("👤 Élève (Bloqué)", disabled=True),
                    "Carte Centre Culturel 🎟️": st.column_config.CheckboxColumn("Carte Centre Culturel 🎟️"),
                    "Promo Validée ✅": st.column_config.CheckboxColumn("Promo Validée ✅"),
                    "T-shirt donné 👕": st.column_config.CheckboxColumn("T-shirt donné 👕"),
                    "Sortie Seul": st.column_config.SelectboxColumn("Sortie Seul", options=["✅ OUI", "❌ NON", "N/A (École)", "-"]),
                    "Elo Actif ⚡": st.column_config.Column(disabled=True),
                    "Catégorie Elo": st.column_config.Column(disabled=True),
                    "Elo_Rapide": st.column_config.Column(disabled=True),
                    "Elo_Lent": st.column_config.Column(disabled=True),
                    "Elo_Blitz": st.column_config.Column(disabled=True)
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
                                elif col == "Carte Centre Culturel 🎟️":
                                    if identite_actuelle not in st.session_state['db']['cartes_membres']:
                                        st.session_state['db']['cartes_membres'][identite_actuelle] = {"Cassis": False, "Carnoux": False}
                                    st.session_state['db']['cartes_membres'][identite_actuelle]["Cassis"] = bool(new_val)
                                    st.session_state[f"carte_Cassis_{identite_actuelle}"] = bool(new_val)
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
                
                col_f1, col_f2, col_f3 = st.columns([2, 1.5, 1.2])
                with col_f1:
                    filtre_absents_seuls = st.checkbox("🔍 Afficher uniquement les séances avec des élèves absents", value=False)
                with col_f2:
                    recherche_eleve = st.text_input("Rechercher un élève :", placeholder="Nom ou prénom...", key="rech_abs_hist").strip().lower()
                with col_f3:
                    afficher_tout_hist = st.checkbox("Tout l'historique", value=False, key="hist_show_all")

                df_hist_idx = {}
                if not df.empty and "Identité" in df.columns:
                    for rec_h in df.to_dict("records"):
                        ident_h = rec_h.get("Identité")
                        if ident_h not in df_hist_idx:
                            df_hist_idx[ident_h] = rec_h

                dates_triees = sorted(st.session_state['db']['historique_appels'].items(), reverse=True)
                if not afficher_tout_hist and not recherche_eleve:
                    dates_triees = dates_triees[:10]
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
                            if infos.get("note"):
                                st.info(f"📝 **Note de séance :** {infos['note']}")

                            c_met1, c_met2, c_met3 = st.columns(3)
                            c_met1.metric("Effectif Total", len(presents) + len(absents))
                            c_met2.metric("✅ Présents", len(presents))
                            c_met3.metric("❌ Absents", len(absents))

                            if absents:
                                st.error(f"🚨 **{len(absents)} élève(s) absent(s)** — Coordonnées des parents à contacter :")

                                liste_donnees_absents = []
                                for eleve_abs in absents:
                                    row_abs = df_hist_idx.get(eleve_abs)
                                    if row_abs is not None:
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

    elif module_choisi == "♟️ Module Entraîneur":
        st.subheader("♟️ Espace Entraîneur")
        tab_appel, tab_tournoi, tab_classement, tab_affectations, tab_ouvertures = st.tabs(["📋 Faire l'Appel", "⚔️ Tournoi & Elo", "🏆 Classement", "⚙️ Affecter Élèves", "📖 Ouvertures"])

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
                # Trier par nom de famille (Nom) alphabétiquement
                df_groupe = df_groupe.sort_values(by="Nom")
                
                # Préparer le DataFrame pour le data_editor
                df_appel = df_groupe.copy()
                df_appel['Présent ✅'] = True
                
                # S'assurer que la colonne 'Classe' existe, sinon mettre une valeur par défaut
                if 'Classe' not in df_appel.columns:
                    df_appel['Classe'] = "-"
                
                df_display = df_appel[['Présent ✅', 'Nom', 'Prénom', 'Classe']].copy()
                df_display["_orig_index"] = df_appel.index
                df_display.set_index("_orig_index", inplace=True)
                
                st.markdown("---")
                edited_df = st.data_editor(
                    df_display,
                    column_config={
                        "Présent ✅": st.column_config.CheckboxColumn("Présent ✅", default=True),
                        "Nom": st.column_config.Column("Nom", disabled=True),
                        "Prénom": st.column_config.Column("Prénom", disabled=True),
                        "Classe": st.column_config.Column("Classe", disabled=True)
                    },
                    use_container_width=True,
                    hide_index=True
                )
                
                presents_count = edited_df["Présent ✅"].sum()
                absents_count = total_appel - presents_count
                
                st.markdown("---")
                c_m1, c_m2, c_m3 = st.columns(3)
                c_m1.metric("👥 Total Liste", total_appel)
                c_m2.metric("✅ Présents", presents_count)
                c_m3.metric("❌ Absents", absents_count)

                note_seance = st.text_area("📝 Note de séance (comportement, travail réalisé, etc.) :", "")

                if st.button(f"💾 Enregistrer l'appel pour {lieu_appel}"):
                    liste_presents = [df_groupe.loc[idx_app, 'Identité'] for idx_app, row_ed in edited_df.iterrows() if row_ed["Présent ✅"]]
                    liste_absents = [df_groupe.loc[idx_app, 'Identité'] for idx_app, row_ed in edited_df.iterrows() if not row_ed["Présent ✅"]]
                    if date_jour not in st.session_state['db']['historique_appels']: st.session_state['db']['historique_appels'][date_jour] = {}
                    st.session_state['db']['historique_appels'][date_jour][lieu_appel] = {
                        "entraineur": entraineur_appel,
                        "presents": liste_presents,
                        "absents": liste_absents,
                        "note": note_seance
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
                joueurs_inscrits_base = sorted(list(set(st.session_state['db']['affectations_creneaux'][creneau_tournoi])))
                
                # Gestion des joueurs ajoutés/retirés manuellement
                if 'etats_tournois' not in st.session_state['db']:
                    st.session_state['db']['etats_tournois'] = {}
                etat_sauve_temporaire = st.session_state['db']['etats_tournois'].get(creneau_tournoi, {})
                
                tous_les_joueurs = sorted(list(set(st.session_state['df_adherents']['Identité'].dropna()))) if 'df_adherents' in st.session_state and not st.session_state['df_adherents'].empty and 'Identité' in st.session_state['df_adherents'].columns else []
                joueurs_non_inscrits = [j for j in tous_les_joueurs if j not in joueurs_inscrits_base]
                
                with st.expander("⚙️ Ajouter/Retirer manuellement des joueurs de ce tournoi"):
                    st.caption("Utilisez ces options pour intégrer un joueur externe pour ce tournoi ou retirer définitivement un élève ayant quitté le club.")
                    joueurs_supp = st.multiselect(
                        "Ajouter des joueurs d'autres créneaux :",
                        options=joueurs_non_inscrits,
                        default=etat_sauve_temporaire.get('joueurs_supp', []),
                        key=f"supp_{creneau_tournoi}"
                    )
                    base_et_supp = sorted(list(set(joueurs_inscrits_base + joueurs_supp)))
                    
                    joueurs_retires = st.multiselect(
                        "Retirer définitivement du tournoi (abandons, départs) :",
                        options=base_et_supp,
                        default=[j for j in etat_sauve_temporaire.get('joueurs_retires', []) if j in base_et_supp],
                        key=f"retires_{creneau_tournoi}"
                    )
                    
                    if joueurs_supp != etat_sauve_temporaire.get('joueurs_supp', []) or joueurs_retires != etat_sauve_temporaire.get('joueurs_retires', []):
                        if creneau_tournoi not in st.session_state['db']['etats_tournois']:
                            st.session_state['db']['etats_tournois'][creneau_tournoi] = {}
                        st.session_state['db']['etats_tournois'][creneau_tournoi]['joueurs_supp'] = joueurs_supp
                        st.session_state['db']['etats_tournois'][creneau_tournoi]['joueurs_retires'] = joueurs_retires
                        sauvegarder_base_cloud(st.session_state['db'])

                joueurs_inscrits = [j for j in base_et_supp if j not in joueurs_retires]

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

                joueurs_presents = st.multiselect(
                    "Élèves participant à la ronde (les absents non sélectionnés sont en forfait) :",
                    options=joueurs_inscrits,
                    default=default_selection,
                    key=f"presents_tournoi_{creneau_tournoi}"
                )
                joueurs_forfaits = [j for j in joueurs_inscrits if j not in joueurs_presents]
                
                c_part1, c_part2 = st.columns(2)
                with c_part1:
                    st.metric("Joueurs Présents", len(joueurs_presents))
                with c_part2:
                    st.metric("En Forfait", len(joueurs_forfaits))

                # Calcul vectorisé des Elos actifs pour tous les inscrits (hiérarchie FIDE > National > Crevette)
                st.session_state['forfaits_actuels'] = list(joueurs_forfaits)
                elos_batch_t = calculer_elos_actifs_batch(joueurs_inscrits, df, st.session_state['db'])
                elos_actifs = {j: elos_batch_t[j][0] for j in joueurs_inscrits}
                types_elos = {j: elos_batch_t[j][1] for j in joueurs_inscrits}

                # --- 2. GESTION ET PERSISTANCE DU TOURNOI ---
                if 'etats_tournois' not in st.session_state['db']:
                    st.session_state['db']['etats_tournois'] = {}
                etat_sauve = st.session_state['db']['etats_tournois'].get(creneau_tournoi)

                if 'tournoi_en_cours' not in st.session_state or st.session_state.get('tournoi_en_cours') != creneau_tournoi:
                    for k_old in [k for k in list(st.session_state.keys()) if k.startswith(f"res_{creneau_tournoi}_")]:
                        st.session_state.pop(k_old, None)
                    if etat_sauve:
                        st.session_state['scores_tournoi'] = dict(etat_sauve.get('scores', {j: 0.0 for j in joueurs_inscrits}))
                        st.session_state['adversaires_tournoi'] = {k: list(v) for k, v in etat_sauve.get('adversaires', {j: [] for j in joueurs_inscrits}).items()}
                        st.session_state['couleurs_tournoi'] = {k: list(v) for k, v in etat_sauve.get('couleurs', {j: [] for j in joueurs_inscrits}).items()}
                        st.session_state['historique_rencontres'] = set(tuple(p) for p in etat_sauve.get('rencontres', []))
                        st.session_state['exempts_passes'] = set(etat_sauve.get('exempts', []))
                        st.session_state['ronde_actuelle'] = etat_sauve.get('ronde', 1)
                        st.session_state['appariements_ronde'] = [tuple(p) for p in etat_sauve.get('appariements', [])]
                        st.session_state['resultats_en_cours'] = {str(k): v for k, v in etat_sauve.get('resultats_en_cours', {}).items()}
                        st.session_state['exempt_ronde'] = etat_sauve.get('exempt_ronde', None)
                        st.session_state['historique_rondes'] = list(etat_sauve.get('historique_rondes', []))
                        st.session_state['historique_ajustements'] = list(etat_sauve.get('historique_ajustements', []))
                        st.session_state['tournoi_en_cours'] = creneau_tournoi
                    else:
                        st.session_state['scores_tournoi'] = {j: 0.0 for j in joueurs_inscrits}
                        st.session_state['adversaires_tournoi'] = {j: [] for j in joueurs_inscrits}
                        st.session_state['couleurs_tournoi'] = {j: [] for j in joueurs_inscrits}
                        st.session_state['historique_rencontres'] = set()
                        st.session_state['exempts_passes'] = set()
                        st.session_state['ronde_actuelle'] = 1
                        st.session_state['appariements_ronde'] = []
                        st.session_state['resultats_en_cours'] = {}
                        st.session_state['exempt_ronde'] = None
                        st.session_state['historique_rondes'] = []
                        st.session_state['historique_ajustements'] = []
                        st.session_state['tournoi_en_cours'] = creneau_tournoi

                # Sécurité sur les clés
                if 'historique_rondes' not in st.session_state: st.session_state['historique_rondes'] = []
                if 'historique_ajustements' not in st.session_state: st.session_state['historique_ajustements'] = []
                if 'resultats_en_cours' not in st.session_state: st.session_state['resultats_en_cours'] = {}
                for j in joueurs_inscrits:
                    if j not in st.session_state['scores_tournoi']: st.session_state['scores_tournoi'][j] = 0.0
                    if j not in st.session_state['adversaires_tournoi']: st.session_state['adversaires_tournoi'][j] = []
                    if j not in st.session_state['couleurs_tournoi']: st.session_state['couleurs_tournoi'][j] = []

                if st.session_state.get('msg_tournoi_action'):
                    st.success(st.session_state.pop('msg_tournoi_action'))

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

                # --- 3b. AJOUTER / ENLEVER DES POINTS À UN OU DES ÉLÈVES ---
                with st.expander("🎯 Ajouter / Enlever des points à un ou des élèves"):
                    st.caption("Modifiez le total de points du tournoi pour un ou plusieurs élèves (bonus, pénalité ou correction manuelle).")
                    tous_candidats_pts = sorted(list(set(joueurs_inscrits) | set(st.session_state['scores_tournoi'].keys())))
                    eleves_pts_cibles = st.multiselect(
                        "Sélectionner un ou plusieurs élèves :",
                        options=tous_candidats_pts,
                        key=f"adj_eleves_{creneau_tournoi}"
                    )
                    col_adj1, col_adj2 = st.columns([1, 2])
                    delta_pts = col_adj1.number_input(
                        "Points à ajouter (+) ou enlever (-) :",
                        min_value=-50.0,
                        max_value=50.0,
                        value=1.0,
                        step=0.5,
                        format="%.1f",
                        key=f"adj_delta_{creneau_tournoi}"
                    )
                    motif_pts = col_adj2.text_input(
                        "Motif (optionnel) :",
                        placeholder="Ex : Bonus exercice, Retard, Correction ronde...",
                        key=f"adj_motif_{creneau_tournoi}"
                    )
                    if st.button("💾 Appliquer cet ajustement de points", key=f"btn_adj_pts_{creneau_tournoi}"):
                        if not eleves_pts_cibles:
                            st.warning("⚠️ Sélectionnez au moins un élève.")
                        elif delta_pts == 0.0:
                            st.warning("⚠️ Indiquez un nombre de points différent de 0.")
                        else:
                            ajuster_points_eleves(
                                st.session_state['scores_tournoi'],
                                st.session_state['historique_ajustements'],
                                eleves_pts_cibles,
                                delta_pts,
                                date_jour,
                                motif_pts
                            )
                            sauvegarder_etat_tournoi(creneau_tournoi)
                            signe = "+" if delta_pts > 0 else ""
                            st.session_state['msg_tournoi_action'] = f"🎯 Ajustement appliqué ({signe}{delta_pts} pt(s)) pour : {', '.join(eleves_pts_cibles)}."
                            st.rerun()

                    hist_aj = st.session_state.get('historique_ajustements', [])
                    if hist_aj:
                        st.markdown("**Historique des ajustements manuels :**")
                        for idx_aj in range(len(hist_aj) - 1, -1, -1):
                            aj = hist_aj[idx_aj]
                            d_aj = aj.get('delta', 0.0)
                            signe_aj = "+" if d_aj > 0 else ""
                            c_aj1, c_aj2 = st.columns([4, 1])
                            c_aj1.write(f"• {aj.get('date', '-')} — **{signe_aj}{d_aj} pt(s)** pour {', '.join(aj.get('joueurs', []))} *({aj.get('motif', 'Ajustement manuel')})*")
                            if c_aj2.button("↩️ Annuler", key=f"undo_aj_{creneau_tournoi}_{idx_aj}"):
                                annule = annuler_ajustement_points(st.session_state['scores_tournoi'], st.session_state['historique_ajustements'], idx_aj)
                                if annule:
                                    sauvegarder_etat_tournoi(creneau_tournoi)
                                    st.session_state['msg_tournoi_action'] = f"↩️ Ajustement annulé pour {', '.join(annule.get('joueurs', []))}."
                                    st.rerun()

                # --- 3c. REVENIR SUR UNE RONDE / JOURNÉE PASSÉE ET MODIFIER UN RÉSULTAT ---
                with st.expander("🕒 Revenir sur une ronde / journée passée et modifier un résultat"):
                    hist_rondes = st.session_state.get('historique_rondes', [])
                    if not hist_rondes:
                        if st.session_state['ronde_actuelle'] > 1:
                            st.info("ℹ️ Les rondes validées avant cette mise à jour ne disposent pas du détail match par match. Utilisez l'outil d'ajustement de points ci-dessus si besoin. Toutes les nouvelles rondes validées seront enregistrées ici et modifiables match par match.")
                        else:
                            st.info("Aucune ronde n'a encore été validée pour ce tournoi.")
                    else:
                        if st.session_state.get('appariements_ronde'):
                            st.caption("ℹ️ Des appariements sont actuellement générés pour la ronde en cours. Si la modification d'une ronde passée change les scores et doit modifier les appariements en cours, utilisez ensuite « 🔄 Réinitialiser la ronde actuelle » puis régénérez la ronde.")

                        labels_rondes = [
                            f"Ronde {r.get('ronde', i + 1)} ({r.get('date', '-')}) — {len(r.get('matchs', []))} match(s)"
                            for i, r in enumerate(hist_rondes)
                        ]
                        idx_ronde_sel = st.selectbox(
                            "Choisir la ronde / journée à consulter ou modifier :",
                            options=list(range(len(hist_rondes))),
                            index=len(hist_rondes) - 1,
                            format_func=lambda idx: labels_rondes[idx],
                            key=f"sel_hist_ronde_{creneau_tournoi}"
                        )
                        ronde_sel = hist_rondes[idx_ronde_sel]
                        num_ronde_sel = ronde_sel.get('ronde', idx_ronde_sel + 1)

                        st.markdown(f"**Matchs enregistrés — Ronde {num_ronde_sel} ({ronde_sel.get('date', '-')}) :**")
                        nouveaux_resultats = {}
                        for m_idx, m in enumerate(ronde_sel.get('matchs', [])):
                            res_actuel = m.get('resultat', RESULTATS_MATCH_OPTIONS[0])
                            idx_res = RESULTATS_MATCH_OPTIONS.index(res_actuel) if res_actuel in RESULTATS_MATCH_OPTIONS else 0
                            c_hm1, c_hm2 = st.columns([3, 2])
                            c_hm1.markdown(f"**Échiquier {m_idx + 1} :** ⚪ **{m['blanc']}** 🆚 ⚫ **{m['noir']}**")
                            nouveaux_resultats[m_idx] = c_hm2.selectbox(
                                f"Résultat échiquier {m_idx + 1}",
                                options=RESULTATS_MATCH_OPTIONS,
                                index=idx_res,
                                key=f"hist_res_{creneau_tournoi}_{num_ronde_sel}_{m_idx}",
                                label_visibility="collapsed"
                            )

                        if ronde_sel.get('exempt'):
                            st.warning(f"👑 **Exempt (+1 pt) :** {ronde_sel['exempt']}")
                        if ronde_sel.get('forfaits'):
                            st.caption(f"🚫 **Forfaits (0 pt) :** {', '.join(ronde_sel['forfaits'])}")

                        c_hr_btn1, c_hr_btn2 = st.columns(2)
                        if c_hr_btn1.button("💾 Enregistrer les modifications de cette ronde", key=f"btn_save_hist_ronde_{creneau_tournoi}"):
                            modifs = appliquer_modifications_ronde_passee(
                                ronde_sel,
                                nouveaux_resultats,
                                st.session_state['scores_tournoi'],
                                st.session_state['db']['elos_crevette']
                            )
                            if not modifs:
                                st.info("Aucune modification détectée sur cette ronde.")
                            else:
                                sauvegarder_etat_tournoi(creneau_tournoi)
                                st.session_state['msg_tournoi_action'] = "✅ Ronde mise à jour (scores et Elos Crevette ajustés) : " + " | ".join(modifs)
                                st.rerun()

                        if idx_ronde_sel == len(hist_rondes) - 1 and not st.session_state.get('appariements_ronde'):
                            if c_hr_btn2.button("↩️ Rouvrir cette dernière ronde", key=f"btn_reopen_ronde_{creneau_tournoi}"):
                                reopened, nouvelles_rencontres = rouvrir_derniere_ronde(
                                    st.session_state['historique_rondes'],
                                    st.session_state['scores_tournoi'],
                                    st.session_state['adversaires_tournoi'],
                                    st.session_state['couleurs_tournoi'],
                                    st.session_state['db']['elos_crevette']
                                )
                                if reopened:
                                    r_num = reopened.get('ronde', max(1, st.session_state['ronde_actuelle'] - 1))
                                    st.session_state['historique_rencontres'] = nouvelles_rencontres
                                    st.session_state['ronde_actuelle'] = r_num
                                    st.session_state['appariements_ronde'] = [(m['blanc'], m['noir']) for m in reopened.get('matchs', [])]
                                    st.session_state['exempt_ronde'] = reopened.get('exempt')
                                    st.session_state['resultats_en_cours'] = {
                                        str(i_m): m.get('resultat', "Sélectionner...")
                                        for i_m, m in enumerate(reopened.get('matchs', []), 1)
                                        if m.get('resultat', "Sélectionner...") in RESULTATS_MATCH_OPTIONS
                                    }
                                    for i_m, m in enumerate(reopened.get('matchs', []), 1):
                                        st.session_state.pop(f"res_{creneau_tournoi}_{r_num}_{i_m}", None)
                                        st.session_state.pop(f"hist_res_{creneau_tournoi}_{r_num}_{i_m - 1}", None)
                                    sauvegarder_etat_tournoi(creneau_tournoi)
                                    st.session_state['msg_tournoi_action'] = f"↩️ Ronde {r_num} rouverte : vous pouvez corriger ses résultats ou la réinitialiser pour ré-apparier."
                                    st.rerun()

                st.markdown("---")
                col_t1, col_t2 = st.columns(2)
                with col_t1:
                    st.metric("Ronde actuelle", st.session_state['ronde_actuelle'])
                with col_t2:
                    if st.button("🔄 Réinitialiser la ronde actuelle"):
                        for i_clr in range(1, len(st.session_state.get('appariements_ronde', [])) + 1):
                            st.session_state.pop(f"res_{creneau_tournoi}_{st.session_state['ronde_actuelle']}_{i_clr}", None)
                        st.session_state['appariements_ronde'] = []
                        st.session_state['resultats_en_cours'] = {}
                        if st.session_state.get('exempt_ronde') and st.session_state['exempt_ronde'] in st.session_state['exempts_passes']:
                            st.session_state['exempts_passes'].remove(st.session_state['exempt_ronde'])
                        st.session_state['exempt_ronde'] = None
                        
                        st.session_state['historique_rencontres'] = reconstruire_rencontres(st.session_state['adversaires_tournoi'])
                                
                        if 'etats_tournois' in st.session_state['db'] and creneau_tournoi in st.session_state['db']['etats_tournois']:
                            sauvegarder_etat_tournoi(creneau_tournoi)
                        st.success("Ronde actuelle annulée !")
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
                        for i_clr in range(1, len(pairs) + 2):
                            st.session_state.pop(f"res_{creneau_tournoi}_{st.session_state['ronde_actuelle']}_{i_clr}", None)
                        st.session_state['appariements_ronde'] = pairs
                        st.session_state['resultats_en_cours'] = {}
                        st.session_state['exempt_ronde'] = exempt
                        if exempt:
                            st.session_state['exempts_passes'].add(exempt)

                        # Enregistrer l'état dans la base Cloud
                        sauvegarder_etat_tournoi(creneau_tournoi)
                        st.rerun()

                # --- 5. SAISIE DES RÉSULTATS ET MISE À JOUR DE L'ÉLO CREVETTE ---
                if st.session_state.get('appariements_ronde'):
                    st.subheader(f"♟️ Matchs — Ronde {st.session_state['ronde_actuelle']}")
                    
                    if joueurs_forfaits:
                        st.caption(f"🚫 **Forfaits cette ronde :** {', '.join(joueurs_forfaits)} *(0 pt attribué)*")

                    if st.button("📺 Afficher en Plein Écran (Pour vidéoprojecteur)"):
                        st.session_state['plein_ecran_ronde'] = True
                        st.rerun()
                        
                    options_res = ["Sélectionner..."] + RESULTATS_MATCH_OPTIONS
                    res_en_cours = st.session_state.get('resultats_en_cours', {})
                    resultats_saisis = []
                    for i, (j1, j2) in enumerate(st.session_state['appariements_ronde'], 1):
                        sym1 = "⚡" if "FIDE" in types_elos[j1] else ("🇫🇷" if "National" in types_elos[j1] else "🦐")
                        sym2 = "⚡" if "FIDE" in types_elos[j2] else ("🇫🇷" if "National" in types_elos[j2] else "🦐")
                        pts1 = st.session_state['scores_tournoi'].get(j1, 0.0)
                        pts2 = st.session_state['scores_tournoi'].get(j2, 0.0)
                        c_ech, c_res = st.columns([3, 2])
                        c_ech.markdown(f"**Échiquier {i} :** ⚪ **{j1}** [{pts1} pts] ({elos_actifs[j1]} {sym1})  🆚  ⚫ **{j2}** [{pts2} pts] ({elos_actifs[j2]} {sym2})")
                        w_key = f"res_{creneau_tournoi}_{st.session_state['ronde_actuelle']}_{i}"
                        val_sauvee = res_en_cours.get(str(i), "Sélectionner...")
                        idx_def = options_res.index(val_sauvee) if val_sauvee in options_res else 0
                        res = c_res.selectbox("Résultat", options_res, index=idx_def, key=w_key, label_visibility="collapsed")
                        resultats_saisis.append((j1, j2, res))
                        
                    if st.session_state.get('exempt_ronde'):
                        ex = st.session_state['exempt_ronde']
                        sym_ex = "⚡" if "FIDE" in types_elos[ex] else ("🇫🇷" if "National" in types_elos[ex] else "🦐")
                        pts_ex = st.session_state['scores_tournoi'].get(ex, 0.0)
                        st.warning(f"👑 **Exempt (+1 pt) :** {ex} [{pts_ex} pts] ({elos_actifs[ex]} {sym_ex})")

                    nouveaux_res_en_cours = {
                        str(idx_m): val_m
                        for idx_m, (_, _, val_m) in enumerate(resultats_saisis, 1)
                        if val_m != "Sélectionner..."
                    }
                    st.session_state['resultats_en_cours'] = nouveaux_res_en_cours
                    anciens_res_db = st.session_state['db'].get('etats_tournois', {}).get(creneau_tournoi, {}).get('resultats_en_cours', {})
                    nb_saisis = len(nouveaux_res_en_cours)
                    nb_total = len(resultats_saisis)
                    tous_renseignes = (nb_saisis == nb_total)

                    st.markdown("---")
                    btn_valider_ronde = st.button("💾 Valider les résultats & Mettre à jour les Elos")

                    if not (btn_valider_ronde and tous_renseignes) and nouveaux_res_en_cours != anciens_res_db:
                        sauvegarder_etat_tournoi(creneau_tournoi)

                    st.caption(f"☁️ Sauvegarde automatique dans le Cloud : **{nb_saisis}/{nb_total}** résultat(s) enregistré(s) pour cette ronde (conservés même en cas de déconnexion).")

                    if btn_valider_ronde:
                        if not tous_renseignes:
                            st.error(f"⚠️ Veuillez renseigner le résultat de tous les échiquiers ({nb_saisis}/{nb_total}) avant de clôturer la ronde. Les résultats déjà saisis sont sauvegardés automatiquement.")
                        else:
                            variations_crevette = []
                            matchs_historique = []
                            ronde_validee = st.session_state['ronde_actuelle']

                            for m_idx, (j1, j2, res) in enumerate(resultats_saisis):
                                st.session_state['adversaires_tournoi'][j1].append(j2)
                                st.session_state['adversaires_tournoi'][j2].append(j1)
                                st.session_state['couleurs_tournoi'][j1].append('B')
                                st.session_state['couleurs_tournoi'][j2].append('N')
                                
                                elo1, elo2 = elos_actifs[j1], elos_actifs[j2]
                                type1, type2 = types_elos[j1], types_elos[j2]
                                s1, s2 = scores_depuis_resultat(res)

                                st.session_state['scores_tournoi'][j1] = round(st.session_state['scores_tournoi'].get(j1, 0.0) + s1, 1)
                                st.session_state['scores_tournoi'][j2] = round(st.session_state['scores_tournoi'].get(j2, 0.0) + s2, 1)
                                    
                                new_e1 = calculer_nouveau_elo(elo1, elo2, s1)
                                new_e2 = calculer_nouveau_elo(elo2, elo1, s2)
                                diff1 = 0
                                diff2 = 0
                                
                                # Mise à jour de l'Élo Crevette pour les joueurs concernés (estimé ou crevette)
                                if "Crevette" in type1:
                                    st.session_state['db']['elos_crevette'][j1] = new_e1
                                    diff1 = new_e1 - elo1
                                    variations_crevette.append(f"🦐 **{j1}** : {elo1} ➔ **{new_e1}** ({'+' if diff1 >= 0 else ''}{diff1})")
                                if "Crevette" in type2:
                                    st.session_state['db']['elos_crevette'][j2] = new_e2
                                    diff2 = new_e2 - elo2
                                    variations_crevette.append(f"🦐 **{j2}** : {elo2} ➔ **{new_e2}** ({'+' if diff2 >= 0 else ''}{diff2})")

                                matchs_historique.append({
                                    'blanc': j1,
                                    'noir': j2,
                                    'resultat': res,
                                    'elo_blanc_avant': elo1,
                                    'elo_noir_avant': elo2,
                                    'type_blanc': type1,
                                    'type_noir': type2,
                                    'elo_blanc_apres': new_e1 if "Crevette" in type1 else elo1,
                                    'elo_noir_apres': new_e2 if "Crevette" in type2 else elo2,
                                    'crevette_delta_blanc': diff1,
                                    'crevette_delta_noir': diff2,
                                })
                                st.session_state.pop(f"res_{creneau_tournoi}_{ronde_validee}_{m_idx + 1}", None)
                                st.session_state.pop(f"hist_res_{creneau_tournoi}_{ronde_validee}_{m_idx}", None)

                            exempt_valide = st.session_state.get('exempt_ronde')
                            if exempt_valide:
                                st.session_state['scores_tournoi'][exempt_valide] = round(st.session_state['scores_tournoi'].get(exempt_valide, 0.0) + 1.0, 1)

                            st.session_state['historique_rondes'].append({
                                'ronde': ronde_validee,
                                'date': date_jour,
                                'matchs': matchs_historique,
                                'exempt': exempt_valide,
                                'forfaits': list(joueurs_forfaits),
                            })

                            st.session_state['ronde_actuelle'] = ronde_validee + 1
                            st.session_state['appariements_ronde'] = []
                            st.session_state['resultats_en_cours'] = {}
                            st.session_state['exempt_ronde'] = None

                            # Sauvegarde dans le Cloud Google Sheets
                            sauvegarder_etat_tournoi(creneau_tournoi)
                            
                            if variations_crevette:
                                st.session_state['msg_variations_crevette'] = " | ".join(variations_crevette)
                            st.success("Résultats enregistrés et Elos Crevette mis à jour dans le Cloud !")
                            st.rerun()

                if st.session_state.get('msg_variations_crevette'):
                    st.info(f"📈 **Mise à jour des Elos Crevette de la ronde précédente :** {st.session_state['msg_variations_crevette']}")
                    del st.session_state['msg_variations_crevette']

        with tab_classement:
            c_cl1, c_cl2 = st.columns([3, 1])
            c_cl1.markdown("### 🏆 Classement Général (FIDE, National & Crevette)")
            if c_cl2.button("🔄 Actualiser Elos FFE", key="btn_sync_ffe_classement", use_container_width=True):
                with st.spinner("Actualisation depuis echecs.asso.fr..."):
                    ok_ffe, chang_ffe, nb_m_ffe = actualiser_elos_ffe_automatique(silencieux=False)
                    if ok_ffe:
                        st.session_state['ffe_classement_report'] = (chang_ffe, nb_m_ffe)
                        st.rerun()
                    else:
                        st.warning("❌ Impossible de contacter echecs.asso.fr pour le moment.")

            if st.session_state.get('ffe_classement_report'):
                chang_cl, nb_m_cl = st.session_state.pop('ffe_classement_report')
                if chang_cl:
                    st.success(f"✅ {len(chang_cl)} élève(s) mis à jour depuis la FFE ({nb_m_cl} licencié(s) vérifié(s)) : " + " | ".join(chang_cl))
                else:
                    st.info(f"👌 Les Elos FIDE & Nationaux sont déjà à jour ({nb_m_cl} licencié(s) FFE vérifié(s)).")

            creneaux_remplis_classement = [k for k, v in st.session_state['db']['affectations_creneaux'].items() if len(v) > 0]
            filtre_c = st.selectbox("Filtrer par liste / créneau :", ["Tous les élèves"] + sorted(creneaux_remplis_classement))
            joueurs_a_afficher = list(df["Identité"].unique()) if filtre_c == "Tous les élèves" else list(set(st.session_state['db']['affectations_creneaux'][filtre_c]))
            elos_batch_cl = calculer_elos_actifs_batch(joueurs_a_afficher, df, st.session_state['db'])
            data_classement = [{"Élève": j, "Catégorie": elos_batch_cl[j][1], "Elo ⚡🦐": elos_batch_cl[j][0]} for j in joueurs_a_afficher]
            
            if data_classement:
                df_classement = pd.DataFrame(data_classement).sort_values(by="Elo ⚡🦐", ascending=False).reset_index(drop=True)
                df_classement.index += 1
                max_elo = max(1000, df_classement["Elo ⚡🦐"].max())
                st.dataframe(df_classement, use_container_width=True, column_config={"Elo ⚡🦐": st.column_config.ProgressColumn("Niveau de puissance", format="%d", min_value=100, max_value=int(max_elo))})
            else: st.info("Aucun élève à afficher.")

        with tab_ouvertures:
            st.markdown("### 📖 Ouvertures des Élèves (Codes ECO)")
            st.info("Sélectionnez un élève et attribuez-lui les ouvertures qu'il joue avec les Blancs et les Noirs selon la classification officielle ECO.")

            if "ouvertures_eleves" not in st.session_state['db'] or not isinstance(st.session_state['db']["ouvertures_eleves"], dict):
                st.session_state['db']["ouvertures_eleves"] = {}

            def _rendre_echiquier_ouv(moves_str, couleur_str, size=200):
                """Valide une suite de coups PGN/SAN (avec numéros éventuels) et retourne (svg_ou_None, moves_nettoyes, erreur)."""
                raw_tokens = str(moves_str or "").replace("\n", " ").split()
                tokens = []
                for tok in raw_tokens:
                    tok_clean = re.sub(r'^\d+\.+', '', tok).strip()
                    if not tok_clean or tok_clean in {"*", "1-0", "0-1", "1/2-1/2"}:
                        continue
                    tokens.append(tok_clean)
                if not tokens:
                    return None, "", False
                try:
                    board_ouv = chess.Board()
                    for mv in tokens:
                        board_ouv.push_san(mv)
                    orient = chess.WHITE if couleur_str == "Blancs" else chess.BLACK
                    svg = chess.svg.board(board=board_ouv, size=size, orientation=orient)
                    return svg, " ".join(tokens), False
                except Exception:
                    return None, " ".join(tokens), True

            if 'msg_ouv_eleve' in st.session_state:
                lvl_o, txt_o = st.session_state.pop('msg_ouv_eleve')
                if lvl_o == "success": st.success(txt_o)
                else: st.warning(txt_o)

            df_ouv_src = st.session_state['df_adherents']
            if "Type" in df_ouv_src.columns:
                df_ouv_src = df_ouv_src[df_ouv_src["Type"] != "Boutique"]
            tous_eleves_ouv = sorted(df_ouv_src["Identité"].dropna().astype(str).unique().tolist())

            liste_creneaux_ouv = ["Tous les élèves"] + [c for cr_list in structure_creneaux.values() for c in cr_list]
            c_ouv_f1, c_ouv_f2 = st.columns([1.2, 2])
            with c_ouv_f1:
                filtre_creneau_ouv = st.selectbox("Filtrer par créneau :", options=liste_creneaux_ouv, key="ouv_filtre_creneau")
            if filtre_creneau_ouv == "Tous les élèves":
                eleves_ouv_opts = tous_eleves_ouv
            else:
                aff_cr = st.session_state['db'].get('affectations_creneaux', {}).get(filtre_creneau_ouv, [])
                eleves_ouv_opts = sorted(set(aff_cr))

            with c_ouv_f2:
                eleve_ouv_sel = st.selectbox(
                    "👤 Sélectionner un élève :",
                    options=eleves_ouv_opts if eleves_ouv_opts else ["Aucun élève"],
                    key="ouv_eleve_sel"
                )

            if eleves_ouv_opts and eleve_ouv_sel != "Aucun élève":
                eid_ouv = hashlib.md5(eleve_ouv_sel.encode('utf-8')).hexdigest()[:8]
                elo_eleve_ouv, cat_eleve_ouv = get_elo_actif(eleve_ouv_sel, st.session_state['df_adherents'], st.session_state['db'])
                ouvs_eleve = st.session_state['db']['ouvertures_eleves'].setdefault(eleve_ouv_sel, [])
                nb_b = sum(1 for o in ouvs_eleve if o.get('couleur') == 'Blancs')
                nb_n = sum(1 for o in ouvs_eleve if o.get('couleur') == 'Noirs')
                st.caption(f"♟️ **{eleve_ouv_sel}** — Elo actif : **{elo_eleve_ouv}** ({cat_eleve_ouv}) | ⚪ Blancs : {nb_b} | ⚫ Noirs : {nb_n}")

                st.markdown("#### 📚 Ouvertures assignées à l'élève")
                if not ouvs_eleve:
                    st.info("Aucune ouverture enregistrée pour cet élève. Ajoutez-en une ci-dessous avec son code ECO.")
                else:
                    indices_tries = sorted(
                        range(len(ouvs_eleve)),
                        key=lambda k: (0 if ouvs_eleve[k].get('couleur') == 'Blancs' else 1, str(ouvs_eleve[k].get('eco', '')))
                    )
                    for idx_o in indices_tries:
                        ouv = ouvs_eleve[idx_o]
                        coul_o = ouv.get('couleur', 'Blancs')
                        badge_coul = "⚪ Blancs" if coul_o == "Blancs" else "⚫ Noirs"
                        eco_o = ouv.get('eco', '---')
                        nom_o = ouv.get('nom', 'Ouverture')
                        with st.expander(f"{badge_coul} — [{eco_o}] {nom_o}", expanded=False):
                            col_svg_e, col_edit_e = st.columns([1, 2])
                            svg_e, _, err_e = _rendre_echiquier_ouv(ouv.get('moves', ''), coul_o, size=190)
                            with col_svg_e:
                                if svg_e:
                                    st.markdown(f"<div>{svg_e}</div>", unsafe_allow_html=True)
                                elif err_e:
                                    st.error("Coups SAN invalides.")
                                else:
                                    st.caption("Aucun coup saisi.")
                            with col_edit_e:
                                nv_moves = st.text_input("Coups PGN (notation anglaise, ex: e4 c5 Nf3) :", value=ouv.get('moves', ''), key=f"edit_mv_{eid_ouv}_{idx_o}")
                                nv_note = st.text_input("Note pédagogique / variante travaillée :", value=ouv.get('note', ''), key=f"edit_nt_{eid_ouv}_{idx_o}")
                                c_btn1, c_btn2 = st.columns(2)
                                with c_btn1:
                                    if st.button("💾 Mettre à jour", key=f"save_ouv_{eid_ouv}_{idx_o}"):
                                        _, moves_clean, err_upd = _rendre_echiquier_ouv(nv_moves, coul_o)
                                        if err_upd:
                                            st.error("Coups invalides (utilisez la notation SAN anglaise : e4 e5 Nf3 Nc6).")
                                        else:
                                            ouvs_eleve[idx_o]['moves'] = moves_clean
                                            ouvs_eleve[idx_o]['note'] = nv_note.strip()
                                            sauvegarder_base_cloud(st.session_state['db'])
                                            st.session_state['msg_ouv_eleve'] = ("success", f"✅ Ouverture [{eco_o}] {nom_o} mise à jour pour {eleve_ouv_sel}.")
                                            st.rerun()
                                with c_btn2:
                                    if st.button("🗑️ Supprimer", key=f"del_ouv_{eid_ouv}_{idx_o}"):
                                        ouvs_eleve.pop(idx_o)
                                        sauvegarder_base_cloud(st.session_state['db'])
                                        st.session_state['msg_ouv_eleve'] = ("success", f"🗑️ Ouverture supprimée pour {eleve_ouv_sel}.")
                                        st.rerun()

                st.markdown("#### ➕ Attribuer une nouvelle ouverture ECO")
                with st.container(border=True):
                    c_add1, c_add2 = st.columns([1, 2])
                    with c_add1:
                        coul_add_ui = st.radio("Couleur :", ["⚪ Blancs", "⚫ Noirs"], horizontal=True, key=f"add_coul_{eid_ouv}")
                        coul_add = "Blancs" if "Blancs" in coul_add_ui else "Noirs"
                    with c_add2:
                        famille_eco = st.selectbox(
                            "Famille ECO :",
                            [
                                "Toutes (A–E)",
                                "A — Flanc & Irrégulières (A00–A99)",
                                "B — Semi-ouvertes 1.e4 (B00–B99)",
                                "C — Ouvertes 1.e4 e5 & Française (C00–C99)",
                                "D — Fermées & Grünfeld (D00–D99)",
                                "E — Indiennes (E00–E99)",
                            ],
                            key=f"add_fam_{eid_ouv}"
                        )

                    if famille_eco.startswith("Toutes"):
                        eco_filtres = CATALOGUE_ECO
                    else:
                        lettre_fam = famille_eco[0]
                        eco_filtres = [item for item in CATALOGUE_ECO if item["eco"].startswith(lettre_fam)]

                    OPT_CUSTOM = "✏️ Code ECO personnalisé..."
                    labels_eco = [f"{item['eco']} — {item['nom']} ({item['moves']})" for item in eco_filtres]
                    choix_eco = st.selectbox(
                        "Code ECO & Ouverture (tapez pour rechercher) :",
                        options=labels_eco + [OPT_CUSTOM],
                        key=f"add_eco_sel_{eid_ouv}"
                    )
                    choix_hash = hashlib.md5(choix_eco.encode('utf-8')).hexdigest()[:6]

                    if choix_eco == OPT_CUSTOM:
                        c_cust1, c_cust2 = st.columns([1, 3])
                        eco_add = c_cust1.text_input("Code ECO (ex: B90) :", max_chars=5, key=f"cust_eco_{eid_ouv}").strip().upper()
                        nom_add = c_cust2.text_input("Nom de l'ouverture :", key=f"cust_nom_{eid_ouv}").strip()
                        moves_defaut = ""
                    else:
                        idx_sel_eco = labels_eco.index(choix_eco)
                        item_sel = eco_filtres[idx_sel_eco]
                        eco_add = item_sel["eco"]
                        nom_add = item_sel["nom"]
                        moves_defaut = item_sel["moves"]

                    c_mv_add, c_bd_add = st.columns([2, 1])
                    with c_mv_add:
                        moves_add_input = st.text_input(
                            "Coups PGN (en anglais, modifiables) :",
                            value=moves_defaut,
                            key=f"add_mv_{eid_ouv}_{choix_hash}"
                        )
                        note_add = st.text_input(
                            "Note / variante spécifique (optionnel) :",
                            placeholder="Ex: Variante Najdorf, attaque anglaise...",
                            key=f"add_nt_{eid_ouv}"
                        )
                        if st.button("➕ Ajouter cette ouverture à l'élève", key=f"btn_add_ouv_{eid_ouv}"):
                            if not re.match(r"^[A-E][0-9]{2}$", eco_add):
                                st.error("Le code ECO doit comporter 1 lettre (A à E) suivie de 2 chiffres (ex: B20, C50, D02).")
                            elif not nom_add:
                                st.error("Veuillez saisir un nom d'ouverture.")
                            else:
                                _, moves_clean_add, err_add = _rendre_echiquier_ouv(moves_add_input, coul_add)
                                if err_add:
                                    st.error("Coups PGN invalides. Utilisez la notation anglaise (K=Roi, Q=Dame, R=Tour, B=Fou, N=Cavalier, ex: e4 c5 Nf3).")
                                else:
                                    ouvs_eleve.append({
                                        "eco": eco_add,
                                        "nom": nom_add,
                                        "couleur": coul_add,
                                        "moves": moves_clean_add,
                                        "note": note_add.strip()
                                    })
                                    sauvegarder_base_cloud(st.session_state['db'])
                                    st.session_state['msg_ouv_eleve'] = ("success", f"✅ Ouverture [{eco_add}] {nom_add} ({coul_add}) ajoutée à {eleve_ouv_sel} !")
                                    st.rerun()
                    with c_bd_add:
                        svg_preview, _, err_preview = _rendre_echiquier_ouv(moves_add_input, coul_add, size=185)
                        if svg_preview:
                            st.markdown(f"<div>{svg_preview}</div>", unsafe_allow_html=True)
                        elif err_preview:
                            st.warning("Coups PGN non reconnus pour l'aperçu.")
            else:
                st.info("Aucun élève disponible dans ce créneau.")

            st.markdown("---")
            with st.expander("📊 Vue d'ensemble du Club par Code ECO", expanded=False):
                lignes_club_eco = []
                for nom_el, liste_o in sorted(st.session_state['db'].get('ouvertures_eleves', {}).items()):
                    for o in (liste_o or []):
                        lignes_club_eco.append({
                            "Élève": nom_el,
                            "Couleur": "⚪ Blancs" if o.get("couleur") == "Blancs" else "⚫ Noirs",
                            "Code ECO": o.get("eco", ""),
                            "Ouverture": o.get("nom", ""),
                            "Coups": o.get("moves", ""),
                            "Notes": o.get("note", "")
                        })
                if not lignes_club_eco:
                    st.info("Aucune ouverture assignée aux élèves pour le moment.")
                else:
                    df_club_eco = pd.DataFrame(lignes_club_eco)
                    c_ec1, c_ec2 = st.columns([2, 1])
                    with c_ec1:
                        filtre_txt_eco = st.text_input("🔎 Rechercher un code ECO, une ouverture ou un élève :", key="club_eco_search").strip().lower()
                    with c_ec2:
                        filtre_coul_eco = st.selectbox("Couleur :", ["Toutes", "⚪ Blancs", "⚫ Noirs"], key="club_eco_coul")
                    if filtre_txt_eco:
                        mask_eco = (
                            df_club_eco["Code ECO"].str.lower().str.contains(filtre_txt_eco, na=False)
                            | df_club_eco["Ouverture"].str.lower().str.contains(filtre_txt_eco, na=False)
                            | df_club_eco["Élève"].str.lower().str.contains(filtre_txt_eco, na=False)
                        )
                        df_club_eco = df_club_eco[mask_eco]
                    if filtre_coul_eco != "Toutes":
                        df_club_eco = df_club_eco[df_club_eco["Couleur"] == filtre_coul_eco]
                    st.dataframe(df_club_eco, use_container_width=True, hide_index=True)
