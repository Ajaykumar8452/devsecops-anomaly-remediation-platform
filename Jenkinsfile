pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        skipDefaultCheckout(true)
    }

    triggers {
        pollSCM('H/5 * * * *')
    }

    environment {
        DOCKERHUB_REPOSITORY = 'ajaykumar8452/devsecops-platform'
        TRIVY_IMAGE = 'aquasec/trivy:0.74.0'
        BACKEND_LOCAL_IMAGE = 'devsecops-platform-backend:ci'
        DASHBOARD_LOCAL_IMAGE = 'devsecops-platform-dashboard:ci'
    }

    stages {
        stage('Checkout') {
            steps {
                deleteDir()
                checkout scm
                script {
                    env.FULL_GIT_SHA = sh(
                        script: 'git rev-parse --verify HEAD^{commit}',
                        returnStdout: true
                    ).trim()
                    if (!(env.FULL_GIT_SHA ==~ /[0-9a-f]{40}/)) {
                        error('Checkout did not produce a full 40-character Git SHA.')
                    }
                    env.BACKEND_TAG = "${env.DOCKERHUB_REPOSITORY}:backend-${env.FULL_GIT_SHA}"
                    env.DASHBOARD_TAG = "${env.DOCKERHUB_REPOSITORY}:dashboard-${env.FULL_GIT_SHA}"
                }
            }
        }

        stage('Python 3.13 unit tests') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail
                    docker run --rm \
                      --user "$(id -u):$(id -g)" \
                      -e PYTHONDONTWRITEBYTECODE=1 \
                      -v "$WORKSPACE:/workspace" \
                      -w /workspace \
                      python:3.13-slim \
                      sh -ec 'python -m pip install --no-cache-dir --target /tmp/ci-deps -r requirements.txt pytest && PYTHONPATH=/tmp/ci-deps python -m pytest -q -p no:cacheprovider'
                '''
            }
        }

        stage('Filesystem and dependency security scan') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail
                    docker run --rm \
                      -v "$WORKSPACE:/workspace:ro" \
                      -v jenkins-trivy-cache:/root/.cache/ \
                      "$TRIVY_IMAGE" fs \
                      --scanners vuln,secret,misconfig \
                      --severity HIGH,CRITICAL \
                      --exit-code 1 \
                      /workspace
                '''
            }
        }

        stage('Build backend image') {
            steps {
                sh 'docker build --pull --no-cache --file Dockerfile --tag "$BACKEND_LOCAL_IMAGE" .'
            }
        }

        stage('Build dashboard image') {
            steps {
                sh 'docker build --pull --no-cache --file Dockerfile.dashboard --tag "$DASHBOARD_LOCAL_IMAGE" .'
            }
        }

        stage('Scan container images') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail
                    scan_failed=0
                    for image in "$BACKEND_LOCAL_IMAGE" "$DASHBOARD_LOCAL_IMAGE"; do
                      if docker run --rm \
                        -v /var/run/docker.sock:/var/run/docker.sock \
                        -v jenkins-trivy-cache:/root/.cache/ \
                        "$TRIVY_IMAGE" image \
                        --scanners vuln,secret,misconfig \
                        --severity HIGH,CRITICAL \
                        --exit-code 1 \
                        "$image"; then
                        echo "Trivy scan passed for $image"
                      else
                        echo "Trivy scan failed for $image" >&2
                        scan_failed=1
                      fi
                    done
                    exit "$scan_failed"
                '''
            }
        }

        stage('Push immutable Docker Hub images') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-token',
                    usernameVariable: 'DOCKERHUB_USER',
                    passwordVariable: 'DOCKERHUB_TOKEN'
                )]) {
                    sh '''#!/usr/bin/env bash
                        set +x
                        set -euo pipefail
                        printf '%s' "$DOCKERHUB_TOKEN" | docker login \
                          --username "$DOCKERHUB_USER" \
                          --password-stdin
                        trap 'docker logout >/dev/null 2>&1 || true' EXIT
                        docker tag "$BACKEND_LOCAL_IMAGE" "$BACKEND_TAG"
                        docker tag "$DASHBOARD_LOCAL_IMAGE" "$DASHBOARD_TAG"
                        docker push "$BACKEND_TAG"
                        docker push "$DASHBOARD_TAG"
                    '''
                }
            }
        }
    }

    post {
        always {
            sh '''#!/usr/bin/env bash
                set +e
                docker image rm "$BACKEND_LOCAL_IMAGE" "$DASHBOARD_LOCAL_IMAGE" >/dev/null 2>&1 || echo 'Warning: Docker cleanup failed or one or both local images were absent.' >&2
            '''
        }
    }
}
