"""Controller package initialization."""

# Load the additive Student/Supervisor Trash coverage before Flask registers
# controller blueprints. Existing routes, sidebars, CSRF forms, and schema are
# reused; this import only extends the current Trash behavior.
from . import role_trash_extension as _role_trash_extension  # noqa: F401
