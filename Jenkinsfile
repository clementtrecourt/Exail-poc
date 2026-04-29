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
                        sh '''
                            rm -rf backend/build
                        '''
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
                    podman build --no-cache -f Dockerfile.backend  \
                        -t ${BACKEND_IMAGE}             \
                        --label git-commit=${GIT_COMMIT} \
                        .

                    podman build --no-cache -f Dockerfile.frontend \
                        -t ${FRONTEND_IMAGE}            \
                        --label git-commit=${GIT_COMMIT} \
                        .

                    echo "=== Taille des images finales ==="
                    podman images | grep exail
                """
            }
        }

        stage('Security Scan — Trivy') {
            steps {
                sh '''
                    if [ ! -f ./trivy ]; then
                        curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b .
                    fi

                    echo "=== Scan Backend ==="
                    ./trivy image --severity HIGH,CRITICAL --no-progress ${BACKEND_IMAGE} || true

                    echo "=== Scan Frontend ==="
                    ./trivy image --severity HIGH,CRITICAL --no-progress ${FRONTEND_IMAGE} || true

                    # Export JSON
                    ./trivy image --format json -o trivy-backend.json  ${BACKEND_IMAGE} || true
                    ./trivy image --format json -o trivy-frontend.json ${FRONTEND_IMAGE} || true
                '''
            }
            post {
                always {
                    archiveArtifacts artifacts: 'trivy-*.json', allowEmptyArchive: true
                }
            }
        }

        stage('Export — Archives Air-Gapped') {
            steps {
                sh """
                    podman save -o exail-backend.tar  ${BACKEND_IMAGE}
                    podman save -o exail-frontend.tar ${FRONTEND_IMAGE}
                    echo "=== Archives générées ==="
                    ls -lh exail-*.tar
                """
                archiveArtifacts artifacts: 'exail-*.tar'
            }
        }

        stage('Deploy — Ansible') {
            steps {
                sh """
                    mkdir -p ansible/roles/podman-deploy/files/
                    mv exail-*.tar ansible/roles/podman-deploy/files/
                """
                sshagent(credentials: ['jenkins-ssh-key']) {
                    sh """
                        ansible-playbook                          \
                            -i ansible/inventory/production.ini   \
                            ansible/deploy-app.yml                \
                            --extra-vars "build_number=${BUILD_NUMBER}" \
                            -v
                    """
                }
            }
        }

        stage('Health Check') {
            steps {
                sshagent(credentials: ['jenkins-ssh-key']) {
                    sh '''
                        ansible all                                  \
                            -i ansible/inventory/production.ini      \
                            -m uri                                    \
                            -a "url=http://localhost:8080/health"

                        ansible all                                  \
                            -i ansible/inventory/production.ini      \
                            -m command                               \
                            -a "podman exec exail-backend /app/exail_backend --health-check"
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
