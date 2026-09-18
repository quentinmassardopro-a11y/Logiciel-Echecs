elif module_choisi == "🏆 Module Interclubs":
        st.subheader("🏆 Gestion des Équipes & Interclubs")
        st.info("Interface Capitaine : Saisissez vos compositions, vérifiez les règles FFE et générez vos feuilles de match.")
        
        pdf_ready = True
        try:
            import PyPDF2
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
            import io
        except ImportError:
            pdf_ready = False
            
        # 1. RÉCUPÉRATION DES JOUEURS DEPUIS LA BASE LOCALE (GARANTI SANS BLOCAGE)
        df_licence_a = pd.DataFrame()
        if 'Licence_FFE' in df.columns:
            df_licence_a = df[df['Licence_FFE'] == 'A']
            
        if not df_licence_a.empty:
            liste_totale_joueurs = df_licence_a['Identité'].tolist()
            dict_elo_global = dict(zip(df_licence_a['Identité'], df_licence_a['Elo_FFE'].fillna(1000).astype(int)))
        else:
            liste_totale_joueurs = sorted(df["Identité"].unique().tolist())
            dict_elo_global = {j: get_elo_actif(j, df, st.session_state['db'])[0] for j in liste_totale_joueurs}

        tab_adultes, tab_jeunes, tab_brulage = st.tabs(["🏅 Interclubs Adultes", "👦👧 Interclubs Jeunes", "🔥 Suivi & Brûlage"])
        
        def afficher_gestion_equipes(categorie):
            # Formulaire manuel de création d'équipe avec choix du nombre d'échiquiers !
            with st.expander(f"➕ Créer une nouvelle équipe {categorie}", expanded=False):
                with st.form(f"form_{categorie}"):
                    c1, c2, c3 = st.columns([2, 1, 1])
                    nv_nom = c1.text_input(f"Nom (ex: Cassis 1)")
                    nv_div = c2.text_input("Division (ex: N1, N3, Régional...)")
                    nb_ech_defaut = 8 if categorie == "Adultes" else 4
                    nv_nb_ech = c3.number_input("Nb d'échiquiers", min_value=2, max_value=16, value=nb_ech_defaut)
                    
                    if st.form_submit_button("Ajouter l'équipe"):
                        if nv_nom:
                            if nv_nom not in st.session_state['db']['equipes_interclubs']:
                                st.session_state['db']['equipes_interclubs'][nv_nom] = {
                                    "Categorie": categorie, 
                                    "Division": nv_div, 
                                    "Nb_Echiquiers": int(nv_nb_ech),
                                    "roster": [], 
                                    "compo": {}, 
                                    "couleurs": {}
                                }
                                sauvegarder_base_cloud(st.session_state['db'])
                                st.rerun()

            equipes_db = st.session_state['db'].get('equipes_interclubs', {})
            equipes_cat = {k: v for k, v in equipes_db.items() if v.get("Categorie") == categorie}
            
            if not equipes_cat:
                st.info(f"👆 Utilisez le formulaire ci-dessus pour créer vos équipes {categorie}.")
                return
                
            st.markdown("---")
            liste_noms_equipes = sorted(list(equipes_cat.keys()))
            
            # --- BOUTON DE SUPPRESSION ---
            c_sel1, c_sel2 = st.columns([3, 1])
            equipe_choisie = c_sel1.selectbox(f"🎯 Sélectionnez l'équipe {categorie} à gérer :", [""] + liste_noms_equipes)
            
            if equipe_choisie:
                if c_sel2.button("🗑️ Supprimer cette équipe", key=f"del_{equipe_choisie}"):
                    del st.session_state['db']['equipes_interclubs'][equipe_choisie]
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.success(f"Équipe '{equipe_choisie}' supprimée !")
                    st.rerun()
            
            if equipe_choisie:
                eq_data = equipes_db[equipe_choisie]
                nb_ech_equipe = eq_data.get("Nb_Echiquiers", 8 if categorie == "Adultes" else 4)
                
                st.markdown(f"""<div class="match-card">
                            <h3 style="margin-bottom:0;">🛡️ {equipe_choisie}</h3>
                            <span style='font-size:16px; color:#FF8C00; font-weight:bold;'>{eq_data.get('Division', '')} — {nb_ech_equipe} Échiquiers</span>
                            </div>""", unsafe_allow_html=True)
                
                # --- 1. BASSIN DE JOUEURS ---
                joueurs_roster = eq_data.get("roster", [])
                nouveau_roster = st.multiselect(
                    f"👥 1. Bassin de joueurs (Roster pour la saison) :", 
                    options=liste_totale_joueurs, 
                    default=[j for j in joueurs_roster if j in liste_totale_joueurs],
                    key=f"rost_{equipe_choisie}"
                )
                if st.button(f"💾 Sauvegarder le bassin de {equipe_choisie}", key=f"sv_rost_{equipe_choisie}"):
                    st.session_state['db']['equipes_interclubs'][equipe_choisie]["roster"] = nouveau_roster
                    sauvegarder_base_cloud(st.session_state['db'])
                    st.success("Bassin mis à jour !")
                    st.rerun()
                
                if nouveau_roster:
                    st.markdown("---")
                    st.markdown(f"### ⚔️ 2. Préparation de la Feuille de Match")
                    
                    rondes_dispos = [f"Ronde {i}" for i in range(1, 12)]
                    
                    c_r1, c_r2 = st.columns([1, 2])
                    ronde_choisie = c_r1.selectbox("Sélectionnez la ronde :", rondes_dispos, key=f"sel_r_{equipe_choisie}")
                    
                    # --- CHOIX DE LA COULEUR ---
                    if "couleurs" not in st.session_state['db']['equipes_interclubs'][equipe_choisie]:
                        st.session_state['db']['equipes_interclubs'][equipe_choisie]["couleurs"] = {}
                        
                    couleur_saved = st.session_state['db']['equipes_interclubs'][equipe_choisie]["couleurs"].get(ronde_choisie, "⚪ Blancs")
                    
                    couleur_ech1 = c_r2.radio(
                        "Couleur de notre équipe au 1er échiquier :", 
                        ["⚪ Blancs", "⚫ Noirs"], 
                        index=0 if couleur_saved == "⚪ Blancs" else 1,
                        horizontal=True,
                        key=f"coul_{equipe_choisie}"
                    )

                    # --- SÉLECTION DES JOUEURS ---
                    joueurs_indispos = []
                    for eq, d in equipes_db.items():
                        if eq != equipe_choisie:
                            for j in d.get("compo", {}).get(ronde_choisie, []):
                                if j: joueurs_indispos.append(j)

                    options_joueurs = [""]
                    for nom in nouveau_roster:
                        if nom not in joueurs_indispos:
                            options_joueurs.append(f"{nom} ({dict_elo_global.get(nom, 1000)})")

                    st.caption(f"Les joueurs assignés à d'autres équipes pour la {ronde_choisie} sont automatiquement masqués.")
                    
                    if "compo" not in st.session_state['db']['equipes_interclubs'][equipe_choisie]: 
                        st.session_state['db']['equipes_interclubs'][equipe_choisie]["compo"] = {}
                    
                    compo_actuelle = st.session_state['db']['equipes_interclubs'][equipe_choisie]["compo"].get(ronde_choisie, [""]*nb_ech_equipe)
                    while len(compo_actuelle) < nb_ech_equipe: compo_actuelle.append("")

                    nouvelle_compo = []
                    erreurs_100_pts = []
                    
                    # Interface de saisie
                    st.markdown("""<div style='background-color:#f8f9fa; padding:20px; border-radius:10px; border:1px solid #e0e0e0;'>""", unsafe_allow_html=True)
                    
                    if categorie == "Jeunes":
                        st.info("RAPPEL FFE JEUNES : L'ordre des échiquiers est strictement défini par l'âge (1er: U16/Minime, 2e: U14/Benjamin, 3e: U12/Pupille, 4e: U10/Poussin). L'Elo ne sert qu'à départager deux joueurs d'une même catégorie d'âge.")
                    
                    c_echs = st.columns(2)
                    for i in range(nb_ech_equipe):
                        val_saved = compo_actuelle[i]
                        val_formatted = f"{val_saved} ({dict_elo_global.get(val_saved, '??')})" if val_saved else ""
                        if val_formatted not in options_joueurs and val_saved != "": options_joueurs.append(val_formatted)
                        
                        if couleur_ech1 == "⚪ Blancs": icon_couleur = "⚪" if i % 2 == 0 else "⚫"
                        else: icon_couleur = "⚫" if i % 2 == 0 else "⚪"
                            
                        idx_defaut = options_joueurs.index(val_formatted) if val_formatted in options_joueurs else 0
                        choix = st.selectbox(f"Échiquier {i+1} {icon_couleur}", options_joueurs, index=idx_defaut, key=f"ech_{i}_{equipe_choisie}")
                        nouvelle_compo.append(choix.split(" (")[0] if choix else "")
                        
                    st.markdown("</div>", unsafe_allow_html=True)

                    # Garde fou 101 pts (Prioritaire en Adultes, secondaire en Jeunes)
                    if categorie == "Adultes":
                        for i in range(len(nouvelle_compo) - 1):
                            for j in range(i+1, len(nouvelle_compo)):
                                j1, j2 = nouvelle_compo[i], nouvelle_compo[j]
                                if j1 and j2:
                                    elo1, elo2 = dict_elo_global.get(j1, 1000), dict_elo_global.get(j2, 1000)
                                    if elo1 < elo2 - 100:
                                        erreurs_100_pts.append(f"🚨 **Échiquier {i+1} ({j1}, {elo1})** est placé devant l'**Échiquier {j+1} ({j2}, {elo2})**. Écart : {elo2 - elo1} pts (>100 interdit).")
                    
                    st.write("")
                    if erreurs_100_pts:
                        for err in erreurs_100_pts: st.error(err)
                    else: 
                        if any(nouvelle_compo): st.success("✅ Contrôle Elo validé pour cette composition.")

                    if st.button("💾 Enregistrer la Composition", use_container_width=True):
                        # Sécuriser la taille de la liste sauvegardée
                        st.session_state['db']['equipes_interclubs'][equipe_choisie]["compo"][ronde_choisie] = nouvelle_compo[:nb_ech_equipe]
                        st.session_state['db']['equipes_interclubs'][equipe_choisie]["couleurs"][ronde_choisie] = couleur_ech1
                        sauvegarder_base_cloud(st.session_state['db'])
                        st.success(f"Composition et couleurs enregistrées pour la {ronde_choisie} !")
                        st.rerun()

                    # --- 3. GÉNÉRATION DU PDF ---
                    if pdf_ready:
                        st.markdown("---")
                        with st.expander("📄 3. Générer la Feuille de Match (PDF)"):
                            c_p1, c_p2 = st.columns(2)
                            date_pdf = c_p1.text_input("Date du match", value=datetime.now().strftime("%d/%m/%Y"), key=f"date_{equipe_choisie}")
                            lieu_pdf = c_p2.text_input("Lieu de rencontre", value="Domicile" if "cassis" in equipe_choisie.lower() else "", key=f"lieu_{equipe_choisie}")
                            
                            pdf_vierge = st.file_uploader("Importer la feuille FFE vierge (PDF)", type=['pdf'], key=f"up_{equipe_choisie}")
                            if pdf_vierge and st.button("🖨️ Télécharger le PDF complété", key=f"gen_{equipe_choisie}"):
                                try:
                                    packet = io.BytesIO()
                                    c = canvas.Canvas(packet, pagesize=A4)
                                    
                                    c.drawString(100, 770, str(date_pdf))
                                    c.drawString(250, 770, str(lieu_pdf))
                                    c.drawString(450, 770, str(ronde_choisie))
                                    
                                    # Logique de décalage selon la couleur du 1er échiquier
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
                                                if code_ffe != "Non croisé": 
                                                    c.drawString(240 + x_offset, y_start - (idx * y_step), code_ffe)
                                            c.drawString(300 + x_offset, y_start - (idx * y_step), str(dict_elo_global.get(joueur, "")))
                                    
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
                                    
                                    st.download_button("⬇️ Télécharger le PDF de match", data=output_stream.getvalue(), file_name=f"Feuille_{equipe_choisie}_{ronde_choisie}.pdf", mime="application/pdf")
                                except Exception as e:
                                    st.error(f"Impossible de dessiner sur le PDF : {e}")

        with tab_adultes: afficher_gestion_equipes("Adultes")
        with tab_jeunes: afficher_gestion_equipes("Jeunes")
            
        with tab_brulage:
            st.markdown("### 🔥 Suivi des Brûlages FFE")
            st.info("Un joueur ayant participé à 4 matchs dans une équipe ou division est considéré comme **BRÛLÉ**. Il lui est strictement interdit de redescendre.")
            
            joueurs_stats = {}
            for nom_eq, data in st.session_state['db'].get('equipes_interclubs', {}).items():
                for r_nom, compo in data.get("compo", {}).items():
                    for j in compo:
                        if j:
                            if j not in joueurs_stats: joueurs_stats[j] = {}
                            if nom_eq not in joueurs_stats[j]: joueurs_stats[j][nom_eq] = 0
                            joueurs_stats[j][nom_eq] += 1
                                
            data_brulage = []
            for j, stats in joueurs_stats.items():
                if stats:
                    details = " | ".join([f"{eq}: {c} matchs" for eq, c in stats.items()])
                    est_brule = any(c >= 4 for c in stats.values())
                    data_brulage.append({
                        "Joueur": j,
                        "Statut": "🔥 BRÛLÉ (Ne peut plus redescendre)" if est_brule else "✅ OK",
                        "Détails des sélections": details
                    })
            if data_brulage:
                df_brulage = pd.DataFrame(data_brulage).sort_values(by="Statut", ascending=False).reset_index(drop=True)
                st.dataframe(df_brulage, use_container_width=True)
            else:
                st.info("Aucun match n'a été saisi pour le moment.")
