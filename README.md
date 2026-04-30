# Exail Edge — Pipeline DevSecOps

Pipeline CI/CD complet pour déployer une application de supervision drone (backend C++ + frontend Vue.js) sur infrastructure air-gapped, avec hardening ANSSI.

---

## Architecture

```
Ton PC
├── VM Jenkins        (192.168.56.10)  → Build, scan, déploiement
├── VM Prod           (192.168.56.11)  → Cible de déploiement
└── VM Drone          (192.168.56.12)  → Cible de déploiement
```

**Flow du pipeline :**

```
Code (GitHub) → Jenkins → Build C++/npm → Podman build → Trivy scan
→ Export .tar → Ansible deploy → Hardening OS → Podman run → Health check
```

---

## Prérequis

- [Vagrant](https://www.vagrantup.com/) + plugin libvirt
- [VirtualBox](https://www.virtualbox.org/) ou libvirt/KVM
- Plugin vagrant-scp : `vagrant plugin install vagrant-scp`

---

## Installation from scratch

### 1. Cloner le repo

```bash
git clone git@github.com:clementtrecourt/Exail-poc.git
cd Exail-poc/infra/vagrant
```

### 2. Lancer les VMs

```bash
vagrant up
```

Les VMs sont créées avec des IPs fixes :
- `vm-jenkins` → `192.168.56.10:8080`
- `vm-prod` → `192.168.56.11`
- `vm-drone` → `192.168.56.12`

### 3. Générer la clé SSH Jenkins

```bash
vagrant ssh vm-jenkins

# Depuis la VM Jenkins
sudo -u jenkins ssh-keygen -t ed25519 -C "jenkins-deploy" \
  -f /var/lib/jenkins/.ssh/jenkins_deploy -N ""

# Afficher la clé publique (à copier)
sudo cat /var/lib/jenkins/.ssh/jenkins_deploy.pub
```

### 4. Injecter la clé publique dans les VMs cibles

```bash
# Depuis ton PC — remplace CONTENU_CLE_PUB par la clé affichée ci-dessus
vagrant ssh vm-prod  -c "echo 'CONTENU_CLE_PUB' >> ~/.ssh/authorized_keys"
vagrant ssh vm-drone -c "echo 'CONTENU_CLE_PUB' >> ~/.ssh/authorized_keys"
```

### 5. Installer le plugin SSH Agent dans Jenkins

```bash
vagrant ssh vm-jenkins

# Télécharger le plugin directement
sudo wget -O /var/lib/jenkins/plugins/ssh-agent.jpi \
  https://updates.jenkins.io/latest/ssh-agent.hpi

sudo chown jenkins:jenkins /var/lib/jenkins/plugins/ssh-agent.jpi
sudo systemctl restart jenkins
```

### 6. Configurer Jenkins GUI

Accès : `http://192.168.56.10:8080`

Mot de passe initial :
```bash
vagrant ssh vm-jenkins -c "sudo cat /var/lib/jenkins/secrets/initialAdminPassword"
```

**Ajouter le credential SSH :**

Jenkins → Manage Jenkins → Credentials → System → Global → Add Credentials
- Kind : `SSH Username with private key`
- ID : `jenkins-ssh-key` ← exact, c'est ce que le Jenkinsfile utilise
- Username : `vagrant`
- Private Key : coller le contenu de `/var/lib/jenkins/.ssh/jenkins_deploy`

```bash
# Afficher la clé privée à coller
vagrant ssh vm-jenkins -c "sudo cat /var/lib/jenkins/.ssh/jenkins_deploy"
```

### 7. Créer le pipeline Jenkins

Jenkins → New Item → Pipeline
- Name : `Exail`
- Definition : `Pipeline script from SCM`
- SCM : Git
- Repository URL : `git@github.com:clementtrecourt/Exail-poc.git`
- Credentials : le credential GitHub SSH existant
- Branch : `*/main`
- Script Path : `Jenkinsfile`

---



## Structure du projet

```
.
├── backend/
│   └── src/main.cpp          # Backend C++ (simulation)
├── frontend/
│   ├── nginx.conf            # Config Nginx rootless port 8080
│   └── package.json
├── ansible/
│   ├── deploy-app.yml        # Playbook principal
│   ├── inventory/
│   │   └── production.ini    # IPs des VMs cibles
│   └── roles/
│       ├── os-hardening/     # Hardening ANSSI (sysctl, SSH, UFW)
│       └── podman-deploy/    # Déploiement conteneurs
├── Dockerfile.backend        # Distroless/nonroot ~25MB
├── Dockerfile.frontend       # Nginx alpine rootless ~50MB
└── Jenkinsfile               # Pipeline CI/CD
```



## Pipeline Jenkins — Stages

| Stage | Description |
|-------|-------------|
| Build | Compilation C++ (CMake) + build npm en parallèle |
| Package | Build images Podman avec labels git-commit |
| Security Scan | Trivy — CVE HIGH/CRITICAL, export JSON |
| Export Air-Gapped | `podman save` → archives `.tar` |
| Deploy Ansible | Hardening OS + chargement images + lancement conteneurs |
| Health Check | GET /health frontend + status conteneurs |

---

## Inventory Ansible

```ini
# ansible/inventory/production.ini
[all]
vm-prod-01       ansible_host=192.168.56.11 ansible_user=vagrant
vm-edge-drone-01 ansible_host=192.168.56.12 ansible_user=vagrant
```

---

## Sécurité appliquée (ANSSI)

**Kernel (sysctl) :**
- `net.ipv4.conf.all.accept_redirects = 0`
- `net.ipv4.tcp_syncookies = 1`
- `kernel.randomize_va_space = 2`
- `kernel.dmesg_restrict = 1`

**SSH :**
- `PermitRootLogin no`
- `PasswordAuthentication no` (clé uniquement)

**Firewall UFW :**
- Politique par défaut : deny incoming
- Ports ouverts : 22 (SSH), 8080 (frontend), 9090 (backend)

**Conteneurs :**
- Images distroless (backend) et alpine (frontend)
- `cap_drop: ALL`
- Utilisateur non-root (`nonroot` / `nginx`)
- Mode rootless Podman

---

## Problèmes connus et solutions

### `sshagent` not found
Le plugin SSH Agent n'est pas chargé. Installer via wget + restart :
```bash
sudo wget -O /var/lib/jenkins/plugins/ssh-agent.jpi \
  https://updates.jenkins.io/latest/ssh-agent.hpi
sudo systemctl restart jenkins
```

### Trivy ne voit pas les images Podman
Trivy cherche le socket Podman de l'utilisateur courant. Fix :
```bash
CONTAINER_HOST=unix:///run/user/$(id -u)/podman/podman.sock \
./trivy image localhost/exail-backend:vX
```

### Port déjà utilisé au redéploiement
Un conteneur root du build précédent occupe le port. Le script Ansible fait :
```bash
sudo podman rm -f exail-backend 2>/dev/null || true
podman rm -f exail-backend 2>/dev/null || true
```

### IPs des VMs qui changent
Fixer les IPs dans le Vagrantfile avec `private_network` pour éviter ce problème.
