#!/usr/bin/env bash
# ============================================================
# inject-jenkins-key.sh
# À lancer UNE FOIS après `vagrant up` pour propager la clé
# publique SSH de Jenkins vers les VMs cibles.
#
# Usage: bash infra/vagrant/inject-jenkins-key.sh
# ============================================================
set -e

echo "=== Récupération de la clé publique Jenkins ==="

JENKINS_PUBKEY=$(vagrant ssh vm-jenkins -- \
  sudo cat /var/lib/jenkins/.ssh/id_ed25519.pub 2>/dev/null | tr -d '\r')

if [ -z "$JENKINS_PUBKEY" ]; then
  echo "❌ Clé publique introuvable sur vm-jenkins."
  echo "   Vérifie que le provisioning s'est bien terminé :"
  echo "   vagrant ssh vm-jenkins -- sudo ls -la /var/lib/jenkins/.ssh/"
  exit 1
fi

if [[ "$JENKINS_PUBKEY" != ssh-ed25519* ]]; then
  echo "❌ La valeur récupérée ne ressemble pas à une clé SSH publique :"
  echo "   '$JENKINS_PUBKEY'"
  exit 1
fi

echo "✅ Clé récupérée : ${JENKINS_PUBKEY:0:50}..."

inject_key() {
  local vm="$1"
  echo ""
  echo "=== Injection dans ${vm} ==="
  vagrant ssh "$vm" -- bash -c "
    grep -qF '${JENKINS_PUBKEY}' ~/.ssh/authorized_keys 2>/dev/null \
      && echo '⏭  Clé déjà présente, skip.' \
      || { echo '${JENKINS_PUBKEY}' >> ~/.ssh/authorized_keys && echo '✅ Clé injectée.'; }
  "
}

inject_key "vm-prod"
inject_key "vm-drone"
inject_key "vm-monitoring"

echo ""
echo "=== Vérification connectivité SSH depuis Jenkins ==="
for vm in vm-prod vm-drone vm-monitoring; do
  IP=$(vagrant ssh "$vm" -- hostname -I | awk '{print $2}' | tr -d '\r')
  RESULT=$(vagrant ssh vm-jenkins -- \
    sudo -u jenkins ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    vagrant@"$IP" "echo OK" 2>/dev/null || echo "FAIL")
  if [ "$RESULT" = "OK" ]; then
    echo "✅ Jenkins → ${vm} (${IP}) : OK"
  else
    echo "❌ Jenkins → ${vm} (${IP}) : FAIL"
  fi
done

echo ""
echo "============================================"
echo "✅ Clé Jenkins propagée sur toutes les VMs"
echo "   Lancer le pipeline depuis Jenkins"
echo "   http://10.0.0.10:8080  —  admin / exail2026"
echo "============================================"
