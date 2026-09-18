import streamlit as st, requests, pandas as pd, random, unicodedata, json, io, hashlib, re, urllib.parse, gspread
from datetime import datetime
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Académie d'Échecs des Calanques", layout="wide", page_icon="♟️")

st.markdown("""
    <style>
    h1, h2, h3, h4, h5, h6 { color: #005b96 !important; font-weight: bold; }
    .stButton>button { background-color: #FF8C00 !important; color: white !important; border: none; font-weight: bold; width:100%; border-radius: 8px; transition: 0.3s; }
    .stButton>button:hover { background-color: #005b96 !important; color: white !important; }
    button[data-baseweb="tab"][aria-selected="true"] > div { color: #005b96 !important; font-weight: bold; }
    button[data-baseweb="tab"][aria-selected="true"] { border-bottom-color: #FF8C00 !important; }
    .match-card { background-color: #ffffff; padding: 15px; border-radius: 8px; border-left: 5px solid #005b96; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
    </style>
""", unsafe_allow_html=True)

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

def get_gsheets_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scopes)
    return gspread.authorize(creds)

def initialiser_memoire_vierge():
    return {"elos_crevette": {}, "historique_appels": {}, "eleves_essai": [], "affectations_creneaux": {}, "cartes_membres": {}, "validations_promo": {}, "sorties_manuelles": {}, "eleves_deja_affectes": [], "identites_helloasso_connues": [], "dossiers_supprimes": [], "tshirts_donnes": {}, "boutique_donnees": {}, "equipes_interclubs": {}, "ffe_joueurs": []}

def charger_base_cloud():
    try:
        sh = get_gsheets_client().open("Base_Calanques_DB")
        try: ws = sh.worksheet("DB_JSON")
        except: ws = sh.add_worksheet(title="DB_JSON", rows="1000", cols="50")
        vals = ws.col_values(1)
        if vals: return json.loads("".join(vals))
        return initialiser_memoire_vierge()
    except Exception as e:
        st.error(f"Erreur DB Cloud: {e}")
        return None 

def sauvegarder_base_cloud(db):
    try:
        sh = get_gsheets_client().open("Base_Calanques_DB")
        try: ws = sh.worksheet("DB_JSON")
        except: ws = sh.add_worksheet(title="DB_JSON", rows="1000", cols="50")
        json_str = json.dumps(db, ensure_ascii=False)
        chunks = [[json_str[i:i+40000]] for i in range(0, len(json_str), 40000)]
        ws.clear()
        try: ws.update(values=chunks, range_name="A1")
        except TypeError: ws.update("A1", chunks)
    except: pass

def charger_adherents_cloud():
    try:
        sh = get_gsheets_client().open("Base_Calanques_DB")
        try: ws = sh.worksheet("Adherents")
        except: ws = sh.add_worksheet(title="Adherents", rows="1000", cols="50")
        data = ws.get_all_records()
        if data: return pd.DataFrame(data)
        return pd.DataFrame()
    except: return None

def sauvegarder_adherents_cloud(df):
    try:
        if df is None or df.empty: return
        sh = get_gsheets_client().open("Base_Calanques_DB")
        try: ws = sh.worksheet("Adherents")
        except: ws = sh.add_worksheet(title="Adherents", rows="1000", cols="50")
        data = [df.columns.values.tolist()] + df.fillna("").astype(str).values.tolist()
        ws.clear() 
        try: ws.update(values=data, range_name="A1")
        except TypeError: ws.update("A1", data)
    except: pass

def is_different(val1, val2):
    v1 = str(val1).strip().lower() if pd.notna(val1) and str(val1) != "nan" else ""
    v2 = str(val2).strip().lower() if pd.notna(val2) and str(val2) != "nan" else ""
    return v1 != v2

def nettoyer_id_dossier(val):
    val_str = str(val).strip()
    return val_str[:-2] if val_str.endswith('.0') else ("" if val_str.lower() in ['nan', 'none', ''] else val_str)

def format_phone(tel):
    if pd.isna(tel) or str(tel).strip().lower() in ["nan", "none", ""]: return ""
    t = str(tel).strip().replace(" ", "").replace(".", "").replace("-", "")
    if t.startswith("+33"): t = "0" + t[3:]
    elif t.startswith("33") and len(t) == 11: t = "0" + t[2:]
    elif len(t) == 9 and not t.startswith("0"): t = "0" + t
    if len(t) == 10 and t.isdigit(): return f"{t[0:2]}.{t[2:4]}.{t[4:6]}.{t[6:8]}.{t[8:10]}"
    return str(tel)

def normaliser_nom(nom):
    if pd.isna(nom): return ""
    return ''.join(c for c in unicodedata.normalize('NFD', str(nom).lower().strip().replace("*", "")) if unicodedata.category(c) != 'Mn')

def estimer_sexe(prenom):
    if not prenom: return "M"
    p = normaliser_nom(str(prenom).split("-")[0].split()[0])
    femmes = ["manon", "carmen", "iris", "margaux", "margot", "maud", "astrid", "sarah", "esther", "fleur", "marion", "lison", "ninon", "suzon", "lou", "alison", "myriam", "sharon", "eden", "ines", "anais", "agnes", "charlotte", "marianne"]
    return "F" if p in femmes or p.endswith(('a', 'e', 'ine', 'elle', 'ette', 'ie', 'ia')) else "M"

def extract_elo_val(val):
    val_str = str(val).upper().strip()
    if val_str in ["NAN", "NONE", ""]: return 0, False, False
    match = re.search(r'(\d{3,4})', val_str)
    if match:
        score = int(match.group(1))
        is_fide = 'F' in val_str
        is_nat = 'N' in val_str
        if not is_fide and not is_nat: is_nat = True
        return score, is_fide, is_nat
    return 0, False, False

def get_elo_actif(identite, df_adherents, db):
    try:
        row = df_adherents[df_adherents["Identité"] == identite].iloc[0]
        r_val, r_f, r_n = extract_elo_val(row.get("Elo_Rapide", ""))
        l_val, l_f, l_n = extract_elo_val(row.get("Elo_Lent", ""))
        b_val, b_f, b_n = extract_elo_val(row.get("Elo_Blitz", ""))
        
        if r_f and r_val > 0: return r_val, "⚡ Rapide FIDE"
        if l_f and l_val > 0: return l_val, "⚡ Lent FIDE"
        if b_f and b_val > 0: return b_val, "⚡ Blitz FIDE"
        if r_n and r_val > 0: return r_val, "🇫🇷 Rapide National"
        if l_n and l_val > 0: return l_val, "🇫🇷 Lent National"
        if b_n and b_val > 0: return b_val, "🇫🇷 Blitz National"
        
        if r_val > 0: return r_val, "🇫🇷 Rapide National"
        if l_val > 0: return l_val, "🇫🇷 Lent National"
        if b_val > 0: return b_val, "🇫🇷 Blitz National"
        
        old_elo = row.get("Elo_FFE", 0)
        if str(old_elo).lower() not in ["nan", "none", ""]:
            try:
                old_elo = int(float(old_elo))
                if old_elo > 0 and old_elo not in [799, 899, 999, 1099, 1199, 1299, 1399, 1499]: return old_elo, "⚡ FFE (Ancien format)"
            except: pass
    except: pass
    return db['elos_crevette'].get(identite, 400), "🦐 Crevette"

def calculer_nouveau_elo(r_a, r_b, score_a, k=40):
    e_a = 1.0 / (1.0 + 10.0 ** ((r_b - r_a) / 400.0))
    return max(100, round(r_a + k * (score_a - e_a)))

def generer_appariements_suisses(joueurs_scores, elos_dict, historique_rencontres):
    joueurs = sorted(joueurs_scores.keys(), key=lambda j: (joueurs_scores[j], elos_dict.get(j, 400)), reverse=True)
    appariements = []
    exempt = None
    if len(joueurs) % 2 != 0: exempt = joueurs.pop()

    while len(joueurs) >= 2:
        current_score = joueurs_scores[joueurs[0]]
        groupe_idx = 0
        while groupe_idx < len(joueurs) and joueurs_scores[joueurs[groupe_idx]] == current_score: groupe_idx += 1
        if groupe_idx % 2 != 0: groupe_idx += 1 
        if groupe_idx > len(joueurs): groupe_idx = len(joueurs)

        groupe = sorted(joueurs[:groupe_idx], key=lambda j: elos_dict.get(j, 400), reverse=True)
        demi = len(groupe) // 2
        s1, s2 = groupe[:demi], groupe[demi:]
        paired_this_round = set()

        for j1 in s1:
            paired = False
            for j2 in s2:
                if j2 not in paired_this_round:
                    pair = (min(j1, j2), max(j1, j2))
                    if pair not in historique_rencontres:
                        appariements.append((j1, j2)); historique_rencontres.add(pair); paired_this_round.update([j1, j2]); paired = True; break
            if not paired:
                for j2 in s1:
                    if j1 != j2 and j2 not in paired_this_round:
                        pair = (min(j1, j2), max(j1, j2))
                        if pair not in historique_rencontres:
                            appariements.append((j1, j2)); historique_rencontres.add(pair); paired_this_round.update([j1, j2]); paired = True; break
            if not paired:
                for j2 in joueurs:
                    if j1 != j2 and j2 not in paired_this_round:
                        pair = (min(j1, j2), max(j1, j2))
                        appariements.append((j1, j2)); historique_rencontres.add(pair); paired_this_round.update([j1, j2]); paired = True; break
        joueurs = [j for j in joueurs if j not in paired_this_round]
    return appariements, exempt, historique_rencontres

@st.cache_data(ttl=3600)
def fetch_ffe_team_calendar(team_url):
    if not team_url: return []
    if not team_url.startswith("http"): team_url = f"https://www.echecs.asso.fr/{team_url}"
    rondes = []
    html_content = ""
    try:
        html_content = requests.get(team_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5).text
    except:
        try:
            url_proxy = f"https://api.allorigins.win/get?url={urllib.parse.quote(team_url)}"
            html_content = requests.get(url_proxy, timeout=10).json()['contents']
        except: pass

    if html_content:
        try:
            lignes = re.findall(r'<tr[^>]*>(.*?)</tr>', html_content, re.IGNORECASE | re.DOTALL)
            for ligne in lignes:
                cols = [re.sub(r'<[^>]+>', '', c).replace("&nbsp;", " ").strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', ligne, re.IGNORECASE | re.DOTALL)]
                if len(cols) >= 5 and re.search(r'\d{2}/\d{2}/\d{4}', cols[0]):
                    rondes.append({"Ronde": f"Ronde {len(rondes) + 1}", "Date": cols[0], "Equipe domicile": cols[2], "Score": cols[3], "Equipe extérieur": cols[4], "Lieu": cols[5] if len(cols) > 5 else ""})
        except: pass
    return rondes

def analyser_fichier_ffe(fichier):
    try:
        if not isinstance(fichier, str):
            with open("base_ffe_locale_tmp.csv", "wb") as f: f.write(fichier.getbuffer())
            fichier_a_lire = "base_ffe_locale_tmp.csv"
        else: fichier_a_lire = fichier
        try: df_ffe = pd.read_csv(fichier_a_lire, sep=None, engine='python', encoding='utf-8')
        except: df_ffe = pd.read_csv(fichier_a_lire, sep=None, engine='python', encoding='latin1')
            
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
            df_ffe['Annee_FFE'] = df_ffe[col_dna].astype(str).str.extract(r'(\d{4})')[0].fillna("") if col_dna else ""
            df_ffe['Cle_Forte'] = df_ffe['Nom_Norm'] + df_ffe['Prenom_Norm'] + df_ffe['Annee_FFE']
            df_ffe['Cle_Souple'] = df_ffe['Nom_Norm'] + df_ffe['Prenom_Norm']
            df_ffe['Elo_Lent'] = df_ffe[col_lent].astype(str) if col_lent else ""
            df_ffe['Elo_Rapide'] = df_ffe[col_rapide].astype(str) if col_rapide else ""
            df_ffe['Elo_Blitz'] = df_ffe[col_blitz].astype(str) if col_blitz else ""
            df_ffe['Licence_FFE'] = df_ffe[col_licence].astype(str) if col_licence else "Non croisé"
            return df_ffe[['Cle_Forte', 'Cle_Souple', 'Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']]
    except: return pd.DataFrame()
    return pd.DataFrame()

# --- INITIALISATION DE L'ÉCRAN GÉANT (Doit bloquer l'affichage des autres modules) ---
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
        pts1, pts2 = st.session_state['scores_tournoi'].get(j1, 0), st.session_state['scores_tournoi'].get(j2, 0)
        html_table += f"<tr><td>{i}</td><td>{j1} <br><span class='pts'>({pts1} pts)</span></td><td>... - ...</td><td>{j2} <br><span class='pts'>({pts2} pts)</span></td></tr>"
    if st.session_state.get('exempt_ronde'):
        ex = st.session_state['exempt_ronde']
        html_table += f"<tr><td colspan='4' style='background-color:#ffe4b5;'>👑 <b>Exempt :</b> {ex} <span class='pts'>({st.session_state['scores_tournoi'].get(ex, 0)} pts)</span></td></tr>"
    html_table += "</table>"
    st.markdown(html_table, unsafe_allow_html=True)
    st.write("")
    if st.button("🔙 Retour à l'écran de gestion", use_container_width=True):
        st.session_state['plein_ecran_ronde'] = False
        st.rerun()
    st.stop()

if 'db' not in st.session_state:
    with st.spinner("Connexion sécurisée au Cloud Google..."):
        st.session_state['db'] = charger_base_cloud()
        if st.session_state['db'] is None: st.stop()

if 'df_adherents' not in st.session_state:
    with st.spinner("Récupération de la base adhérents..."):
        df_loaded = charger_adherents_cloud()
        if df_loaded is not None and not df_loaded.empty:
            df_loaded['ID_Dossier'] = df_loaded['ID_Dossier'].apply(nettoyer_id_dossier)
            st.session_state['df_adherents'] = df_loaded
        else: st.session_state['df_adherents'] = pd.DataFrame()

default_mem = initialiser_memoire_vierge()
for cle, val_defaut in default_mem.items():
    if cle not in st.session_state['db']: st.session_state['db'][cle] = val_defaut

df = st.session_state['df_adherents']
date_jour = datetime.now().strftime("%d/%m/%Y")
structure_creneaux = {
    "Lundi": ["Lundi - Sainte-Trinité (CP)", "Lundi - La Ciotat", "Lundi - Carnoux", "Lundi - Club Cassis"],
    "Mardi": ["Mardi - Sainte-Trinité (CE1)", "Mardi - Saint-Augustin (CP-CE1)", "Mardi - Ceyreste", "Mardi - Marseille"],
    "Mercredi": ["Mercredi - Ceyreste", "Mercredi - Cassis"],
    "Jeudi": ["Jeudi - Sainte-Trinité (Collège)", "Jeudi - Don Bosco (École)", "Jeudi - Don Bosco (Collège)", "Jeudi - Cassis", "Jeudi - La Ciotat"],
    "Vendredi": ["Vendredi - Saint-Augustin (CE2-CM2)", "Vendredi - Sainte-Trinité (CE2-CM2)", "Vendredi - Cassis"]
}

# --- BARRE LATÉRALE ---
st.sidebar.header("🔑 Espace de Travail")
module_choisi = st.sidebar.radio("", ["🛠️ Module Administration", "♟️ Module Entraîneur", "🛒 Module Boutique", "🏆 Module Interclubs"])

st.sidebar.markdown("---")
st.sidebar.header("☁️ CLOUD & TEMPS RÉEL")
st.sidebar.info("Base de données synchronisée.")
if st.sidebar.button("🔄 Rafraîchir les données"):
    with st.spinner("Récupération..."):
        st.session_state['db'] = charger_base_cloud()
        df_loaded = charger_adherents_cloud()
        if df_loaded is not None and not df_loaded.empty: st.session_state['df_adherents'] = df_loaded
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("1️⃣ Base FFE (Licences)")
fichier_ffe = st.sidebar.file_uploader("Fichier FFE (Glissez CSV ici)", type=['csv', 'xls', 'xlsx'])
if fichier_ffe:
    df_ffe = analyser_fichier_ffe(fichier_ffe)
    if not df_ffe.empty: st.session_state['df_ffe'] = df_ffe; st.sidebar.success("Fichier chargé !")

if 'df_ffe' in st.session_state: 
    if st.sidebar.button("🔄 Recroiser les Licences FFE"):
        if 'df_adherents' in st.session_state and not st.session_state['df_adherents'].empty:
            df_base = st.session_state['df_adherents'].copy()
            df_base['Cle_Forte'] = df_base['Nom'].apply(normaliser_nom) + df_base['Prénom'].apply(normaliser_nom) + df_base['Date de naissance'].astype(str).str.extract(r'(\d{4})')[0].fillna("")
            df_base['Cle_Souple'] = df_base['Nom'].apply(normaliser_nom) + df_base['Prénom'].apply(normaliser_nom)
            df_ffe_strict = st.session_state['df_ffe'].drop_duplicates(subset=['Cle_Forte'])
            df_ffe_souple = st.session_state['df_ffe'].drop_duplicates(subset=['Cle_Souple'])
            df_base = df_base.drop(columns=[c for c in ['Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE', 'Elo_FFE'] if c in df_base.columns], errors='ignore')
            df_base = pd.merge(df_base, df_ffe_strict[['Cle_Forte', 'Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']], on='Cle_Forte', how='left')
            manquants = df_base['Licence_FFE'].isna() | (df_base['Licence_FFE'] == "Non croisé")
            if manquants.any():
                df_base_m = pd.merge(df_base[manquants].drop(columns=['Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE'], errors='ignore'), df_ffe_souple[['Cle_Souple', 'Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']], on='Cle_Souple', how='left')
                for col in ['Elo_Lent', 'Elo_Rapide', 'Elo_Blitz', 'Licence_FFE']: df_base.loc[manquants, col] = df_base_m[col].values
            df_base['Licence_FFE'] = df_base['Licence_FFE'].fillna("Non croisé")
            st.session_state['df_adherents'] = df_base.drop(columns=['Cle_Forte', 'Cle_Souple'])
            sauvegarder_adherents_cloud(st.session_state['df_adherents'])
            st.sidebar.success("✅ Licences et Elos recroisés !")
            st.rerun()

# --- MODULES PRINCIPAUX ---
if df.empty:
    st.info("👋 **Bienvenue !** Importez vos élèves depuis le code complet.")
else:
    if module_choisi == "🛠️ Module Administration":
        st.subheader("🛠️ Espace Administration du Club")
        tab_admin, tab_ecoles, tab_cartes, tab_historique = st.tabs(["📊 Base Adhérents", "🏫 Écoles", "🎟️ Cartes de Centres", "📅 Historique Appels"])
        
        with tab_admin:
            c_tools1, c_tools2 = st.columns(2)
            with c_tools2:
                with st.expander("✏️ Corriger une faute dans un Nom / Prénom"):
                    df_correction = df[df["Type"] != "Boutique"]
                    mapping_renommage = {f"👤 {row['Nom']} {row['Prénom']} | 📋 {row.get('Campagne', '-')}": idx for idx, row in df_correction.iterrows()}
                    eleve_a_renommer = st.selectbox("Élève à corriger :", [""] + sorted(list(mapping_renommage.keys())))
                    if eleve_a_renommer:
                        idx_cible = mapping_renommage[eleve_a_renommer]
                        identite_cible = df.loc[idx_cible, 'Identité']
                        c_r1, c_r2 = st.columns(2)
                        nv_nom = c_r1.text_input("Nouveau Nom", value=df.loc[idx_cible, 'Nom']).strip().upper()
                        nv_prenom = c_r2.text_input("Nouveau Prénom", value=df.loc[idx_cible, 'Prénom']).strip().title()
                        if st.button("✅ Valider"):
                            nv_identite = f"{nv_prenom} {nv_nom}"
                            st.session_state['df_adherents'].loc[idx_cible, ['Nom', 'Prénom', 'Identité']] = [nv_nom, nv_prenom, nv_identite]
                            sauvegarder_adherents_cloud(st.session_state['df_adherents'])
                            st.success("Modifié!")
                            st.rerun()

            st.markdown("---")
            df_admin = df[df["Type"] != "Boutique"].copy()
            df_admin['Elo Actif ⚡'] = df_admin['Identité'].apply(lambda x: get_elo_actif(x, df_admin, st.session_state['db'])[0])
            df_admin['Catégorie Elo'] = df_admin['Identité'].apply(lambda x: get_elo_actif(x, df_admin, st.session_state['db'])[1])
            df_admin['Promo Validée ✅'] = df_admin['Identité'].apply(lambda x: st.session_state['db']['validations_promo'].get(x, False))
            df_admin['Sortie Seul'] = df_admin.apply(lambda r: st.session_state['db']['sorties_manuelles'].get(r['Identité'], r['Sortie Seul']), axis=1)
            df_admin['T-shirt donné 👕'] = df_admin['Identité'].apply(lambda x: st.session_state['db']['tshirts_donnes'].get(x, False))
            
            df_admin.insert(0, "👤 Élève (Fige)", df_admin["Nom"] + " " + df_admin["Prénom"])
            df_display = df_admin.set_index(df_admin.index)
            
            colonnes_par_defaut = ["👤 Élève (Fige)", "T-shirt donné 👕", "Promo Validée ✅", "Licence_FFE", "Type", "Elo Actif ⚡", "Catégorie Elo", "Formule", "Campagne"]
            colonnes_finales = st.multiselect("Sélectionnez les colonnes à afficher :", options=[c for c in df_display.columns if c != "👤 Élève (Fige)"], default=[c for c in colonnes_par_defaut if c != "👤 Élève (Fige)"])
            colonnes_finales.insert(0, "👤 Élève (Fige)")
            
            st.info("✏️ Modifiez le tableau ci-dessous, puis cliquez sur le bouton d'enregistrement.")
            edited_df = st.data_editor(
                df_display[colonnes_finales], use_container_width=True,
                column_config={"👤 Élève (Fige)": st.column_config.Column(disabled=True), "Elo Actif ⚡": st.column_config.Column(disabled=True), "Catégorie Elo": st.column_config.Column(disabled=True)}
            )
            
            if st.button("💾 Enregistrer toutes les modifications du tableau", use_container_width=True):
                with st.spinner("Sauvegarde..."):
                    changement_detecte = False
                    for idx_main in edited_df.index:
                        if idx_main not in df_display.index: continue
                        for col in colonnes_finales:
                            if col not in ["👤 Élève (Fige)", "Elo Actif ⚡", "Catégorie Elo"]:
                                if is_different(df_display.loc[idx_main, col], edited_df.loc[idx_main, col]):
                                    changement_detecte = True
                                    identite_actuelle = df_display.loc[idx_main, "Identité"]
                                    if col == "Promo Validée ✅": st.session_state['db']['validations_promo'][identite_actuelle] = bool(edited_df.loc[idx_main, col])
                                    elif col == "Sortie Seul": st.session_state['db']['sorties_manuelles'][identite_actuelle] = edited_df.loc[idx_main, col]
                                    elif col == "T-shirt donné 👕": st.session_state['db']['tshirts_donnes'][identite_actuelle] = bool(edited_df.loc[idx_main, col])
                                    else: st.session_state['df_adherents'].at[idx_main, col] = edited_df.loc[idx_main, col]
                    if changement_detecte:
                        sauvegarder_base_cloud(st.session_state['db']); sauvegarder_adherents_cloud(st.session_state['df_adherents']); st.success("✅ Modifications enregistrées !"); st.rerun()

        with tab_ecoles:
            st.markdown("### 🏫 Pilotage des Établissements Scolaires")
            ecoles_dispos = [c for c in df["Campagne"].unique() if "club" not in c.lower() and "boutique" not in c.lower()]
            if ecoles_dispos:
                ecole_choisie = st.selectbox("Sélectionnez l'établissement :", ecoles_dispos)
                df_ec = df[df["Campagne"] == ecole_choisie].copy()
                st.metric("🎓 Total Élèves", len(df_ec))
                df_ec['Sortie Seul'] = df_ec.apply(lambda r: st.session_state['db']['sorties_manuelles'].get(r['Identité'], r['Sortie Seul']), axis=1)
                st.dataframe(df_ec[["Identité", "Classe", "Formule", "Sortie Seul", "N° Portable"]], use_container_width=True)

                st.markdown("#### 📱 Exporter pour WhatsApp / Google Contacts")
                st.write("Ce fichier CSV est prêt à être importé dans vos Contacts Google pour créer le groupe WhatsApp de l'école.")
                df_wa = pd.DataFrame()
                df_wa["Name"], df_wa["Given Name"], df_wa["Family Name"] = df_ec["Identité"], df_ec["Prénom"], df_ec["Nom"]
                df_wa["Group Membership"], df_wa["Phone 1 - Type"], df_wa["Phone 1 - Value"] = ecole_choisie, "Mobile", df_ec["N° Portable"]
                df_wa = df_wa[df_wa["Phone 1 - Value"].astype(str).str.strip().replace("nan", "") != ""] 
                csv_wa = df_wa.to_csv(index=False).encode('utf-8-sig')
                st.download_button(f"📥 Télécharger Contacts ({len(df_wa)} numéros valides)", data=csv_wa, file_name=f"WhatsApp_{ecole_choisie}.csv", mime="text/csv")

        with tab_cartes: st.write("Géré via la base globale.")
        with tab_historique: st.write("Géré via la base globale.")

    elif module_choisi == "🛒 Module Boutique":
        st.subheader("🛒 Suivi des Achats Boutique")
        st.write("Cochez la case une fois l'article remis à l'élève.")
        df_boutique = df[df['Campagne'].str.contains("boutique", case=False, na=False)].copy()
        if not df_boutique.empty:
            df_boutique['Article Donné 🎁'] = df_boutique['ID_Dossier'].apply(lambda x: st.session_state['db']['boutique_donnees'].get(nettoyer_id_dossier(x), False))
            edited_boutique = st.data_editor(df_boutique[["Nom", "Prénom", "Formule", "Montant Payé", "Article Donné 🎁"]], use_container_width=True)

    elif module_choisi == "🏆 Module Interclubs":
        st.subheader("🏆 Gestion des Équipes & Interclubs (Mode Manager)")
        
        pdf_ready = True
        try:
            import PyPDF2; from reportlab.pdfgen import canvas; from reportlab.lib.pagesizes import A4
        except: pdf_ready = False
            
        liste_totale_joueurs = sorted(df["Identité"].unique().tolist())
        dict_elo_global = {j: get_elo_actif(j, df, st.session_state['db'])[0] for j in liste_totale_joueurs}

        tab_adultes, tab_jeunes = st.tabs(["🏅 Interclubs Adultes", "👦👧 Interclubs Jeunes"])
        
        def afficher_gestion_equipes(categorie):
            with st.expander(f"⚙️ Paramétrer une équipe {categorie}", expanded=False):
                with st.form(f"form_{categorie}"):
                    c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
                    nv_nom = c1.text_input("Nom de l'équipe (ex: Cassis 1)")
                    nv_div = c2.text_input("Division")
                    nv_nb_ech = c3.number_input("Nb d'échiquiers", min_value=2, max_value=16, value=8 if categorie == "Adultes" else 4)
                    nv_lien = c4.text_input("Lien FFE (ex: Equipe.aspx?EquipeRef=21406)")
                    if st.form_submit_button("Sauvegarder l'équipe") and nv_nom:
                        st.session_state['db']['equipes_interclubs'][nv_nom] = {"Categorie": categorie, "Division": nv_div, "Nb_Echiquiers": int(nv_nb_ech), "Lien": nv_lien, "roster": st.session_state['db']['equipes_interclubs'].get(nv_nom, {}).get("roster", []), "compo": st.session_state['db']['equipes_interclubs'].get(nv_nom, {}).get("compo", {}), "couleurs": st.session_state['db']['equipes_interclubs'].get(nv_nom, {}).get("couleurs", {})}
                        sauvegarder_base_cloud(st.session_state['db']); st.rerun()

            equipes_cat = {k: v for k, v in st.session_state['db'].get('equipes_interclubs', {}).items() if v.get("Categorie") == categorie}
            if not equipes_cat: return st.info("Aucune équipe.")
                
            c_sel1, c_sel2 = st.columns([3, 1])
            equipe_choisie = c_sel1.selectbox(f"🎯 Manager l'équipe :", [""] + sorted(list(equipes_cat.keys())))
            if equipe_choisie and c_sel2.button("🗑️ Supprimer l'équipe"):
                del st.session_state['db']['equipes_interclubs'][equipe_choisie]; sauvegarder_base_cloud(st.session_state['db']); st.rerun()
            
            if equipe_choisie:
                eq_data = equipes_cat[equipe_choisie]
                nb_ech_equipe = eq_data.get("Nb_Echiquiers", 8)
                url_equipe = eq_data.get("Lien", "")
                if url_equipe and not url_equipe.startswith("http"): url_equipe = f"https://www.echecs.asso.fr/{url_equipe}"
                st.markdown(f"### 🛡️ {equipe_choisie} — {eq_data.get('Division', '')}")

                # SCRAPING FFE (Proxy intégré)
                df_classement, df_calendrier = pd.DataFrame(), pd.DataFrame()
                if url_equipe:
                    with st.spinner("Recherche du calendrier FFE en direct..."):
                        try:
                            r_html = requests.get(f"https://api.allorigins.win/get?url={urllib.parse.quote(url_equipe)}", timeout=10).json()['contents']
                            dfs = pd.read_html(io.StringIO(r_html))
                            for t in dfs:
                                cols = [str(c).lower() for c in t.columns]
                                if any('pl' in c for c in cols) and any('pts' in c for c in cols): df_classement = t
                                if any('date' in c for c in cols) and any('score' in c for c in cols): df_calendrier = t
                        except: pass

                if not df_classement.empty: st.expander("🏆 Classement FFE").dataframe(df_classement, hide_index=True)
                if not df_calendrier.empty: st.expander("📅 Calendrier FFE").dataframe(df_calendrier, hide_index=True)

                joueurs_roster = eq_data.get("roster", [])
                nouveau_roster = st.multiselect("👥 1. Bassin de joueurs :", options=liste_totale_joueurs, default=[j for j in joueurs_roster if j in liste_totale_joueurs])
                if st.button("💾 Figer le Bassin"):
                    st.session_state['db']['equipes_interclubs'][equipe_choisie]["roster"] = nouveau_roster; sauvegarder_base_cloud(st.session_state['db']); st.rerun()

                if nouveau_roster:
                    st.markdown("#### ⚔️ 2. Établir la Composition")
                    rondes_dispos = [f"Ronde {i}" for i in range(1, 12)]
                    c_r1, c_r2 = st.columns([1, 2])
                    ronde_choisie = c_r1.selectbox("Sélectionnez la ronde :", rondes_dispos)
                    couleur_ech1 = c_r2.radio("Couleur au 1er échiquier :", ["⚪ Blancs", "⚫ Noirs"], index=0, horizontal=True)

                    joueurs_etats = {p: "✅ Dispo" for p in liste_totale_joueurs}
                    for eq_n, eq_d in st.session_state['db']['equipes_interclubs'].items():
                        if eq_n != equipe_choisie:
                            for p in eq_d.get("compo", {}).get(ronde_choisie, []):
                                if p in joueurs_etats: joueurs_etats[p] = f"⛔ Joue en {eq_n}"

                    options_affichees = [""] + [f"{joueurs_etats[p]} | {p} ({dict_elo_global.get(p, 1000)})" for p in liste_totale_joueurs if p in nouveau_roster or "⛔" in joueurs_etats[p]]
                    map_options = {opt: opt.split(" | ")[1].split(" (")[0] for opt in options_affichees if " | " in opt}
                    map_options[""] = ""

                    compo_actuelle = st.session_state['db']['equipes_interclubs'][equipe_choisie].get("compo", {}).get(ronde_choisie, [""]*nb_ech_equipe)
                    while len(compo_actuelle) < nb_ech_equipe: compo_actuelle.append("")

                    nouvelle_compo, erreurs_bloquantes = [], []
                    c_echs = st.columns(2)
                    for i in range(nb_ech_equipe):
                        val_saved_name = compo_actuelle[i]
                        idx_defaut = next((idx for idx, opt in enumerate(options_affichees) if map_options[opt] == val_saved_name), 0)
                        icon_c = "⚪" if (i % 2 == 0 and couleur_ech1 == "⚪ Blancs") or (i % 2 != 0 and couleur_ech1 != "⚪ Blancs") else "⚫"
                        choix = st.selectbox(f"Échiquier {i+1} {icon_c}", options_affichees, index=idx_defaut, key=f"ech_{i}_{equipe_choisie}")
                        j_sel = map_options[choix]
                        nouvelle_compo.append(j_sel)
                        if "⛔" in choix: erreurs_bloquantes.append(f"{j_sel} est déjà pris !")

                    if categorie == "Adultes":
                        for i in range(len(nouvelle_compo) - 1):
                            for j in range(i+1, len(nouvelle_compo)):
                                if nouvelle_compo[i] and nouvelle_compo[j]:
                                    if dict_elo_global.get(nouvelle_compo[i], 1000) < dict_elo_global.get(nouvelle_compo[j], 1000) - 100:
                                        erreurs_bloquantes.append(f"Règle des 100 points enfreinte (Ech {i+1} vs {j+1}).")

                    if erreurs_bloquantes:
                        for err in erreurs_bloquantes: st.error(err)
                    else:
                        if st.button("💾 Enregistrer la Composition", use_container_width=True):
                            st.session_state['db']['equipes_interclubs'][equipe_choisie].setdefault("compo", {})[ronde_choisie] = nouvelle_compo
                            st.session_state['db']['equipes_interclubs'][equipe_choisie].setdefault("couleurs", {})[ronde_choisie] = couleur_ech1
                            sauvegarder_base_cloud(st.session_state['db']); st.success("Enregistré !"); st.rerun()

                    if pdf_ready:
                        pdf_vierge = st.file_uploader("Feuille FFE vierge (PDF)", type=['pdf'])
                        if pdf_vierge and st.button("🖨️ Télécharger le PDF"):
                            try:
                                packet = io.BytesIO(); c = canvas.Canvas(packet, pagesize=A4)
                                offset = 0 if couleur_ech1 == "⚪ Blancs" else 280
                                c.drawString(80 + offset, 750, str(equipe_choisie))
                                y = 615
                                for idx, j in enumerate(nouvelle_compo):
                                    if j: c.drawString(70 + offset, y - (idx * 28), str(j)); c.drawString(300 + offset, y - (idx * 28), str(dict_elo_global.get(j, "")))
                                c.save(); packet.seek(0)
                                new_pdf = PyPDF2.PdfReader(packet); existing_pdf = PyPDF2.PdfReader(pdf_vierge)
                                output = PyPDF2.PdfWriter(); page = existing_pdf.pages[0]; page.merge_page(new_pdf.pages[0])
                                output.add_page(page); out_stream = io.BytesIO(); output.write(out_stream)
                                st.download_button("⬇️ PDF de match", data=out_stream.getvalue(), file_name=f"Feuille.pdf", mime="application/pdf")
                            except: st.error("Erreur PDF")

        with tab_adultes: afficher_gestion_equipes("Adultes")
        with tab_jeunes: afficher_gestion_equipes("Jeunes")

    elif module_choisi == "♟️ Module Entraîneur":
        st.subheader("♟️ Espace Entraîneur")
        tab_appel, tab_tournoi, tab_classement, tab_affectations = st.tabs(["📋 Faire l'Appel", "⚔️ Tournoi & Elo", "🏆 Classement", "⚙️ Affecter Élèves"])

        with tab_affectations:
            st.markdown("### ⚙️ Affectation Créneaux")
            lieu_aff = st.selectbox("Créneau :", [c for c_list in structure_creneaux.values() for c in c_list])
            eleves_sauvegardes = st.session_state['db']['affectations_creneaux'].get(lieu_aff, [])
            nouveaux_eleves = st.multiselect(f"Élèves assignés :", options=sorted(df["Identité"].tolist()), default=[e for e in eleves_sauvegardes if e in df["Identité"].tolist()])
            if st.button("💾 Sauvegarder liste"):
                st.session_state['db']['affectations_creneaux'][lieu_aff] = nouveaux_eleves; sauvegarder_base_cloud(st.session_state['db']); st.success("OK")

        with tab_appel:
            st.markdown(f"### 📋 Appel du {date_jour}")
            lieu_appel = st.selectbox("Sélectionner le Créneau :", [c for c_list in structure_creneaux.values() for c in c_list], key="appel_creneau")
            liste_identites = st.session_state['db']['affectations_creneaux'].get(lieu_appel, [])
            if not liste_identites: st.info("Aucun élève.")
            else:
                df_groupe = df[df["Identité"].isin(liste_identites)]
                presences = {idx: st.checkbox(row['Identité'], value=True, key=f"appel_{idx}_{row['Identité']}") for idx, row in df_groupe.iterrows()}
                if st.button("💾 Enregistrer l'appel"):
                    if date_jour not in st.session_state['db']['historique_appels']: st.session_state['db']['historique_appels'][date_jour] = {}
                    st.session_state['db']['historique_appels'][date_jour][lieu_appel] = {"presents": [df_groupe.loc[i, 'Identité'] for i, p in presences.items() if p]}
                    sauvegarder_base_cloud(st.session_state['db']); st.success("Appel enregistré !")

        with tab_tournoi:
            st.markdown("### ⚔️ Tournoi Suisse")
            creneaux_remplis = [k for k, v in st.session_state['db']['affectations_creneaux'].items() if len(v) > 0]
            if creneaux_remplis:
                creneau_tournoi = st.selectbox("Lancer le tournoi pour :", options=creneaux_remplis)
                joueurs_presents = st.multiselect("Joueurs présents :", options=st.session_state['db']['affectations_creneaux'][creneau_tournoi], default=st.session_state['db']['affectations_creneaux'][creneau_tournoi])
                
                elos_actifs = {j: get_elo_actif(j, df, st.session_state['db'])[0] for j in joueurs_presents}

                if st.session_state.get('tournoi_en_cours') != creneau_tournoi:
                    st.session_state['scores_tournoi'] = {j: 0.0 for j in joueurs_presents}
                    st.session_state['adversaires_tournoi'] = {j: [] for j in joueurs_presents}
                    st.session_state['historique_rencontres'] = set()
                    st.session_state['ronde_actuelle'] = 1
                    st.session_state['appariements_ronde'] = []
                    st.session_state['tournoi_en_cours'] = creneau_tournoi

                for j in joueurs_presents:
                    if j not in st.session_state['scores_tournoi']: st.session_state['scores_tournoi'][j] = 0.0
                    if j not in st.session_state.get('adversaires_tournoi', {}): st.session_state.setdefault('adversaires_tournoi', {})[j] = []

                if st.button("📊 Voir la Grille Américaine"):
                    data_grille = [{"Élève": j, "Points": st.session_state['scores_tournoi'].get(j, 0.0), "Buchholz": sum(st.session_state['scores_tournoi'].get(adv, 0.0) for adv in st.session_state['adversaires_tournoi'].get(j, []))} for j in joueurs_presents]
                    st.dataframe(pd.DataFrame(data_grille).sort_values(by=["Points", "Buchholz"], ascending=[False, False]).reset_index(drop=True).rename_axis("Place"))

                if st.button("🎲 Générer la Ronde"):
                    scores_actifs = {j: st.session_state['scores_tournoi'][j] for j in joueurs_presents}
                    pairs, exempt, st.session_state['historique_rencontres'] = generer_appariements_suisses(scores_actifs, elos_actifs, st.session_state['historique_rencontres'])
                    st.session_state['appariements_ronde'], st.session_state['exempt_ronde'] = pairs, exempt

                if st.session_state.get('appariements_ronde'):
                    st.subheader(f"♟️ Matchs — Ronde {st.session_state['ronde_actuelle']}")
                    if st.button("📺 Afficher en Plein Écran"): st.session_state['plein_ecran_ronde'] = True; st.rerun()
                        
                    resultats = []
                    for i, (j1, j2) in enumerate(st.session_state['appariements_ronde'], 1):
                        c1, c2 = st.columns([3, 1])
                        c1.markdown(f"**Table {i}:** ⚪ {j1} ({elos_actifs[j1]}) 🆚 ⚫ {j2} ({elos_actifs[j2]})")
                        resultats.append((j1, j2, c2.selectbox("Résultat", ["...", "1 - 0 (Blancs)", "0 - 1 (Noirs)", "0.5 - 0.5 (Nulle)"], key=f"r_{i}", label_visibility="collapsed")))
                        
                    if st.session_state.get('exempt_ronde'): st.warning(f"👑 Exempt : {st.session_state['exempt_ronde']}")

                    if st.button("💾 Valider les résultats"):
                        if any(r[2] == "..." for r in resultats): st.error("Saisissez tous les résultats.")
                        else:
                            for j1, j2, res in resultats:
                                st.session_state['adversaires_tournoi'][j1].append(j2)
                                st.session_state['adversaires_tournoi'][j2].append(j1)
                                if res == "1 - 0 (Blancs)":
                                    st.session_state['scores_tournoi'][j1] += 1.0
                                    st.session_state['db']['elos_crevette'][j1], st.session_state['db']['elos_crevette'][j2] = calculer_nouveau_elo(elos_actifs[j1], elos_actifs[j2], 1.0), calculer_nouveau_elo(elos_actifs[j2], elos_actifs[j1], 0.0)
                                elif res == "0 - 1 (Noirs)":
                                    st.session_state['scores_tournoi'][j2] += 1.0
                                    st.session_state['db']['elos_crevette'][j1], st.session_state['db']['elos_crevette'][j2] = calculer_nouveau_elo(elos_actifs[j1], elos_actifs[j2], 0.0), calculer_nouveau_elo(elos_actifs[j2], elos_actifs[j1], 1.0)
                                else:
                                    st.session_state['scores_tournoi'][j1] += 0.5; st.session_state['scores_tournoi'][j2] += 0.5
                                    st.session_state['db']['elos_crevette'][j1], st.session_state['db']['elos_crevette'][j2] = calculer_nouveau_elo(elos_actifs[j1], elos_actifs[j2], 0.5), calculer_nouveau_elo(elos_actifs[j2], elos_actifs[j1], 0.5)

                            if st.session_state.get('exempt_ronde'): st.session_state['scores_tournoi'][st.session_state['exempt_ronde']] += 1.0
                            sauvegarder_base_cloud(st.session_state['db'])
                            st.session_state['ronde_actuelle'] += 1; st.session_state['appariements_ronde'] = []; st.rerun()

        with tab_classement:
            st.markdown("### 🏆 Classement Interne")
            data_classement = [{"Élève": j, "Niveau ⚡🦐": get_elo_actif(j, df, st.session_state['db'])[0]} for j in list(df["Identité"].unique())]
            st.dataframe(pd.DataFrame(data_classement).sort_values(by="Niveau ⚡🦐", ascending=False).reset_index(drop=True), use_container_width=True)
