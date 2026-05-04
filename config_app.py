import streamlit as st
import os

st.set_page_config(page_title="Exail Edge - Config", page_icon="🚀", layout="centered")

st.title("⚙️ Exail Edge - Panneau de Configuration")
st.markdown("Modifiez les variables de l'environnement de déploiement avant de lancer votre pipeline CI/CD ou Ansible.")

st.header("📡 Infrastructure (Inventaire Ansible)")

col1, col2 = st.columns(2)
with col1:
    prod_ip = st.text_input("IP de la VM Production (Vue.js)", value="192.168.56.11")
with col2:
    drone_ip = st.text_input("IP de la VM Drone (Backend C++)", value="192.168.56.12")

ssh_user = st.text_input("Utilisateur SSH Ansible", value="vagrant")

st.header("🛠️ Configuration Applicative")

col3, col4 = st.columns(2)
with col3:
    frontend_port = st.number_input("Port Frontend (Nginx)", min_value=1024, max_value=65535, value=8080)
with col4:
    backend_port = st.number_input("Port Backend (C++)", min_value=1024, max_value=65535, value=9090)

st.divider()

if st.button("💾 Sauvegarder les configurations", type="primary"):
    
    inventory_content = f"""[production]
vm-prod-01       ansible_host={prod_ip}  ansible_user={ssh_user}[edge]
vm-edge-drone-01 ansible_host={drone_ip}  ansible_user={ssh_user}

[all:vars]
ansible_user={ssh_user}
ansible_ssh_common_args='-o StrictHostKeyChecking=no'
"""
    
    inventory_path = "ansible/inventory/production.ini"
    
    try:
        os.makedirs(os.path.dirname(inventory_path), exist_ok=True)
        
        with open(inventory_path, "w") as f:
            f.write(inventory_content)
            
        st.success(f"✅ Inventaire Ansible mis à jour avec succès dans `{inventory_path}`")
        
        with st.expander("Voir le contenu généré"):
            st.code(inventory_content, language="ini")
            
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde : {e}")

    vars_content = f"""
frontend_port: {frontend_port}
backend_port: {backend_port}
    """
    st.info("💡 Vous pouvez également étendre ce script pour générer un fichier `group_vars/all.yml` pour vos ports applicatifs.")
