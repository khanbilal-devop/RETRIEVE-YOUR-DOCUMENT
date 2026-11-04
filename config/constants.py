"""Keys used in default.yaml.

Each string must match the YAML exactly. Layers import these constants instead of
writing the key strings, so renaming a key means changing it here and in the YAML.
"""

# Section
PATHS = "paths"

# Keys under `paths`
DATASET_DIR = "dataset_dir"
REGISTRY_DIR = "registry_dir"
