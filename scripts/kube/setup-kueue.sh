#!/bin/bash

kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.16.0/manifests.yaml
kubectl wait deploy/kueue-controller-manager -nkueue-system --for=condition=available --timeout=5m
kubectl apply -f "$(dirname "$0")/kueue-setup.yaml"