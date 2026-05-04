import streamlit as st
import os
import yaml

st.set_page_config(page_title="Exail Edge - DevSecOps", page_icon="🛡️", layout="wide")

st.title("🛡️ Exail Edge V2 - Configuration Manager")
st.markdown("Ce portail permet de générer dynamiquement l'inventaire et les variables Ansible pour le déploiement Air-Gapped.")


tab1, tab2, tab3, tab4 = st.tabs(["📡 Réseau & Inventaire", "🔒 Sécurité & Hardening", "🐳 Conteneurs Podman", "⚙️ Génération"])


ansible_vars = {}
inventory_data = {}


with tab1:
    st.subheader("Machines Cibles")
    col1, col2 = st.columns(2)
    with col1:
        inventory_data['prod_ip'] = st.text_input("IP Prod (Frontend Vue.js)", value="192.168.121.103")
        inventory_data['drone_ip'] = st.text_input("IP Drone (Backend C++)", value="192.168.121.2")
    with col2:
        ansible_vars['ansible_ssh_user'] = st.text_input("Utilisateur SSH Cible", value="vagrant")
        inventory_data['workspace_path'] = st.text_input("Chemin absolu du projet (Local/Jenkins)", value="/home/clem/Code/exail-v2")


with tab2:
    st.subheader("Hardening OS & Pare-feu (UFW)")
    col3, col4 = st.columns(2)
    
    with col3:
        ansible_vars['ssh_port'] = st.number_input("Port SSH", value=22)
        ansible_vars['ufw_frontend_port'] = st.number_input("Port public UFW Frontend", value=8080)
        ansible_vars['ufw_backend_port'] = st.number_input("Port public UFW Backend", value=9090)
    
    with col4:
        ansible_vars['hardening_disable_root'] = st.toggle("Désactiver le login Root (SSH)", value=True)
        ansible_vars['hardening_disable_passwords'] = st.toggle("Désactiver l'authentification par mot de passe", value=True)
        ansible_vars['apply_anssi_sysctl'] = st.toggle("Appliquer les règles sysctl restrictives ANSSI", value=True)

    ansible_vars['ssh_banner_text'] = st.text_area("Bannière d'avertissement légal (/etc/issue.net)", value="""===========================================================
⚠️ SYSTÈME D'INFORMATION RESTREINT — EXAIL
Accès réservé aux personnels habilités.
Toute intrusion est traçable et pénalement répréhensible.
===========================================================""", height=150)

with tab3:
    st.subheader("Déploiement Air-Gapped")
    col5, col6 = st.columns(2)
    
    with col5:
        ansible_vars['podman_service_user'] = st.text_input("Compte de service OS", value="exail_svc")
        ansible_vars['podman_transfer_dir'] = st.text_input("Répertoire temporaire de transfert", value="/tmp")
        
    with col6:

        ansible_vars['container_frontend_port'] = st.number_input("Port d'écoute interne Frontend (Nginx)", value=8080, disabled=True, help="Défini dans nginx.conf")
        ansible_vars['container_backend_port'] = st.number_input("Port d'écoute interne Backend (C++)", value=9090, disabled=True, help="Défini dans le code source C++")


with tab4:
    st.subheader("💾 Appliquer la configuration")
    st.markdown("Validez pour réécrire les fichiers d'environnement Ansible avant d'exécuter `deploy-app.yml`.")
    
    if st.button("Générer les fichiers Ansible", type="primary", use_container_width=True):
        
        inventory_content = f"""[production]
vm-prod-01       ansible_host={inventory_data['prod_ip']}

[edge]
vm-edge-drone-01 ansible_host={inventory_data['drone_ip']}

[all:vars]
ansible_user={ansible_vars['ansible_ssh_user']}
ansible_ssh_common_args='-o StrictHostKeyChecking=no'
ansible_ssh_private_key_file={inventory_data['workspace_path']}/infra/vagrant/.vagrant/machines/{{{{ 'vm-prod' if inventory_hostname == 'vm-prod' else 'vm-drone' }}}}/libvirt/private_key
"""
        try:
            os.makedirs("ansible/inventory", exist_ok=True)
            os.makedirs("ansible/group_vars", exist_ok=True)
            
            with open("ansible/inventory/production.ini", "w") as f:
                f.write(inventory_content)
                
            with open("ansible/group_vars/all.yml", "w") as f:
                yaml.dump(ansible_vars, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                
            st.success("✅ Fichiers `production.ini` et `group_vars/all.yml` générés avec succès !")
            
            col7, col8 = st.columns(2)
            with col7:
                with st.expander("Voir production.ini"):
                    st.code(inventory_content, language="ini")
            with col8:
                with st.expander("Voir group_vars/all.yml"):
                    with open("ansible/group_vars/all.yml", "r") as f:
                        st.code(f.read(), language="yaml")
                        
        except Exception as e:
            st.error(f"Erreur d'écriture : {e}")