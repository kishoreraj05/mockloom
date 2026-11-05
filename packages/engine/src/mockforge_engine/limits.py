"""Hard limits. These are what keep user-supplied specs and rules from hurting the server."""

MAX_SPEC_BYTES = 5 * 1024 * 1024
MAX_YAML_EXPANDED_NODES = 2_000_000
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 5 * 1024 * 1024
MAX_DELAY_MS = 60_000

# How many times one $ref may repeat along a single generation path before we stop descending.
MAX_CIRCULAR_REF_DEPTH = 5
# Beyond this many nested $refs, only required properties are generated.
MAX_OPTIONAL_REF_DEPTH = 3
# Total schema nodes visited for one generated response, so wide cyclic graphs stay cheap.
GENERATION_NODE_BUDGET = 2_000

REGEX_TIMEOUT_SECONDS = 0.05
MAX_VALIDATION_ERRORS = 20
MAX_SPEC_ISSUES = 50
