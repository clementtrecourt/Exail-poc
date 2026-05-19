import os
import re
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import streamlit as st
import yaml

st.set_page_config(
    page_title="Exail Edge V2 — Config Manager",
    page_icon="🛡️",
    layout="wide",
)

st.markdown(
    """
<style>
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [data-baseweb="tab"] { padding: 8px 16px; font-size: 14px; }
.metric-card {
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: center;
}
.metric-card .value { font-size: 28px; font-weight: 600; font-family: monospace; }
.metric-card .label { font-size: 12px; color: #6c757d; margin-top: 4px; }
.host-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
}
.badge-prod       { background: #d1fae5; color: #065f46; }
.badge-edge       { background: #dbeafe; color: #1e40af; }
.badge-monitoring { background: #fef3c7; color: #92400e; }
.status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    border: 1px solid #e9ecef;
    border-radius: 8px;
    margin-bottom: 8px;
    background: #fff;
}
.status-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 8px;
}
.dot-up      { background: #10b981; }
.dot-down    { background: #ef4444; }
.dot-unknown { background: #9ca3af; }
.dot-pending { background: #f59e0b; }
.status-label { font-size: 13px; font-weight: 500; }
.status-meta  { font-size: 12px; color: #6c757d; }
.latency-badge {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 12px;
    font-family: monospace;
}
.latency-fast   { background: #d1fae5; color: #065f46; }
.latency-medium { background: #fef3c7; color: #92400e; }
.latency-slow   { background: #fee2e2; color: #991b1b; }
</style>
""",
    unsafe_allow_html=True,
)


# ── Helpers validation ───────────────────────────────────────────────────────


def is_valid_ip(ip: str) -> bool:
    pattern = r"^(\d{1,3}\.){3}\d{1,3}$"
    if not re.match(pattern, ip):
        return False
    return all(0 <= int(o) <= 255 for o in ip.split("."))


def is_valid_port(port: int) -> bool:
    return 1 <= port <= 65535


# ── Helpers fichiers Ansible ─────────────────────────────────────────────────


def build_inventory(data: dict) -> str:
    wp = data["workspace_path"]
    return f"""[production]
vm-prod-01       ansible_host={data["prod_ip"]} ansible_ssh_private_key_file={wp}/infra/vagrant/.vagrant/machines/vm-prod/libvirt/private_key

[edge]
vm-edge-drone-01 ansible_host={data["drone_ip"]} ansible_ssh_private_key_file={wp}/infra/vagrant/.vagrant/machines/vm-drone/libvirt/private_key

[monitoring]
vm-monitoring    ansible_host={data["monitoring_ip"]} ansible_ssh_private_key_file={wp}/infra/vagrant/.vagrant/machines/vm-monitoring/libvirt/private_key

[all:vars]
ansible_user={data["ssh_user"]}
ansible_ssh_common_args='-o StrictHostKeyChecking=no'
"""


def build_group_vars(data: dict) -> dict:
    return {
        "ansible_ssh_user": data["ssh_user"],
        "ssh_port": data["ssh_port"],
        "ufw_frontend_port": data["ufw_frontend_port"],
        "ufw_backend_port": data["ufw_backend_port"],
        "hardening_disable_root": data["hardening_disable_root"],
        "hardening_disable_passwords": data["hardening_disable_passwords"],
        "apply_anssi_sysctl": data["apply_anssi_sysctl"],
        "podman_service_user": data["podman_service_user"],
        "podman_transfer_dir": data["podman_transfer_dir"],
        "enable_podman_exporter": data["enable_podman_exporter"],
        "enable_cadvisor": data["enable_cadvisor"],
        "ssh_banner_text": data["ssh_banner_text"],
    }


def validate(data: dict) -> list[str]:
    errors = []
    for key, label in [
        ("prod_ip", "IP Prod"),
        ("drone_ip", "IP Drone"),
        ("monitoring_ip", "IP Monitoring"),
    ]:
        if not is_valid_ip(data[key]):
            errors.append(f"❌ {label} invalide : `{data[key]}`")
    for key, label in [
        ("ssh_port", "Port SSH"),
        ("ufw_frontend_port", "Port Frontend"),
        ("ufw_backend_port", "Port Backend"),
    ]:
        if not is_valid_port(data[key]):
            errors.append(f"❌ {label} invalide : `{data[key]}`")
    if not data["ssh_user"].strip():
        errors.append("❌ Utilisateur SSH requis")
    if not data["workspace_path"].strip():
        errors.append("❌ Chemin projet requis")
    ips = [data["prod_ip"], data["drone_ip"], data["monitoring_ip"]]
    if len(set(ips)) < 3:
        errors.append("❌ Les IPs des trois machines doivent être distinctes")
    return errors


# ── Status checker ───────────────────────────────────────────────────────────


@dataclass
class PortResult:
    port: int
    label: str
    reachable: bool
    latency_ms: Optional[float] = None


@dataclass
class HostStatus:
    name: str
    ip: str
    role: str
    ping_ok: bool = False
    ping_ms: Optional[float] = None
    ports: list[PortResult] = field(default_factory=list)
    checked_at: Optional[datetime] = None
    error: Optional[str] = None


def check_ping(ip: str, timeout: float = 2.0) -> tuple[bool, Optional[float]]:
    """ICMP ping via subprocess — retourne (ok, latency_ms)."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(int(timeout)), ip],
            capture_output=True,
            text=True,
            timeout=timeout + 1,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "time=" in line:
                    ms = float(line.split("time=")[1].split()[0])
                    return True, ms
            return True, None
        return False, None
    except Exception:
        return False, None


def check_port(
    ip: str, port: int, timeout: float = 2.0
) -> tuple[bool, Optional[float]]:
    """TCP connect check — retourne (ok, latency_ms)."""
    try:
        start = time.monotonic()
        with socket.create_connection((ip, port), timeout=timeout):
            ms = (time.monotonic() - start) * 1000
            return True, round(ms, 1)
    except Exception:
        return False, None


def check_host(
    name: str, ip: str, role: str, ports: list[tuple[int, str]]
) -> HostStatus:
    status = HostStatus(name=name, ip=ip, role=role, checked_at=datetime.now())
    if not is_valid_ip(ip):
        status.error = "IP invalide"
        return status

    status.ping_ok, status.ping_ms = check_ping(ip)

    results = []
    for port, label in ports:
        ok, latency = check_port(ip, port)
        results.append(
            PortResult(port=port, label=label, reachable=ok, latency_ms=latency)
        )
    status.ports = results
    return status


def run_all_checks(hosts: list[dict]) -> list[HostStatus]:
    results = [None] * len(hosts)

    def worker(idx, h):
        results[idx] = check_host(h["name"], h["ip"], h["role"], h["ports"])

    threads = [
        threading.Thread(target=worker, args=(i, h)) for i, h in enumerate(hosts)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


ROLE_EMOJI = {"production": "🖥️", "edge": "🤖", "monitoring": "📊"}
ROLE_COLOR = {"production": "green", "edge": "blue", "monitoring": "orange"}


def fmt_latency(ms: Optional[float]) -> str:
    if ms is None:
        return "—"
    if ms < 1:
        return "< 1 ms"
    return f"{ms:.0f} ms"


def render_host_status(s: HostStatus):
    role_emoji = ROLE_EMOJI.get(s.role, "🖥️")
    ping_icon = "🟢" if s.ping_ok else "🔴"
    ping_label = f"{ping_icon} **{s.name}**"
    ping_sub = (
        f"`{s.ip}` · ping {fmt_latency(s.ping_ms)}"
        if s.ping_ok
        else f"`{s.ip}` · **unreachable**"
    )
    if s.error:
        ping_sub += f" · ⚠️ {s.error}"
    ts = s.checked_at.strftime("%H:%M:%S") if s.checked_at else "—"

    with st.expander(
        f"{role_emoji} {s.name}  ·  `{s.ip}`  ·  {ping_icon}  ·  _{ts}_", expanded=True
    ):
        st.caption(ping_sub)
        if s.ports:
            n = len(s.ports)
            cols = st.columns(n)
            for col, pr in zip(cols, s.ports):
                with col:
                    up = pr.reachable
                    col.metric(
                        label=f":{pr.port} {pr.label}",
                        value="UP" if up else "DOWN",
                        delta=fmt_latency(pr.latency_ms) if up else "unreachable",
                        delta_color="normal" if up else "inverse",
                    )


# ── App ──────────────────────────────────────────────────────────────────────

st.title("🛡️ Exail Edge V2 — Configuration Manager")
st.caption(
    "Génération dynamique de l'inventaire et des variables Ansible pour déploiement Air-Gapped"
)

tab0, tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📊 Status",
        "📡 Inventaire",
        "🔒 Sécurité & Hardening",
        "🐳 Conteneurs Podman",
        "⚙️ Aperçu & Export",
    ]
)

# ── Tab Inventaire (doit être défini avant tab0 pour récupérer les IPs) ──────
with tab1:
    st.subheader("Machines cibles")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            '<span class="host-badge badge-prod">production</span>',
            unsafe_allow_html=True,
        )
        prod_ip = st.text_input(
            "vm-prod-01 · Frontend Vue.js", value="192.168.121.103", key="prod_ip"
        )
        if prod_ip and not is_valid_ip(prod_ip):
            st.error("IP invalide")

    with col2:
        st.markdown(
            '<span class="host-badge badge-edge">edge</span>', unsafe_allow_html=True
        )
        drone_ip = st.text_input(
            "vm-edge-drone-01 · Backend C++", value="192.168.121.2", key="drone_ip"
        )
        if drone_ip and not is_valid_ip(drone_ip):
            st.error("IP invalide")

    with col3:
        st.markdown(
            '<span class="host-badge badge-monitoring">monitoring</span>',
            unsafe_allow_html=True,
        )
        monitoring_ip = st.text_input(
            "vm-monitoring · Grafana/Loki/Prom",
            value="192.168.121.200",
            key="monitoring_ip",
        )
        if monitoring_ip and not is_valid_ip(monitoring_ip):
            st.error("IP invalide")

    st.divider()
    st.subheader("Connexion SSH")
    col4, col5 = st.columns(2)
    with col4:
        ssh_user = st.text_input("Utilisateur SSH", value="vagrant")
    with col5:
        workspace_path = st.text_input(
            "Chemin absolu du projet", value="/home/clem/Code/exail-v2"
        )


# ── Tab Status ───────────────────────────────────────────────────────────────
with tab0:
    hosts_to_check = [
        {
            "name": "vm-prod-01",
            "ip": prod_ip,
            "role": "production",
            "ports": [
                (22, "SSH"),
                (8080, "Frontend"),
                (9100, "node-exporter"),
                (8081, "cAdvisor"),
            ],
        },
        {
            "name": "vm-edge-drone-01",
            "ip": drone_ip,
            "role": "edge",
            "ports": [
                (22, "SSH"),
                (9090, "Backend"),
                (9100, "node-exporter"),
                (8081, "cAdvisor"),
            ],
        },
        {
            "name": "vm-monitoring",
            "ip": monitoring_ip,
            "role": "monitoring",
            "ports": [
                (22, "SSH"),
                (3000, "Grafana"),
                (9090, "Prometheus"),
                (3100, "Loki"),
            ],
        },
    ]

    # Toolbar
    c_btn, c_tog, _ = st.columns([2, 2, 6])
    with c_btn:
        do_check = st.button("🔄 Lancer les checks", use_container_width=True)
    with c_tog:
        auto_refresh = st.toggle("Auto-refresh 30s", value=False)

    if auto_refresh and time.time() - st.session_state.get("last_check_ts", 0) > 30:
        do_check = True

    if do_check:
        with st.spinner("Checks en cours..."):
            statuses = run_all_checks(hosts_to_check)
        st.session_state["statuses"] = statuses
        st.session_state["last_check_ts"] = time.time()

    statuses: list[HostStatus] = st.session_state.get("statuses", [])

    if not statuses:
        st.info(
            "Cliquez sur **Lancer les checks** pour tester la connectivité de l'infrastructure."
        )
    else:
        total = len(statuses)
        up_count = sum(1 for s in statuses if s.ping_ok)
        ports_total = sum(len(s.ports) for s in statuses)
        ports_up = sum(p.reachable for s in statuses for p in s.ports)
        all_ok = up_count == total and ports_up == ports_total
        last_ts = st.session_state.get("last_check_ts")

        # ── Résumé global ──
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            "VMs joignables",
            f"{up_count} / {total}",
            delta="OK" if up_count == total else f"{total - up_count} down",
            delta_color="normal" if up_count == total else "inverse",
        )
        m2.metric(
            "Ports ouverts",
            f"{ports_up} / {ports_total}",
            delta="OK"
            if ports_up == ports_total
            else f"{ports_total - ports_up} fermés",
            delta_color="normal" if ports_up == ports_total else "inverse",
        )
        m3.metric(
            "Dernier check",
            datetime.fromtimestamp(last_ts).strftime("%H:%M:%S") if last_ts else "—",
        )
        m4.metric("Statut global", "✅  Nominal" if all_ok else "⚠️  Dégradé")

        st.divider()

        # ── Hosts ──
        for s in statuses:
            render_host_status(s)

        # ── Tableau récap ──
        st.divider()
        st.subheader("Récapitulatif")
        import pandas as pd

        rows = [
            {
                "Host": s.name,
                "Rôle": s.role,
                "IP": s.ip,
                "Ping": "🟢" if s.ping_ok else "🔴",
                "Latence ping": fmt_latency(s.ping_ms),
                "Ports UP": f"{sum(p.reachable for p in s.ports)}/{len(s.ports)}",
                "Services KO": ", ".join(p.label for p in s.ports if not p.reachable)
                or "—",
            }
            for s in statuses
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Tab Sécurité ─────────────────────────────────────────────────────────────
with tab2:
    st.subheader("Ports & UFW")
    col6, col7, col8 = st.columns(3)
    with col6:
        ssh_port = st.number_input("Port SSH", value=22, min_value=1, max_value=65535)
    with col7:
        ufw_frontend_port = st.number_input(
            "Port UFW Frontend", value=8080, min_value=1, max_value=65535
        )
    with col8:
        ufw_backend_port = st.number_input(
            "Port UFW Backend", value=9090, min_value=1, max_value=65535
        )

    st.divider()
    st.subheader("Hardening OS")
    col9, col10 = st.columns(2)
    with col9:
        hardening_disable_root = st.toggle(
            "Désactiver login root SSH",
            value=True,
            help="Applique `PermitRootLogin no` dans sshd_config",
        )
        hardening_disable_passwords = st.toggle(
            "Désactiver auth par mot de passe",
            value=True,
            help="Applique `PasswordAuthentication no`",
        )
    with col10:
        apply_anssi_sysctl = st.toggle(
            "Règles sysctl ANSSI",
            value=True,
            help="Durcissement réseau kernel selon recommandations ANSSI",
        )

    st.divider()
    st.subheader("Bannière légale")
    ssh_banner_text = st.text_area(
        "/etc/issue.net",
        value=(
            "===========================================================\n"
            "⚠️ SYSTÈME D'INFORMATION RESTREINT — EXAIL\n"
            "Accès réservé aux personnels habilités.\n"
            "Toute intrusion est traçable et pénalement répréhensible.\n"
            "==========================================================="
        ),
        height=140,
    )


# ── Tab Conteneurs ────────────────────────────────────────────────────────────
with tab3:
    st.subheader("Déploiement Air-Gapped")
    col11, col12 = st.columns(2)
    with col11:
        podman_service_user = st.text_input("Compte de service OS", value="exail_svc")
    with col12:
        podman_transfer_dir = st.text_input(
            "Répertoire transfert temporaire", value="/tmp"
        )

    st.divider()
    st.subheader("Ports internes (non modifiables)")
    col13, col14 = st.columns(2)
    with col13:
        st.markdown(
            """
        <div class="metric-card">
            <div class="value">8080</div>
            <div class="label">Frontend Nginx · défini dans nginx.conf</div>
        </div>
        """,
            unsafe_allow_html=True,
        )
    with col14:
        st.markdown(
            """
        <div class="metric-card">
            <div class="value">9090</div>
            <div class="label">Backend C++ · défini dans le source</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    st.divider()
    st.subheader("Observabilité")
    col15, col16 = st.columns(2)
    with col15:
        enable_podman_exporter = st.toggle(
            "Activer podman-exporter",
            value=True,
            help="Métriques containers Podman → Prometheus (port 9882). Nécessite Podman API v3+.",
        )
    with col16:
        enable_cadvisor = st.toggle(
            "Activer cAdvisor",
            value=True,
            help="Métriques système containers, port 8081. Lance avec --network=host.",
        )


# ── Tab Aperçu & Export ───────────────────────────────────────────────────────
with tab4:
    data = {
        "prod_ip": prod_ip,
        "drone_ip": drone_ip,
        "monitoring_ip": monitoring_ip,
        "ssh_user": ssh_user,
        "workspace_path": workspace_path,
        "ssh_port": int(ssh_port),
        "ufw_frontend_port": int(ufw_frontend_port),
        "ufw_backend_port": int(ufw_backend_port),
        "hardening_disable_root": hardening_disable_root,
        "hardening_disable_passwords": hardening_disable_passwords,
        "apply_anssi_sysctl": apply_anssi_sysctl,
        "ssh_banner_text": ssh_banner_text,
        "podman_service_user": podman_service_user,
        "podman_transfer_dir": podman_transfer_dir,
        "enable_podman_exporter": enable_podman_exporter,
        "enable_cadvisor": enable_cadvisor,
    }

    errors = validate(data)

    if errors:
        st.error("**Erreurs de validation — corrigez avant de générer**")
        for e in errors:
            st.markdown(e)
    else:
        st.success("✅ Configuration valide")

    inventory_content = build_inventory(data)
    group_vars_dict = build_group_vars(data)
    group_vars_content = yaml.dump(
        group_vars_dict,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    st.subheader("Aperçu des fichiers générés")
    col17, col18 = st.columns(2)
    with col17:
        st.caption("📄 ansible/inventory/production.ini")
        st.code(inventory_content, language="ini")
    with col18:
        st.caption("📄 ansible/group_vars/all.yml")
        st.code(group_vars_content, language="yaml")

    st.divider()

    if st.button(
        "💾 Générer les fichiers Ansible",
        type="primary",
        use_container_width=True,
        disabled=bool(errors),
    ):
        try:
            os.makedirs("ansible/inventory", exist_ok=True)
            os.makedirs("ansible/group_vars", exist_ok=True)

            with open("ansible/inventory/production.ini", "w") as f:
                f.write(inventory_content)

            with open("ansible/group_vars/all.yml", "w") as f:
                f.write(group_vars_content)

            st.success(
                "✅ Fichiers écrits : `ansible/inventory/production.ini` "
                "et `ansible/group_vars/all.yml`"
            )
            st.balloons()

        except Exception as e:
            st.error(f"Erreur d'écriture : {e}")
