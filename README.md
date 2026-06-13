# 🛡️ Exail Edge V2 — DevSecOps POC

> Pipeline CI/CD air-gapped complet avec hardening ANSSI, scan de vulnérabilités, génération SBOM et déploiement Ansible sur infrastructure multi-VM Libvirt/Vagrant.

![Jenkins](https://img.shields.io/badge/Jenkins-LTS-D24939?logo=jenkins&logoColor=white)
![Podman](https://img.shields.io/badge/Podman-Rootless-892CA0?logo=podman&logoColor=white)
![Ansible](https://img.shields.io/badge/Ansible-Hardening_ANSSI-EE0000?logo=ansible&logoColor=white)
![Trivy](https://img.shields.io/badge/Trivy-CVE_Scan-1904DA?logo=aqua&logoColor=white)
![Syft](https://img.shields.io/badge/Syft-SBOM_SPDX-4A90D9)
![Distroless](https://img.shields.io/badge/Backend-Distroless%2FNonroot-333333)

---

## Table des matières

1. [Vue d'ensemble](#vue-densemble)
2. [Architecture](#architecture)
3. [Pipeline CI/CD](#pipeline-cicd)
4. [Stack applicative](#stack-applicative)
5. [Hardening & Sécurité](#hardening--sécurité)
6. [Stack Observabilité](#stack-observabilité)
7. [Prérequis & Installation](#prérequis--installation)
8. [Utilisation](#utilisation)
9. [Config Manager (Streamlit)](#config-manager-streamlit)
10. [Gestion des CVE](#gestion-des-cve)

---

## Vue d'ensemble

Ce dépôt est une preuve de concept DevSecOps pensée pour un environnement **air-gapped** (sans accès Internet sur les cibles), inspiré des contraintes opérationnelles défense/industrie.

**Ce que démontre ce POC :**

- Build d'images conteneurs Podman avec compilation C++/CMake multi-stage et build Vue.js en CI
- Export des images en archives `.tar` pour transfert air-gapped (aucun registry requis sur les cibles)
- Génération automatique de **SBOM au format SPDX-JSON** via Syft à chaque build
- Scan de vulnérabilités **Trivy** sur archives — pipeline bloquant sur `CRITICAL` non corrigées
- Déploiement **Ansible** avec hardening OS conforme aux recommandations **ANSSI**
- Stack d'observabilité complète : Grafana + Prometheus + Loki + Node Exporter + cAdvisor + Promtail
- **Config Manager** Streamlit pour la génération dynamique des fichiers Ansible et le monitoring d'infrastructure

---

## Architecture

### Infrastructure Vagrant / Libvirt

| VM | Hostname | IP | Rôle |
|---|---|---|---|
| `vm-jenkins` | `vm-jenkins` | `10.0.0.10` | Orchestrateur CI/CD — Jenkins + Podman + Ansible + Syft |
| `vm-prod` | `vm-prod-01` | `10.0.0.11` | Cible production — Frontend Vue.js (Nginx rootless) |
| `vm-drone` | `vm-edge-drone-01` | `10.0.0.12` | Cible edge — Backend C++ (Distroless/Nonroot) |
| `vm-monitoring` | `vm-monitoring` | `10.0.0.13` | Observabilité — Grafana, Prometheus, Loki |

Toutes les VMs sont sur le réseau privé Libvirt `exail-v2-net`. La communication CI→cibles se fait exclusivement par **SSH avec clé Ed25519** (pas de mot de passe).

### Topologie réseau

```
  ┌─────────────────────────────────────────────────────┐
  │               exail-v2-net (10.0.0.0/24)            │
  │                                                     │
  │  ┌──────────────┐      SSH + Ansible                │
  │  │  vm-jenkins  │ ──────────────────────────────┐   │
  │  │  10.0.0.10   │                               │   │
  │  │  Jenkins     │                    ┌──────────▼─┐ │
  │  │  Podman      │                    │  vm-prod   │ │
  │  │  Ansible     │                    │  10.0.0.11 │ │
  │  │  Syft        │                    │  Frontend  │ │
  │  └──────────────┘                    └────────────┘ │
  │         │                                           │
  │         │ SSH + Ansible          ┌──────────────┐   │
  │         └───────────────────────►│  vm-drone    │   │
  │         │                        │  10.0.0.12   │   │
  │         │                        │  Backend C++ │   │
  │         │                        └──────────────┘   │
  │         │                                           │
  │         │ SSH + Ansible          ┌──────────────┐   │
  │         └───────────────────────►│ vm-monitoring│   │
  │                                  │  10.0.0.13   │   │
  │                                  │  Grafana     │   │
  │                                  │  Prometheus  │   │
  │                                  │  Loki        │   │
  │                                  └──────────────┘   │
  └─────────────────────────────────────────────────────┘
```
## Choix architecturaux (ADR)

**Jenkins** : seul CI fonctionnel sans dépendance cloud. GitLab CI = instance self-hosted
supplémentaire. GitHub Actions = cloud-native incompatible air-gapped.
**Podman rootless** : pas de daemon root. Compatible RHEL/Fedora courant en défense.
**Archives .tar** : seul vecteur viable en air-gapped strict. Applicable au transfert
physique USB vers un drone en opération.
**Vagrant** : reproductibilité immédiate sur tout laptop Linux. Terraform pour environnements
persistants (voir homelab).
---

## Pipeline CI/CD

### Vue d'ensemble du flux

```mermaid
flowchart TD
    A([👨‍💻 Git Push]) --> B

    subgraph JENKINS ["🔧 vm-jenkins — Jenkins Pipeline"]
        B[Stage: Build]
        B --> B1[Backend — rm build artifacts\nCompilation dans Dockerfile multi-stage]
        B --> B2[Frontend — npm install && npm run build]
        B1 & B2 --> C

        C[Stage: Package — Images Podman]
        C --> C1["podman build Dockerfile.backend\n→ localhost/exail-backend:vN"]
        C --> C2["podman build Dockerfile.frontend\n→ localhost/exail-frontend:vN"]
        C1 & C2 --> D

        D[Stage: Export Air-Gapped]
        D --> D1["podman save → exail-backend.tar\npodman save → exail-frontend.tar"]
        D1 --> D2[archiveArtifacts *.tar]
        D2 --> E

        E[Stage: SBOM — Syft]
        E --> E1["syft docker-archive:*.tar\n→ sbom-backend.json SPDX\n→ sbom-frontend.json SPDX"]
        E1 --> F

        F[Stage: Security Scan — Trivy]
        F --> F1["trivy image --input *.tar\n--severity CRITICAL\n--ignore-unfixed\n--exit-code 1"]
        F1 -->|✅ 0 CRITICAL unfixed| G
        F1 -->|❌ CRITICAL found| FAIL([Pipeline bloqué])

        G[Stage: Deploy — Ansible]
        G --> G1["mv *.tar → ansible/roles/podman-deploy/files/"]
        G1 --> G2["ansible-playbook deploy-app.yml\n• os-hardening ANSSI\n• podman-deploy air-gapped\n• observability stack"]
        G2 --> H

        H[Stage: Health Check]
        H --> H1["ansible uri → GET /health ansible_host:8080\nansible command → --health-check backend"]
        H1 -->|✅| SUCCESS([✅ Build validé])
        H1 -->|❌| FAIL2([Pipeline échoué])
    end

    SUCCESS --> TARGETS

    subgraph TARGETS ["🎯 Cibles déployées"]
        T1["vm-prod-01\nFrontend Nginx :8080"]
        T2["vm-edge-drone-01\nBackend C++ :9090"]
        T3["vm-monitoring\nGrafana :3000\nPrometheus :9090\nLoki :3100"]
    end
```

### Détail des stages

#### Build
Le stage Backend se contente de nettoyer les artefacts locaux (`rm -rf backend/build`). La **compilation C++/CMake est intentionnellement déléguée au `Dockerfile.backend`** via un build multi-stage : cela garantit la reproductibilité de l'environnement de compilation et évite toute dépendance sur l'environnement local de l'agent Jenkins.

#### Package — Images Podman
Les images sont construites en **Podman rootless** sur `vm-jenkins`. Chaque image est labelisée avec :
- `git.commit` — SHA du commit source
- `git.branch` — branche d'origine
- `build.date` — timestamp ISO 8601
- `build.number` — numéro de build Jenkins

#### Export Air-Gapped
Les images sont exportées au format `docker-archive` via `podman save`. Ces archives sont le seul vecteur de transfert vers les VMs cibles — **aucun registry n'est requis**, ce qui est conforme au modèle air-gapped.

#### SBOM — Syft
Un **Software Bill of Materials** au format **SPDX-JSON** est généré pour chaque image. Ces fichiers sont archivés comme artefacts Jenkins et permettent la traçabilité de tous les composants logiciels embarqués.

#### Security Scan — Trivy
Scan sur archive `.tar` (compatible air-gapped). Le pipeline **bloque sur toute CVE CRITICAL non corrigée** (`--exit-code 1 --ignore-unfixed`). Les rapports JSON sont archivés même en cas d'échec (`allowEmptyArchive: true`). Voir section [Gestion des CVE](#gestion-des-cve) pour les exceptions documentées.

#### Deploy — Ansible
Trois rôles sont appliqués dans l'ordre :
1. `os-hardening` — sur toutes les cibles sauf monitoring
2. `podman-deploy` — déploiement des conteneurs air-gapped
3. `observability` — stack monitoring (agents sur prod/drone, serveur sur monitoring)

Le déploiement utilise `sshagent` avec la credential Jenkins `jenkins-ssh-key`. Les conteneurs sont lancés sous le compte de service **`exail_svc`** (`become_user: exail_svc`) — jamais en root.

## Rollback
Chaque image est labelisée `git.commit`. Rollback via relance Jenkins sur le commit cible,
ou manuellement : `ansible-playbook deploy-app.yml -e "image_tag=<sha>"`
Les 5 dernières archives .tar sont conservées dans le workspace Jenkins.
---

## Stack applicative

### Backend C++ (`Dockerfile.backend`)

```
debian:bookworm-slim (builder)
  └── cmake + g++ + make
  └── cmake -B build -DCMAKE_BUILD_TYPE=Release
  └── cmake --build build
        │
        ▼
gcr.io/distroless/cc-debian12:nonroot (runtime)
  └── /app/exail_backend
  └── USER nonroot
  └── EXPOSE 9090
  └── HEALTHCHECK --health-check flag
```

- **Image runtime ~15 MB**, zéro shell, zéro package manager
- Exécuté en tant que `nonroot` (UID 65532)
- `--cap-drop ALL` appliqué au démarrage par Ansible

### Frontend Vue.js (`Dockerfile.frontend`)

```
node:20-alpine (builder)
  └── npm run build → /app/dist
        │
        ▼
nginx:stable-alpine (runtime)
  └── nginx.conf personnalisé (port 8080, server_tokens off)
  └── USER nginx (rootless)
  └── EXPOSE 8080
  └── apk upgrade --no-cache (patches Alpine au build)
  └── HEALTHCHECK GET /health
```

- Headers sécurité : `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection`
- `server_tokens off` — pas de divulgation de version Nginx
- `--cap-drop ALL` appliqué par Ansible

---

## Hardening & Sécurité

### Rôle `os-hardening` (ANSSI)

#### Kernel — sysctl

| Paramètre | Valeur | Justification |
|---|---|---|
| `net.ipv4.conf.all.accept_redirects` | `0` | Bloquer les redirections ICMP (MITM) |
| `net.ipv4.conf.all.send_redirects` | `0` | Désactiver l'émission de redirections |
| `net.ipv4.tcp_syncookies` | `1` | Protection SYN flood |
| `kernel.dmesg_restrict` | `1` | Restreindre l'accès aux logs kernel (fuite d'info) |
| `kernel.randomize_va_space` | `2` | ASLR complet |

#### SSH (`sshd_config`)

- `PermitRootLogin no`
- `PasswordAuthentication no` — clé uniquement
- `Banner /etc/issue.net` — bannière légale affichée à chaque connexion SSH
- Contenu bannière : avertissement SYSTÈME RESTREINT EXAIL

#### Pare-feu UFW

| Port | Protocole | Cible | Service |
|---|---|---|---|
| 22 | TCP | Toutes | SSH |
| 8080 | TCP | Production | Frontend Nginx |
| 9090 | TCP | Edge | Backend C++ |
| 9100 | TCP | Prod/Edge | Node Exporter |
| 8081 | TCP | Prod/Edge | cAdvisor |
| 9882 | TCP | Prod/Edge | podman-exporter (si activé) |
| 3000 | TCP | Monitoring | Grafana |
| 9090 | TCP | Monitoring | Prometheus |
| 3100 | TCP | Monitoring | Loki |

Politique par défaut : **DENY ALL inbound**.

#### Compte de service Podman

Les conteneurs sont lancés sous le compte **`exail_svc`** (shell `/sbin/nologin`). Le rôle `podman-deploy` utilise `become_user: exail_svc` sur toutes les tasks de chargement et d'exécution des conteneurs — aucun conteneur ne tourne en root.

> **Note** : le package `acl` doit être installé sur les VMs cibles pour que `become_user` vers un utilisateur non-privilégié fonctionne (`setfacl` requis par Ansible). Il est installé en tête du rôle `os-hardening`.

---

## Stack Observabilité

```
vm-prod-01  ──► node_exporter :9100 ──┐
vm-prod-01  ──► cadvisor :8081        ├──► Prometheus :9090 (vm-monitoring)
vm-edge-01  ──► node_exporter :9100 ──┤         │
vm-edge-01  ──► cadvisor :8081        ┘          ▼
                                             Grafana :3000 (vm-monitoring)

vm-prod-01  ──► promtail (journal) ──┐
vm-edge-01  ──► promtail (journal) ──┴──► Loki :3100 (vm-monitoring)
                                              │
                                              ▼
                                         Grafana :3000
```

### Composants

| Composant | Rôle | Port | Conditionnel |
|---|---|---|---|
| **Prometheus** | Scrape métriques (15s interval) | 9090 | Non |
| **Grafana** | Dashboards — source Prometheus + Loki | 3000 | Non |
| **Loki** | Agrégation logs | 3100 | Non |
| **Node Exporter** | Métriques système OS | 9100 | Non |
| **cAdvisor** | Métriques conteneurs Podman | 8081 | `enable_cadvisor` |
| **podman-exporter** | Métriques Podman API → Prometheus | 9882 | `enable_podman_exporter` |
| **Promtail** | Collecte `systemd-journal` → Loki | — | Non |

Les composants marqués **Conditionnel** sont pilotés par des variables dans `group_vars/all.yml`, modifiables via le Config Manager Streamlit. Mettre `enable_cadvisor: false` désactive la task Ansible **et** la règle UFW correspondante.

---

## Prérequis & Installation

### Dépendances hôte

```bash
# Vagrant + Libvirt
sudo apt install vagrant vagrant-libvirt libvirt-daemon-system

# Ansible + collections
pip install ansible ansible-lint
ansible-galaxy collection install ansible.posix community.general containers.podman

# Syft (SBOM)
curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin

# Streamlit (Config Manager, optionnel)
pip install streamlit pyyaml pandas
```

### Démarrage de l'infrastructure

```bash
git clone <repo-url> exail-v2
cd exail-v2/infra/vagrant

# Démarrer toutes les VMs (~5 min)
vagrant up

# Vérifier l'état
vagrant status
```

### Configuration Jenkins post-install

Une fois `vagrant up` terminé, lancer le script de setup :

```bash
bash infra/vagrant/setup-jenkins.sh
```

Ce script automatise via l'API Jenkins :
1. Attente que Jenkins soit disponible
2. Injection de la clé SSH `jenkins-ssh-key` comme credential
3. Création du job Pipeline `exail-v2-pipeline` pointant sur le Jenkinsfile du repo
4. Propagation de la clé publique Jenkins vers les VMs cibles (`vm-prod`, `vm-drone`, `vm-monitoring`)

Jenkins est ensuite accessible sur **`http://10.0.0.10:8080`** — `admin / exail2026`.

> La clé SSH Jenkins est générée au provisioning de `vm-jenkins` et stockée dans `/var/lib/jenkins/.ssh/id_ed25519`. Elle est regénérée à chaque `vagrant destroy && vagrant up`.

### Structure des clés SSH

Les clés SSH par VM sont déclarées dans `ansible/host_vars/` pour éviter tout chemin hardcodé :

```
ansible/host_vars/
├── vm-prod.yml        # ansible_ssh_private_key_file relatif à playbook_dir
├── vm-drone.yml
└── vm-monitoring.yml
```

---

## Utilisation

### Lancer un déploiement complet

```bash
# Via Jenkins UI sur http://10.0.0.10:8080
# Job : exail-v2-pipeline → Build Now
```

### Déploiement Ansible manuel (hors Jenkins)

```bash
# Déploiement complet
ansible-playbook -i ansible/inventory/production.ini ansible/deploy-app.yml -v

# Hardening uniquement
ansible-playbook -i ansible/inventory/production.ini ansible/deploy-app.yml \
  --tags os-hardening
```

### Vérifications post-déploiement

```bash
# Health check frontend
curl http://10.0.0.11:8080/health    # → OK

# Health check backend
vagrant ssh vm-drone -c \
  "podman exec exail-backend /app/exail_backend --health-check"
# → STATUS: OK

# Grafana
open http://10.0.0.13:3000           # admin / admin
```

---

## Config Manager (Streamlit)

`config_builder.py` est une application **Streamlit** permettant de :

- **Monitorer l'infrastructure** en temps réel (ping ICMP + TCP connect sur tous les ports exposés, avec auto-refresh 30s optionnel)
- **Générer les fichiers Ansible** (`inventory/production.ini` et `group_vars/all.yml`) depuis une interface graphique avec validation des IPs/ports
- **Piloter les toggles d'observabilité** — activer/désactiver `cAdvisor` et `podman-exporter` se répercute réellement sur les tasks Ansible via les variables `enable_cadvisor` et `enable_podman_exporter`

```bash
streamlit run config_builder.py
# → http://localhost:8501
```

---

## Gestion des CVE

### Politique générale

Le pipeline Trivy est configuré en mode **strict** :

```
--severity CRITICAL --ignore-unfixed --exit-code 1
```

Seules les CVE **CRITICAL** pour lesquelles un correctif existe bloquent le pipeline. Les CVE sans correctif disponible upstream sont exclues du critère de blocage mais restent visibles dans les rapports JSON archivés.

### Exception documentée — CVE-2026-0861

| Champ | Valeur |
|---|---|
| **CVE** | CVE-2026-0861 |
| **Fichier** | `.trivyignore` |
| **Image concernée** | `exail-backend` (base `distroless/cc-debian12`) |
| **Sévérité** | HIGH |
| **Statut upstream** | Pas de correctif disponible au moment du build |

**Justification d'acceptation du risque :**

1. **Surface d'exposition** : l'image distroless ne contient ni shell, ni interpréteur, ni gestionnaire de paquets. Le vecteur d'exploitation nécessite une exécution de code arbitraire préalable, impossible dans ce contexte.
2. **Isolation réseau** : les conteneurs s'exécutent dans un environnement air-gapped avec UFW `DENY ALL` par défaut ; seul le port 9090 est accessible depuis le réseau privé.
3. **Absence de correctif** : aucun patch disponible dans Debian 12 au moment de la décision. Le risque résiduel est jugé acceptable en attendant un correctif upstream.
4. **Traçabilité** : la décision est enregistrée dans `.trivyignore` avec le numéro de CVE explicite. Les rapports Trivy JSON complets restent archivés dans Jenkins pour audit.

**Action de suivi** : surveiller les advisories Debian/distroless et retirer l'exception dès qu'un correctif est disponible.

---

## Structure du dépôt

```
exail-v2/
├── ansible/
│   ├── deploy-app.yml                  # Playbook principal (3 rôles)
│   ├── inventory/
│   │   └── production.ini              # Inventaire 4 VMs (10.0.0.x)
│   ├── group_vars/
│   │   └── all.yml                     # Variables globales + toggles observabilité
│   ├── host_vars/
│   │   ├── vm-prod.yml                 # Clé SSH par host (chemin relatif)
│   │   ├── vm-drone.yml
│   │   └── vm-monitoring.yml
│   └── roles/
│       ├── os-hardening/               # Hardening ANSSI (sysctl, SSH, UFW, bannière, acl)
│       ├── podman-deploy/              # Déploiement air-gapped sous exail_svc
│       └── observability/              # Stack monitoring conditionnelle
├── backend/
│   └── src/main.cpp                    # Backend C++ edge simulé
├── frontend/
│   ├── nginx.conf                      # Nginx rootless port 8080
│   └── package.json
├── infra/
│   └── vagrant/
│       ├── Vagrantfile                 # 4 VMs Libvirt (jenkins, prod, drone, monitoring)
│       └── setup-jenkins.sh            # Post-provisioning : credential + job Jenkins via API
├── Dockerfile.backend                  # Multi-stage debian → distroless/nonroot
├── Dockerfile.frontend                 # Multi-stage node:alpine → nginx:stable-alpine
├── Jenkinsfile                         # Pipeline 7 stages
├── config_builder.py                   # Config Manager Streamlit
├── .trivyignore                        # CVE documentées et justifiées
└── .dockerignore
```
