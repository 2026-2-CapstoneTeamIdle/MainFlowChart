#!/bin/sh
set -eu

cp /seed/sd-turbo.yaml /configuration/sd-turbo.yaml
exec /local-ai backends install cuda12-diffusers
