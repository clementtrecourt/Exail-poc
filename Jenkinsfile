pipeline {
    agent any

    environment {
        BACKEND_IMAGE  = "localhost/exail-backend:v${BUILD_NUMBER}"
        FRONTEND_IMAGE = "localhost/exail-frontend:v${BUILD_NUMBER}"
    }

    stages {
        stage('Build') {
            parallel {
                stage('Backend — C++ / CMake') {
                    steps {
                        // La compilation C++/CMake est déléguée au Dockerfile.backend (multi-stage).
                        // Ce stage nettoie uniquement les artefacts locaux pour forcer un build propre.
                        sh 'rm -rf backend/build'
                    }
                }
                stage('Frontend — Vue.js / npm') {
                    steps {
                        sh '''
                            cd frontend
                            npm install
                            npm run build
                        '''
                    }
                }
            }
        }

        stage('Package — Images Podman') {
            steps {
                sh """
                    BUILD_DATE=\$(date -u +'%Y-%m-%dT%H:%M:%SZ')
                    GIT_BRANCH_NAME=\${GIT_BRANCH:-\$(git rev-parse --abbrev-ref HEAD)}

                    podman build --no-cache -f Dockerfile.backend  \
                        -t ${BACKEND_IMAGE} \
                        --label git.commit=${GIT_COMMIT} \
                        --label git.branch=\${GIT_BRANCH_NAME} \
                        --label build.date=\${BUILD_DATE} \
                        --label build.number=${BUILD_NUMBER} \
                        .

                    podman build --no-cache -f Dockerfile.frontend \
                        -t ${FRONTEND_IMAGE} \
                        --label git.commit=${GIT_COMMIT} \
                        --label git.branch=\${GIT_BRANCH_NAME} \
                        --label build.date=\${BUILD_DATE} \
                        --label build.number=${BUILD_NUMBER} \
                        .

                    echo "=== Taille des images finales ==="
                    podman images | grep exail
                """
            }
        }

        stage('Export — Archives Air-Gapped') {
            steps {
                sh """
                    rm -f exail-backend.tar exail-frontend.tar
                    podman save --format docker-archive -o exail-backend.tar  ${BACKEND_IMAGE}
                    podman save --format docker-archive -o exail-frontend.tar ${FRONTEND_IMAGE}
                    echo "=== Archives générées ==="
                    ls -lh exail-*.tar
                """
                archiveArtifacts artifacts: 'exail-*.tar'
            }
        }

        stage('SBOM Generation — Syft') {
            steps {
                sh '''
                    echo "=== Génération SBOM (SPDX) Backend ==="
                    syft docker-archive:exail-backend.tar -o spdx-json=sbom-backend.json

                    echo "=== Génération SBOM (SPDX) Frontend ==="
                    syft docker-archive:exail-frontend.tar -o spdx-json=sbom-frontend.json
                '''
            }
            post {
                always {
                    archiveArtifacts artifacts: 'sbom-*.json', allowEmptyArchive: true
                }
            }
        }

        stage('Security Scan — Trivy') {
            steps {
                sh '''
                    if [ ! -f ./trivy ]; then
                        curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b .
                    fi

                    echo "=== Scan Backend ==="
                    ./trivy image --exit-code 1 --input exail-backend.tar --severity CRITICAL --ignore-unfixed --no-progress

                    echo "=== Scan Frontend ==="
                    ./trivy image --exit-code 1 --input exail-frontend.tar --severity CRITICAL --ignore-unfixed --no-progress

                    # Export JSON pour traçabilité et audit
                    ./trivy image --input exail-backend.tar --format json -o trivy-backend.json
                    ./trivy image --input exail-frontend.tar --format json -o trivy-frontend.json
                '''
            }
            post {
                always {
                    archiveArtifacts artifacts: 'trivy-*.json', allowEmptyArchive: true
                }
            }
        }

        stage('Deploy — Ansible') {
            steps {
                sh """
                    mkdir -p ansible/roles/podman-deploy/files/
                    mv exail-*.tar ansible/roles/podman-deploy/files/
                """
                ansiblePlaybook(
                    inventory: 'ansible/inventory/production.ini',
                    playbook: 'ansible/deploy-app.yml',
                    extraVars: "build_number=${BUILD_NUMBER}"
                )
            }
        }

        stage('Health Check') {
            steps {
                sh '''

                    ansible production,edge                       \
                        -i ansible/inventory/production.ini       \
                        -m uri                                     \
                        -a "url=http://{{ ansible_host }}:8080/health status_code=200" \
                        --connection=ssh


                    ansible production,edge                       \
                        -i ansible/inventory/production.ini       \
                        -m command                                 \
                        -a "podman exec exail-backend /app/exail_backend --health-check" \
                        --become                                   \
                        --become-user=exail_svc
                '''
            }
        }


        }
    }

    post {
        success {
            echo "✅ Build #${BUILD_NUMBER} — Déploiement validé sur toutes les cibles."
        }
        failure {
            echo "❌ Build #${BUILD_NUMBER} — Échec pipeline. Consulter les logs ci-dessus."
        }
        always {
            sh """
                podman rmi ${BACKEND_IMAGE}  || true
                podman rmi ${FRONTEND_IMAGE} || true
            """
        }
    }
}
