# Threat model — Exail Edge V2
| Menace | Contre-mesure |
|--------|---------------|
| Exécution root | Podman rootless + exail_svc nologin + --cap-drop ALL |
| SSH non autorisé | PasswordAuthentication no + bannière légale |
| ICMP MITM | accept_redirects=0 |
| SYN flood | tcp_syncookies=1 |
| Fuite info kernel | dmesg_restrict=1 |
| Exécution arbitraire conteneur | Distroless — zéro shell, zéro package manager |
| Supply chain | Trivy CRITICAL bloquant + SBOM SPDX-JSON Syft |
| Mouvement latéral | UFW DENY ALL + ports minimum |
## Risque résiduel accepté
CVE-2026-0861 — voir .trivyignore pour justification complète.
